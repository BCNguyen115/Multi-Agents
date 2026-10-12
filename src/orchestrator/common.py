"""Pieces of the orchestrator shared by its mixins (see core.py, approvals.py, streaming.py)."""

from __future__ import annotations

from typing import Any, Optional

from src.config import settings
from src.orchestrator.state import AgentState
from src.shared.messages import msg

# Default max retries for Verifier rejection (``PEV_MAX_ATTEMPTS`` and ``PEV_MAX_ATTEMPTS_BY_AGENT`` override it)
_DEFAULT_MAX_RETRIES: int = 2


def reexecutions(retry_count: int, verified: bool) -> int:
    """How many times the Executor really ran AGAIN. ``retry_count`` counts the Verifier's rejections: a verified run ran once more
    after each of them, a run that ended unverified ran once less (the last rejection ended it)."""
    return max(0, retry_count - (0 if verified else 1))


def max_retries_for(state: Any) -> int:
    """The run's limit on Verifier rejections, which is the number of times the agent may produce an answer (the loop stops when the
    rejections reach it): the agent's own ``PEV_MAX_ATTEMPTS_BY_AGENT`` entry when configured, else the run's (``PEV_MAX_ATTEMPTS``
    when the run began)."""
    per_agent = settings.PEV_MAX_ATTEMPTS_BY_AGENT
    agent = str(state.get("target_agent") or "")
    if agent in per_agent:
        return max(1, int(per_agent[agent]))
    return int(state.get("max_retries", settings.PEV_MAX_ATTEMPTS))


def _run_config(session_id: str, run_id: str, langfuse_handler: Any = None) -> dict[str, Any]:
    """LangGraph config of one request. The run id is the thread (see checkpointing.py); the session rides along as
    checkpoint metadata so ``scripts.replay_run list --session`` can find the runs of a conversation."""
    config: dict[str, Any] = {"configurable": {"thread_id": run_id}, "metadata": {"session_id": session_id}}
    if langfuse_handler:
        config["callbacks"] = [langfuse_handler]
    return config


def _build_pev_trace(
    target_agent: str, plan: str, is_verified: bool, verifier_feedback: str, run_id: Optional[str] = None, retries: int = 0
) -> dict[str, Any]:
    """PEV trace metadata attached to every final response (sync + SSE paths). ``run_id`` only when the run was checkpointed."""
    trace = _pev_trace_body(target_agent, plan, is_verified, verifier_feedback, retries)
    if run_id:
        trace["run_id"] = run_id
    return trace


def _pev_trace_body(
    target_agent: str, plan: str, is_verified: bool, verifier_feedback: str, retries: int = 0
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
            "retries": retries,
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
        "max_retries": settings.PEV_MAX_ATTEMPTS,
    }
