"""Embedding, per-document deduplication & pgvector storage (incremental).

A document is (re)ingested only when its content hash changed; its old chunks are replaced in ONE
transaction, so a failure never leaves a half-loaded document behind. Near-duplicate chunks are removed
*within* a document only: the same clause in two different contracts must stay retrievable (and citable)
from both.

Usage:
    embedder = IngestionEmbedder(pg=pg, openai_client=client)
    await embedder.ensure_schema()
    stats = await embedder.ingest(chunks)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
import openai

from src.agents.data_agent.i18n import detect_language
from src.config import settings
from src.ingestion.chunker import DocumentChunk
from src.ingestion.passages import split_passages
from src.ingestion.schema import ensure_schema
from src.shared.logger import get_logger
from src.shared.postgres_client import PostgresClient

logger: logging.Logger = get_logger(__name__)

DEDUP_THRESHOLD: float = 0.95
EMBEDDING_BATCH_SIZE: int = 100

_INSERT_CHUNK_SQL: str = """
INSERT INTO rag_chunks (content, raw_content, embedding, filename, category, section_title,
                        detected_pattern, doc_key, doc_hash, chunk_index, page, lang)
VALUES ($1, $2, $3::vector, $4, $5, $6, $7, $8, $9, $10, $11, $12);
"""

_INSERT_CHUNK_RETURNING_SQL: str = _INSERT_CHUNK_SQL.rstrip().rstrip(";") + " RETURNING id;"

_INSERT_PASSAGE_SQL: str = """
INSERT INTO rag_passages (chunk_id, position, content, embedding) VALUES ($1, $2, $3, $4::vector);
"""

# Also removes rows written before doc_key existed (matched by category + filename)
_DELETE_DOC_SQL: str = """
DELETE FROM rag_chunks
WHERE doc_key = $1 OR (doc_key IS NULL AND category = $2 AND filename = $3);
"""


def _cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    """Pairwise cosine similarity, shape ``(n, n)``."""
    norms: np.ndarray = np.linalg.norm(vectors, axis=1, keepdims=True)
    normalised: np.ndarray = vectors / np.where(norms == 0, 1, norms)
    return normalised @ normalised.T


def _find_duplicates(similarity_matrix: np.ndarray, threshold: float = DEDUP_THRESHOLD) -> set[int]:
    """Indices to drop: for each pair ``i < j`` above ``threshold`` the later chunk ``j`` is removed."""
    n: int = similarity_matrix.shape[0]
    to_remove: set[int] = set()
    for i in range(n):
        if i in to_remove:
            continue
        for j in np.nonzero(similarity_matrix[i, i + 1:] > threshold)[0] + i + 1:
            to_remove.add(int(j))
    return to_remove


def _doc_key(chunk: DocumentChunk) -> str:
    meta: dict[str, Any] = chunk.metadata
    return str(meta.get("doc_key") or f"{meta.get('category', '')}/{meta.get('filename', '')}")


class IngestionEmbedder:
    """Embeds chunks and keeps ``rag_chunks`` in sync with the dataset folder."""

    def __init__(self, pg: PostgresClient, openai_client: openai.AsyncOpenAI, model: str | None = None) -> None:
        self.pg: PostgresClient = pg
        self.openai_client: openai.AsyncOpenAI = openai_client
        self.model: str = model or settings.EMBEDDING_MODEL

    async def ensure_schema(self, session_id: str = "INGESTION") -> None:
        await ensure_schema(self.pg, session_id=session_id)

    @property
    def embedding_label(self) -> str:
        """What identifies the vector space: the model and, when it is cut down, the size."""
        return f"{self.model}|{settings.EMBEDDING_DIMENSIONS or 'default'}"

    async def _guard_embedding_model(self, session_id: str = "INGESTION") -> None:
        """One corpus, one embedding model: vectors of two models are not comparable and search would quietly degrade.
        Records the model on first use; raises when a different one is asked for (re-embed everything: run_ingestion --reset)."""
        try:
            rows = await self.pg.fetch("SELECT value FROM rag_meta WHERE key = 'embedding_model'", session_id=session_id)
            stored: str | None = rows[0]["value"] if rows else None
        except Exception as exc:  # noqa: BLE001 - the table comes with migration 0007; before that there is nothing to guard
            logger.warning("Could not read rag_meta (%s); the embedding model is not checked", exc, extra={"session_id": session_id})
            return
        if stored is not None and stored != self.embedding_label:
            raise RuntimeError(
                f"the corpus was embedded with {stored!r} but this run uses {self.embedding_label!r}: "
                "re-embed the whole corpus with `python -m scripts.run_ingestion --reset`"
            )
        if stored is None:
            try:
                await self.pg.execute(
                    "INSERT INTO rag_meta (key, value) VALUES ('embedding_model', $1) ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = NOW()",
                    self.embedding_label, session_id=session_id,
                )
            except Exception as exc:  # noqa: BLE001 - recording is a safeguard, never a reason to refuse a document
                logger.warning("Could not record the embedding model: %s", exc, extra={"session_id": session_id})

    async def clear_table(self, session_id: str = "INGESTION") -> None:
        await self.pg.execute("TRUNCATE TABLE rag_chunks CASCADE;", session_id=session_id)  # CASCADE: rag_passages references it
        try:  # an empty corpus has no model yet: the next ingestion decides
            await self.pg.execute("DELETE FROM rag_meta WHERE key = 'embedding_model'", session_id=session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not clear rag_meta: %s", exc, extra={"session_id": session_id})
        logger.info("rag_chunks truncated", extra={"session_id": session_id})

    async def existing_documents(self, session_id: str = "INGESTION") -> dict[str, str]:
        """``{doc_key: doc_hash}`` of documents already stored (rows without a hash are treated as stale)."""
        rows = await self.pg.fetch(
            "SELECT doc_key, max(doc_hash) AS doc_hash FROM rag_chunks WHERE doc_key IS NOT NULL GROUP BY doc_key;",
            session_id=session_id,
        )
        return {r["doc_key"]: r["doc_hash"] for r in rows if r["doc_hash"]}

    # ------------------------------------------------------------------ embedding

    async def _embed_batch(self, texts: list[str], session_id: str = "INGESTION") -> list[list[float]]:
        try:
            dimensions: dict[str, int] = {"dimensions": settings.EMBEDDING_DIMENSIONS} if settings.EMBEDDING_DIMENSIONS else {}
            response: Any = await self.openai_client.embeddings.create(model=self.model, input=texts, **dimensions)
            return [item.embedding for item in response.data]
        except openai.APIError as exc:
            logger.error("Embedding API call failed: %s", exc, extra={"session_id": session_id})
            raise

    async def embed_all_chunks(
        self, chunks: list[DocumentChunk], batch_size: int = EMBEDDING_BATCH_SIZE, session_id: str = "INGESTION"
    ) -> np.ndarray:
        """Embed ``chunks`` in batches -> array ``(len(chunks), dim)``."""
        texts: list[str] = [chunk.content for chunk in chunks]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            vectors.extend(await self._embed_batch(texts[start:start + batch_size], session_id=session_id))
        return np.array(vectors, dtype=np.float32)

    def deduplicate(
        self, chunks: list[DocumentChunk], embeddings: np.ndarray, threshold: float = DEDUP_THRESHOLD
    ) -> tuple[list[DocumentChunk], np.ndarray, int]:
        """Drop near-duplicates among ``chunks`` (call per document). Returns ``(chunks, embeddings, removed)``."""
        if len(chunks) < 2:
            return chunks, embeddings, 0
        duplicates: set[int] = _find_duplicates(_cosine_similarity_matrix(embeddings), threshold)
        keep: list[int] = [i for i in range(len(chunks)) if i not in duplicates]
        return [chunks[i] for i in keep], embeddings[keep], len(duplicates)

    # ------------------------------------------------------------------ storage

    async def replace_document(
        self, doc_key: str, chunks: list[DocumentChunk], embeddings: np.ndarray, session_id: str = "INGESTION"
    ) -> int:
        """Atomically replace every stored chunk of one document. Returns the number of inserted chunks."""
        first: dict[str, Any] = chunks[0].metadata
        rows: list[tuple[Any, ...]] = []
        for chunk, vector in zip(chunks, embeddings):
            m: dict[str, Any] = chunk.metadata
            rows.append((
                chunk.content, chunk.raw_content, json.dumps(vector.tolist()), m.get("filename", ""), m.get("category", ""),
                m.get("section_title", ""), m.get("detected_pattern", ""), doc_key, m.get("doc_hash"), m.get("chunk_index"), m.get("page"),
                detect_language(chunk.raw_content[:600]),
            ))
        passages: list[tuple[int, int, str]] = []  # (index of the chunk, position, text)
        if settings.RAG_INDEX_PASSAGES:
            for index, chunk in enumerate(chunks):
                passages += [(index, position, text) for position, text in enumerate(split_passages(chunk.raw_content))]
        passage_vectors: list[list[float]] = []
        for start in range(0, len(passages), EMBEDDING_BATCH_SIZE):  # the network part first: the transaction stays short
            passage_vectors.extend(await self._embed_batch([p[2] for p in passages[start:start + EMBEDDING_BATCH_SIZE]], session_id=session_id))
        async with self.pg.transaction() as conn:
            await conn.execute(_DELETE_DOC_SQL, doc_key, first.get("category", ""), first.get("filename", ""))
            if passages:
                ids = [await conn.fetchval(_INSERT_CHUNK_RETURNING_SQL, *row) for row in rows]
                await conn.executemany(_INSERT_PASSAGE_SQL, [(ids[i], pos, text, json.dumps(vec)) for (i, pos, text), vec in zip(passages, passage_vectors)])
            else:
                await conn.executemany(_INSERT_CHUNK_SQL, rows)
        return len(rows)

    async def prune(self, keep_keys: set[str], session_id: str = "INGESTION") -> int:
        """Delete documents that are no longer in the dataset folder. Returns the number of deleted chunks."""
        result: str = await self.pg.execute(
            "DELETE FROM rag_chunks WHERE doc_key IS NULL OR NOT (doc_key = ANY($1::text[]));", sorted(keep_keys), session_id=session_id
        )
        return int(result.split()[-1])

    # ------------------------------------------------------------------ pipeline

    async def ingest(self, chunks: list[DocumentChunk], prune: bool = False, session_id: str = "INGESTION") -> dict[str, Any]:
        """Bring the table in line with ``chunks``: unchanged documents are skipped, changed ones replaced.

        One failing document does not stop the others; it is reported in ``failed`` so the caller can exit non-zero.
        """
        by_doc: dict[str, list[DocumentChunk]] = {}
        for chunk in chunks:
            by_doc.setdefault(_doc_key(chunk), []).append(chunk)
        await self._guard_embedding_model(session_id)

        stored: dict[str, str] = await self.existing_documents(session_id)
        stats: dict[str, Any] = {
            "docs_total": len(by_doc), "docs_skipped": 0, "docs_ingested": 0, "failed": [],
            "chunks_before_dedup": 0, "chunks_after_dedup": 0, "removed": 0, "inserted": 0, "pruned": 0,
        }
        for key, doc_chunks in by_doc.items():
            if stored.get(key) == doc_chunks[0].metadata.get("doc_hash"):
                stats["docs_skipped"] += 1
                continue
            try:
                embeddings = await self.embed_all_chunks(doc_chunks, session_id=session_id)
                unique, unique_vectors, removed = self.deduplicate(doc_chunks, embeddings)
                stats["inserted"] += await self.replace_document(key, unique, unique_vectors, session_id=session_id)
            except Exception as exc:  # noqa: BLE001 - isolate one bad document
                logger.error("Ingestion of %s failed: %s", key, exc, extra={"session_id": session_id})
                stats["failed"].append(key)
                continue
            stats["docs_ingested"] += 1
            stats["chunks_before_dedup"] += len(doc_chunks)
            stats["chunks_after_dedup"] += len(unique)
            stats["removed"] += removed
            logger.info("Ingested %s: %d chunks (%d duplicates removed)", key, len(unique), removed, extra={"session_id": session_id})

        if prune:
            stats["pruned"] = await self.prune(set(by_doc), session_id=session_id)
        return stats
