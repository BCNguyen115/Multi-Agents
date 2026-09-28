"""TEI Reranker client module.

Sends candidate text documents to HuggingFace TEI (Text Embeddings Inference)
Reranker endpoint for high-precision cross-encoder re-ranking.

Usage:
    from src.shared.reranker_client import rerank_documents

    reranked_docs = await rerank_documents(
        query="What is the NDA clause?",
        documents=candidate_docs,
        top_k=5,
        session_id="abc"
    )
"""

import logging
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
            # Half-open: allow a trial request
            _consecutive_failures = 0
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

    # Circuit breaker early exit
    if _is_circuit_open():
        logger.warning(
            "TEI Reranker circuit breaker is OPEN (consecutive_failures=%d). Skipping HTTP call.",
            _consecutive_failures,
            extra={"session_id": session_id},
        )
        return documents[:target_top_k]

    target_endpoint: str = endpoint or settings.RERANKER_ENDPOINT
    target_top_k: int = top_k if top_k is not None else settings.RERANK_TOP_K
    candidates_limit: int = getattr(settings, "HYBRID_CANDIDATES_K", 10)
    max_chars: int = getattr(settings, "MAX_RERANK_TEXT_LENGTH", 500)
    reranker_timeout: float = getattr(settings, "RERANKER_TIMEOUT", 0.8)  # Circuit breaker: 800ms hard timeout

    # Limit candidate documents pool to max candidates_limit (e.g. 10) to optimize CPU inference speed
    candidate_docs: List[dict[str, Any]] = documents[:candidates_limit]

    # Safely truncate candidate texts and query to fit within TEI token limits (~512 tokens)
    texts: List[str] = [
        truncate_text(doc.get("content", ""), max_chars=max_chars)
        for doc in candidate_docs
    ]
    truncated_query: str = truncate_text(query, max_chars=max_chars) if query else ""

    payload: dict[str, Any] = {
        "query": truncated_query,
        "texts": texts,
        "truncate": True,
    }

    # Candidate endpoints for automatic container vs local resolution
    candidate_urls: List[str] = [
        target_endpoint,
        "http://tei-reranker:80/rerank",
        "http://localhost:8080/rerank",
        "http://127.0.0.1:8080/rerank",
    ]
    seen_urls: set[str] = set()
    unique_urls: List[str] = []
    for u in candidate_urls:
        if u not in seen_urls:
            seen_urls.add(u)
            unique_urls.append(u)

    working_url: Optional[str] = None
    results: Optional[List[dict[str, Any]]] = None
    last_exc: Optional[Exception] = None

    for url in unique_urls:
        try:
            async with httpx.AsyncClient(timeout=reranker_timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                results = response.json()
                working_url = url
                break
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError, Exception) as exc:
            last_exc = exc
            continue

    if results is None:
        _record_failure()
        logger.warning(
            "TEI Reranker service call failed (%s: %s). Falling back to top %d hybrid search results.",
            type(last_exc).__name__ if last_exc else "Error",
            last_exc,
            target_top_k,
            extra={"session_id": session_id},
        )
        return candidate_docs[:target_top_k]

    _record_success()

    # TEI reranker returns a list of items: [{"index": 0, "score": 0.95}, ...]
    reranked_docs: List[dict[str, Any]] = []
    for item in results:
        idx: Optional[int] = item.get("index")
        score: float = float(item.get("score", 0.0))
        if idx is not None and 0 <= idx < len(candidate_docs):
            doc_copy: dict[str, Any] = dict(candidate_docs[idx])
            doc_copy["rerank_score"] = score
            reranked_docs.append(doc_copy)

    # Sort descending by rerank_score
    reranked_docs.sort(key=lambda d: d.get("rerank_score", 0.0), reverse=True)
    top_docs: List[dict[str, Any]] = reranked_docs[:target_top_k]

    logger.info(
        "TEI Reranker successfully reranked %d candidates down to top %d (endpoint=%s)",
        len(candidate_docs),
        len(top_docs),
        working_url,
        extra={"session_id": session_id},
    )
    return top_docs
