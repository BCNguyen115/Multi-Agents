"""HITL binding/expiry rules and shared routing helpers in the orchestrator."""
import asyncio
from unittest.mock import MagicMock

import pytest

from src.orchestrator.core import Orchestrator, _is_dashboard_request
from src.registry.manager import AgentRegistry


@pytest.fixture
def orch():
    s = MagicMock()
    s.HITL_APPROVAL_TTL_SECONDS = 900
    return Orchestrator(registry=AgentRegistry(), settings=s, llm_client=MagicMock(), memory_manager=MagicMock())


def _pending(orch, action_id="act_1", session="sess_1"):
    orch._store_pending(action_id, {"query": "q"}, {"agent": "db_agent", "session_id": session})


def _decide(orch, **kw):
    return asyncio.run(orch.handle_approval_decision(**kw))


def test_other_session_cannot_decide(orch):
    _pending(orch)
    res = _decide(orch, session_id="attacker", action_id="act_1", decision="approve")
    assert res["status"] == "error" and "act_1" in orch.pending_approvals


def test_unknown_decision_is_not_approve(orch):
    _pending(orch)
    res = _decide(orch, session_id="sess_1", action_id="act_1", decision="aprove")
    assert res["status"] == "error" and "act_1" in orch.pending_approvals


def test_no_fallback_to_another_action_of_same_session(orch):
    _pending(orch, "act_real")
    res = _decide(orch, session_id="sess_1", action_id="act_wrong", decision="reject")
    assert res["status"] == "error" and "act_real" in orch.pending_approvals


def test_expired_approval_is_purged(orch):
    _pending(orch)
    orch.pending_approvals["act_1"]["created_at"] -= 901
    assert _decide(orch, session_id="sess_1", action_id="act_1", decision="approve")["status"] == "error"
    assert "act_1" not in orch.pending_approvals


def test_dashboard_intent_helper():
    assert _is_dashboard_request("vẽ biểu đồ xu hướng")
    assert not _is_dashboard_request("vẽ biểu đồ nhưng chỉ tóm tắt")
    assert not _is_dashboard_request("tóm tắt văn bản")


def test_forced_route_plan(orch):
    out = asyncio.run(orch._planner_node({"query": "hi", "session_id": "s", "forced_target_agent": "search_agent"}))
    assert out["target_agent"] == "search_agent" and out["requires_dashboard"] is False


def test_the_graph_keeps_no_per_session_checkpoints(orch):
    """MemorySaver used to keep every checkpoint (CSV contents included) of every session in RAM, and nothing read them."""
    assert orch.graph.checkpointer is None and not hasattr(orch, "checkpointer")


def test_decision_messages_follow_the_interface_language(orch):
    from src.shared.messages import reset_lang, set_lang

    token = set_lang("en")
    try:
        res = _decide(orch, session_id="sess_1", action_id="act_missing", decision="reject")
        bad = _decide(orch, session_id="sess_1", action_id="act_missing", decision="maybe")
    finally:
        reset_lang(token)
    assert "does not exist" in res["message"] and "act_missing" in res["message"]
    assert "is not valid" in bad["message"]
    assert "không tồn tại" in _decide(orch, session_id="sess_1", action_id="act_missing", decision="reject")["message"]
