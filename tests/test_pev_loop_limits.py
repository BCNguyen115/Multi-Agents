"""The PEV loop's limits: how many times a rejected answer is produced again (per agent), what the Monitoring numbers say about it, and what a
Verifier that cannot answer means (the answer goes out marked unverified, not silently passed)."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.config import settings
from src.orchestrator.common import max_retries_for
from src.orchestrator.core import Orchestrator
from src.shared import metrics
from src.shared.security import wrap_user_input

REJECTED = {"answer": "Thời hạn là 2 năm.", "sources": [], "verification": {"status": "ok", "grounded": False, "cited": [], "unsupported_numbers": []}}
PASSED = {"answer": "Thời hạn là 2 năm [1].", "sources": [], "verification": {"status": "ok", "grounded": True, "cited": [1], "unsupported_numbers": []}}


def orchestrator(reply, judge=None):
    agent = SimpleNamespace(process_request=AsyncMock(return_value=reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)))
    registry = MagicMock()
    registry.lookup = MagicMock(return_value=agent)
    cfg = MagicMock(HITL_APPROVAL_TTL_SECONDS=900, FAST_LLM_MODEL="fast", OPENROUTER_MODEL="m", HEAVY_LLM_MODEL="heavy")
    memory = MagicMock()
    memory.get_relevant_memories = MagicMock(return_value=[])
    memory.add_memory = MagicMock(return_value={})
    llm = MagicMock()
    llm.get_langfuse_callback = MagicMock(return_value=None)
    llm.flush_async = AsyncMock()
    if judge is not None:
        llm.chat_completion = judge
    return Orchestrator(registry=registry, settings=cfg, llm_client=llm, memory_manager=memory), agent


def run(orch, **kw):
    return json.loads(asyncio.run(orch.handle_request(query=wrap_user_input("Thời hạn NDA?")[0], session_id="s1", agent_mode="rag_agent", **kw)))


def test_a_rejected_answer_is_produced_again_until_the_attempts_run_out_and_then_marked(monkeypatch):
    for limit, calls in ((1, 1), (2, 2), (3, 3), (4, 4)):
        monkeypatch.setattr(settings, "PEV_MAX_ATTEMPTS", limit)
        orch, agent = orchestrator(REJECTED)
        out = run(orch)
        assert agent.process_request.await_count == calls  # the agent produced an answer `limit` times
        assert out["pev_trace"]["verifier"]["retries"] == calls - 1 and out["pev_trace"]["verifier"]["is_verified"] is False
        assert "chưa được kiểm duyệt" in out["answer"]  # and the answer is marked, not hidden


def test_an_agent_can_have_its_own_limit_while_the_others_keep_the_default(monkeypatch):
    monkeypatch.setattr(settings, "PEV_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "PEV_MAX_ATTEMPTS_BY_AGENT", {"rag_agent": 1})
    assert max_retries_for({"target_agent": "rag_agent", "max_retries": 2}) == 1
    assert max_retries_for({"target_agent": "search_agent", "max_retries": 2}) == 2
    orch, agent = orchestrator(REJECTED)
    run(orch)
    assert agent.process_request.await_count == 1


def test_a_passing_answer_is_not_retried_and_the_run_is_counted(monkeypatch):
    monkeypatch.setattr(settings, "PEV_MAX_ATTEMPTS", 2)
    before = {row["agent"]: row for row in metrics.pev_snapshot()}.get("rag_agent", {"verified": 0, "unverified": 0, "retries": 0})
    orch, agent = orchestrator(PASSED)
    run(orch)
    orch2, _ = orchestrator(REJECTED)
    run(orch2)
    after = {row["agent"]: row for row in metrics.pev_snapshot()}["rag_agent"]
    assert agent.process_request.await_count == 1
    assert after["verified"] - before["verified"] == 1 and after["unverified"] - before["unverified"] == 1
    assert after["retries"] - before["retries"] == 1 and after["runs"] == after["verified"] + after["unverified"]


def test_a_verifier_that_cannot_judge_marks_the_answer_unverified_instead_of_passing_it(monkeypatch):
    monkeypatch.setattr(settings, "PEV_MAX_ATTEMPTS", 2)
    down = AsyncMock(side_effect=ConnectionError("LLM down"))
    orch, agent = orchestrator("Câu trả lời dạng văn bản thường, cần LLM chấm.", judge=down)
    monkeypatch.setattr(settings, "VERIFIER_FAIL_CLOSED", True)
    out = run(orch)
    assert out["pev_trace"]["verifier"]["is_verified"] is False
    assert agent.process_request.await_count == 1  # a retry would meet the same outage
    assert "không phản hồi" in json.dumps(out, ensure_ascii=False)

    monkeypatch.setattr(settings, "VERIFIER_FAIL_CLOSED", False)  # the old behaviour stays available
    orch, _ = orchestrator("Câu trả lời dạng văn bản thường, cần LLM chấm.", judge=down)
    assert run(orch)["pev_trace"]["verifier"]["is_verified"] is True
