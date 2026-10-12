"""answer quality and cost attribution: what a thumbs-down was about (agent, answer, run, verdict, reasons), answers graded by a model, and which
agent / PEV step / attempt each LLM call belonged to

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-09
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for statement in (
        "ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS agent   TEXT    NOT NULL DEFAULT ''",
        "ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS answer  TEXT    NOT NULL DEFAULT ''",
        "ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS run_id  TEXT    NOT NULL DEFAULT ''",
        "ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS verified BOOLEAN",
        "ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS retries INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE rag_feedback ADD COLUMN IF NOT EXISTS reasons TEXT[]  NOT NULL DEFAULT '{}'",
        "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS agent   TEXT    NOT NULL DEFAULT ''",
        "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS node    TEXT    NOT NULL DEFAULT ''",
        "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 0",
    ):
        connection.exec_driver_sql(statement)
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS answer_reviews (
            id        BIGSERIAL   PRIMARY KEY,
            at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            tenant_id TEXT        NOT NULL DEFAULT '',
            user_id   TEXT        NOT NULL DEFAULT '',
            agent     TEXT        NOT NULL DEFAULT '',
            query     TEXT        NOT NULL DEFAULT '',
            answer    TEXT        NOT NULL DEFAULT '',
            score     SMALLINT    NOT NULL CHECK (score BETWEEN 1 AND 5),
            reason    TEXT        NOT NULL DEFAULT '',
            verified  BOOLEAN,
            retries   INTEGER     NOT NULL DEFAULT 0,
            model     TEXT        NOT NULL DEFAULT ''
        )
        """
    )
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS answer_reviews_tenant_at ON answer_reviews (tenant_id, at DESC)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS answer_reviews_agent_at ON answer_reviews (agent, at DESC)")


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("DROP TABLE IF EXISTS answer_reviews")
    for statement in (
        "ALTER TABLE usage_events DROP COLUMN IF EXISTS attempt",
        "ALTER TABLE usage_events DROP COLUMN IF EXISTS node",
        "ALTER TABLE usage_events DROP COLUMN IF EXISTS agent",
        "ALTER TABLE rag_feedback DROP COLUMN IF EXISTS reasons",
        "ALTER TABLE rag_feedback DROP COLUMN IF EXISTS retries",
        "ALTER TABLE rag_feedback DROP COLUMN IF EXISTS verified",
        "ALTER TABLE rag_feedback DROP COLUMN IF EXISTS run_id",
        "ALTER TABLE rag_feedback DROP COLUMN IF EXISTS answer",
        "ALTER TABLE rag_feedback DROP COLUMN IF EXISTS agent",
    ):
        connection.exec_driver_sql(statement)
