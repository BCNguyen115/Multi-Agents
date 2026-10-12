# ruff: noqa: F811  (the fixture jwt_mode is imported from test_admin_ops and then requested by name)
"""What a department may use: the fallback rules, the Principal's answers, the orchestrator's refusal, the console endpoints and deleting a
tenant or department with its accounts moved (real PostgreSQL via RAG_TEST_DSN where it matters)."""
import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import Depends, FastAPI

from src.config import settings
from src.gateway import admin, admin_ops
from src.orchestrator.core import Orchestrator
from src.shared import audit, auth, policy
from src.shared.auth import Principal, acting_as
from src.shared.security import wrap_user_input

from tests.test_admin_ops import FakeRedis, bearer, jwt_mode

DSN = os.getenv("RAG_TEST_DSN")


# ---------------------------------------------------------------- no database needed
def test_each_field_falls_back_on_its_own_from_the_department_to_the_tenant_to_nothing():
    tenant = {"allowed_agents": ["rag_agent", "search_agent"], "can_upload_knowledge": False}
    assert policy.merge(None, None) == policy.Policy()
    assert policy.merge(None, tenant) == policy.Policy(frozenset({"rag_agent", "search_agent"}), False)
    # a department that sets only the agents still inherits the tenant's upload rule, and the other way round
    assert policy.merge({"allowed_agents": ["data_agent"], "can_upload_knowledge": None}, tenant) == policy.Policy(frozenset({"data_agent"}), False)
    assert policy.merge({"allowed_agents": None, "can_upload_knowledge": True}, tenant) == policy.Policy(frozenset({"rag_agent", "search_agent"}), True)


def test_a_principal_is_limited_by_the_policy_but_an_administrator_never_is(monkeypatch):
    monkeypatch.setattr(settings, "KNOWLEDGE_UPLOAD_ROLES", ["uploader"])
    monkeypatch.setattr(settings, "ADMIN_ROLES", ["admin"])

    def who(roles=(), agents=None, upload=None):
        return Principal("u", "acme", "legal", frozenset(roles), authenticated=True, allowed_agents=agents, upload_override=upload)

    assert who().can_use_agent("db_agent")  # no policy: every agent
    limited = who(agents=frozenset({"rag_agent"}))
    assert limited.can_use_agent("rag_agent") and not limited.can_use_agent("db_agent")
    assert who(roles=["admin"], agents=frozenset({"rag_agent"})).can_use_agent("db_agent")
    assert Principal("anonymous", "t", "d", allowed_agents=frozenset()).can_use_agent("db_agent")  # anonymous dev mode is not restricted

    assert who(roles=["uploader"]).can_manage_knowledge and not who().can_manage_knowledge
    assert not who(roles=["uploader"], upload=False).can_manage_knowledge  # the policy takes it away
    assert who(upload=True).can_manage_knowledge  # ...or grants it without the role
    assert not who(roles=["admin"]).can_manage_knowledge  # unchanged: an administrator needs a KNOWLEDGE_UPLOAD_ROLES role like anybody
    assert who(roles=["admin", "uploader"], upload=False).can_manage_knowledge  # and a policy never takes it from an administrator


def _orchestrator():
    reply = {"answer": "Thời hạn là 2 năm [1].", "sources": [], "verification": {"status": "ok", "grounded": True, "cited": [1], "unsupported_numbers": []}}
    agent = SimpleNamespace(process_request=AsyncMock(return_value=json.dumps(reply, ensure_ascii=False)))
    registry = MagicMock()
    registry.lookup = MagicMock(return_value=agent)
    cfg = MagicMock(HITL_APPROVAL_TTL_SECONDS=900, FAST_LLM_MODEL="fast", OPENROUTER_MODEL="m", HEAVY_LLM_MODEL="heavy")
    memory = MagicMock()
    memory.get_relevant_memories = MagicMock(return_value=[])
    memory.add_memory = MagicMock(return_value={})
    llm = MagicMock()
    llm.get_langfuse_callback = MagicMock(return_value=None)
    llm.flush_async = AsyncMock()
    return Orchestrator(registry=registry, settings=cfg, llm_client=llm, memory_manager=memory), agent


def test_the_orchestrator_refuses_an_agent_the_department_may_not_use_and_never_calls_it():
    query = wrap_user_input("Thời hạn NDA?")[0]
    for agents, expected_calls in ((frozenset({"data_agent"}), 0), (frozenset({"rag_agent"}), 1), (None, 1)):
        orch, agent = _orchestrator()
        caller = Principal("amy", "acme", "legal", frozenset(), authenticated=True, allowed_agents=agents)
        with acting_as(caller):
            out = json.loads(asyncio.run(orch.handle_request(query=query, session_id="s1", agent_mode="rag_agent")))
        assert agent.process_request.await_count == expected_calls
        if expected_calls == 0:
            assert "chưa được phép" in json.dumps(out, ensure_ascii=False) or "not allowed" in json.dumps(out)


# ---------------------------------------------------------------- real PostgreSQL
def app_with(pg):
    app = FastAPI()
    app.include_router(admin.router)
    app.include_router(admin_ops.router)
    app.state.redis_client = SimpleNamespace(client=FakeRedis())
    app.state.pg_client = pg

    @app.get("/whoami")
    async def whoami(principal: Principal = Depends(auth.authenticate)):
        return {"rag": principal.can_use_agent("rag_agent"), "data": principal.can_use_agent("data_agent"), "upload": principal.can_manage_knowledge}

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
class TestAgainstPostgres:
    @staticmethod
    def run(scenario):
        from src.shared.migrations import upgrade_to_head
        from src.shared.postgres_client import PostgresClient

        upgrade_to_head(DSN)
        tables = ("department_policies", "app_users", "departments", "tenants")

        async def go():
            pg = PostgresClient(dsn=DSN)
            await pg.connect(min_size=1, max_size=4)
            audit.configure(pg)
            policy.configure(pg)
            try:
                for table in tables:
                    await pg.execute(f"DELETE FROM {table}")
                await scenario(pg)
            finally:
                audit.configure(None)
                policy.configure(None)
                for table in tables:
                    await pg.execute(f"DELETE FROM {table}")
                await pg.disconnect()

        asyncio.run(go())

    def test_policies_are_set_validated_inherited_and_seen_by_the_next_request(self, jwt_mode, monkeypatch):
        monkeypatch.setattr(settings, "KNOWLEDGE_UPLOAD_ROLES", ["uploader"])

        async def scenario(pg):
            async with app_with(pg) as client:
                admin_headers = bearer("opsalice", roles=("admin",), tenant="polco")
                await client.post("/api/admin/tenants", headers=admin_headers, json={"id": "polco"})
                await client.post("/api/admin/tenants/polco/departments", headers=admin_headers, json={"id": "legal"})
                member = bearer("opsmember", roles=("uploader",), tenant="polco")  # department "legal" (see bearer)
                assert (await client.get("/whoami", headers=member)).json() == {"rag": True, "data": True, "upload": True}  # no policy: no restriction

                def put(body, scope="polco/legal"):
                    return client.put(f"/api/admin/policies/{scope}", headers=admin_headers, json=body)

                assert (await put({"allowed_agents": ["rag_agent", "made_up"]})).status_code == 422
                assert (await put({"allowed_agents": []})).status_code == 422  # "none at all" is not a choice: leave it empty for the default
                assert (await put({"allowed_agents": ["rag_agent"]}, "polco/ghost")).status_code == 422
                assert (await put({"allowed_agents": ["rag_agent"]}, "nowhere/legal")).status_code == 422
                assert (await put({"allowed_agents": ["rag_agent"]}, f"{settings.REGISTRATION_TENANT_ID}/*")).status_code == 409

                # the tenant default limits every department that says nothing itself
                assert (await put({"allowed_agents": ["rag_agent"], "can_upload_knowledge": False}, "polco/*")).status_code == 200
                assert (await client.get("/whoami", headers=member)).json() == {"rag": True, "data": False, "upload": False}
                # a department's own value wins, field by field
                assert (await put({"allowed_agents": ["rag_agent", "data_agent"], "can_upload_knowledge": True})).status_code == 200
                assert (await client.get("/whoami", headers=member)).json() == {"rag": True, "data": True, "upload": True}
                # an administrator is never limited
                admin_as_user = (await client.get("/whoami", headers=admin_headers)).json()
                assert admin_as_user["rag"] and admin_as_user["data"]

                listing = (await client.get("/api/admin/policies", headers=admin_headers)).json()
                assert listing["agents"] == list(policy.KNOWN_AGENTS)
                by_scope = {(p["tenant_id"], p["department_id"]): p for p in listing["policies"]}
                assert by_scope[("polco", "legal")]["allowed_agents"] == ["data_agent", "rag_agent"] and by_scope[("polco", "legal")]["updated_by"] == "opsalice"
                assert by_scope[("polco", "*")]["can_upload_knowledge"] is False

                # both fields empty removes the policy: the department follows the tenant default again
                assert (await put({})).status_code == 200
                assert (await client.get("/whoami", headers=member)).json() == {"rag": True, "data": False, "upload": False}
                assert await pg.fetch("SELECT 1 FROM audit_log WHERE action = 'admin.policy_set' AND target = 'polco/legal'")

        self.run(scenario)

    def test_a_department_with_accounts_is_deleted_only_when_they_are_moved_and_the_policy_goes_with_it(self, jwt_mode):
        async def scenario(pg):
            async with app_with(pg) as client:
                headers = bearer("opsalice", roles=("admin",), tenant="delco")
                await client.post("/api/admin/tenants", headers=headers, json={"id": "delco"})
                for dept in ("sales", "ops"):
                    await client.post("/api/admin/tenants/delco/departments", headers=headers, json={"id": dept})
                for name in ("opsone", "opstwo"):
                    await pg.execute("INSERT INTO app_users (username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id) VALUES ($1, $1, 'x', 'x', '{}', 'delco', 'sales')", name)
                await client.put("/api/admin/policies/delco/sales", headers=headers, json={"allowed_agents": ["rag_agent"]})

                url = "/api/admin/tenants/delco/departments/sales"
                assert (await client.delete(url, headers=headers)).status_code == 409  # accounts still use it, and nowhere to send them
                assert (await client.delete(url, headers=headers, params={"move_to": "sales"})).status_code == 422  # not itself
                assert (await client.delete(url, headers=headers, params={"move_to": "ghost"})).status_code == 422  # not a department that exists
                assert (await client.delete(url, headers=headers, params={"move_to": "ops"})).status_code == 204
                moved = {r["username"]: r["department_id"] for r in await pg.fetch("SELECT username, department_id FROM app_users")}
                assert moved == {"opsone": "ops", "opstwo": "ops"}
                assert not await pg.fetch("SELECT 1 FROM department_policies WHERE tenant_id = 'delco'")  # its policy is gone
                assert set(jwt_mode) >= {"opsone", "opstwo"}  # they were signed out: the new scope applies now
                record = (await pg.fetch("SELECT detail FROM audit_log WHERE action = 'admin.org_move_users' AND target = 'delco/sales'"))[0]["detail"]
                assert json.loads(record)["users"] == ["opsone", "opstwo"]  # the audit names who was moved

        self.run(scenario)

    def test_a_tenant_is_deleted_with_its_departments_and_policies_after_its_accounts_move_elsewhere(self, jwt_mode, monkeypatch):
        async def scenario(pg):
            async with app_with(pg) as client:
                headers = bearer("opsalice", roles=("admin",), tenant="oldco")
                for tenant in ("oldco", "newco"):
                    await client.post("/api/admin/tenants", headers=headers, json={"id": tenant})
                    await client.post(f"/api/admin/tenants/{tenant}/departments", headers=headers, json={"id": "hq"})
                await client.put("/api/admin/policies/oldco/*", headers=headers, json={"allowed_agents": ["rag_agent"]})
                await pg.execute("INSERT INTO app_users (username, display_name, password_hash, recovery_hash, roles, tenant_id, department_id) VALUES ('opsone', 'o', 'x', 'x', '{}', 'oldco', 'hq')")

                assert (await client.delete("/api/admin/tenants/oldco", headers=headers)).status_code == 409
                assert (await client.delete("/api/admin/tenants/oldco", headers=headers, params={"move_to": "oldco/hq"})).status_code == 422  # not into itself
                assert (await client.delete("/api/admin/tenants/oldco", headers=headers, params={"move_to": "newco/ghost"})).status_code == 422
                assert (await client.delete("/api/admin/tenants/oldco", headers=headers, params={"move_to": "newco/hq"})).status_code == 204
                row = (await pg.fetch("SELECT tenant_id, department_id FROM app_users WHERE username = 'opsone'"))[0]
                assert (row["tenant_id"], row["department_id"]) == ("newco", "hq")
                assert not await pg.fetch("SELECT 1 FROM tenants WHERE id = 'oldco'") and not await pg.fetch("SELECT 1 FROM departments WHERE tenant_id = 'oldco'")
                assert not await pg.fetch("SELECT 1 FROM department_policies WHERE tenant_id = 'oldco'")
                # an account of the server configuration cannot be moved from here
                monkeypatch.setattr(settings, "AUTH_USERS", [{"username": "rootenv", "password_hash": "x", "roles": ["admin"], "tenant_id": "newco", "department_id": "hq"}])
                target = f"{settings.REGISTRATION_TENANT_ID}/{settings.REGISTRATION_DEPARTMENT_ID}"
                assert (await client.delete("/api/admin/tenants/newco", headers=headers, params={"move_to": target})).status_code == 409

        self.run(scenario)
