"""AgentState module — defines the state schema for the LangGraph PEV workflow.

The ``AgentState`` dictionary is passed through every node in the
StateGraph (Planner -> Executor -> Verifier).
"""

from typing import Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """TypedDict defining state fields for the LangGraph Orchestrator.

    Fields:
        query: The end-user's natural-language query.
        session_id: Correlation ID for end-to-end request tracing.
        csv_content: Optional raw CSV file string for data analysis.
        csv_filename: Optional original filename of the uploaded CSV.
        messages: Accumulated conversation history.
        team_memory: Shared working memory dictionary across agents.
        plan: Natural-language execution plan produced by Planner.
        target_agent: Name of the agent selected to execute the plan.
        execution_result: Raw string output returned by the Executor node.
        final_response: Formatted final answer returned to the end-user.
        is_verified: Whether the Verifier node approved the result.
        verifier_feedback: Specific guidance from Verifier if retry needed.
        retry_count: Current retry iteration count.
        max_retries: Maximum allowed retry attempts.
    """

    query: str
    session_id: str
    csv_content: Optional[str]
    csv_filename: Optional[str]
    messages: list[dict[str, str]]
    team_memory: dict[str, Any]
    plan: str
    target_agent: str
    execution_result: str
    final_response: str
    is_verified: bool
    verifier_feedback: str
    retry_count: int
    max_retries: int
    agent_mode: Optional[str]
    target_agent: str
    forced_target_agent: Optional[str]
    requires_dashboard: Optional[bool]

    # Human-in-the-Loop (HITL) fields
    requires_human_approval: Optional[bool]
    approval_payload: Optional[dict[str, Any]]
    is_approved: Optional[bool]
    action_id: Optional[str]
    human_feedback: Optional[str]

    # DAG Parallel Execution fields
    sub_tasks: Optional[list[dict[str, Any]]]
    parallel_results: Optional[list[dict[str, Any]]]
