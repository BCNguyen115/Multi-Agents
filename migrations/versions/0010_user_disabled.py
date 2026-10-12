"""app_users.disabled: an administrator can lock an account without deleting it

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-08
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS disabled BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE app_users DROP COLUMN IF EXISTS disabled")
