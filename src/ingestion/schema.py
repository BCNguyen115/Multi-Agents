"""Single source of truth for the ``rag_chunks`` table.

``ensure_schema`` is idempotent: it creates the table on a fresh database and migrates an older one in place
(new provenance columns, a stored full-text column with a GIN index, one HNSW vector index instead of two).
Existing rows keep working; only ``doc_hash``/``page`` stay empty until the document is re-ingested.

FROZEN: this is the baseline (Alembic revision 0001, ``migrations/versions/0001_baseline_rag_chunks.py`` runs these very
statements). Do not edit ``CREATE_TABLE_SQL`` / ``MIGRATION_SQL`` for a new change: add an Alembic revision
(``alembic revision -m "..."``), which the gateway applies at start (see ``src/shared/migrations.py``).
"""

from __future__ import annotations

import logging
from typing import Any

from src.shared.logger import get_logger
from src.shared.postgres_client import SETUP_LOCK_ID

logger: logging.Logger = get_logger(__name__)

EMBEDDING_DIM: int = 1536

CREATE_TABLE_SQL: str = f"""
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

# Applied in order; every statement is safe to repeat.
MIGRATION_SQL: tuple[str, ...] = (
    "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS doc_key     TEXT",     # '<category>/<filename>': document identity
    "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS doc_hash    TEXT",     # sha256 of the extracted text: change detection
    "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS chunk_index INT",
    "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS page        INT",      # PDF page of the chunk start (NULL for DOCX)
    "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS tenant_id   TEXT NOT NULL DEFAULT 'public'",
    # stored, always in sync with content; the GIN index makes keyword search index-backed
    "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED",
    "DROP INDEX IF EXISTS idx_rag_chunks_embedding",  # duplicate ivfflat (lists=100) of the HNSW index below
    "CREATE INDEX IF NOT EXISTS idx_rag_chunks_hnsw ON rag_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)",
    "CREATE INDEX IF NOT EXISTS idx_rag_chunks_tsv ON rag_chunks USING gin (tsv)",
    "CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_key ON rag_chunks (doc_key)",
    "CREATE INDEX IF NOT EXISTS idx_rag_chunks_category ON rag_chunks (category)",
)


async def ensure_schema(pg: Any, session_id: str = "SYSTEM") -> None:
    """Create or migrate ``rag_chunks``. Raises if a statement fails (a half-migrated table must not go unnoticed)."""
    statements: tuple[str, ...] = (CREATE_TABLE_SQL, *MIGRATION_SQL)
    transaction = getattr(pg, "transaction", None)
    if transaction is None:  # a minimal client without transactions (tests)
        for statement in statements:
            await pg.execute(statement, session_id=session_id)
    else:
        # one transaction under an advisory lock: replicas starting together on an empty database take turns instead of
        # racing on CREATE TABLE / CREATE INDEX (duplicate key in pg_class)
        async with transaction() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock($1)", SETUP_LOCK_ID)
            for statement in statements:
                await conn.execute(statement)
    logger.info("rag_chunks schema verified / migrated", extra={"session_id": session_id})
