"""self-registered users for the built-in sign-in (AUTH_USERS stays the list of administrator-made accounts)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS app_users (
            username      TEXT        PRIMARY KEY,
            display_name  TEXT        NOT NULL DEFAULT '',
            password_hash TEXT        NOT NULL,
            roles         TEXT[]      NOT NULL DEFAULT '{}',
            tenant_id     TEXT        NOT NULL,
            department_id TEXT        NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS app_users")
