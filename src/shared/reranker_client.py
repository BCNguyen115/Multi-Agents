"""TEI Reranker client module.

Sends candidate text documents to HuggingFace TEI (Text Embeddings Inference)
Reranker endpoint for high-precision cross-encoder re-ranking.

The first ``RERANK_POOL_K`` candidates are scored, each cut to ``MAX_RERANK_TEXT_LENGTH`` chars, within ONE time budget
(``RERANKER_TIMEOUT``). The cost of a CPU cross-encoder grows with candidates x text length. A two-stage variant (screen
20 candidates on a 300-400 char prefix, rescore the best 5-6 on the full text) and a pool of 20 were measured on the real
corpus and rejected: see docs/RAG_REVIEW_AND_FIXES.md.

Usage:
    from src.shared.reranker_client import rerank_documents

    reranked_docs = await rerank_documents(
        query="What is the NDA clause?",
        documents=candidate_docs,
        top_k=5,
        session_id="abc"
    )
"""

import asyncio
import logging
import re
import time
from typing import Any, List, Optional
import httpx

from src.config import settings
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Circuit breaker settings & state
_CIRCUIT_BREAKER_THRESHOLD: int = 3
_CIRCUIT_BREAKER_COOLDOWN: float = 30.0  # seconds
_consecutive_failures: int = 0
_last_failure_time: float = 0.0


def _is_circuit_open() -> bool:
    """Check if the circuit breaker is currently open."""
    global _consecutive_failures, _last_failure_time
    if _consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
        elapsed = time.monotonic() - _last_failure_time
        if elapsed > _CIRCUIT_BREAKER_COOLDOWN:
            # Half-open: allow ONE trial request; if it fails the breaker re-opens immediately
            _consecutive_failures = _CIRCUIT_BREAKER_THRESHOLD - 1
            return False
        return True
    return False


def _record_success() -> None:
    """Reset circuit breaker failure counter on success."""
    global _consecutive_failures, _last_failure_time
    _consecutive_failures = 0
    _last_failure_time = 0.0


def _record_failure() -> None:
    """Increment failure counter and record timestamp."""
    global _consecutive_failures, _last_failure_time
    _consecutive_failures += 1
    _last_failure_time = time.monotonic()


def truncate_text(text: str, max_chars: int = 1000) -> str:
    """Safely truncate text to max_chars characters to fit within TEI token limits (~512 tokens).

    Args:
        text: Input string to truncate.
        max_chars: Maximum allowed character length (default: 1000).

    Returns:
        str: Truncated text string.
    """
    if not text:
        return ""
    if len(text) > max_chars:
        return text[:max_chars]
    return text


_WORD = re.compile(r"\w{3,}")


def rerank_text(doc: dict[str, Any], query: str, max_chars: int, mode: str = "content") -> str:
    """The text the cross-encoder reads for one candidate.

    ``content`` (default): the stored text, ingestion prefix included, cut to ``max_chars``. ``titled_raw``: section title and the
    raw text, so the characters go to the document, not to ``[Source: ...]``. ``window``: the ``max_chars`` window of the raw text
    that shares most words with the query (a chunk of up to 6000 characters is otherwise judged by its first 1000).
    """
    raw: str = doc.get("raw_content") or doc.get("content", "")
    if mode == "passage":  # the passage the search matched; a chunk without one (found by keywords only) falls back to its best window
        if doc.get("best_passage"):
            return truncate_text(doc["best_passage"], max_chars)
        mode = "window"
    if mode == "titled_raw" and doc.get("raw_content"):
        return truncate_text(f"{doc.get('section_title') or ''}\n{raw}".strip(), max_chars)
    if mode == "window" and len(raw) > max_chars:
        terms = set(_WORD.findall(query.lower()))
        best_start, best_hits = 0, -1
        for start in range(0, len(raw) - max_chars + 250, 250):
            window = raw[start:start + max_chars].lower()
            hits = sum(1 for t in terms if t in window)
            if hits > best_hits:
                best_start, best_hits = start, hits
        return raw[best_start:best_start + max_chars]
    return truncate_text(doc.get("content", ""), max_chars=max_chars)


async def _score(
    query: str,
    docs: List[dict[str, Any]],
    max_chars: int,
    budget: float,
    endpoint: Optional[str],
    session_id: str,
) -> Optional[List[dict[str, Any]]]:
    """One TEI call: ``docs`` (texts cut to ``max_chars``) scored against ``query`` within ``budget`` seconds.

    Returns copies of the documents with ``rerank_score``, best first; ``None`` on failure or timeout
    (the circuit breaker is updated either way).
    """
    payload: dict[str, Any] = {
        "query": truncate_text(query, max_chars=max_chars) if query else "",
        "texts": [rerank_text(doc, query, max_chars, getattr(settings, "RERANK_TEXT_MODE", "content")) for doc in docs],
        "truncate": True,
    }

    # Candidate endpoints for automatic container vs local resolution
    unique_urls: List[str] = list(dict.fromkeys([endpoint or settings.RERANKER_ENDPOINT, *settings.RERANKER_FALLBACK_ENDPOINTS]))

    async def _first_working() -> tuple[Optional[str], Optional[List[dict[str, Any]]], Optional[Exception]]:
        error: Optional[Exception] = None
        for url in unique_urls:
            try:
                async with httpx.AsyncClient(timeout=budget) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    return url, response.json(), None
            except Exception as exc:  # noqa: BLE001 - try the next endpoint
                error = exc
        return None, None, error

    # One TOTAL budget for every endpoint: httpx timeouts do not cover DNS resolution, so an unresolvable
    # host used to cost seconds per endpoint (and 30 s per query with RERANKER_TIMEOUT=30).
    working_url: Optional[str] = None
    results: Optional[List[dict[str, Any]]] = None
    last_exc: Optional[Exception] = None
    try:
        working_url, results, last_exc = await asyncio.wait_for(_first_working(), timeout=max(budget, 0.05))
    except asyncio.TimeoutError:
        last_exc = TimeoutError(f"reranker did not answer within {budget:g}s")

    if results is None:
        _record_failure()
        logger.warning(
            "TEI Reranker service call failed (%s: %s).",
            type(last_exc).__name__ if last_exc else "Error",
            last_exc,
            extra={"session_id": session_id},
        )
        return None

    _record_success()

    # TEI reranker returns a list of items: [{"index": 0, "score": 0.95}, ...]
    scored: List[dict[str, Any]] = []
    for item in results:
        idx: Optional[int] = item.get("index")
        if idx is not None and 0 <= idx < len(docs):
            doc_copy: dict[str, Any] = dict(docs[idx])
            doc_copy["rerank_score"] = float(item.get("score", 0.0))
            scored.append(doc_copy)
    scored.sort(key=lambda d: d.get("rerank_score", 0.0), reverse=True)
    logger.debug("TEI Reranker scored %d texts (endpoint=%s)", len(docs), working_url, extra={"session_id": session_id})
    return scored


def _confident(documents: List[dict[str, Any]]) -> bool:
    """Does the first fused candidate lead so clearly that the cross-encoder would not change the top? Off unless configured."""
    floor = getattr(settings, "RERANK_SKIP_MIN_SCORE", 0.0)
    if not floor or len(documents) < 2:
        return False
    first, second = documents[0].get("vector_score") or 0.0, documents[1].get("vector_score") or 0.0
    return first >= floor and first - second >= getattr(settings, "RERANK_SKIP_MARGIN", 0.0)


async def rerank_documents(
    query: str,
    documents: List[dict[str, Any]],
    endpoint: Optional[str] = None,
    top_k: Optional[int] = None,
    session_id: str = "N/A",
) -> List[dict[str, Any]]:
    """Send candidate documents to TEI Reranker service and return top_k reranked items.

    Args:
        query: User search query or HyDE query string.
        documents: List of document dicts (each containing 'content').
        endpoint: TEI Reranker URL (defaults to settings.RERANKER_ENDPOINT).
        top_k: Number of top documents to return (defaults to settings.RERANK_TOP_K).
        session_id: Correlation ID for logging.

    Returns:
        List[dict[str, Any]]: Top_k reranked documents with updated 'rerank_score'.
        Falls back to original documents cut to top_k on failure or timeout.
    """
    if not documents:
        return []

    target_top_k: int = top_k if top_k is not None else settings.RERANK_TOP_K

    if _confident(documents):
        logger.info("Rerank skipped: the first candidate leads clearly (cosine %.2f)", documents[0].get("vector_score") or 0.0, extra={"session_id": session_id})
        return documents[:target_top_k]

    # Circuit breaker early exit
    if _is_circuit_open():
        logger.warning(
            "TEI Reranker circuit breaker is OPEN (consecutive_failures=%d). Skipping HTTP call.",
            _consecutive_failures,
            extra={"session_id": session_id},
        )
        return documents[:target_top_k]

    pool: List[dict[str, Any]] = documents[: getattr(settings, "RERANK_POOL_K", 10)]
    max_chars: int = getattr(settings, "MAX_RERANK_TEXT_LENGTH", 1000)
    budget: float = getattr(settings, "RERANKER_TIMEOUT", 4.0)

    ranked: Optional[List[dict[str, Any]]] = await _score(query, pool, max_chars, budget, endpoint, session_id)
    if ranked is None:
        logger.warning("Falling back to top %d hybrid search results.", target_top_k, extra={"session_id": session_id})
        return pool[:target_top_k]

    top_docs: List[dict[str, Any]] = ranked[:target_top_k]
    logger.info(
        "TEI Reranker successfully reranked %d candidates down to top %d",
        len(pool), len(top_docs),
        extra={"session_id": session_id},
    )
    return top_docs
