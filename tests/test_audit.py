"""Audit trail: rows are written for sensitive actions, an approval is never executed unrecorded, the table is append-only."""
import asyncio
import os

import pytest

from src.shared import audit
from src.shared.auth import Principal

DSN = os.getenv("RAG_TEST_DSN")
APPROVER = Principal("alice", "acme", "legal", frozenset({"approver"}), authenticated=True)


class FakePG:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    async def execute(self, sql, *args):
        if self.fail:
            raise ConnectionError("database down")
        self.rows.append(args)


@pytest.fixture(autouse=True)
def reset():
    yield
    audit.configure(None)


def run(coro):
    return asyncio.run(coro)


def test_a_row_carries_who_what_where_and_the_outcome():
    pg = FakePG()
    audit.configure(pg)
    assert run(audit.record("hitl.approve", "act-1", "decided", {"feedback": "ok"}, principal=APPROVER))
    tenant, actor, action, target, outcome, detail = pg.rows[0]
    assert (tenant, actor, action, target, outcome) == ("acme", "alice", "hitl.approve", "act-1", "decided")
    assert '"feedback": "ok"' in detail


def test_an_oversized_detail_is_cut_not_dropped():
    pg = FakePG()
    audit.configure(pg)
    run(audit.record("kb.upload", "x", detail={"blob": "y" * 20000}, principal=APPROVER))
    assert len(pg.rows[0][5]) < audit.MAX_DETAIL_CHARS + 50 and "truncated" in pg.rows[0][5]


def test_a_failed_write_is_reported_and_only_raises_when_required():
    audit.configure(FakePG(fail=True))
    assert run(audit.record("kb.delete", "x", principal=APPROVER)) is False
    with pytest.raises(ConnectionError):
        run(audit.record("hitl.approve", "x", principal=APPROVER, required=True))


def test_without_configuration_nothing_is_written_and_required_still_fails():
    assert run(audit.record("kb.delete", "x", principal=APPROVER)) is False
    with pytest.raises(RuntimeError):
        run(audit.record("hitl.approve", "x", principal=APPROVER, required=True))


def test_an_approval_is_not_executed_when_its_decision_cannot_be_recorded(monkeypatch):
    from src.gateway import main

    executed = []

    class Orchestrator:
        async def handle_approval_decision(self, **kw):
            executed.append(kw)
            return {"status": "success"}

    audit.configure(FakePG(fail=True))
    monkeypatch.setattr(main, "orchestrator", Orchestrator())
    body = main.ApprovalDecisionRequest(session_id="s", action_id="act-1", decision="approve")
    with pytest.raises(main.HTTPException) as refused:
        run(main.chat_approve(body, APPROVER))
    assert refused.value.status_code == 503 and executed == []


def test_an_approval_runs_after_its_decision_row_and_leaves_a_result_row(monkeypatch):
    from src.gateway import main

    pg = FakePG()
    audit.configure(pg)

    class Orchestrator:
        async def handle_approval_decision(self, **kw):
            return {"status": "success", "response": "done"}

    monkeypatch.setattr(main, "orchestrator", Orchestrator())
    run(main.chat_approve(main.ApprovalDecisionRequest(session_id="s", action_id="act-1", decision="approve"), APPROVER))
    assert [row[2] for row in pg.rows] == ["hitl.approve", "hitl.result"]


def test_the_migration_chain_ends_at_the_audit_table():
    from src.shared.migrations import head_revision

    assert head_revision() >= "0006"


@pytest.mark.skipif(not DSN, reason="needs a scratch PostgreSQL (RAG_TEST_DSN)")
def test_the_table_refuses_update_delete_and_truncate_in_the_database_itself():
    import asyncpg

    from src.shared.migrations import upgrade_to_head

    upgrade_to_head(DSN)  # the scratch database, not whatever POSTGRES_URL points at

    async def scenario():
        conn = await asyncpg.connect(DSN)
        try:
            await conn.execute("INSERT INTO audit_log (actor, action) VALUES ('t', 'probe')")
            for statement in ("UPDATE audit_log SET actor = 'x'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
                with pytest.raises(asyncpg.PostgresError, match="append-only"):
                    await conn.execute(statement)
        finally:
            await conn.close()

    asyncio.run(scenario())
