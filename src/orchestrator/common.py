"""Pieces of the orchestrator shared by its mixins (see core.py, approvals.py, streaming.py)."""

from __future__ import annotations

from typing import Any, Optional

from src.orchestrator.state import AgentState
from src.shared.messages import msg

# Default max retries for Verifier rejection
_DEFAULT_MAX_RETRIES: int = 2


def _build_pev_trace(
    target_agent: str, plan: str, is_verified: bool, verifier_feedback: str
) -> dict[str, Any]:
    """PEV trace metadata attached to every final response (sync + SSE paths)."""
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
