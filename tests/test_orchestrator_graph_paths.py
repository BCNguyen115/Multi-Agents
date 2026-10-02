"""The compiled PEV graph, end to end, through both entry points (JSON and SSE) with a fake agent.

Regression: removing the LangGraph checkpointer broke the SSE path (it read the final state back with ``aget_state``)
and no test noticed, because nothing ran the whole graph.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.orchestrator.core import Orchestrator
from src.shared.security import wrap_user_input

ANSWER = {"answer": "Thời hạn là 2 năm [1].", "sources": [], "verification": {"status": "ok", "grounded": True, "cited": [1], "unsupported_numbers": []}}


def orchestrator(reply=ANSWER):
    agent = SimpleNamespace(process_request=AsyncMock(return_value=json.dumps(reply, ensure_ascii=False)))
    registry = MagicMock()
    registry.lookup = MagicMock(return_value=agent)
    settings = MagicMock(HITL_APPROVAL_TTL_SECONDS=900, FAST_LLM_MODEL="fast", OPENROUTER_MODEL="m", HEAVY_LLM_MODEL="heavy")
    memory = MagicMock()
    memory.get_relevant_memories = MagicMock(return_value=[])
    memory.add_memory = MagicMock(return_value={})
    llm = MagicMock()
    llm.get_langfuse_callback = MagicMock(return_value=None)
    llm.flush_async = AsyncMock()
    return Orchestrator(registry=registry, settings=settings, llm_client=llm, memory_manager=memory), agent


def run_stream(orch, **kw):
    async def collect():
        return [event async for event in orch.handle_stream_request(query=wrap_user_input("Thời hạn NDA?")[0], session_id="s1", **kw)]

    return asyncio.run(collect())


def test_the_json_entry_point_runs_the_whole_graph():
    orch, agent = orchestrator()
    out = json.loads(asyncio.run(orch.handle_request(query=wrap_user_input("Thời hạn NDA?")[0], session_id="s1", agent_mode="rag_agent")))
    assert "2 năm" in out["answer"] and agent.process_request.await_count == 1


def test_the_sse_entry_point_runs_the_whole_graph_and_ends_with_the_final_response():
    orch, agent = orchestrator()
    events = run_stream(orch, agent_mode="rag_agent")
    names = [e["event"] for e in events]
    assert "error" not in names, [e["data"] for e in events if e["event"] == "error"]
    assert names[-1] == "final_response" and {"plan", "executing", "verifying"} <= set(names)
    final = json.loads(events[-1]["data"])
    assert final["is_verified"] is True and final["target_agent"] == "rag_agent" and "2 năm" in final["response"]


def test_the_final_state_does_not_depend_on_a_checkpointer():
    orch, _ = orchestrator()
    assert orch.graph.checkpointer is None
    events = run_stream(orch, agent_mode="rag_agent")
    assert events[-1]["event"] == "final_response"
