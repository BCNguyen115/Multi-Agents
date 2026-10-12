"""Admin console numbers: the overview adds up what exists, the health page names the service that is down (real PostgreSQL via RAG_TEST_DSN)."""
import asyncio
import os
import time
from datetime import timedelta
from types import SimpleNamespace

import httpx
import jwt
import pytest
from fastapi import FastAPI

from src.config import settings
from src.gateway import admin
from src.shared import audit, health, metrics
from src.shared.migrations import head_revision

SECRET = "0123456789abcdef0123456789abcdef-test-secret"
DSN = os.getenv("RAG_TEST_DSN")


def bearer(user, roles=("admin",), tenant="acme"):
    claims = {"sub": user, "exp": int(time.time()) + 300, "tenant_id": tenant, "department_id": "legal", "roles": list(roles)}
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


class FakeClient:
    """The slice of redis.asyncio the admin pages use: ping and scan_iter."""

    def __init__(self, keys=(), up=True):
        self.keys, self.up = list(keys), up

    async def ping(self):
        if not self.up:
            raise ConnectionError("redis down")

    async def scan_iter(self, match="*", count=100):
        for key in self.keys:
            yield key


@pytest.fixture
def jwt_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "AUTH_JWKS_URL", "")
    monkeypatch.setattr(settings, "AUTH_JWT_AUDIENCE", "")
    monkeypatch.setattr(settings, "AUTH_JWT_ISSUER", "")
    monkeypatch.setattr(settings, "AUTH_USERS", [{"username": "root", "password_hash": "x", "roles": ["admin"], "tenant_id": "acme", "department_id": "it"}])
    monkeypatch.setattr(settings, "SANDBOX_URL", "http://sandbox.test:8080")


def client_for(pg=None, redis=None, llm=None):
    app = FastAPI()
    app.include_router(admin.router)
    app.state.redis_client = redis or SimpleNamespace(client=FakeClient())
    app.state.llm_client = llm
    if pg is not None:
        app.state.pg_client = pg
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------- no database needed
def test_the_monitoring_routes_are_for_administrators_only(jwt_mode):
    async def scenario():
        async with client_for() as client:
            for path in ("/api/admin/overview", "/api/admin/health"):
                assert (await client.get(path)).status_code == 401
                assert (await client.get(path, headers=bearer("bob", roles=("approver",)))).status_code == 403
                assert (await client.get(path, headers=bearer("alice"))).status_code == 503  # an admin, but no database here

    asyncio.run(scenario())


def test_the_snapshot_reports_routes_status_classes_and_average_latency():
    before = metrics.snapshot(top=1000)
    metrics.record_request("GET", "/t/snapshot-a", 200, 0.10)
    metrics.record_request("GET", "/t/snapshot-a", 200, 0.30)
    metrics.record_request("GET", "/t/snapshot-a", 500, 0.20)
    metrics.record_request("POST", "/t/snapshot-b", 429, 0.01)
    after = metrics.snapshot(top=1000)
    routes = {(r["method"], r["route"]): r for r in after["routes"]}
    assert routes[("GET", "/t/snapshot-a")]["count"] == 3 and routes[("GET", "/t/snapshot-a")]["errors"] == 1
    assert routes[("GET", "/t/snapshot-a")]["avg_ms"] == 200  # (0.10 + 0.30 + 0.20) / 3
    assert after["total"] - before["total"] == 4
    assert after["by_class"]["2xx"] - before["by_class"]["2xx"] == 2 and after["by_class"]["5xx"] - before["by_class"]["5xx"] == 1
    assert after["by_class"]["4xx"] - before["by_class"]["4xx"] == 1 and after["rate_limited"] - before["rate_limited"] == 1
    assert 0 <= after["error_rate"] <= 1 and after["uptime_seconds"] >= 0
    assert len(metrics.snapshot(top=2)["routes"]) <= 2  # only the busiest are listed


def test_a_probe_never_raises_and_says_how_long_it_took():
    async def broken():
        raise ConnectionError("down")

    async def slow():
        await asyncio.sleep(1)

    async def scenario():
        assert (await health.probe_timed(broken))["status"] == "ConnectionError"
        timed = await health.probe_timed(slow, timeout=0.05)
        assert timed["status"] == "TimeoutError" and timed["ms"] < 500

    asyncio.run(scenario())


# ---------------------------------------------------------------- real PostgreSQL
@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
class TestAgainstPostgres:
    @staticmethod
    def run(scenario):
        from src.shared.migrations import upgrade_to_head
        from src.shared.postgres_client import PostgresClient

        upgrade_to_head(DSN)
        tables = ("jobs", "usage_events", "rag_feedback", "app_users", "conversations", "dashboards")

        async def go():
            pg = PostgresClient(dsn=DSN)
            await pg.connect(min_size=1, max_size=4)
            audit.configure(pg)
            try:
                for table in tables:
                    await pg.execute(f"DELETE FROM {table}")
                await scenario(pg)
            finally:
                audit.configure(None)
                for table in tables:
                    await pg.execute(f"DELETE FROM {table}")
                await pg.disconnect()

        asyncio.run(go())

    def test_the_overview_adds_up_accounts_jobs_cost_content_approvals_and_activity(self, jwt_mode):
        async def scenario(pg):
            for name, tenant in (("bob", settings.REGISTRATION_TENANT_ID), ("carol", "acme")):
                await pg.execute(
                    "INSERT INTO app_users (username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id) VALUES ($1, $1, 'x', 'x', '{}', $2, 'legal')",
                    name, tenant,
                )
            await pg.execute("UPDATE app_users SET disabled = TRUE WHERE username = 'carol'")
            for number, (status, age) in enumerate((("queued", 0), ("running", 0), ("done", 1), ("failed", 2), ("failed", 72))):  # age in hours
                await pg.execute("INSERT INTO jobs (id, kind, status, created_at) VALUES ($1, 'k', $2, now() - $3::interval)", f"job-{number}", status, timedelta(hours=age))
            await pg.execute("INSERT INTO usage_events (tenant_id, user_id, model, prompt_tokens, completion_tokens, cost_usd) VALUES ('acme', 'carol', 'm', 10, 5, 0.50), ('acme', 'carol', 'm', 1, 1, 0.25)")
            await pg.execute("INSERT INTO usage_events (tenant_id, user_id, model, cost_usd, ts) VALUES ('acme', 'carol', 'm', 9, now() - interval '30 days')")
            await pg.execute("INSERT INTO rag_feedback (user_id, rating) VALUES ('carol', 1), ('carol', 1), ('carol', -1)")
            await pg.execute("INSERT INTO conversations (tenant_id, user_id, id, title) VALUES ('acme', 'carol', 'c1', 't')")
            await audit.record("admin.tenant_create", "initech", principal=SimpleNamespace(user_id="alice", tenant_id="acme"))
            redis = SimpleNamespace(client=FakeClient(keys=["hitl:pending:a", "hitl:pending:b"]))
            async with client_for(pg, redis) as client:
                body = (await client.get("/api/admin/overview", headers=bearer("alice"))).json()
            assert body["accounts"] == {"total": 3, "pending": 1, "locked": 1, "env": 1}  # bob, carol and the AUTH_USERS account `root`
            assert body["approvals_pending"] == 2
            assert body["jobs"] == {"queued": 1, "running": 1, "done_24h": 1, "failed_24h": 1}  # the 3-day-old failure is outside the day
            assert body["cost"]["today"] == pytest.approx(0.75) and body["cost"]["week_total"] == pytest.approx(0.75)  # the 30-day-old row is not in the week
            assert (body["content"]["conversations"], body["content"]["feedback_up"], body["content"]["feedback_down"]) == (1, 2, 1)
            assert body["activity"][0]["action"] == "admin.tenant_create" and body["activity"][0]["actor"] == "alice"

        self.run(scenario)

    def test_the_overview_says_none_when_redis_cannot_be_asked(self, jwt_mode):
        async def scenario(pg):
            async with client_for(pg, SimpleNamespace(client=None)) as client:
                assert (await client.get("/api/admin/overview", headers=bearer("alice"))).json()["approvals_pending"] is None

        self.run(scenario)

    def test_health_is_ok_and_reports_the_revision_the_queue_and_this_instances_requests(self, jwt_mode, monkeypatch):
        async def fine(*args, **kwargs):
            return None

        monkeypatch.setattr(health, "check_reranker", fine)
        monkeypatch.setattr(health, "check_sandbox", fine)

        async def scenario(pg):
            await pg.execute("INSERT INTO jobs (id, kind, status, created_at) VALUES ('q1', 'kb.ingest', 'queued', now() - interval '5 minutes')")
            await pg.execute("INSERT INTO jobs (id, kind, user_id, status, error, finished_at) VALUES ('f1', 'kb.ingest', 'carol', 'failed', 'This PDF has no text.', now())")
            metrics.record_request("GET", "/t/health-route", 200, 0.05)
            async with client_for(pg, llm=SimpleNamespace(langfuse_enabled=True)) as client:
                body = (await client.get("/api/admin/health", headers=bearer("alice"))).json()
            assert body["status"] == "ok"
            assert {name: s["status"] for name, s in body["services"].items()} == {"postgres": "ok", "redis": "ok", "reranker": "ok", "sandbox": "ok", "langfuse": "ok"}
            assert body["instance"]["db_head"] == head_revision() and body["instance"]["db_current"] is True
            assert body["queue"]["queued"] == 1 and body["queue"]["failed_24h"] == 1 and 250 <= body["queue"]["oldest_queued_seconds"] <= 400
            assert body["queue"]["recent_failures"][0]["error"] == "This PDF has no text." and body["queue"]["recent_failures"][0]["user_id"] == "carol"
            assert body["http"]["total"] >= 1 and body["http"]["uptime_seconds"] >= 0  # this process has served requests (and the test recorded one)

        self.run(scenario)

    def test_a_missing_reranker_is_degraded_and_a_missing_redis_is_down(self, jwt_mode, monkeypatch):
        async def fine(*args, **kwargs):
            return None

        async def reranker_down(*args, **kwargs):
            raise ConnectionError("no reranker")

        monkeypatch.setattr(health, "check_sandbox", fine)
        monkeypatch.setattr(health, "check_reranker", reranker_down)
        monkeypatch.setattr(settings, "SANDBOX_URL", "")  # the child-process setup: reported as "off", not as a failure

        async def scenario(pg):
            async with client_for(pg) as client:
                degraded = (await client.get("/api/admin/health", headers=bearer("alice"))).json()
            assert degraded["status"] == "degraded" and degraded["services"]["reranker"]["status"] == "ConnectionError"
            assert degraded["services"]["sandbox"]["status"] == "off" and degraded["services"]["langfuse"]["status"] in ("ok", "off")
            async with client_for(pg, SimpleNamespace(client=FakeClient(up=False))) as client:
                down = (await client.get("/api/admin/health", headers=bearer("alice"))).json()
            assert down["status"] == "down" and down["services"]["redis"]["status"] == "ConnectionError"

        self.run(scenario)
