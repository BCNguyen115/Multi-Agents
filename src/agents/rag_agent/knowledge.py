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
from src.shared.auth import knowledge_tenants
from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger
from src.shared.postgres_client import PostgresClient

logger: logging.Logger = get_logger(__name__)

_HYDE_SYSTEM_PROMPT: str = (
    "You write passages for a search index. Given a question, write ONE factual passage (at most 120 words), in English, "
    "in the style of an internal contract, policy or procedure document, that would answer it. "
    "Output only the passage, no preamble."
)
_HYDE_CACHE_SIZE: int = 256
_CATEGORY_TTL_SECONDS: float = 300.0
_MAX_KEYWORDS: int = 12
_TOKEN = re.compile(r"\w{3,}")

_COLUMNS: str = "id, content, raw_content, filename, category, section_title, page, chunk_index"


def _filters(category: int, tenant: int) -> str:
    return f"(${category}::text[] IS NULL OR category = ANY(${category})) AND (${tenant}::text[] IS NULL OR tenant_id = ANY(${tenant}))"


_FILTERS: str = _filters(2, 3)

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


_PASSAGE_SQL: str = f"""
SELECT p.chunk_id AS id, p.content AS best_passage, 1 - (p.embedding <=> $1::vector) AS vector_score
FROM   rag_passages p JOIN rag_chunks c ON c.id = p.chunk_id
WHERE  {_FILTERS}
ORDER  BY p.embedding <=> $1::vector
LIMIT  $4;
"""

_CHUNKS_BY_ID_SQL: str = f"SELECT {_COLUMNS}, 0.0::float AS fts_score FROM rag_chunks WHERE id = ANY($1::bigint[]);"

_FTS_ONLY_SQL: str = f"""
SELECT {_COLUMNS}, 0.0::float AS vector_score, ts_rank_cd(tsv, q) AS fts_score
FROM   rag_chunks, to_tsquery('simple', immutable_unaccent($4)) q
WHERE  tsv @@ q AND {_filters(1, 2)}
ORDER  BY fts_score DESC
LIMIT  $3;
"""

_STOPWORDS: frozenset[str] = frozenset(
    (
        "the and for are was were not but all any can had has have its may our out shall such than that their them then there these "
        "they this those will with would you your from into upon under over also each other which who whom what when where how why "
        "của các cho khi và là có này đó những một được trong với để theo như không về từ đã sẽ đang bởi tại hay hoặc nếu thì mà "
        "cũng rất vào ra lên xuống nào gì sao đâu bao nhiêu thế"
    ).split()
)


def build_tsquery(text: str, max_terms: int = _MAX_KEYWORDS, stopwords: bool = False) -> Optional[str]:
    """OR-query of the distinct words of ``text`` (``'a' | 'b'``), or ``None`` when it has none.

    AND semantics (``websearch_to_tsquery``) return nothing for a natural question with 20 words; OR plus
    ``ts_rank_cd`` ranking finds the chunks that share the most terms. Words are ``\\w`` only: no quoting risk.
    """
    seen: list[str] = []
    for token in _TOKEN.findall(text.lower()):
        if token not in seen and not (stopwords and token in _STOPWORDS):
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
            if row.get("best_passage") and not item.get("best_passage"):
                item["best_passage"] = row["best_passage"]  # the passage that matched: what the reranker reads (RERANK_TEXT_MODE=passage)
    return sorted(merged.values(), key=lambda r: -r["rrf_score"])[:limit]


class KnowledgeStore:
    """Hybrid retrieval over the ingested documents."""

    def __init__(self, pg: PostgresClient, llm_client: LLMClient) -> None:
        self.pg: PostgresClient = pg
        self.llm_client: LLMClient = llm_client
        self._hyde_cache: OrderedDict[str, str] = OrderedDict()
        self._categories: tuple[float, list[str]] = (0.0, [])
        self._languages: tuple[float, dict[str, int]] = (0.0, {})
        self._model_checked: bool = False
        self._passages_ok: bool = True
        self.version: int = 0          # bumped when documents change on THIS replica: retrieval caches keyed on it go stale at once
        self._hnsw_settings_ok: bool = True

    async def ensure_schema(self, session_id: str = "SYSTEM") -> None:
        """Create/migrate ``rag_chunks`` (safe to run on every start)."""
        await ensure_schema(self.pg, session_id=session_id)

    # ------------------------------------------------------------------ query side

    async def _embed(self, text: str, session_id: str) -> list[float]:
        vector: list[float] = await self.llm_client.embedding(
            input_text=text, model=settings.EMBEDDING_MODEL, metadata={"purpose": "rag_search"}, session_id=session_id
        )
        if not vector:
            raise ValueError("empty embedding")
        return vector

    async def embed_query(self, text: str, session_id: str = "N/A") -> list[float]:
        """The embedding of ``text`` (what ``search`` would compute for it): the agent starts it while the planner is still working."""
        return await self._embed(text, session_id)

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
        self._languages = (0.0, {})
        self.version += 1

    async def known_categories(self, session_id: str = "N/A") -> list[str]:
        stamp, cached = self._categories
        if cached and time.monotonic() - stamp < _CATEGORY_TTL_SECONDS:
            return cached
        rows = await self.pg.fetch("SELECT DISTINCT category FROM rag_chunks WHERE category <> ''", session_id=session_id)
        self._categories = (time.monotonic(), [r["category"] for r in rows])
        return self._categories[1]

    async def _passage_hits(self, literals: list[str], scope: Optional[list[str]], tenants: Optional[list[str]], top_k: int, session_id: str) -> list[dict[str, Any]]:
        """Chunks whose best PASSAGE matches, best first, each carrying that passage. ``[]`` when there is no passage table yet."""
        if not self._passages_ok:
            return []
        try:
            per_query = await asyncio.gather(*(self._run(_PASSAGE_SQL, (lit, scope, tenants, top_k), session_id) for lit in literals))
            best: dict[Any, dict[str, Any]] = {}
            for rows in per_query:
                for row in rows:
                    if row["id"] not in best or row["vector_score"] > best[row["id"]]["vector_score"]:
                        best[row["id"]] = row
            if not best:
                return []
            chunks = {r["id"]: r for r in await self._run(_CHUNKS_BY_ID_SQL, ([int(i) for i in best],), session_id)}
        except Exception as exc:  # noqa: BLE001 - migration 0008 not applied: search as before
            self._passages_ok = False
            logger.warning("Passage search unavailable (%s); searching chunks only", exc, extra={"session_id": session_id})
            return []
        ranked = sorted(best.values(), key=lambda r: -r["vector_score"])
        return [{**chunks[r["id"]], "vector_score": r["vector_score"], "best_passage": r["best_passage"]} for r in ranked if r["id"] in chunks]

    async def corpus_languages(self, session_id: str = "N/A") -> dict[str, int]:
        """Chunk counts per language (``{"en": 1900, "vi": 120}``), cached; ``{}`` when unknown. The planner writes its HyDE
        passages in the languages the corpus actually speaks."""
        stamp, cached = self._languages
        if cached and time.monotonic() - stamp < _CATEGORY_TTL_SECONDS:
            return cached
        try:
            rows = await self.pg.fetch("SELECT lang, count(*) AS n FROM rag_chunks WHERE lang IS NOT NULL GROUP BY lang", session_id=session_id)
        except Exception as exc:  # noqa: BLE001 - before migration 0007 there is no column: behave as before
            logger.warning("Corpus languages unavailable: %s", exc, extra={"session_id": session_id})
            return {}
        self._languages = (time.monotonic(), {r["lang"]: int(r["n"]) for r in rows})
        return self._languages[1]

    async def _check_embedding_model(self, session_id: str) -> None:
        """Once per process: say loudly when queries are embedded with another model than the corpus was."""
        self._model_checked = True
        try:
            rows = await self.pg.fetch("SELECT value FROM rag_meta WHERE key = 'embedding_model'", session_id=session_id)
            stored: Optional[str] = rows[0]["value"] if rows else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("rag_meta not readable: %s", exc)
            return
        wanted = f"{settings.EMBEDDING_MODEL}|{settings.EMBEDDING_DIMENSIONS or 'default'}"
        if stored is not None and stored != wanted:
            logger.error(
                "EMBEDDING MODEL MISMATCH: the corpus was embedded with %r, queries use %r. Search quality is unreliable until the "
                "corpus is re-embedded (python -m scripts.run_ingestion --reset) or EMBEDDING_MODEL is set back.",
                stored, wanted, extra={"session_id": session_id},
            )

    async def _run(self, sql: str, args: tuple[Any, ...], session_id: str) -> list[dict[str, Any]]:
        tuned = bool(settings.RAG_HNSW_EF_SEARCH or settings.RAG_HNSW_ITERATIVE) and self._hnsw_settings_ok
        transaction = getattr(self.pg, "transaction", None) if tuned else None
        if transaction is not None:
            try:  # per-query pgvector settings; an older pgvector does not know hnsw.iterative_scan: say so once and stop trying
                async with transaction() as conn:
                    if settings.RAG_HNSW_EF_SEARCH:
                        await conn.execute(f"SET LOCAL hnsw.ef_search = {int(settings.RAG_HNSW_EF_SEARCH)}")
                    if settings.RAG_HNSW_ITERATIVE in ("relaxed_order", "strict_order"):
                        await conn.execute(f"SET LOCAL hnsw.iterative_scan = '{settings.RAG_HNSW_ITERATIVE}'")
                    return [dict(r) for r in await conn.fetch(sql, *args)]
            except Exception as exc:  # noqa: BLE001
                self._hnsw_settings_ok = False
                logger.warning("pgvector HNSW settings not applied (%s); using the server defaults", exc, extra={"session_id": session_id})
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
        if not self._model_checked:
            await self._check_embedding_model(session_id)
        mode: str = settings.RAG_QUERY_MODE
        passage: Optional[str] = None
        if mode in ("hyde", "both"):
            passage = (plan.passage if plan is not None else "") or await self._hypothetical_passage(query, session_id)
        passages: list[str] = [p for p in (passage, plan.passage_alt if plan is not None else "") if p]
        texts: list[str] = [query]
        if passages:
            texts = passages if mode == "hyde" else [query, *passages]
        source: str = {"passage": passage or query, "both": f"{query} {passage or ''}".strip()}.get(settings.RAG_FTS_SOURCE, query)
        keywords: Optional[str] = build_tsquery(source, _MAX_KEYWORDS * (2 if settings.RAG_FTS_SOURCE == "both" else 1), settings.RAG_FTS_STOPWORDS)
        tenants: Optional[list[str]] = knowledge_tenants()  # the caller's, not a global setting

        scopes: list[Optional[list[str]]] = []
        named: list[str] = categories if categories is not None else detect_categories(query, await self.known_categories(session_id))
        if named:
            scopes.append(named)
        scopes.append(None)

        reuse: Optional[list[float]] = plan.query_vector if plan is not None and plan.standalone == query else None

        async def vector_of(index: int, text: str) -> list[float]:
            return reuse if (reuse and index == 0 and text == query) else await self._embed(text, session_id)

        try:
            vectors: list[list[float]] = await asyncio.gather(*(vector_of(i, t) for i, t in enumerate(texts)))
        except Exception as exc:  # noqa: BLE001 - the embedding API is down: keyword search still finds documents
            if not keywords:
                raise
            logger.warning("Embedding unavailable (%s): keyword search only", exc or type(exc).__name__, extra={"session_id": session_id})
            for scope in scopes:
                rows = await self._run(_FTS_ONLY_SQL, (scope, tenants, top_k, keywords), session_id)
                if rows:
                    return [{**row, "degraded": True} for row in rows]
            return []
        literals: list[str] = ["[" + ",".join(map(str, v)) + "]" for v in vectors]

        for scope in scopes:
            jobs = [self._run(_VECTOR_SQL, (lit, scope, tenants, top_k), session_id) for lit in literals]
            if keywords:
                jobs.append(self._run(_FTS_SQL, (literals[0], scope, tenants, top_k, keywords), session_id))
            ranked_lists = list(await asyncio.gather(*jobs))
            if settings.RAG_PASSAGE_SEARCH:
                ranked_lists.append(await self._passage_hits(literals, scope, tenants, top_k, session_id))
            fused = fuse(ranked_lists, settings.RAG_RRF_K, top_k)
            if fused:
                logger.info(
                    "Retrieved %d candidates (mode=%s, scope=%s, keywords=%s)", len(fused), mode, scope or "all", bool(keywords),
                    extra={"session_id": session_id},
                )
                return fused
        return []
