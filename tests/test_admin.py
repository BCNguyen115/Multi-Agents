"""Account administration: who may use it, what it may change, the audit-first rule, locked accounts (real PostgreSQL via RAG_TEST_DSN)."""
import asyncio
import os
import time

import httpx
import jwt
import pytest
from fastapi import FastAPI

from src.config import settings
from src.gateway import admin
from src.shared import audit
from src.shared.auth import hash_password

SECRET = "0123456789abcdef0123456789abcdef-test-secret"
DSN = os.getenv("RAG_TEST_DSN")


def bearer(user, roles=("admin",), tenant="acme"):
    claims = {"sub": user, "exp": int(time.time()) + 300, "tenant_id": tenant, "department_id": "legal", "roles": list(roles)}
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


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


def client_for(pg=None):
    app = FastAPI()
    app.include_router(admin.router)
    app.state.redis_client = object()
    if pg is not None:
        app.state.pg_client = pg
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------- no database needed
def test_only_administrators_get_in_and_bad_input_is_refused_early(jwt_mode):
    async def scenario():
        async with client_for() as client:
            assert (await client.get("/api/admin/users")).status_code == 401
            assert (await client.get("/api/admin/users", headers=bearer("bob", roles=("approver",)))).status_code == 403
            assert (await client.patch("/api/admin/users/x", headers=bearer("bob", roles=()), json={"disabled": True})).status_code == 403
            assert (await client.get("/api/admin/users", headers=bearer("alice"))).status_code == 503  # an admin, but no database here
            admin_headers = bearer("alice")
            assert (await client.patch("/api/admin/users/root", headers=admin_headers, json={"disabled": True})).status_code == 409  # AUTH_USERS: environment
            assert (await client.patch("/api/admin/users/bob", headers=admin_headers, json={"roles": ["Not Valid"]})).status_code == 422
            assert (await client.patch("/api/admin/users/bob", headers=admin_headers, json={"tenant_id": "bad tenant!"})).status_code == 422

    asyncio.run(scenario())


def test_a_locked_account_reads_as_wrong_credentials_at_sign_in(monkeypatch):
    from src.gateway import main

    row = {"username": "bob", "password_hash": hash_password("correct horse battery"), "roles": [], "tenant_id": "acme", "department_id": "legal", "disabled": False}

    async def lookup(pg, username):
        return dict(row)

    monkeypatch.setattr(main, "get_user", lookup)

    async def scenario():
        assert (await main._registered_user("bob", "correct horse battery")) is not None
        row["disabled"] = True
        assert (await main._registered_user("bob", "correct horse battery")) is None

    asyncio.run(scenario())


def test_the_org_view_merges_the_registry_with_what_accounts_use(jwt_mode):
    everyone = [
        {"tenant_id": "acme", "department_id": "legal"}, {"tenant_id": "acme", "department_id": "legal"},
        {"tenant_id": "globex", "department_id": "ops"}, {"tenant_id": settings.REGISTRATION_TENANT_ID, "department_id": settings.REGISTRATION_DEPARTMENT_ID},
    ]
    tenants = [{"id": "acme", "name": "Acme Corp"}, {"id": "initech", "name": ""}]
    departments = [{"tenant_id": "acme", "id": "legal", "name": "Pháp chế"}, {"tenant_id": "acme", "id": "hr", "name": ""}]
    org = {t["id"]: t for t in admin._org(everyone, tenants, departments)}
    assert [t["id"] for t in admin._org(everyone, tenants, departments)][-1] == settings.REGISTRATION_TENANT_ID  # pending last
    assert (org["acme"]["name"], org["acme"]["registered"], org["acme"]["users"]) == ("Acme Corp", True, 2)
    assert {d["id"]: (d["registered"], d["users"]) for d in org["acme"]["departments"]} == {"legal": (True, 2), "hr": (True, 0)}
    assert (org["globex"]["registered"], org["globex"]["users"]) == (False, 1)  # used by an account, never created here
    assert org["initech"]["users"] == 0 and org["initech"]["registered"] is True  # created, nobody in it yet
    assert org[settings.REGISTRATION_TENANT_ID]["pending"] is True


def test_the_org_routes_are_for_administrators_and_check_ids_first(jwt_mode):
    async def scenario():
        async with client_for() as client:
            member = bearer("bob", roles=())
            assert (await client.get("/api/admin/org", headers=member)).status_code == 403
            assert (await client.post("/api/admin/tenants", headers=member, json={"id": "acme"})).status_code == 403
            admin_headers = bearer("alice")
            assert (await client.post("/api/admin/tenants", headers=admin_headers, json={"id": "bad tenant!"})).status_code == 422
            assert (await client.post("/api/admin/tenants/acme/departments", headers=admin_headers, json={"id": "x" * 65})).status_code == 422
            assert (await client.post("/api/admin/tenants/bad id!/departments", headers=admin_headers, json={"id": "legal"})).status_code == 422
            assert (await client.post("/api/admin/tenants", headers=admin_headers, json={"id": "acme"})).status_code == 503  # valid, but no database here

    asyncio.run(scenario())


# ---------------------------------------------------------------- real PostgreSQL
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
            audit.configure(pg)
            try:
                await pg.execute("DELETE FROM app_users")
                await pg.execute("DELETE FROM departments")
                await pg.execute("DELETE FROM tenants")
                for name in ("bob", "alice"):
                    await pg.execute(
                        "INSERT INTO app_users (username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id) VALUES ($1, $1, 'x', 'x', '{}', $2, $3)",
                        name, settings.REGISTRATION_TENANT_ID, settings.REGISTRATION_DEPARTMENT_ID,
                    )
                async with client_for(pg) as client:
                    await scenario(client, pg)
            finally:
                audit.configure(None)
                await pg.execute("DELETE FROM app_users")
                await pg.execute("DELETE FROM departments")
                await pg.execute("DELETE FROM tenants")
                await pg.disconnect()

        asyncio.run(go())

    def test_list_then_grant_a_pending_account_and_it_is_traced(self, jwt_mode):
        async def scenario(client, pg):
            headers = bearer("alice")
            listing = (await client.get("/api/admin/users", headers=headers)).json()
            by_name = {u["username"]: u for u in listing["users"]}
            assert by_name["bob"]["pending"] is True and by_name["bob"]["source"] == "registered"
            assert by_name["root"]["source"] == "env" and "password_hash" not in by_name["bob"]
            assert "acme" in listing["tenants"] and "admin" in listing["roles"]
            done = await client.patch("/api/admin/users/Bob", headers=headers, json={"tenant_id": "acme", "department_id": "legal", "roles": ["approver", "approver"]})
            assert done.status_code == 200
            assert done.json()["tenant_id"] == "acme" and done.json()["roles"] == ["approver"] and done.json()["pending"] is False
            assert jwt_mode == ["bob"]  # his open sessions ended: the new scope applies now
            trail = await pg.fetch("SELECT actor, action, target, detail FROM audit_log WHERE action = 'admin.user_update' AND target = 'bob'")
            assert len(trail) == 1 and trail[0]["actor"] == "alice"

        self.run(scenario)

    def test_lock_and_unlock(self, jwt_mode):
        async def scenario(client, pg):
            headers = bearer("alice")
            assert (await client.patch("/api/admin/users/bob", headers=headers, json={"disabled": True})).json()["disabled"] is True
            assert (await client.patch("/api/admin/users/bob", headers=headers, json={"disabled": False})).json()["disabled"] is False
            assert (await client.patch("/api/admin/users/nobody", headers=headers, json={"disabled": True})).status_code == 404

        self.run(scenario)

    def test_an_administrator_cannot_lock_themselves_out(self, jwt_mode):
        async def scenario(client, pg):
            headers = bearer("alice")
            assert (await client.patch("/api/admin/users/alice", headers=headers, json={"disabled": True})).status_code == 409
            assert (await client.patch("/api/admin/users/alice", headers=headers, json={"roles": ["approver"]})).status_code == 409
            ok = await client.patch("/api/admin/users/alice", headers=headers, json={"roles": ["admin", "approver"]})
            assert ok.status_code == 200 and jwt_mode == []  # allowed, and their own session is not cut

        self.run(scenario)

    def test_no_audit_record_means_no_change(self, jwt_mode):
        async def scenario(client, pg):
            audit.configure(None)  # the trail is unavailable
            with pytest.raises(RuntimeError):
                await client.patch("/api/admin/users/bob", headers=bearer("alice"), json={"roles": ["admin"]})
            row = await pg.fetch("SELECT roles FROM app_users WHERE username = 'bob'")
            assert list(row[0]["roles"]) == [] and jwt_mode == []

        self.run(scenario)

    def test_create_a_tenant_then_a_department_and_both_show_in_the_registry_and_the_trail(self, jwt_mode):
        async def scenario(client, pg):
            headers = bearer("alice")
            made = await client.post("/api/admin/tenants", headers=headers, json={"id": "initech", "name": "Initech JSC"})
            assert made.status_code == 201 and (made.json()["id"], made.json()["name"], made.json()["registered"]) == ("initech", "Initech JSC", True)
            assert (await client.post("/api/admin/tenants", headers=headers, json={"id": "initech"})).status_code == 409  # already there
            assert (await client.post("/api/admin/tenants", headers=headers, json={"id": settings.REGISTRATION_TENANT_ID})).status_code == 409
            dept = await client.post("/api/admin/tenants/initech/departments", headers=headers, json={"id": "finance", "name": "Tài chính"})
            assert dept.status_code == 201 and [d["id"] for d in dept.json()["departments"]] == ["finance"] and dept.json()["departments"][0]["registered"] is True
            assert (await client.post("/api/admin/tenants/initech/departments", headers=headers, json={"id": "finance"})).status_code == 409
            assert (await client.post("/api/admin/tenants/nowhere/departments", headers=headers, json={"id": "x"})).status_code == 404
            assert (await client.post(f"/api/admin/tenants/{settings.REGISTRATION_TENANT_ID}/departments", headers=headers, json={"id": "x"})).status_code == 409
            listing = (await client.get("/api/admin/users", headers=headers)).json()  # the pickers of the users table offer them
            assert "initech" in listing["tenants"] and "finance" in listing["departments"]
            org = {t["id"]: t for t in (await client.get("/api/admin/org", headers=headers)).json()}
            assert org["initech"]["departments"][0]["name"] == "Tài chính" and org[settings.REGISTRATION_TENANT_ID]["users"] == 2  # alice and bob
            trail = await pg.fetch("SELECT action, target, actor FROM audit_log WHERE action LIKE 'admin.%_create' ORDER BY id")
            assert [(r["action"], r["target"], r["actor"]) for r in trail][-2:] == [("admin.tenant_create", "initech", "alice"), ("admin.department_create", "initech/finance", "alice")]

        self.run(scenario)

    def test_a_department_can_be_added_to_a_tenant_that_only_accounts_use(self, jwt_mode):
        async def scenario(client, pg):
            # "acme" is registered nowhere: the AUTH_USERS account `root` uses it. Creating a department there registers the pair.
            made = await client.post("/api/admin/tenants/acme/departments", headers=bearer("alice"), json={"id": "legal"})
            assert made.status_code == 201 and made.json()["registered"] is False  # the tenant itself is still not in the registry
            assert [d["registered"] for d in made.json()["departments"] if d["id"] == "legal"] == [True]

        self.run(scenario)

    def test_no_audit_record_means_no_tenant(self, jwt_mode):
        async def scenario(client, pg):
            audit.configure(None)
            with pytest.raises(RuntimeError):
                await client.post("/api/admin/tenants", headers=bearer("alice"), json={"id": "ghost"})
            assert await pg.fetch("SELECT 1 FROM tenants WHERE id = 'ghost'") == []

        self.run(scenario)
