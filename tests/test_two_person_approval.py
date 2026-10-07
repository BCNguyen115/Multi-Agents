"""Two-person approval: somebody else decides, the action runs in the REQUESTER's scope, the result goes back to the requester only."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from src.config import settings
from src.orchestrator.approvals import ApprovalMixin
from src.shared import audit
from src.shared.auth import Principal, acting_as, current_scope

ALICE = Principal("alice", "acme", "legal", frozenset({"approver"}), authenticated=True)
BOB = Principal("bob", "acme", "finance", frozenset({"approver"}), authenticated=True)
CAROL = Principal("carol", "globex", "legal", frozenset({"approver"}), authenticated=True)
DAN = Principal("dan", "acme", "legal", frozenset(), authenticated=True)   # no approver role


class FakeRedis:
    """The few Redis calls approvals use, shared by every 'replica' that is given the same instance."""

    def __init__(self):
        self.client, self.data, self.ttls = self, {}, {}

    async def set(self, key, value, ex=None):
        self.data[key] = value
        self.ttls[key] = ex

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        return 1 if self.data.pop(key, None) is not None else 0

    async def ttl(self, key):
        return self.ttls.get(key, -1)

    async def scan_iter(self, match="*", count=10):
        prefix = match.rstrip("*")
        for key in list(self.data):
            if key.startswith(prefix):
                yield key


class Sql:
    """Remembers under which scope and session the approved SQL ran."""

    def __init__(self):
        self.runs = []

    async def execute_sql_query(self, query_sql, session_id):
        self.runs.append({"sql": query_sql, "scope": current_scope(), "session": session_id})
        return json.dumps({"data": [{"salary": 100}]})


class Host(ApprovalMixin):
    def __init__(self, redis=None):
        self.pending_approvals, self.redis_client = {}, redis
        self.settings = SimpleNamespace(HITL_APPROVAL_TTL_SECONDS=900)
        self.sql = Sql()
        agent = SimpleNamespace(mcp_client=self.sql)
        self.registry = SimpleNamespace(lookup=lambda name: agent if name == "db_agent" else None)


def run(coro):
    return asyncio.run(coro)


def ask(host, who=ALICE, action_id="act_0000000a"):
    """``who`` raises a sensitive query: the pending record is stored while they are the caller, like the executor does."""
    payload = {"action_id": action_id, "session_id": f"{who.user_id}:s1", "agent": "db_agent", "action_type": "sensitive_db_query",
               "description": "salary report", "risk_level": "critical", "payload": {"sql": "SELECT salary FROM employees", "query": "q"}}
    with acting_as(who):
        host._store_pending(action_id, {"query": "q"}, payload)
        run(host._persist_pending(action_id))
    return action_id


def decide(host, approver, action_id, decision="approve", session="inbox"):
    return run(host.handle_approval_decision(f"{approver.user_id}:{session}", action_id, decision, approver=approver))


@pytest.fixture(autouse=True)
def audit_off():
    yield
    audit.configure(None)


@pytest.fixture
def two_person(monkeypatch):
    monkeypatch.setattr(settings, "HITL_REQUIRE_OTHER_APPROVER", True)


# ---- the default: nothing changes -----------------------------------------------------------------------------------------------------

def test_without_the_switch_the_requester_still_approves_their_own_action(monkeypatch):
    monkeypatch.setattr(settings, "HITL_REQUIRE_OTHER_APPROVER", False)
    host = Host()
    act = ask(host)
    result = run(host.handle_approval_decision("alice:s1", act, "approve", approver=ALICE))
    assert result["status"] == "success" and result["data"] == [{"salary": 100}]


# ---- a second person ----------------------------------------------------------------------------------------------------------------------

def test_the_requester_cannot_approve_their_own_action_and_the_request_stays_pending(two_person):
    host = Host()
    act = ask(host)
    refused = run(host.handle_approval_decision("alice:s1", act, "approve", approver=ALICE))
    assert refused["status"] == "error" and refused["code"] == "self_approval"
    assert act in host.pending_approvals and host.sql.runs == []


def test_another_approver_decides_the_action_runs_as_the_requester_and_the_approver_sees_no_data(two_person):
    host = Host()
    act = ask(host)
    answer = decide(host, BOB, act)
    assert answer["status"] == "delivered" and "data" not in answer and "response" not in answer
    (ran,) = host.sql.runs
    assert ran["scope"] == ("acme", "legal")            # alice's department, not bob's
    assert ran["session"] == "alice:s1"                  # alice's session
    assert "legal" in ran["sql"] and "finance" not in ran["sql"]
    assert act not in host.pending_approvals             # claimed: it cannot be decided twice


def test_the_requester_collects_the_result_and_nobody_else_can(two_person):
    host = Host()
    act = ask(host)
    assert run(host.approval_result(act, ALICE)) == {"state": "pending"}
    assert run(host.approval_result(act, BOB)) is None                   # a stranger learns nothing, not even that it exists
    decide(host, BOB, act)
    done = run(host.approval_result(act, ALICE))
    assert done["state"] == "done" and done["result"]["status"] == "success" and done["result"]["data"] == [{"salary": 100}]
    assert run(host.approval_result(act, BOB)) is None and run(host.approval_result(act, CAROL)) is None
    assert run(host.approval_result("act_deadbeef", ALICE)) is None


def test_a_rejection_is_delivered_to_the_requester_too(two_person):
    host = Host()
    act = ask(host)
    assert decide(host, BOB, act, "reject")["status"] == "delivered"
    assert run(host.approval_result(act, ALICE))["result"]["status"] == "rejected" and host.sql.runs == []


def test_an_approver_of_another_tenant_cannot_touch_the_request(two_person):
    host = Host()
    act = ask(host)
    answer = decide(host, CAROL, act)
    assert answer["status"] == "error" and "code" not in answer       # looks like an unknown action
    assert act in host.pending_approvals and host.sql.runs == []


# ---- the inbox --------------------------------------------------------------------------------------------------------------------------------

def test_the_inbox_shows_other_peoples_requests_in_the_approvers_tenant_only(two_person):
    host = Host()
    ask(host, ALICE, "act_0000000a")
    ask(host, BOB, "act_0000000b")
    seen_by_bob = run(host.list_pending_approvals(BOB))
    assert [i["action_id"] for i in seen_by_bob] == ["act_0000000a"] and seen_by_bob[0]["requested_by"] == "alice"
    assert seen_by_bob[0]["request"]["sql"].startswith("SELECT salary") and 0 < seen_by_bob[0]["expires_in"] <= 900
    assert [i["action_id"] for i in run(host.list_pending_approvals(ALICE))] == ["act_0000000b"]   # not their own
    assert run(host.list_pending_approvals(CAROL)) == []                                         # another tenant
    assert run(host.list_pending_approvals(DAN)) == []                                           # no approver role


def test_the_inbox_is_empty_when_the_switch_is_off(monkeypatch):
    monkeypatch.setattr(settings, "HITL_REQUIRE_OTHER_APPROVER", False)
    host = Host()
    ask(host)
    assert run(host.list_pending_approvals(BOB)) == []


# ---- several replicas ---------------------------------------------------------------------------------------------------------------------------

def test_the_request_and_its_result_travel_through_redis_between_replicas(two_person):
    redis = FakeRedis()
    first, second = Host(redis), Host(redis)
    act = ask(first)
    assert [i["action_id"] for i in run(second.list_pending_approvals(BOB))] == [act]     # the other replica sees it
    assert decide(second, BOB, act)["status"] == "delivered"                               # and decides it
    done = run(first.approval_result(act, ALICE))                                          # the requester's replica collects the result
    assert done["state"] == "done" and done["result"]["data"] == [{"salary": 100}]
    assert redis.ttls[f"hitl:result:{act}"] == 900


# ---- the gateway -------------------------------------------------------------------------------------------------------------------------------

def test_the_gateway_answers_403_to_a_self_approval_and_hides_foreign_results(monkeypatch):
    from src.gateway import main

    class Orchestrator:
        async def handle_approval_decision(self, **kw):
            return {"status": "error", "code": "self_approval", "message": "no"}

        async def approval_result(self, action_id, principal):
            return None

        async def list_pending_approvals(self, principal):
            return [{"action_id": "act_0000000a"}]

    class PG:
        async def execute(self, *a):
            return "OK"

    audit.configure(PG())
    monkeypatch.setattr(main, "orchestrator", Orchestrator())
    with pytest.raises(main.HTTPException) as refused:
        run(main.chat_approve(main.ApprovalDecisionRequest(session_id="s", action_id="act_0000000a", decision="approve"), ALICE))
    assert refused.value.status_code == 403
    with pytest.raises(main.HTTPException) as unknown:
        run(main.approval_result("act_0000000a", ALICE))
    assert unknown.value.status_code == 404
    assert run(main.pending_approvals(BOB)) == [{"action_id": "act_0000000a"}]
    with pytest.raises(main.HTTPException) as forbidden:
        run(main.pending_approvals(DAN))
    assert forbidden.value.status_code == 403


def test_the_ui_is_told_when_two_person_approval_is_on(monkeypatch):
    from src.gateway import main

    monkeypatch.setattr(settings, "HITL_REQUIRE_OTHER_APPROVER", True)
    assert main._who(ALICE)["two_person_approval"] is True
    monkeypatch.setattr(settings, "HITL_REQUIRE_OTHER_APPROVER", False)
    assert main._who(ALICE)["two_person_approval"] is False


def test_acting_as_puts_the_previous_caller_back():
    with acting_as(ALICE):
        assert current_scope() == ("acme", "legal")
        with acting_as(BOB):
            assert current_scope() == ("acme", "finance")
        assert current_scope() == ("acme", "legal")
