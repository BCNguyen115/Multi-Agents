"""Admin console, operating side: audit viewer and CSV, accounts (create, reset, sign out, bulk), org rename/delete and enforcement,
cost by tenant and the hard budget, jobs, feedback, configuration, alerts, backups (real PostgreSQL via RAG_TEST_DSN where it matters)."""
import asyncio
import os
import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from fastapi import FastAPI, HTTPException

from src.config import settings
from src.gateway import admin, admin_ops
from src.shared import audit, usage
from src.shared.auth import Principal, verify_recovery_key, verify_user_row
from src.shared.user_store import get_user

SECRET = "0123456789abcdef0123456789abcdef-test-secret"
DSN = os.getenv("RAG_TEST_DSN")


def bearer(user, roles=("admin",), tenant="acme"):
    claims = {"sub": user, "exp": int(time.time()) + 300, "tenant_id": tenant, "department_id": "legal", "roles": list(roles)}
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


class FakeRedis:
    """The slice of redis.asyncio the admin pages use: scan_iter, get, ttl, set."""

    def __init__(self, records=None, up=True):
        self.records, self.up = dict(records or {}), up

    async def scan_iter(self, match="*", count=100):
        if not self.up:
            raise ConnectionError("redis down")
        for key in list(self.records):
            yield key

    async def get(self, key):
        return self.records.get(key)

    async def ttl(self, key):
        return 120

    async def set(self, *args, **kwargs):
        return True


@pytest.fixture
def jwt_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(settings, "AUTH_JWT_SECRET", SECRET)
    monkeypatch.setattr(settings, "AUTH_JWKS_URL", "")
    monkeypatch.setattr(settings, "AUTH_JWT_AUDIENCE", "")
    monkeypatch.setattr(settings, "AUTH_JWT_ISSUER", "")
    monkeypatch.setattr(settings, "AUTH_USERS", [{"username": "root", "password_hash": "x", "roles": ["admin"], "tenant_id": "acme", "department_id": "it"}])
    revoked = []

    async def fake_revoke(redis_client, user_id):
        revoked.append(user_id)
        return True

    monkeypatch.setattr(admin, "revoke_user_sessions", fake_revoke)
    return revoked


def client_for(pg=None, redis=None, orchestrator=None):
    app = FastAPI()
    app.include_router(admin.router)
    app.include_router(admin_ops.router)
    app.state.redis_client = SimpleNamespace(client=redis or FakeRedis())
    app.state.orchestrator = orchestrator
    if pg is not None:
        app.state.pg_client = pg
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


ADMIN_ROUTES = [
    ("GET", "/api/admin/audit"), ("GET", "/api/admin/audit/export"), ("GET", "/api/admin/approvals"), ("GET", "/api/admin/jobs"),
    ("POST", "/api/admin/jobs/j1/cancel"), ("GET", "/api/admin/config"), ("GET", "/api/admin/alerts"), ("GET", "/api/admin/backup"),
    ("GET", "/api/admin/feedback"), ("POST", "/api/admin/users"), ("POST", "/api/admin/users/bulk"), ("POST", "/api/admin/users/opsbob/sign-out"),
    ("POST", "/api/admin/users/opsbob/reset-credentials"), ("PATCH", "/api/admin/tenants/acme"), ("DELETE", "/api/admin/tenants/acme"),
    ("PATCH", "/api/admin/tenants/acme/departments/legal"), ("DELETE", "/api/admin/tenants/acme/departments/legal"),
]


# ---------------------------------------------------------------- no database needed
def test_every_new_route_is_for_administrators_only(jwt_mode):
    async def scenario():
        async with client_for() as client:
            for method, path in ADMIN_ROUTES:
                assert (await client.request(method, path)).status_code == 401, path
                member = await client.request(method, path, headers=bearer("opsbob", roles=("approver",)), json={})
                assert member.status_code == 403, path

    asyncio.run(scenario())


def test_a_spreadsheet_cannot_run_an_audit_cell_as_a_formula():
    assert admin_ops._csv_cell("=HYPERLINK(\"http://evil\")") == "'=HYPERLINK(\"http://evil\")"
    assert admin_ops._csv_cell("+1") == "'+1" and admin_ops._csv_cell("@x") == "'@x" and admin_ops._csv_cell("-2") == "'-2"
    assert admin_ops._csv_cell("nda/a.pdf") == "nda/a.pdf" and admin_ops._csv_cell({"a": "=1"}) == '{"a": "=1"}'


def test_the_configuration_names_what_is_set_but_never_a_secret(jwt_mode, monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-super-secret-value")
    monkeypatch.setattr(settings, "SANDBOX_URL", "http://user:pass@sandbox.internal:8080/token/abc")
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")

    async def scenario():
        async with client_for() as client:
            response = await client.get("/api/admin/config", headers=bearer("opsalice"))
            assert response.status_code == 200
            text = response.text
            assert "sk-super-secret-value" not in text and "user:pass" not in text and "token/abc" not in text
            groups = {g["group"]: {i["key"]: i["value"] for i in g["items"]} for g in response.json()["groups"]}
            assert groups["secrets"]["OPENROUTER_API_KEY"] is True and groups["secrets"]["METRICS_TOKEN"] is False
            assert groups["endpoints"]["SANDBOX_URL"] == "http://sandbox.internal:8080"
            assert "AUTH_MODE" in groups["access"] and "FAST_LLM_MODEL" in groups["models"]

    asyncio.run(scenario())


def test_alerts_say_when_they_are_not_configured_or_unreachable_and_list_what_fires(jwt_mode, monkeypatch):
    class Alertmanager:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            assert url == "http://am.test:9093/api/v2/alerts" and params["active"] == "true"
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: [{"labels": {"alertname": "HighErrorRate", "severity": "critical"}, "annotations": {"summary": "5xx above 5%"}, "startsAt": "2026-10-08T07:00:00Z"}],
            )

    async def scenario():
        async with client_for() as client:
            headers = bearer("opsalice")
            assert (await client.get("/api/admin/alerts", headers=headers)).json() == {"configured": False, "alerts": []}
            monkeypatch.setattr(settings, "ALERTMANAGER_URL", "http://127.0.0.1:9")  # nothing listens there
            down = (await client.get("/api/admin/alerts", headers=headers)).json()
            assert down["configured"] is True and down["alerts"] == [] and down["error"]
            monkeypatch.setattr(settings, "ALERTMANAGER_URL", "http://am.test:9093/")
            monkeypatch.setattr(admin_ops.httpx, "AsyncClient", Alertmanager)
            firing = (await client.get("/api/admin/alerts", headers=headers)).json()
            assert firing["alerts"] == [{"name": "HighErrorRate", "severity": "critical", "summary": "5xx above 5%", "since": "2026-10-08T07:00:00Z"}]

    asyncio.run(scenario())


def test_the_backup_page_reports_the_newest_file_and_its_age(jwt_mode, monkeypatch, tmp_path):
    async def scenario():
        async with client_for() as client:
            headers = bearer("opsalice")
            assert (await client.get("/api/admin/backup", headers=headers)).json() == {"configured": False}
            monkeypatch.setattr(settings, "BACKUP_STATUS_DIR", str(tmp_path / "missing"))
            assert (await client.get("/api/admin/backup", headers=headers)).json()["error"] == "FileNotFoundError"
            monkeypatch.setattr(settings, "BACKUP_STATUS_DIR", str(tmp_path))
            assert (await client.get("/api/admin/backup", headers=headers)).json()["latest"] is None
            old, new = tmp_path / "db-old.sql.gz", tmp_path / "db-new.sql.gz"
            old.write_bytes(b"1" * 10)
            new.write_bytes(b"2" * 25)
            os.utime(old, (time.time() - 7200, time.time() - 7200))
            os.utime(new, (time.time() - 3600, time.time() - 3600))
            report = (await client.get("/api/admin/backup", headers=headers)).json()
            assert report["count"] == 2 and report["total_bytes"] == 35 and report["latest"]["name"] == "db-new.sql.gz"
            assert 3500 < report["latest"]["age_seconds"] < 3800

    asyncio.run(scenario())


def test_pending_approvals_list_who_asked_for_what_without_the_request_itself(jwt_mode):
    import json

    record = {"payload": {"agent": "db_agent", "action_type": "sql", "description": "Read salaries", "risk_level": "high",
                          "payload": {"sql": "SELECT salary FROM hr"}, "requester": {"user": "opsbob", "tenant": "acme", "department": "hr"}}}
    redis = FakeRedis({"hitl:pending:act_12345678": json.dumps(record)})

    async def scenario():
        async with client_for(redis=redis) as client:
            body = (await client.get("/api/admin/approvals", headers=bearer("opsalice"))).json()
            assert body["available"] is True and len(body["items"]) == 1
            item = body["items"][0]
            assert (item["action_id"], item["agent"], item["requested_by"], item["tenant_id"], item["expires_in"]) == ("act_12345678", "db_agent", "opsbob", "acme", 120)
            assert "SELECT salary" not in str(body)  # the request is for the approvers, not the overview
        async with client_for(redis=FakeRedis(up=False)) as client:
            assert (await client.get("/api/admin/approvals", headers=bearer("opsalice"))).json()["available"] is False

    asyncio.run(scenario())


def test_the_hard_budget_refuses_only_when_switched_on_and_spent_and_fails_open(monkeypatch):
    usage._SPENT_CACHE.clear()
    spent = {"value": 0.5}

    class Pg:
        async def fetch(self, sql, *args):
            if spent["value"] is None:
                raise ConnectionError("db down")
            return [{"cost": spent["value"]}]

    monkeypatch.setattr(usage, "_pg", Pg())
    user = Principal("amy", "acme", "legal", frozenset(), authenticated=True)

    async def scenario():
        monkeypatch.setattr(settings, "USAGE_BUDGET_USD_PER_USER_DAY", 1.0)
        monkeypatch.setattr(settings, "USAGE_BUDGET_HARD", False)
        spent["value"] = 5.0
        await usage.enforce_budget(user)  # marking only: nothing is refused
        monkeypatch.setattr(settings, "USAGE_BUDGET_HARD", True)
        usage._SPENT_CACHE.clear()
        with pytest.raises(HTTPException) as refused:
            await usage.enforce_budget(user)
        assert refused.value.status_code == 429 and "1" in refused.value.detail
        await usage.enforce_budget(Principal("anonymous", "acme", "legal"))  # not signed in: no one to charge
        usage._SPENT_CACHE.clear()
        spent["value"] = 0.99
        await usage.enforce_budget(user)  # under budget
        usage._SPENT_CACHE.clear()
        spent["value"] = None
        await usage.enforce_budget(user)  # the database is down: chat stays up

    asyncio.run(scenario())
    usage._SPENT_CACHE.clear()


def test_the_cost_report_says_whether_the_budget_blocks_or_only_marks(monkeypatch):
    class EmptyPg:
        async def fetch(self, sql, *args):
            return []

    async def hard(budget, switch):
        monkeypatch.setattr(settings, "USAGE_BUDGET_USD_PER_USER_DAY", budget)
        monkeypatch.setattr(settings, "USAGE_BUDGET_HARD", switch)
        return (await usage.summary(EmptyPg(), 7))["budget_hard"]

    assert asyncio.run(hard(2.0, True)) is True
    assert asyncio.run(hard(2.0, False)) is False
    assert asyncio.run(hard(0.0, True)) is False  # no budget, nothing to block


def test_creating_an_account_needs_the_switch_that_lets_database_accounts_sign_in(jwt_mode, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ALLOW_REGISTRATION", False)

    async def scenario():
        async with client_for(pg=object()) as client:
            body = {"username": "opsdana", "tenant_id": "acme", "department_id": "legal"}
            assert (await client.post("/api/admin/users", headers=bearer("opsalice"), json=body)).status_code == 409
            monkeypatch.setattr(settings, "AUTH_ALLOW_REGISTRATION", True)
            assert (await client.post("/api/admin/users", headers=bearer("opsalice"), json={**body, "username": "x"})).status_code == 422  # too short
            assert (await client.post("/api/admin/users", headers=bearer("opsalice"), json={**body, "roles": ["Bad Role"]})).status_code == 422
            assert (await client.post("/api/admin/users", headers=bearer("opsalice"), json={**body, "username": "root"})).status_code == 409  # AUTH_USERS name

    asyncio.run(scenario())


# ---------------------------------------------------------------- real PostgreSQL
@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
class TestAgainstPostgres:
    @staticmethod
    def run(scenario):
        from src.shared.migrations import upgrade_to_head
        from src.shared.postgres_client import PostgresClient

        upgrade_to_head(DSN)
        tables = ("jobs", "usage_events", "rag_feedback", "answer_reviews", "app_users", "departments", "tenants")

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

    def test_the_audit_trail_filters_pages_and_exports_without_formulas(self, jwt_mode):
        async def scenario(pg):
            opsalice = Principal("opsalice", "acme", "legal", frozenset({"admin"}), authenticated=True)
            opscarol = Principal("opscarol", "globex", "ops", frozenset({"admin"}), authenticated=True)
            marker = f"t{int(time.time())}"
            await audit.record("admin.user_update", f"{marker}-opsbob", principal=opsalice)
            await audit.record("hitl.requested", f"{marker}-act_1", "pending", principal=opscarol)
            await audit.record("kb.delete", f"=cmd|{marker}", principal=opsalice)
            await audit.record("admin.tenant_create", f"{marker}-X", "denied", principal=opsalice)
            async with client_for(pg=pg) as client:
                headers = bearer("root-admin")

                async def rows(**params):
                    response = await client.get("/api/admin/audit", headers=headers, params={"q": marker, **params})
                    assert response.status_code == 200
                    return response.json()

                assert len((await rows())["rows"]) == 4
                assert [r["action"] for r in (await rows(actor="opscarol"))["rows"]] == ["hitl.requested"]
                assert {r["action"] for r in (await rows(action="admin."))["rows"]} == {"admin.user_update", "admin.tenant_create"}  # a prefix
                assert [r["tenant_id"] for r in (await rows(tenant="globex"))["rows"]] == ["globex"]
                assert [r["target"] for r in (await rows(outcome="denied"))["rows"]] == [f"{marker}-X"]
                assert len((await rows(q=marker.upper()))["rows"]) == 4  # the target match ignores case
                first = await rows(limit=3)
                assert len(first["rows"]) == 3 and first["next_before"] == first["rows"][-1]["id"]
                second = await rows(limit=3, before=first["next_before"])
                assert len(second["rows"]) == 1 and second["next_before"] is None
                assert (await rows(since="2999-01-01T00:00:00"))["rows"] == []
                bad = await client.get("/api/admin/audit", headers=headers, params={"since": "2026-10-02T00:00:00", "until": "2026-10-01T00:00:00"})
                assert bad.status_code == 422

                export = await client.get("/api/admin/audit/export", headers=headers, params={"q": marker})
                assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
                assert "attachment" in export.headers["content-disposition"] and export.text.startswith("﻿id,at,tenant,actor")
                assert f"'=cmd|{marker}" in export.text and f",=cmd|{marker}" not in export.text  # neutralised
                assert (await rows(action="admin.audit_export", q="audit_log"))["rows"]  # the export is itself on the record

        self.run(scenario)

    def test_an_administrator_creates_an_account_that_can_sign_in_then_resets_and_signs_it_out(self, jwt_mode, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_ALLOW_REGISTRATION", True)

        async def scenario(pg):
            async with client_for(pg=pg) as client:
                headers = bearer("opsalice")
                await client.post("/api/admin/tenants", headers=headers, json={"id": "acme", "name": "Acme"})
                await client.post("/api/admin/tenants/acme/departments", headers=headers, json={"id": "legal"})
                made = await client.post("/api/admin/users", headers=headers, json={"username": "Opsdana", "display_name": "Opsdana", "tenant_id": "acme", "department_id": "legal", "roles": ["approver"]})
                assert made.status_code == 201 and made.headers["cache-control"] == "no-store"
                body = made.json()
                assert body["user"]["username"] == "opsdana" and body["user"]["roles"] == ["approver"] and body["user"]["pending"] is False
                row = await get_user(pg, "opsdana")
                assert verify_user_row(body["temporary_password"], row) and verify_recovery_key(body["recovery_key"], row)
                assert body["temporary_password"] not in str(await pg.fetch("SELECT detail FROM audit_log"))  # secrets never reach the trail
                assert (await client.post("/api/admin/users", headers=headers, json={"username": "opsdana", "tenant_id": "acme", "department_id": "legal"})).status_code == 409

                reset = await client.post("/api/admin/users/opsdana/reset-credentials", headers=headers)
                assert reset.status_code == 200
                fresh = reset.json()
                row = await get_user(pg, "opsdana")
                assert fresh["temporary_password"] != body["temporary_password"]
                assert verify_user_row(fresh["temporary_password"], row) and not verify_user_row(body["temporary_password"], row)
                assert verify_recovery_key(fresh["recovery_key"], row) and not verify_recovery_key(body["recovery_key"], row)
                assert jwt_mode[-1] == "opsdana"  # her open sessions ended

                assert (await client.post("/api/admin/users/opsdana/sign-out", headers=headers)).json() == {"signed_out": True}
                assert (await client.post("/api/admin/users/ghost/sign-out", headers=headers)).status_code == 404
                assert (await client.post("/api/admin/users/opsalice/sign-out", headers=headers)).status_code == 409  # not yourself
                assert (await client.post("/api/admin/users/root/reset-credentials", headers=headers)).status_code == 409  # AUTH_USERS
                await pg.execute("INSERT INTO app_users (username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id) VALUES ('sso:e@x', '', 'sso', '', '{}', 'acme', 'legal')")
                assert (await client.post("/api/admin/users/sso:e@x/reset-credentials", headers=headers)).status_code == 409  # its password is the provider's
                actions = {r["action"] for r in await pg.fetch("SELECT action FROM audit_log")}
                assert {"admin.user_create", "admin.user_reset", "admin.user_signout"} <= actions

        self.run(scenario)

    def test_bulk_actions_report_what_was_done_and_what_was_skipped_and_why(self, jwt_mode, monkeypatch):
        async def scenario(pg):
            for name in ("opsbob", "opscarol", "opsalice"):
                await pg.execute("INSERT INTO app_users (username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id) VALUES ($1, $1, 'x', 'x', '{}', 'acme', 'legal')", name)
            first_id = (await pg.fetch("SELECT COALESCE(max(id), 0) AS m FROM audit_log"))[0]["m"]
            async with client_for(pg=pg) as client:
                headers = bearer("opsalice")
                locked = (await client.post("/api/admin/users/bulk", headers=headers, json={"usernames": ["opsbob", "opscarol", "opsalice", "root", "ghost"], "action": "lock"})).json()
                assert locked["done"] == ["opsbob", "opscarol"]
                assert {s["username"]: s["reason"] for s in locked["skipped"]} == {"opsalice": "self", "root": "env_managed", "ghost": "not_found"}
                assert {r["username"]: r["disabled"] for r in await pg.fetch("SELECT username, disabled FROM app_users")} == {"opsbob": True, "opscarol": True, "opsalice": False}
                assert (await client.post("/api/admin/users/bulk", headers=headers, json={"usernames": ["opsbob"], "action": "unlock"})).json()["done"] == ["opsbob"]
                assert (await client.post("/api/admin/users/bulk", headers=headers, json={"usernames": ["opsbob"], "action": "move"})).status_code == 422  # no target
                moved = (await client.post("/api/admin/users/bulk", headers=headers, json={"usernames": ["opsbob", "opscarol"], "action": "move", "tenant_id": "globex", "department_id": "ops"})).json()
                assert moved["done"] == ["opsbob", "opscarol"]
                assert {r["tenant_id"] for r in await pg.fetch("SELECT tenant_id FROM app_users WHERE username IN ('opsbob', 'opscarol')")} == {"globex"}
                assert (await client.post("/api/admin/users/bulk", headers=headers, json={"usernames": [], "action": "lock"})).status_code == 422
                assert set(jwt_mode) >= {"opsbob", "opscarol"}  # everyone touched was signed out
                updates = await pg.fetch("SELECT detail FROM audit_log WHERE action = 'admin.user_update' AND id > $1", first_id)  # audit_log is append-only: earlier rows stay
                assert len(updates) == 5  # one record per account, every time

                monkeypatch.setattr(settings, "ORG_ENFORCE_REGISTRY", True)
                refused = await client.post("/api/admin/users/bulk", headers=headers, json={"usernames": ["opsbob"], "action": "move", "tenant_id": "nowhere", "department_id": "x"})
                assert refused.status_code == 422  # not in the registry

        self.run(scenario)

    def test_enforcing_the_registry_limits_where_an_account_may_be_put(self, jwt_mode, monkeypatch):
        monkeypatch.setattr(settings, "ORG_ENFORCE_REGISTRY", True)
        monkeypatch.setattr(settings, "AUTH_ALLOW_REGISTRATION", True)

        async def scenario(pg):
            await pg.execute("INSERT INTO app_users (username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id) VALUES ('opsbob', 'opsbob', 'x', 'x', '{}', $1, $2)", settings.REGISTRATION_TENANT_ID, settings.REGISTRATION_DEPARTMENT_ID)
            async with client_for(pg=pg) as client:
                headers = bearer("opsalice")
                assert (await client.patch("/api/admin/users/opsbob", headers=headers, json={"tenant_id": "acme", "department_id": "legal"})).status_code == 422
                await client.post("/api/admin/tenants", headers=headers, json={"id": "acme"})
                assert (await client.patch("/api/admin/users/opsbob", headers=headers, json={"tenant_id": "acme", "department_id": "legal"})).status_code == 422  # the department too
                await client.post("/api/admin/tenants/acme/departments", headers=headers, json={"id": "legal"})
                assert (await client.patch("/api/admin/users/opsbob", headers=headers, json={"tenant_id": "acme", "department_id": "legal"})).status_code == 200
                assert (await client.patch("/api/admin/users/opsbob", headers=headers, json={"roles": ["approver"]})).status_code == 200  # a role change is not a move
                created = {"username": "opserin", "tenant_id": "ghost", "department_id": "x"}
                assert (await client.post("/api/admin/users", headers=headers, json=created)).status_code == 422
                pending = {"username": "opserin", "tenant_id": settings.REGISTRATION_TENANT_ID, "department_id": settings.REGISTRATION_DEPARTMENT_ID}
                assert (await client.post("/api/admin/users", headers=headers, json=pending)).status_code == 201  # the pending pair is always allowed

        self.run(scenario)

    def test_tenants_and_departments_are_renamed_registered_and_deleted_only_when_unused(self, jwt_mode):
        async def scenario(pg):
            await pg.execute("INSERT INTO app_users (username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id) VALUES ('opsbob', 'opsbob', 'x', 'x', '{}', 'globex', 'ops')")
            async with client_for(pg=pg) as client:
                headers = bearer("opsalice")
                await client.post("/api/admin/tenants", headers=headers, json={"id": "initech", "name": "Initech"})
                renamed = (await client.patch("/api/admin/tenants/initech", headers=headers, json={"name": "  Initech Corp "})).json()
                assert renamed["name"] == "Initech Corp"
                registered = (await client.patch("/api/admin/tenants/globex", headers=headers, json={"name": "Globex"})).json()  # only accounts used it until now
                assert registered["registered"] is True and registered["name"] == "Globex"
                assert (await client.patch("/api/admin/tenants/nobody", headers=headers, json={"name": "x"})).status_code == 404
                assert (await client.patch(f"/api/admin/tenants/{settings.REGISTRATION_TENANT_ID}", headers=headers, json={"name": "x"})).status_code == 409

                await client.post("/api/admin/tenants/initech/departments", headers=headers, json={"id": "legal"})
                assert (await client.patch("/api/admin/tenants/initech/departments/legal", headers=headers, json={"name": "Pháp chế"})).status_code == 200
                assert (await client.patch("/api/admin/tenants/initech/departments/none", headers=headers, json={"name": "x"})).status_code == 404
                assert (await client.delete("/api/admin/tenants/globex", headers=headers)).status_code == 409  # an account uses it
                assert (await client.delete("/api/admin/tenants/nobody", headers=headers)).status_code == 404
                assert (await client.delete("/api/admin/tenants/initech/departments/legal", headers=headers)).status_code == 204
                assert (await client.delete("/api/admin/tenants/initech/departments/legal", headers=headers)).status_code == 404
                assert (await client.delete("/api/admin/tenants/initech", headers=headers)).status_code == 204
                assert {r["action"] for r in await pg.fetch("SELECT action FROM audit_log")} >= {"admin.tenant_rename", "admin.department_rename", "admin.tenant_delete", "admin.department_delete"}

        self.run(scenario)

    def test_the_cost_report_can_be_narrowed_to_one_tenant(self, jwt_mode):
        async def scenario(pg):
            for tenant, user, cost in (("acme", "amy", 1.5), ("acme", "opsbob", 0.5), ("globex", "gus", 4.0)):
                await pg.execute("INSERT INTO usage_events (tenant_id, user_id, model, call_type, prompt_tokens, completion_tokens, cost_usd) VALUES ($1, $2, 'm', 'acompletion', 10, 5, $3)", tenant, user, cost)
            async with client_for(pg=pg) as client:
                everything = (await client.get("/api/admin/usage", headers=bearer("opsalice"))).json()
                assert everything["totals"]["cost"] == 6.0 and len(everything["tenants"]) == 2
                acme = (await client.get("/api/admin/usage", headers=bearer("opsalice"), params={"tenant": "acme"})).json()
                assert acme["totals"]["cost"] == 2.0 and [t["tenant_id"] for t in acme["tenants"]] == ["acme"] and {u["user_id"] for u in acme["users"]} == {"amy", "opsbob"}
                assert (await client.get("/api/admin/usage", headers=bearer("opsalice"), params={"tenant": "bad tenant!"})).status_code == 422

        self.run(scenario)

    def test_jobs_are_listed_and_only_a_queued_one_can_be_cancelled(self, jwt_mode):
        async def scenario(pg):
            for job_id, status in (("j-queued", "queued"), ("j-running", "running"), ("j-failed", "failed")):
                await pg.execute("INSERT INTO jobs (id, kind, tenant_id, user_id, status, error, payload_bytes) VALUES ($1, 'kb.upload', 'acme', 'opsbob', $2, '', $3)", job_id, status, b"file-bytes")
            async with client_for(pg=pg) as client:
                headers = bearer("opsalice")
                listing = (await client.get("/api/admin/jobs", headers=headers)).json()
                assert {j["id"] for j in listing["jobs"]} == {"j-queued", "j-running", "j-failed"} and listing["counts"] == {"queued": 1, "running": 1, "failed": 1}
                assert [j["id"] for j in (await client.get("/api/admin/jobs", headers=headers, params={"status": "running"})).json()["jobs"]] == ["j-running"]
                assert (await client.get("/api/admin/jobs", headers=headers, params={"status": "weird"})).status_code == 422
                assert (await client.post("/api/admin/jobs/j-running/cancel", headers=headers)).status_code == 409
                assert (await client.post("/api/admin/jobs/j-failed/cancel", headers=headers)).status_code == 409
                assert (await client.post("/api/admin/jobs/ghost/cancel", headers=headers)).status_code == 404
                assert (await client.post("/api/admin/jobs/j-queued/cancel", headers=headers)).json() == {"cancelled": True}
                row = (await pg.fetch("SELECT status, error, payload_bytes, finished_at FROM jobs WHERE id = 'j-queued'"))[0]
                assert row["status"] == "failed" and row["error"] == "Cancelled by opsalice" and row["payload_bytes"] is None and row["finished_at"] is not None
                assert (await pg.fetch("SELECT 1 FROM audit_log WHERE action = 'admin.job_cancel' AND target = 'j-queued'"))

        self.run(scenario)

    def test_the_feedback_report_adds_up_per_day_and_tenant_and_shows_the_down_votes(self, jwt_mode):
        async def scenario(pg):
            rows = (("acme", "amy", 1, "How many leave days?", ""), ("acme", "opsbob", -1, "Where is the NDA?", "wrong file"), ("globex", "gus", -1, "Refund policy?", ""), ("acme", "cat", 1, "q", ""))
            for tenant, user, rating, query, comment in rows:
                await pg.execute("INSERT INTO rag_feedback (tenant_id, user_id, query, rating, comment) VALUES ($1, $2, $3, $4, $5)", tenant, user, query, rating, comment)
            async with client_for(pg=pg) as client:
                report = (await client.get("/api/admin/feedback", headers=bearer("opsalice"))).json()
                assert (report["up"], report["down"]) == (2, 2) and report["satisfaction"] == 0.5
                assert sum(d["up"] for d in report["per_day"]) == 2 and sum(d["down"] for d in report["per_day"]) == 2
                assert {t["tenant_id"]: (t["up"], t["down"]) for t in report["tenants"]} == {"acme": (2, 1), "globex": (0, 1)}
                assert {r["query"] for r in report["recent_down"]} == {"Where is the NDA?", "Refund policy?"}
                acme = (await client.get("/api/admin/feedback", headers=bearer("opsalice"), params={"tenant": "acme"})).json()
                assert (acme["up"], acme["down"]) == (2, 1) and [r["user_id"] for r in acme["recent_down"]] == ["opsbob"]
                await pg.execute("DELETE FROM rag_feedback")
                empty = (await client.get("/api/admin/feedback", headers=bearer("opsalice"))).json()
                assert empty["satisfaction"] is None and empty["per_day"] == []

        self.run(scenario)

    def test_a_thumbs_down_keeps_who_answered_what_and_why_and_the_report_groups_it(self, jwt_mode):
        from fastapi import FastAPI

        from src.gateway.feedback import router as feedback_router
        from src.shared.auth import authenticate

        async def scenario(pg):
            app = FastAPI()
            app.include_router(feedback_router)
            app.state.pg_client = pg
            app.dependency_overrides[authenticate] = lambda: Principal("amy", "acme", "legal", authenticated=True)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as user:
                body = {"rating": -1, "query": "NDA bao lâu?", "agent": "rag_agent", "answer": "Gọi 0901234567 để biết thêm.", "run_id": "run-1",
                        "verified": False, "retries": 1, "reasons": ["wrong", "missing_source"]}
                assert (await user.post("/api/chat/feedback", json=body)).status_code == 204
                assert (await user.post("/api/chat/feedback", json={**body, "rating": 1, "agent": "search_agent", "reasons": []})).status_code == 204
                assert (await user.post("/api/chat/feedback", json={**body, "reasons": ["bogus"]})).status_code == 422  # only the known reasons
            row = (await pg.fetch("SELECT agent, answer, run_id, verified, retries, reasons FROM rag_feedback WHERE rating < 0"))[0]
            assert (row["agent"], row["run_id"], row["verified"], row["retries"], sorted(row["reasons"])) == ("rag_agent", "run-1", False, 1, ["missing_source", "wrong"])
            assert "0901234567" not in row["answer"]  # personal data is masked before it is stored
            await pg.execute("INSERT INTO answer_reviews (tenant_id, user_id, agent, query, answer, score, reason) VALUES ('acme', 'amy', 'rag_agent', 'q1', 'a1', 2, 'né câu hỏi'), ('acme', 'amy', 'rag_agent', 'q2', 'a2', 5, ''), ('globex', 'gus', 'search_agent', 'q3', 'a3', 4, '')")
            async with client_for(pg=pg) as client:
                report = (await client.get("/api/admin/feedback", headers=bearer("opsalice"))).json()
                assert {a["agent"]: (a["up"], a["down"]) for a in report["agents"]} == {"rag_agent": (0, 1), "search_agent": (1, 0)}
                assert {r["reason"]: r["count"] for r in report["reasons"]} == {"wrong": 1, "missing_source": 1}
                down = report["recent_down"][0]
                assert (down["agent"], down["verified"], down["retries"], sorted(down["reasons"])) == ("rag_agent", False, 1, ["missing_source", "wrong"])
                reviews = report["reviews"]
                assert (reviews["graded"], reviews["low"]) == (3, 1) and reviews["average"] == pytest.approx(11 / 3)
                assert {a["agent"]: a["graded"] for a in reviews["agents"]} == {"rag_agent": 2, "search_agent": 1}
                assert [r["query"] for r in reviews["recent_low"]] == ["q1"]
                only_acme = (await client.get("/api/admin/feedback", headers=bearer("opsalice"), params={"tenant": "acme"})).json()["reviews"]
                assert only_acme["graded"] == 2

        self.run(scenario)
