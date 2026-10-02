"""baseline: the rag_chunks table as src/ingestion/schema.py creates it

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""
from alembic import op

from src.ingestion.schema import CREATE_TABLE_SQL, MIGRATION_SQL

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Every statement is idempotent (IF NOT EXISTS): a database that ensure_schema() already built is just recorded at 0001.
    connection = op.get_bind()
    for statement in ("CREATE EXTENSION IF NOT EXISTS vector", CREATE_TABLE_SQL, *MIGRATION_SQL):
        connection.exec_driver_sql(statement)  # not op.execute(): the SQL contains "::" casts that text() would read as bind parameters


def downgrade() -> None:
    raise RuntimeError("The baseline cannot be downgraded: that would drop rag_chunks, i.e. the whole knowledge base.")
