"""recovery key of a self-registered account: the hash of a key shown once at sign-up, used to reset a forgotten password

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-02
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS recovery_hash TEXT")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE app_users DROP COLUMN IF EXISTS recovery_hash")
