"""Embedding & Deduplication module.

Embeds document chunks using ``text-embedding-3-small`` via LangChain's
OpenAI integration, then removes near-duplicate chunks whose cosine
similarity exceeds a configurable threshold (default 0.90).

Usage:
    from src.embedder import embed_and_deduplicate
    unique_chunks, embeddings = embed_and_deduplicate(chunks, api_key=...)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from langchain_openai import OpenAIEmbeddings

from src.chunker import DocumentChunk

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEDUP_THRESHOLD: float = 0.90   # Cosine similarity above this → duplicate
EMBEDDING_BATCH_SIZE: int = 100  # Batch size for OpenAI embedding calls


# ---------------------------------------------------------------------------
# Cosine similarity helpers
# ---------------------------------------------------------------------------


def _cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    """Compute the pairwise cosine similarity matrix for a set of vectors.

    Args:
        vectors: 2-D array of shape ``(n, dim)``.

    Returns:
        Symmetric ``(n, n)`` similarity matrix with values in ``[-1, 1]``.
    """
    # Normalise each row to unit length
    norms: np.ndarray = np.linalg.norm(vectors, axis=1, keepdims=True)
    # Avoid division by zero
    norms = np.where(norms == 0, 1, norms)
    normalised: np.ndarray = vectors / norms
    similarity: np.ndarray = normalised @ normalised.T
    return similarity


def _find_duplicates(
    similarity_matrix: np.ndarray,
    threshold: float = DEDUP_THRESHOLD,
) -> set[int]:
    """Identify indices of duplicate vectors that should be removed.

    For each pair ``(i, j)`` where ``i < j`` and
    ``similarity(i, j) > threshold``, index ``j`` is marked for removal
    (keeping the earlier occurrence).

    Args:
        similarity_matrix: Square cosine similarity matrix.
        threshold: Similarity above which a pair is considered duplicate.

    Returns:
        Set of indices to remove.
    """
    n: int = similarity_matrix.shape[0]
    to_remove: set[int] = set()

    for i in range(n):
        if i in to_remove:
            continue
        for j in range(i + 1, n):
            if j in to_remove:
                continue
            if similarity_matrix[i, j] > threshold:
                to_remove.add(j)

    return to_remove


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_embeddings_model(
    api_key: str,
    base_url: str | None = None,
    model: str = "text-embedding-3-small",
) -> OpenAIEmbeddings:
    """Create a configured ``OpenAIEmbeddings`` instance.

    Args:
        api_key: OpenAI or OpenRouter API key.
        base_url: Optional base URL override (e.g. OpenRouter endpoint).
        model: The embedding model name.

    Returns:
        Configured ``OpenAIEmbeddings`` object.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "openai_api_key": api_key,
    }
    if base_url:
        kwargs["openai_api_base"] = base_url

    return OpenAIEmbeddings(**kwargs)


def embed_chunks(
    chunks: list[DocumentChunk],
    embeddings_model: OpenAIEmbeddings,
    batch_size: int = EMBEDDING_BATCH_SIZE,
) -> np.ndarray:
    """Embed all chunks and return the embedding matrix.

    Args:
        chunks: List of document chunks.
        embeddings_model: Configured LangChain embeddings model.
        batch_size: Number of texts to embed per API call.

    Returns:
        2-D numpy array of shape ``(len(chunks), embedding_dim)``.
    """
    all_embeddings: list[list[float]] = []
    texts: list[str] = [chunk.content for chunk in chunks]
    total: int = len(texts)

    for start in range(0, total, batch_size):
        end: int = min(start + batch_size, total)
        batch: list[str] = texts[start:end]
        logger.info(
            "Embedding batch %d-%d / %d", start + 1, end, total
        )
        try:
            batch_embeddings: list[list[float]] = embeddings_model.embed_documents(
                batch
            )
            all_embeddings.extend(batch_embeddings)
        except Exception as exc:
            logger.error(
                "Embedding failed for batch %d-%d: %s", start + 1, end, exc
            )
            raise

    return np.array(all_embeddings, dtype=np.float32)


def deduplicate_chunks(
    chunks: list[DocumentChunk],
    embeddings: np.ndarray,
    threshold: float = DEDUP_THRESHOLD,
) -> tuple[list[DocumentChunk], np.ndarray, int]:
    """Remove near-duplicate chunks based on cosine similarity.

    Args:
        chunks: List of document chunks.
        embeddings: Corresponding embedding matrix.
        threshold: Cosine similarity above which chunks are considered
            duplicates.

    Returns:
        Tuple of ``(unique_chunks, unique_embeddings, removed_count)``.
    """
    logger.info(
        "Computing cosine similarity matrix for %d chunks…", len(chunks)
    )
    sim_matrix: np.ndarray = _cosine_similarity_matrix(embeddings)

    duplicates: set[int] = _find_duplicates(sim_matrix, threshold)
    removed_count: int = len(duplicates)

    # Build filtered lists
    unique_chunks: list[DocumentChunk] = []
    unique_indices: list[int] = []
    for idx, chunk in enumerate(chunks):
        if idx not in duplicates:
            unique_chunks.append(chunk)
            unique_indices.append(idx)

    unique_embeddings: np.ndarray = embeddings[unique_indices]

    logger.info(
        "Deduplication complete: %d → %d chunks (%d removed, threshold=%.2f)",
        len(chunks),
        len(unique_chunks),
        removed_count,
        threshold,
    )
    return unique_chunks, unique_embeddings, removed_count


def embed_and_deduplicate(
    chunks: list[DocumentChunk],
    api_key: str,
    base_url: str | None = None,
    model: str = "text-embedding-3-small",
    threshold: float = DEDUP_THRESHOLD,
) -> tuple[list[DocumentChunk], np.ndarray, int]:
    """End-to-end: embed all chunks, then deduplicate.

    Args:
        chunks: Document chunks to process.
        api_key: OpenAI / OpenRouter API key.
        base_url: Optional API base URL.
        model: Embedding model name.
        threshold: Deduplication cosine similarity threshold.

    Returns:
        Tuple of ``(unique_chunks, unique_embeddings, removed_count)``.
    """
    embeddings_model: OpenAIEmbeddings = create_embeddings_model(
        api_key=api_key, base_url=base_url, model=model
    )
    embeddings: np.ndarray = embed_chunks(chunks, embeddings_model)
    return deduplicate_chunks(chunks, embeddings, threshold)
