"""Embedding, Deduplication & pgvector Storage module.

Embeds document chunks using ``text-embedding-3-small`` via the OpenAI
async client, removes near-duplicate chunks (cosine similarity > 0.90),
and stores unique chunks directly into PostgreSQL (pgvector).

Usage:
    from src.ingestion.embedder import IngestionEmbedder
    embedder = IngestionEmbedder(pg_client=pg, openai_client=client)
    await embedder.ensure_table()
    stats = await embedder.embed_deduplicate_and_store(chunks)
"""

from __future__ import annotations

import json
import logging
from typing import Any, List

import numpy as np
import openai

from src.ingestion.chunker import DocumentChunk
from src.shared.logger import get_logger
from src.shared.postgres_client import PostgresClient

logger: logging.Logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
EMBEDDING_DIM: int = 1536
DEDUP_THRESHOLD: float = 0.90
EMBEDDING_BATCH_SIZE: int = 100

# ---------------------------------------------------------------------------
# SQL templates
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL: str = f"""
CREATE TABLE IF NOT EXISTS rag_chunks (
    id               BIGSERIAL PRIMARY KEY,
    content          TEXT NOT NULL,
    raw_content      TEXT NOT NULL,
    embedding        VECTOR({EMBEDDING_DIM}),
    filename         TEXT,
    category         TEXT,
    section_title    TEXT,
    detected_pattern TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
"""

_CREATE_INDEX_SQL: str = """
CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding
    ON rag_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
"""

_INSERT_CHUNK_SQL: str = """
INSERT INTO rag_chunks (content, raw_content, embedding, filename, category,
                        section_title, detected_pattern)
VALUES ($1, $2, $3::vector, $4, $5, $6, $7);
"""

_COUNT_CHUNKS_SQL: str = """
SELECT COUNT(*) AS cnt FROM rag_chunks;
"""

_TRUNCATE_SQL: str = """
TRUNCATE TABLE rag_chunks;
"""


# ---------------------------------------------------------------------------
# Cosine similarity helpers
# ---------------------------------------------------------------------------


def _cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    """Compute pairwise cosine similarity matrix.

    Args:
        vectors: 2-D array of shape ``(n, dim)``.

    Returns:
        Symmetric ``(n, n)`` similarity matrix.
    """
    norms: np.ndarray = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normalised: np.ndarray = vectors / norms
    return normalised @ normalised.T


def _find_duplicates(
    similarity_matrix: np.ndarray,
    threshold: float = DEDUP_THRESHOLD,
) -> set[int]:
    """Identify indices of duplicate vectors to remove.

    For each pair ``(i, j)`` where ``i < j`` and similarity exceeds
    threshold, index ``j`` is marked for removal.

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
# Main class
# ---------------------------------------------------------------------------


class IngestionEmbedder:
    """Handles embedding, deduplication, and pgvector storage.

    Attributes:
        pg: Shared PostgreSQL async client.
        openai_client: OpenAI-compatible async client for embeddings.
        model: Embedding model name.
    """

    def __init__(
        self,
        pg: PostgresClient,
        openai_client: openai.AsyncOpenAI,
        model: str = EMBEDDING_MODEL,
    ) -> None:
        """Initialise the ingestion embedder.

        Args:
            pg: Connected ``PostgresClient`` instance.
            openai_client: Configured ``openai.AsyncOpenAI``.
            model: Embedding model identifier.
        """
        self.pg: PostgresClient = pg
        self.openai_client: openai.AsyncOpenAI = openai_client
        self.model: str = model

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    async def ensure_table(self, session_id: str = "INGESTION") -> None:
        """Create the ``rag_chunks`` table and index if not exists.

        Args:
            session_id: Correlation ID for logging.
        """
        try:
            await self.pg.execute(_CREATE_TABLE_SQL, session_id=session_id)
            # ivfflat index needs rows first for training, so we create it
            # but it may fail on empty table — that's acceptable
            try:
                await self.pg.execute(_CREATE_INDEX_SQL, session_id=session_id)
            except Exception:
                logger.debug(
                    "ivfflat index creation deferred (table may be empty)",
                    extra={"session_id": session_id},
                )
            logger.info(
                "rag_chunks table verified / created",
                extra={"session_id": session_id},
            )
        except Exception as exc:
            logger.error(
                "Failed to create rag_chunks table: %s",
                exc,
                extra={"session_id": session_id},
            )
            raise

    async def clear_table(self, session_id: str = "INGESTION") -> None:
        """Truncate the ``rag_chunks`` table for a fresh ingestion run.

        Args:
            session_id: Correlation ID for logging.
        """
        await self.pg.execute(_TRUNCATE_SQL, session_id=session_id)
        logger.info(
            "rag_chunks table truncated",
            extra={"session_id": session_id},
        )

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    async def _embed_batch(
        self,
        texts: list[str],
        session_id: str = "INGESTION",
    ) -> list[list[float]]:
        """Embed a batch of texts via the OpenAI API.

        Args:
            texts: List of text strings to embed.
            session_id: Correlation ID.

        Returns:
            List of embedding vectors.
        """
        try:
            response: Any = await self.openai_client.embeddings.create(
                model=self.model,
                input=texts,
            )
            embeddings: list[list[float]] = [
                item.embedding for item in response.data
            ]
            return embeddings
        except openai.APIError as exc:
            logger.error(
                "Embedding API call failed: %s",
                exc,
                extra={"session_id": session_id},
            )
            raise

    async def embed_all_chunks(
        self,
        chunks: list[DocumentChunk],
        batch_size: int = EMBEDDING_BATCH_SIZE,
        session_id: str = "INGESTION",
    ) -> np.ndarray:
        """Embed all chunks in batches and return the embedding matrix.

        Args:
            chunks: List of document chunks.
            batch_size: Number of texts per API call.
            session_id: Correlation ID.

        Returns:
            2-D numpy array of shape ``(len(chunks), EMBEDDING_DIM)``.
        """
        all_embeddings: list[list[float]] = []
        texts: list[str] = [chunk.content for chunk in chunks]
        total: int = len(texts)

        for start in range(0, total, batch_size):
            end: int = min(start + batch_size, total)
            batch: list[str] = texts[start:end]
            logger.info(
                "Embedding batch %d-%d / %d",
                start + 1,
                end,
                total,
                extra={"session_id": session_id},
            )
            batch_embeddings: list[list[float]] = await self._embed_batch(
                batch, session_id=session_id
            )
            all_embeddings.extend(batch_embeddings)

        return np.array(all_embeddings, dtype=np.float32)

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def deduplicate(
        self,
        chunks: list[DocumentChunk],
        embeddings: np.ndarray,
        threshold: float = DEDUP_THRESHOLD,
        session_id: str = "INGESTION",
    ) -> tuple[list[DocumentChunk], np.ndarray, int]:
        """Remove near-duplicate chunks based on cosine similarity.

        Args:
            chunks: List of document chunks.
            embeddings: Corresponding embedding matrix.
            threshold: Cosine similarity above which chunks are duplicates.
            session_id: Correlation ID.

        Returns:
            Tuple of ``(unique_chunks, unique_embeddings, removed_count)``.
        """
        logger.info(
            "Computing cosine similarity matrix for %d chunks...",
            len(chunks),
            extra={"session_id": session_id},
        )
        sim_matrix: np.ndarray = _cosine_similarity_matrix(embeddings)
        duplicates: set[int] = _find_duplicates(sim_matrix, threshold)
        removed_count: int = len(duplicates)

        unique_chunks: list[DocumentChunk] = []
        unique_indices: list[int] = []
        for idx, chunk in enumerate(chunks):
            if idx not in duplicates:
                unique_chunks.append(chunk)
                unique_indices.append(idx)

        unique_embeddings: np.ndarray = embeddings[unique_indices]

        logger.info(
            "Deduplication: %d -> %d chunks (%d removed, threshold=%.2f)",
            len(chunks),
            len(unique_chunks),
            removed_count,
            threshold,
            extra={"session_id": session_id},
        )
        return unique_chunks, unique_embeddings, removed_count

    # ------------------------------------------------------------------
    # pgvector storage
    # ------------------------------------------------------------------

    async def store_chunks(
        self,
        chunks: list[DocumentChunk],
        embeddings: np.ndarray,
        session_id: str = "INGESTION",
    ) -> int:
        """Insert deduplicated chunks into the ``rag_chunks`` pgvector table.

        Args:
            chunks: Unique document chunks.
            embeddings: Corresponding embedding matrix.
            session_id: Correlation ID.

        Returns:
            Number of chunks inserted.
        """
        inserted: int = 0

        for i, chunk in enumerate(chunks):
            embedding_str: str = json.dumps(embeddings[i].tolist())
            meta: dict[str, Any] = chunk.metadata

            try:
                await self.pg.execute(
                    _INSERT_CHUNK_SQL,
                    chunk.content,
                    chunk.raw_content,
                    embedding_str,
                    meta.get("filename", ""),
                    meta.get("category", ""),
                    meta.get("section_title", ""),
                    meta.get("detected_pattern", ""),
                    session_id=session_id,
                )
                inserted += 1
            except Exception as exc:
                logger.error(
                    "Failed to insert chunk %d: %s",
                    i,
                    exc,
                    extra={"session_id": session_id},
                )

        logger.info(
            "Inserted %d chunks into rag_chunks",
            inserted,
            extra={"session_id": session_id},
        )

        # Try to create ivfflat index now that we have data
        try:
            await self.pg.execute(_CREATE_INDEX_SQL, session_id=session_id)
            logger.info(
                "ivfflat index created on rag_chunks",
                extra={"session_id": session_id},
            )
        except Exception:
            logger.debug(
                "ivfflat index creation skipped (may already exist or too few rows)",
                extra={"session_id": session_id},
            )

        return inserted

    # ------------------------------------------------------------------
    # End-to-end pipeline
    # ------------------------------------------------------------------

    async def embed_deduplicate_and_store(
        self,
        chunks: list[DocumentChunk],
        session_id: str = "INGESTION",
    ) -> dict[str, int]:
        """Full pipeline: embed -> deduplicate -> store in pgvector.

        Args:
            chunks: Document chunks from the chunker.
            session_id: Correlation ID.

        Returns:
            Dictionary with statistics:
            ``{"total_before": ..., "total_after": ..., "removed": ..., "inserted": ...}``
        """
        # Step 1: Embed
        embeddings: np.ndarray = await self.embed_all_chunks(
            chunks, session_id=session_id
        )

        # Step 2: Deduplicate
        unique_chunks: list[DocumentChunk]
        unique_embeddings: np.ndarray
        removed: int
        unique_chunks, unique_embeddings, removed = self.deduplicate(
            chunks, embeddings, session_id=session_id
        )

        # Step 3: Clear old data and store
        await self.clear_table(session_id=session_id)
        inserted: int = await self.store_chunks(
            unique_chunks, unique_embeddings, session_id=session_id
        )

        return {
            "total_before": len(chunks),
            "total_after": len(unique_chunks),
            "removed": removed,
            "inserted": inserted,
        }
