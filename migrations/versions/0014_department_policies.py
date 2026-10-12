"""what a department (or, as a default, a whole tenant) may use: which agents, and whether its members may add documents to the knowledge base

`department_id = '*'` is the tenant's default, used by a department that has no row of its own. NULL means "no restriction here": every agent,
and the knowledge-base upload stays with the roles in KNOWLEDGE_UPLOAD_ROLES.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-09
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS department_policies (
            tenant_id            TEXT        NOT NULL,
            department_id        TEXT        NOT NULL,
            allowed_agents       TEXT[],
            can_upload_knowledge BOOLEAN,
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by           TEXT        NOT NULL DEFAULT '',
            PRIMARY KEY (tenant_id, department_id)
        )
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS department_policies")
