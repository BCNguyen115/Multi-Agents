"""Knowledge store: hybrid retrieval over ``rag_chunks``.

    query --(raw and/or HyDE embeddings)--> vector top-k (HNSW)  \
    query --(OR keyword query)------------> full-text top-k (GIN) / --> reciprocal-rank fusion --> candidates

Vector and keyword search are two index-backed queries fused in Python with RRF, because their scores live on
different scales (cosine 0..1 vs ts_rank ~0.001) and cannot be added. Every candidate carries its own cosine
similarity (``vector_score``), which the agent uses to decide "nothing relevant found".
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from typing import Any, Optional

from src.agents.rag_agent.planner import QueryPlan
from src.config import settings
from src.ingestion.schema import ensure_schema
from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger
from src.shared.postgres_client import PostgresClient

logger: logging.Logger = get_logger(__name__)

_EMBEDDING_MODEL: str = "openai/text-embedding-3-small"  # must match the model used at ingestion
_HYDE_SYSTEM_PROMPT: str = (
    "You write passages for a search index. Given a question, write ONE factual passage (at most 120 words), in English, "
    "in the style of an internal contract, policy or procedure document, that would answer it. "
    "Output only the passage, no preamble."
)
_HYDE_CACHE_SIZE: int = 256
_CATEGORY_TTL_SECONDS: float = 300.0
_MAX_KEYWORDS: int = 12
_TOKEN = re.compile(r"\w{3,}")

_COLUMNS: str = "id, content, filename, category, section_title, page, chunk_index"
_FILTERS: str = "($2::text[] IS NULL OR category = ANY($2)) AND ($3::text[] IS NULL OR tenant_id = ANY($3))"

_VECTOR_SQL: str = f"""
SELECT {_COLUMNS}, 1 - (embedding <=> $1::vector) AS vector_score
FROM   rag_chunks
WHERE  {_FILTERS}
ORDER  BY embedding <=> $1::vector
LIMIT  $4;
"""

_FTS_SQL: str = f"""
SELECT {_COLUMNS}, 1 - (embedding <=> $1::vector) AS vector_score, ts_rank_cd(tsv, q) AS fts_score
FROM   rag_chunks, to_tsquery('simple', immutable_unaccent($5)) q
WHERE  tsv @@ q AND {_FILTERS}
ORDER  BY fts_score DESC
LIMIT  $4;
"""


def build_tsquery(text: str, max_terms: int = _MAX_KEYWORDS) -> Optional[str]:
    """OR-query of the distinct words of ``text`` (``'a' | 'b'``), or ``None`` when it has none.

    AND semantics (``websearch_to_tsquery``) return nothing for a natural question with 20 words; OR plus
    ``ts_rank_cd`` ranking finds the chunks that share the most terms. Words are ``\\w`` only: no quoting risk.
    """
    seen: list[str] = []
    for token in _TOKEN.findall(text.lower()):
        if token not in seen:
            seen.append(token)
    return " | ".join(f"'{t}'" for t in seen[:max_terms]) or None


def detect_categories(query: str, known: list[str]) -> list[str]:
    """Document categories named in the question (``NDA``, ``SOW``...), to narrow the search."""
    return [c for c in known if c and re.search(rf"(?<!\w){re.escape(c)}(?!\w)", query, re.IGNORECASE)]


def fuse(ranked_lists: list[list[dict[str, Any]]], k: int, limit: int) -> list[dict[str, Any]]:
    """Reciprocal-rank fusion of ranked candidate lists (rows are dicts with an ``id``).

    A chunk keeps its best ``vector_score`` / ``fts_score`` from any list it appears in.
    """
    merged: dict[Any, dict[str, Any]] = {}
    for rows in ranked_lists:
        for rank, row in enumerate(rows, start=1):
            item = merged.setdefault(row["id"], {**row, "rrf_score": 0.0, "fts_score": 0.0, "vector_score": 0.0})
            item["rrf_score"] += 1.0 / (k + rank)
            item["vector_score"] = max(item["vector_score"], row.get("vector_score") or 0.0)
            item["fts_score"] = max(item["fts_score"], row.get("fts_score") or 0.0)
    return sorted(merged.values(), key=lambda r: -r["rrf_score"])[:limit]


class KnowledgeStore:
    """Hybrid retrieval over the ingested documents."""

    def __init__(self, pg: PostgresClient, llm_client: LLMClient) -> None:
        self.pg: PostgresClient = pg
        self.llm_client: LLMClient = llm_client
        self._hyde_cache: OrderedDict[str, str] = OrderedDict()
        self._categories: tuple[float, list[str]] = (0.0, [])

    async def ensure_schema(self, session_id: str = "SYSTEM") -> None:
        """Create/migrate ``rag_chunks`` (safe to run on every start)."""
        await ensure_schema(self.pg, session_id=session_id)

    # ------------------------------------------------------------------ query side

    async def _embed(self, text: str, session_id: str) -> list[float]:
        vector: list[float] = await self.llm_client.embedding(
            input_text=text, model=_EMBEDDING_MODEL, metadata={"purpose": "rag_search"}, session_id=session_id
        )
        if not vector:
            raise ValueError("empty embedding")
        return vector

    async def _hypothetical_passage(self, query: str, session_id: str) -> Optional[str]:
        """HyDE: an LLM-written passage that answers ``query``; ``None`` when generation fails (raw query is used)."""
        if query in self._hyde_cache:
            self._hyde_cache.move_to_end(query)
            return self._hyde_cache[query]
        try:
            response: Any = await self.llm_client.chat_completion(
                model=settings.FAST_LLM_MODEL,
                messages=[{"role": "system", "content": _HYDE_SYSTEM_PROMPT}, {"role": "user", "content": query}],
                temperature=0.0,
                max_tokens=300,
                metadata={"purpose": "hyde_generation"},
                session_id=session_id,
            )
            passage: str = (response.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001 - HyDE is an optimisation, never a dependency
            logger.warning("HyDE generation failed, using the raw query: %s", exc, extra={"session_id": session_id})
            return None
        if passage:
            self._hyde_cache[query] = passage
            while len(self._hyde_cache) > _HYDE_CACHE_SIZE:
                self._hyde_cache.popitem(last=False)
        return passage or None

    def invalidate_categories(self) -> None:
        """Forget the cached category list (after documents were added), so a new category is detected at once."""
        self._categories = (0.0, [])

    async def known_categories(self, session_id: str = "N/A") -> list[str]:
        stamp, cached = self._categories
        if cached and time.monotonic() - stamp < _CATEGORY_TTL_SECONDS:
            return cached
        rows = await self.pg.fetch("SELECT DISTINCT category FROM rag_chunks WHERE category <> ''", session_id=session_id)
        self._categories = (time.monotonic(), [r["category"] for r in rows])
        return self._categories[1]

    async def _run(self, sql: str, args: tuple[Any, ...], session_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in await self.pg.fetch(sql, *args, session_id=session_id)]

    async def search(
        self,
        query: str,
        top_k: int = 20,
        session_id: str = "N/A",
        categories: Optional[list[str]] = None,
        plan: Optional[QueryPlan] = None,
    ) -> list[dict[str, Any]]:
        """Best ``top_k`` chunks for ``query``, fused from vector and keyword search.

        A ``plan`` (see ``planner.py``) supplies the HyDE passage, saving the store its own LLM call; without one (or
        when planning failed) the store writes the passage itself. ``query`` is embedded and searched as typed.
        Categories named in the question narrow the search first; if that finds nothing the whole corpus is
        searched. Tenant restriction comes from ``settings.RAG_TENANT_IDS``. Errors propagate: the caller decides.
        """
        mode: str = settings.RAG_QUERY_MODE
        passage: Optional[str] = None
        if mode in ("hyde", "both"):
            passage = (plan.passage if plan is not None else "") or await self._hypothetical_passage(query, session_id)
        texts: list[str] = [query]
        if passage:
            texts = [passage] if mode == "hyde" else [query, passage]
        vectors: list[list[float]] = await asyncio.gather(*(self._embed(t, session_id) for t in texts))
        literals: list[str] = ["[" + ",".join(map(str, v)) + "]" for v in vectors]
        keywords: Optional[str] = build_tsquery(query)
        tenants: Optional[list[str]] = settings.RAG_TENANT_IDS

        scopes: list[Optional[list[str]]] = []
        named: list[str] = categories if categories is not None else detect_categories(query, await self.known_categories(session_id))
        if named:
            scopes.append(named)
        scopes.append(None)

        for scope in scopes:
            jobs = [self._run(_VECTOR_SQL, (lit, scope, tenants, top_k), session_id) for lit in literals]
            if keywords:
                jobs.append(self._run(_FTS_SQL, (literals[0], scope, tenants, top_k, keywords), session_id))
            fused = fuse(list(await asyncio.gather(*jobs)), settings.RAG_RRF_K, top_k)
            if fused:
                logger.info(
                    "Retrieved %d candidates (mode=%s, scope=%s, keywords=%s)", len(fused), mode, scope or "all", bool(keywords),
                    extra={"session_id": session_id},
                )
                return fused
        return []
