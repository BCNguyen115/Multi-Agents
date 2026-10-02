"""full-text search without the English stemmer and accent-insensitive (Vietnamese corpus)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-02
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS unaccent")
    # unaccent() is only STABLE: a generated column / index needs an IMMUTABLE wrapper with a fixed dictionary
    connection.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION immutable_unaccent(text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
        """
    )
    connection.exec_driver_sql("DROP INDEX IF EXISTS idx_rag_chunks_tsv")
    connection.exec_driver_sql("ALTER TABLE rag_chunks DROP COLUMN IF EXISTS tsv")
    connection.exec_driver_sql(
        "ALTER TABLE rag_chunks ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', immutable_unaccent(content))) STORED"
    )
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_rag_chunks_tsv ON rag_chunks USING GIN (tsv)")


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("DROP INDEX IF EXISTS idx_rag_chunks_tsv")
    connection.exec_driver_sql("ALTER TABLE rag_chunks DROP COLUMN IF EXISTS tsv")
    connection.exec_driver_sql(
        "ALTER TABLE rag_chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
    )
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_rag_chunks_tsv ON rag_chunks USING GIN (tsv)")
