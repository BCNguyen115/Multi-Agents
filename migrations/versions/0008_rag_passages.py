"""rag_passages: ~600 character windows of a chunk with their own embedding (small-to-big retrieval, RAG_PASSAGE_SEARCH)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-03
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS rag_passages (
            id        BIGSERIAL PRIMARY KEY,
            chunk_id  BIGINT    NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
            position  INT       NOT NULL,
            content   TEXT      NOT NULL,
            embedding VECTOR(1536)
        )
        """
    )
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_rag_passages_chunk ON rag_passages (chunk_id)")
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_rag_passages_hnsw ON rag_passages USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS rag_passages")
