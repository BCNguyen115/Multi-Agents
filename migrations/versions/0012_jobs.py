"""jobs: a small durable queue for work that should not hold a request open (document ingestion first)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-08
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id            TEXT        PRIMARY KEY,
            kind          TEXT        NOT NULL,
            tenant_id     TEXT        NOT NULL DEFAULT '',
            user_id       TEXT        NOT NULL DEFAULT '',
            department_id TEXT        NOT NULL DEFAULT '',
            payload       JSONB       NOT NULL DEFAULT '{}'::jsonb,
            payload_bytes BYTEA,
            status        TEXT        NOT NULL DEFAULT 'queued',
            result        JSONB,
            error         TEXT        NOT NULL DEFAULT '',
            attempts      INTEGER     NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at    TIMESTAMPTZ,
            finished_at   TIMESTAMPTZ
        )
        """
    )
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs (created_at) WHERE status = 'queued'")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_jobs_owner ON jobs (tenant_id, user_id, created_at DESC)")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS jobs")
