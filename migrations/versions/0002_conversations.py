"""server-side conversations: one row per chat, owned by (tenant, user)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            tenant_id   TEXT        NOT NULL,
            user_id     TEXT        NOT NULL,
            id          TEXT        NOT NULL,
            title       TEXT        NOT NULL DEFAULT '',
            pinned      BOOLEAN     NOT NULL DEFAULT FALSE,
            messages    JSONB       NOT NULL DEFAULT '[]'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, user_id, id)
        )
        """
    )
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_conversations_owner ON conversations (tenant_id, user_id, updated_at DESC)")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS conversations")
