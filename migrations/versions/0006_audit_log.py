"""append-only audit trail: sensitive operations requested / approved / rejected, knowledge-base changes

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id        BIGSERIAL   PRIMARY KEY,
            at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            tenant_id TEXT        NOT NULL DEFAULT '',
            actor     TEXT        NOT NULL,
            action    TEXT        NOT NULL,
            target    TEXT        NOT NULL DEFAULT '',
            outcome   TEXT        NOT NULL DEFAULT 'ok',
            detail    JSONB       NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS audit_log_tenant_at ON audit_log (tenant_id, at DESC)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS audit_log_target ON audit_log (target)")
    # Append-only in the database itself: no UPDATE, DELETE or TRUNCATE, whoever asks
    conn.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    conn.exec_driver_sql("DROP TRIGGER IF EXISTS audit_log_no_row_change ON audit_log")
    conn.exec_driver_sql(
        "CREATE TRIGGER audit_log_no_row_change BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()"
    )
    conn.exec_driver_sql("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
    conn.exec_driver_sql(
        "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only()"
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("DROP TRIGGER IF EXISTS audit_log_no_row_change ON audit_log")
    conn.exec_driver_sql("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
    conn.exec_driver_sql("DROP TABLE IF EXISTS audit_log")
    conn.exec_driver_sql("DROP FUNCTION IF EXISTS audit_log_append_only()")
