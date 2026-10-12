"""Cost report: every LiteLLM call is recorded for the right user, the report adds it up, a lost row never fails a call."""
import asyncio
import os
import time

import httpx
import jwt
import litellm
import pytest
from fastapi import FastAPI

from src.config import settings
from src.gateway import admin
from src.shared import usage
from src.shared.auth import Principal, acting_as

SECRET = "0123456789abcdef0123456789abcdef-test-secret"
DSN = os.getenv("RAG_TEST_DSN")


class Usage:
    prompt_tokens, completion_tokens = 12, 8


class Response:
    usage = Usage()


def test_the_row_carries_the_caller_the_model_the_tokens_and_the_cost():
    event = usage.extract({"model": "gpt-4o-mini", "call_type": "acompletion", "response_cost": 0.0025}, Response())
    assert event == {"tenant_id": "", "user_id": "system", "model": "gpt-4o-mini", "call_type": "acompletion",
                     "prompt_tokens": 12, "completion_tokens": 8, "cost_usd": 0.0025, "agent": "", "node": "", "attempt": 0}
    with acting_as(Principal("alice", "acme", "legal", authenticated=True)):
        mine = usage.extract({"standard_logging_object": {"model": "m", "response_cost": 0.5}}, {"usage": {"prompt_tokens": 3}})
    assert (mine["tenant_id"], mine["user_id"], mine["model"], mine["cost_usd"], mine["prompt_tokens"], mine["completion_tokens"]) == ("acme", "alice", "m", 0.5, 3, 0)


def test_a_call_is_attributed_to_the_agent_step_and_attempt_that_made_it():
    async def inside_a_node():
        usage.attribute("rag_agent", "executor", 2)
        return usage.extract({}, Response()), usage.extract({"litellm_params": {"metadata": {"node": "rewriter"}}}, Response())

    plain, named = asyncio.run(inside_a_node())
    assert (plain["agent"], plain["node"], plain["attempt"]) == ("rag_agent", "executor", 2)
    assert (named["agent"], named["node"]) == ("rag_agent", "rewriter")  # a caller that names its own step wins
    assert usage.extract({}, Response())["agent"] == ""  # and nothing leaked out of that context


def test_a_failed_write_is_dropped_not_raised(monkeypatch):
    class Broken:
        async def execute(self, *args):
            raise RuntimeError("database down")

    monkeypatch.setattr(usage, "_pg", Broken())
    assert asyncio.run(usage.record(usage.extract({}, Response()))) is False
    monkeypatch.setattr(usage, "_pg", None)
    assert asyncio.run(usage.record(usage.extract({}, Response()))) is False


def test_install_registers_the_callback_once():
    usage.install()
    usage.install()
    assert sum(isinstance(c, usage.UsageLogger) for c in litellm.callbacks) == 1


@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
class TestAgainstPostgres:
    @staticmethod
    def run(scenario):
        from src.shared.migrations import upgrade_to_head
        from src.shared.postgres_client import PostgresClient

        upgrade_to_head(DSN)

        async def go():
            pg = PostgresClient(dsn=DSN)
            await pg.connect(min_size=1, max_size=4)
            usage.configure(pg)
            try:
                await pg.execute("DELETE FROM usage_events")
                await scenario(pg)
            finally:
                usage.configure(None)
                await pg.execute("DELETE FROM usage_events")
                await pg.disconnect()

        asyncio.run(go())

    def test_a_real_litellm_call_is_recorded_for_the_user_who_made_it(self):
        usage.install()

        async def scenario(pg):
            with acting_as(Principal("alice", "acme", "legal", authenticated=True)):
                await litellm.acompletion(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}], mock_response="hello")
            for _ in range(50):  # LiteLLM logs after the call returns, from its own task
                rows = await pg.fetch("SELECT tenant_id, user_id, model, prompt_tokens FROM usage_events")
                if rows:
                    break
                await asyncio.sleep(0.1)
            assert len(rows) == 1
            assert (rows[0]["tenant_id"], rows[0]["user_id"]) == ("acme", "alice")  # attributed through the request's contextvar
            assert "gpt-4o-mini" in rows[0]["model"]

        self.run(scenario)

    def test_the_report_adds_up_by_user_tenant_model_and_day_and_marks_the_budget(self, monkeypatch):
        monkeypatch.setattr(settings, "USAGE_BUDGET_USD_PER_USER_DAY", 1.0)

        async def scenario(pg):
            for tenant, user, model, tokens, cost in [("acme", "alice", "m1", 10, 0.6), ("acme", "alice", "m1", 20, 0.6), ("acme", "bob", "m2", 5, 0.1), ("globex", "eve", "m1", 1, 0.0)]:
                await usage.record({"tenant_id": tenant, "user_id": user, "model": model, "call_type": "acompletion",
                                    "prompt_tokens": tokens, "completion_tokens": 0, "cost_usd": cost})
            await pg.execute("INSERT INTO usage_events (tenant_id, user_id, ts, cost_usd) VALUES ('acme', 'alice', now() - interval '60 days', 9)")
            report = await usage.summary(pg, 30)
            by_user = {u["user_id"]: u for u in report["users"]}
            assert by_user["alice"]["calls"] == 2 and by_user["alice"]["tokens"] == 30 and by_user["alice"]["cost"] == pytest.approx(1.2)
            assert by_user["alice"]["over_budget"] is True and by_user["bob"]["over_budget"] is False  # the old row is outside the window
            assert {t["tenant_id"]: t["cost"] for t in report["tenants"]} == {"acme": pytest.approx(1.3), "globex": 0.0}
            assert report["totals"]["calls"] == 4 and report["totals"]["cost"] == pytest.approx(1.3)
            assert {m["model"] for m in report["models"]} == {"m1", "m2"} and len(report["per_day"]) == 1
            assert (await usage.summary(pg, 90))["totals"]["cost"] == pytest.approx(10.3)

        self.run(scenario)

    def test_the_report_splits_cost_by_agent_and_pev_step_and_prices_the_reruns(self):
        async def scenario(pg):
            base = {"tenant_id": "acme", "user_id": "alice", "model": "m", "call_type": "acompletion", "prompt_tokens": 1, "completion_tokens": 0}
            for agent, node, attempt, cost in [("rag_agent", "executor", 1, 0.2), ("rag_agent", "executor", 2, 0.2), ("rag_agent", "verifier", 2, 0.1), ("", "planner", 1, 0.05)]:
                await usage.record({**base, "cost_usd": cost, "agent": agent, "node": node, "attempt": attempt})
            report = await usage.summary(pg, 30)
            agents = {a["agent"]: a for a in report["agents"]}
            assert set(agents) == {"rag_agent"}  # calls with no agent (the planner) are not an agent's cost
            assert agents["rag_agent"]["cost"] == pytest.approx(0.5) and agents["rag_agent"]["retry_cost"] == pytest.approx(0.3)
            assert {n["node"]: n["cost"] for n in report["nodes"]} == {"executor": pytest.approx(0.4), "verifier": pytest.approx(0.1), "planner": pytest.approx(0.05)}

        self.run(scenario)

    def test_only_administrators_read_the_report(self, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
        monkeypatch.setattr(settings, "AUTH_JWT_SECRET", SECRET)
        monkeypatch.setattr(settings, "AUTH_JWKS_URL", "")
        monkeypatch.setattr(settings, "AUTH_JWT_AUDIENCE", "")
        monkeypatch.setattr(settings, "AUTH_JWT_ISSUER", "")

        def bearer(roles):
            claims = {"sub": "u", "exp": int(time.time()) + 300, "tenant_id": "acme", "department_id": "legal", "roles": roles}
            return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}

        async def scenario(pg):
            app = FastAPI()
            app.include_router(admin.router)
            app.state.pg_client = pg
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.get("/api/admin/usage", headers=bearer([]))).status_code == 403
                assert (await client.get("/api/admin/usage?days=0", headers=bearer(["admin"]))).status_code == 422
                ok = await client.get("/api/admin/usage?days=7", headers=bearer(["admin"]))
                assert ok.status_code == 200 and ok.json()["days"] == 7

        self.run(scenario)
