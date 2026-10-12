"""usage_events: one row per LLM call (who, model, tokens, estimated cost) for the cost report

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-08
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
            id                BIGSERIAL        PRIMARY KEY,
            ts                TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
            tenant_id         TEXT             NOT NULL DEFAULT '',
            user_id           TEXT             NOT NULL DEFAULT '',
            model             TEXT             NOT NULL DEFAULT '',
            call_type         TEXT             NOT NULL DEFAULT '',
            prompt_tokens     INTEGER          NOT NULL DEFAULT 0,
            completion_tokens INTEGER          NOT NULL DEFAULT 0,
            cost_usd          DOUBLE PRECISION NOT NULL DEFAULT 0
        )
        """
    )
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_usage_events_ts ON usage_events (ts DESC)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_usage_events_user ON usage_events (tenant_id, user_id, ts DESC)")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS usage_events")
