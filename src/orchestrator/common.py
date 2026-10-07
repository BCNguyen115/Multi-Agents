"""Pieces of the orchestrator shared by its mixins (see core.py, approvals.py, streaming.py)."""

from __future__ import annotations

from typing import Any, Optional

from src.orchestrator.state import AgentState
from src.shared.messages import msg

# Default max retries for Verifier rejection
_DEFAULT_MAX_RETRIES: int = 2


def _run_config(session_id: str, run_id: str, langfuse_handler: Any = None) -> dict[str, Any]:
    """LangGraph config of one request. The run id is the thread (see checkpointing.py); the session rides along as
    checkpoint metadata so ``scripts.replay_run list --session`` can find the runs of a conversation."""
    config: dict[str, Any] = {"configurable": {"thread_id": run_id}, "metadata": {"session_id": session_id}}
    if langfuse_handler:
        config["callbacks"] = [langfuse_handler]
    return config


def _build_pev_trace(
    target_agent: str, plan: str, is_verified: bool, verifier_feedback: str, run_id: Optional[str] = None
) -> dict[str, Any]:
    """PEV trace metadata attached to every final response (sync + SSE paths). ``run_id`` only when the run was checkpointed."""
    trace = _pev_trace_body(target_agent, plan, is_verified, verifier_feedback)
    if run_id:
        trace["run_id"] = run_id
    return trace


def _pev_trace_body(
    target_agent: str, plan: str, is_verified: bool, verifier_feedback: str
) -> dict[str, Any]:
    return {
        "status": "Verified" if is_verified else "Warning",
        "planner": {
            "node": "Planner Node",
            "target_agent": target_agent,
            "plan_summary": plan if len(plan) <= 200 else f"{plan[:200]}...",
            "status": "completed",
        },
        "executor": {
            "node": "Executor Node",
            "agent_used": target_agent,
            "execution_summary": msg("orch.exec_summary", agent=target_agent),
            "status": "completed",
        },
        "verifier": {
            "node": "Verifier Node",
            "is_verified": is_verified,
            "verifier_feedback": verifier_feedback or msg("orch.verify_ok"),
            "status": "completed",
        },
    }


def _initial_state(
    query: str,
    session_id: str,
    csv_content: Optional[str],
    csv_filename: Optional[str],
    agent_mode: Optional[str],
    target_agent: Optional[str],
) -> AgentState:
    return {
        "query": query,
        "session_id": session_id,
        "csv_content": csv_content,
        "csv_filename": csv_filename,
        "agent_mode": agent_mode,
        "target_agent": target_agent or "",
        "forced_target_agent": target_agent or agent_mode,
        "messages": [],
        "team_memory": {},
        "plan": "",
        "execution_result": "",
        "final_response": "",
        "is_verified": False,
        "verifier_feedback": "",
        "retry_count": 0,
        "max_retries": _DEFAULT_MAX_RETRIES,
    }
