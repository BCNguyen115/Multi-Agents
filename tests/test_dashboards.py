"""Saved dashboards: ownership, sharing inside a tenant, open restores the file, refresh (real PostgreSQL via RAG_TEST_DSN)."""
import asyncio
import json
import os
import time

import httpx
import jwt
import pytest
from fastapi import FastAPI

from src.config import settings
from src.gateway import dashboards
from src.gateway.dashboards import router

SECRET = "0123456789abcdef0123456789abcdef-test-secret"
DSN = os.getenv("RAG_TEST_DSN")
CSV = "region,amount\nnorth,10\nsouth,20\n"
SPEC = {"version": 2, "kpis": [], "charts": [], "table": {"rows": [["north", 10]], "totalRows": 2}, "sessionId": "browser-session"}


def bearer(user, tenant="acme"):
    claims = {"sub": user, "exp": int(time.time()) + 300, "tenant_id": tenant, "department_id": "legal", "roles": []}
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


class FakeRedis:
    """Just the two calls the router makes, keyed like the real client."""

    def __init__(self):
        self.files = {}

    async def set_active_file(self, session_id, filename, csv_content, ttl=86400):
        self.files[session_id] = {"filename": filename, "csv_content": csv_content}

    async def get_active_file(self, session_id):
        return self.files.get(session_id)


class FakeOrchestrator:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def handle_request(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


@pytest.fixture
def jwt_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "AUTH_JWKS_URL", "")
    monkeypatch.setattr(settings, "AUTH_JWT_AUDIENCE", "")
    monkeypatch.setattr(settings, "AUTH_JWT_ISSUER", "")

    async def no_limit(*args, **kwargs):
        return None

    monkeypatch.setattr(dashboards, "enforce_rate_limit", no_limit)


def client_for(pg=None, redis=None, orchestrator=None):
    app = FastAPI()
    app.include_router(router)
    app.state.redis_client = redis or FakeRedis()
    app.state.orchestrator = orchestrator
    if pg is not None:
        app.state.pg_client = pg
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------- no database needed
def test_input_is_checked_before_anything_touches_the_database(jwt_mode):
    async def scenario():
        async with client_for() as client:  # no database configured
            assert (await client.get("/api/dashboards", headers=bearer("alice"))).status_code == 503
            assert (await client.post("/api/dashboards/bad id!/open", headers=bearer("alice"))).status_code == 422
            assert (await client.get("/api/dashboards")).status_code == 401
            # the file of the session is gone (Redis keeps it 24 h): nothing to save
            gone = await client.post("/api/dashboards", headers=bearer("alice"), json={"session_id": "s1", "spec": SPEC})
            assert gone.status_code == 404

    asyncio.run(scenario())


def test_an_oversized_spec_loses_its_table_preview_and_then_is_refused(monkeypatch):
    spec, payload = dashboards._fit(SPEC)
    assert "sessionId" not in spec and "sessionId" not in payload  # a session id means nothing once saved
    monkeypatch.setattr(dashboards, "MAX_SPEC_BYTES", 150)
    trimmed, _ = dashboards._fit({"table": {"rows": [["x" * 500]], "totalRows": 1}, "kpis": []})
    assert "rows" not in trimmed["table"] and trimmed["table"]["totalRows"] == 1
    with pytest.raises(Exception) as refused:
        dashboards._fit({"kpis": ["x" * 500]})
    assert getattr(refused.value, "status_code", None) == 413


# ---------------------------------------------------------------- real PostgreSQL
@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
class TestAgainstPostgres:
    @staticmethod
    def run(scenario, orchestrator=None):
        from src.shared.migrations import upgrade_to_head
        from src.shared.postgres_client import PostgresClient

        upgrade_to_head(DSN)

        async def go():
            pg = PostgresClient(dsn=DSN)
            await pg.connect(min_size=1, max_size=4)
            redis = FakeRedis()
            try:
                await pg.execute("DELETE FROM dashboards")
                async with client_for(pg, redis, orchestrator) as client:
                    await scenario(client, pg, redis)
            finally:
                await pg.execute("DELETE FROM dashboards")
                await pg.disconnect()

        asyncio.run(go())

    @staticmethod
    async def save(client, redis, user="alice", tenant="acme", title="Doanh thu"):
        redis.files[f"{user}:s1"] = {"filename": "sales.csv", "csv_content": CSV}
        saved = await client.post("/api/dashboards", headers=bearer(user, tenant), json={"title": title, "session_id": "s1", "spec": SPEC})
        assert saved.status_code == 201, saved.text
        return saved.json()

    def test_save_list_open_and_delete(self, jwt_mode):
        async def scenario(client, pg, redis):
            alice = bearer("alice")
            saved = await self.save(client, redis)
            assert saved["title"] == "Doanh thu" and saved["mine"] is True and saved["shared"] is False
            listing = (await client.get("/api/dashboards", headers=alice)).json()
            assert [d["id"] for d in listing] == [saved["id"]] and "spec" not in listing[0]
            redis.files.clear()  # the 24 h copy expired
            opened = (await client.post(f"/api/dashboards/{saved['id']}/open", headers=alice)).json()
            session = opened["spec"]["sessionId"]
            assert opened["spec"]["table"]["totalRows"] == 2 and session != "browser-session"
            assert redis.files[f"alice:{session}"] == {"filename": "sales.csv", "csv_content": CSV}  # filter/rows/export work again
            assert (await client.delete(f"/api/dashboards/{saved['id']}", headers=alice)).status_code == 204
            assert (await client.post(f"/api/dashboards/{saved['id']}/open", headers=alice)).status_code == 404

        self.run(scenario)

    def test_a_dashboard_is_private_until_shared_and_then_only_inside_its_tenant(self, jwt_mode):
        async def scenario(client, pg, redis):
            saved = await self.save(client, redis)
            path = f"/api/dashboards/{saved['id']}"
            bob, mallory = bearer("bob"), bearer("mallory", tenant="globex")
            assert (await client.get("/api/dashboards", headers=bob)).json() == []
            assert (await client.post(f"{path}/open", headers=bob)).status_code == 404  # not shared yet
            assert (await client.patch(path, headers=bearer("alice"), json={"shared": True})).json()["shared"] is True
            listed = (await client.get("/api/dashboards", headers=bob)).json()
            assert [d["id"] for d in listed] == [saved["id"]] and listed[0]["mine"] is False
            opened = await client.post(f"{path}/open", headers=bob)
            assert opened.status_code == 200
            assert redis.files[f"bob:{opened.json()['spec']['sessionId']}"]["csv_content"] == CSV  # in BOB's session, not alice's
            assert (await client.post(f"{path}/open", headers=mallory)).status_code == 404  # another tenant
            assert (await client.get("/api/dashboards", headers=mallory)).json() == []
            pending = bearer("carol", tenant=settings.REGISTRATION_TENANT_ID)
            assert (await client.post(f"{path}/open", headers=pending)).status_code == 404  # not yet assigned to a tenant
            # the viewer can neither change nor delete it
            assert (await client.patch(path, headers=bob, json={"title": "mine now"})).status_code == 404
            await client.delete(path, headers=bob)
            assert (await client.get("/api/dashboards", headers=bearer("alice"))).json()[0]["title"] == "Doanh thu"

        self.run(scenario)

    def test_refresh_analyses_the_stored_file_again_and_only_for_the_owner(self, jwt_mode):
        new_spec = {"version": 2, "kpis": [{"id": "k"}], "charts": [], "table": {"rows": [], "totalRows": 2}}
        orchestrator = FakeOrchestrator(json.dumps({"type": "dashboard", "dashboard_spec": new_spec}))

        async def scenario(client, pg, redis):
            saved = await self.save(client, redis)
            path = f"/api/dashboards/{saved['id']}"
            await client.patch(path, headers=bearer("alice"), json={"shared": True})
            assert (await client.post(f"{path}/refresh", headers=bearer("bob"))).status_code == 403
            refreshed = await client.post(f"{path}/refresh", headers=bearer("alice"))
            assert refreshed.status_code == 200 and refreshed.json()["spec"]["kpis"] == [{"id": "k"}]
            assert orchestrator.calls[0]["csv_content"] == CSV and orchestrator.calls[0]["csv_filename"] == "sales.csv"
            assert refreshed.json()["updated_at"] != saved["updated_at"]
            orchestrator.reply = "no dashboard here"  # a failed re-analysis keeps the saved version
            assert (await client.post(f"{path}/refresh", headers=bearer("alice"))).status_code == 422
            stored = (await client.post(f"{path}/open", headers=bearer("alice"))).json()
            assert stored["spec"]["kpis"] == [{"id": "k"}]

        self.run(scenario, orchestrator)

    def test_the_number_of_dashboards_per_user_is_capped(self, jwt_mode, monkeypatch):
        monkeypatch.setattr(dashboards, "MAX_DASHBOARDS_PER_USER", 1)

        async def scenario(client, pg, redis):
            await self.save(client, redis)
            redis.files["alice:s1"] = {"filename": "sales.csv", "csv_content": CSV}
            second = await client.post("/api/dashboards", headers=bearer("alice"), json={"session_id": "s1", "spec": SPEC})
            assert second.status_code == 409
            redis.files["bob:s1"] = {"filename": "sales.csv", "csv_content": CSV}
            assert (await client.post("/api/dashboards", headers=bearer("bob"), json={"session_id": "s1", "spec": SPEC})).status_code == 201

        self.run(scenario)
