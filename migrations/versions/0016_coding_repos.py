"""repositories the coding agent may work on: a GitHub link or a git folder this server can see, per tenant

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-09
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS coding_repos (
            id         TEXT        PRIMARY KEY,
            tenant_id  TEXT        NOT NULL DEFAULT '',
            owner      TEXT        NOT NULL DEFAULT '',
            name       TEXT        NOT NULL,
            kind       TEXT        NOT NULL CHECK (kind IN ('github', 'local')),
            location   TEXT        NOT NULL,
            branch     TEXT        NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS coding_repos_tenant_name ON coding_repos (tenant_id, lower(name))")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS coding_repos")
