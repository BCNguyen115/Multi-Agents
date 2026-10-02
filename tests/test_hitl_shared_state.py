"""Pending Human-in-the-Loop approvals are shared through Redis: they survive a restart, work on any replica and can be
claimed only once. Without Redis (or when it fails) the in-process behaviour is unchanged."""
import asyncio
import json
from unittest.mock import MagicMock

from src.orchestrator.core import Orchestrator
from src.registry.manager import AgentRegistry


class FakeRedisClient:
    """The subset of redis.asyncio used for approvals; ``strings`` is shared between two 'replicas'."""

    def __init__(self, strings=None, down=False):
        self.strings, self.ttls, self.down = strings if strings is not None else {}, {}, down

    def _check(self):
        if self.down:
            raise ConnectionError("redis down")

    async def set(self, key, value, ex=None):
        self._check()
        self.strings[key], self.ttls[key] = value, ex

    async def get(self, key):
        self._check()
        return self.strings.get(key)

    async def delete(self, key):
        self._check()
        return 1 if self.strings.pop(key, None) is not None else 0


def replica(redis_client):
    s = MagicMock()
    s.HITL_APPROVAL_TTL_SECONDS = 900
    return Orchestrator(registry=AgentRegistry(), settings=s, llm_client=MagicMock(), memory_manager=MagicMock(),
                        redis_client=MagicMock(client=redis_client) if redis_client is not None else None)


def raise_approval(orch, action_id="act_1", session="s1"):
    state = {"query": "SELECT salary", "session_id": session, "csv_content": "x" * 10_000, "agent_mode": "db_agent"}
    orch._store_pending(action_id, state, {"agent": "db_agent", "session_id": session, "payload": {"sql": "SELECT 1"}})
    asyncio.run(orch._persist_pending(action_id))


def decide(orch, session="s1", action="act_1", decision="reject"):
    return asyncio.run(orch.handle_approval_decision(session_id=session, action_id=action, decision=decision))


def test_an_approval_raised_on_one_replica_can_be_decided_on_another():
    shared = {}
    a, b = replica(FakeRedisClient(shared)), replica(FakeRedisClient(shared))
    raise_approval(a)
    assert decide(b)["status"] == "rejected"                      # b never saw it locally
    assert decide(a)["status"] == "error" and not shared          # ...and a can no longer act on it: claimed exactly once


def test_an_approval_survives_a_restart():
    shared = {}
    raise_approval(replica(FakeRedisClient(shared)))
    restarted = replica(FakeRedisClient(shared))                  # a brand-new process: empty in-memory dict
    assert restarted.pending_approvals == {} and decide(restarted)["status"] == "rejected"


def test_a_wrong_session_neither_decides_nor_consumes_the_approval():
    shared = {}
    a = replica(FakeRedisClient(shared))
    raise_approval(a)
    assert decide(replica(FakeRedisClient(shared)), session="attacker")["status"] == "error"
    assert "hitl:pending:act_1" in shared and decide(a)["status"] == "rejected"


def test_only_what_approving_needs_goes_to_redis_with_the_approval_ttl():
    redis = FakeRedisClient()
    raise_approval(replica(redis))
    key = "hitl:pending:act_1"
    stored = json.loads(redis.strings[key])
    assert redis.ttls[key] == 900 and "csv_content" not in stored["state"] and stored["state"]["query"] == "SELECT salary"
    assert stored["payload"]["payload"] == {"sql": "SELECT 1"}


def test_when_redis_is_down_the_in_process_approval_still_works():
    orch = replica(FakeRedisClient(down=True))
    raise_approval(orch)                                          # sharing fails quietly ...
    assert decide(orch)["status"] == "rejected"                   # ... the local record is used


def test_without_redis_nothing_changes():
    orch = replica(None)
    raise_approval(orch)
    assert decide(orch)["status"] == "rejected" and decide(orch)["status"] == "error"
