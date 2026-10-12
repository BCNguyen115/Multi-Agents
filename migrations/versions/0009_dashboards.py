"""saved dashboards: the verified spec plus the normalised file it was built from, owned by (tenant, user)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS dashboards (
            tenant_id   TEXT        NOT NULL,
            user_id     TEXT        NOT NULL,
            id          TEXT        NOT NULL,
            title       TEXT        NOT NULL DEFAULT '',
            filename    TEXT        NOT NULL DEFAULT '',
            spec        JSONB       NOT NULL,
            csv_gz      BYTEA       NOT NULL,
            shared      BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, user_id, id)
        )
        """
    )
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_dashboards_owner ON dashboards (tenant_id, user_id, updated_at DESC)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_dashboards_shared ON dashboards (tenant_id, updated_at DESC) WHERE shared")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS dashboards")
