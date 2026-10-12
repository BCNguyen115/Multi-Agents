"""tenants and departments: a registry the administration page creates entries in (accounts keep using plain text ids; nothing enforces the registry)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-08
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            id         TEXT        PRIMARY KEY,
            name       TEXT        NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS departments (
            tenant_id  TEXT        NOT NULL,
            id         TEXT        NOT NULL,
            name       TEXT        NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, id)
        )
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("DROP TABLE IF EXISTS departments")
    connection.exec_driver_sql("DROP TABLE IF EXISTS tenants")
