"""RAG: the language of each chunk, which embedding model the corpus was built with, and users' thumbs on answers

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # 'vi' / 'en', detected when the chunk is ingested; NULL for rows written before this revision (scripts/backfill_lang.py fills them)
    conn.exec_driver_sql("ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS lang TEXT")
    # small key/value facts about the corpus; today: 'embedding_model', so a changed model cannot silently mix two vector spaces
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS rag_meta (
            key        TEXT        PRIMARY KEY,
            value      TEXT        NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS rag_feedback (
            id         BIGSERIAL   PRIMARY KEY,
            at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            tenant_id  TEXT        NOT NULL DEFAULT '',
            user_id    TEXT        NOT NULL,
            session_id TEXT        NOT NULL DEFAULT '',
            message_id TEXT        NOT NULL DEFAULT '',
            query      TEXT        NOT NULL DEFAULT '',
            rating     SMALLINT    NOT NULL CHECK (rating IN (-1, 1)),
            comment    TEXT        NOT NULL DEFAULT '',
            cited      JSONB       NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS rag_feedback_tenant_at ON rag_feedback (tenant_id, at DESC)")


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("DROP TABLE IF EXISTS rag_feedback")
    conn.exec_driver_sql("DROP TABLE IF EXISTS rag_meta")
    conn.exec_driver_sql("ALTER TABLE rag_chunks DROP COLUMN IF EXISTS lang")
