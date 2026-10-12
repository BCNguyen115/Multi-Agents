"""``coding_agent``: turns a task written in the chat into a reviewed pull request (or a branch in a local repository).

Asking is cheap and immediate (``process_request`` only queues a ``coding.task`` job and answers with its id); the work runs in the job queue
(``jobs.py``) as the user who asked: clone or snapshot of the CHOSEN repository (``repos.py``), sandbox, loop (``controller.py``), result. The
sandbox session is kept open for a while after the work, so a reviewer can edit the result in the diff editor and have the checks run again.
Nothing is pushed by this module. A person with an approver role looks at the diff and the checks and publishes it through
``/api/coding/{id}/publish`` (``src/gateway/coding.py``).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.agents.base_agent import BaseAgent
from src.agents.coding_agent import repos
from src.agents.coding_agent.controller import ExecutorClient, run_with_new_session
from src.agents.coding_agent.publisher import Publisher, PublishError
from src.config import settings
from src.shared import jobs, usage
from src.shared.auth import current_principal
from src.shared.logger import get_logger
from src.shared.messages import msg
from src.shared.security import unwrap_user_input

logger: logging.Logger = get_logger(__name__)

MAX_TASK_CHARS = 4000
MAX_STORED_PATCH_CHARS = 500_000

_llm_client: Any = None
_executor: Optional[ExecutorClient] = None
_publisher: Optional[Publisher] = None  # an override (tests); normally the publisher is built from the repository the task was given


def configured() -> bool:
    return bool(settings.CODING_AGENT_ENABLED and settings.CODING_SANDBOX_URL and len(settings.CODING_SANDBOX_SECRET) >= 16)


def executor() -> Optional[ExecutorClient]:
    return _executor


def publisher_for_result(result: dict[str, Any]) -> Publisher:
    """The publisher of the repository a finished task was run on (so a later change to the registry cannot redirect it)."""
    if _publisher is not None:
        return _publisher
    saved = result.get("repo")
    if not isinstance(saved, dict):
        raise PublishError(msg("coding.repo_not_found"))
    try:
        return repos.publisher_for(repos.Repo(**{k: saved.get(k, "") for k in ("id", "name", "kind", "location", "branch", "tenant_id", "owner")}))
    except repos.RepoError as exc:
        raise PublishError(msg(exc.key, **exc.values)) from exc


def configure(llm_client: Any) -> Optional["CodingAgent"]:
    """Build the sandbox client from settings. ``None`` (and a log line) when the feature is off or half configured."""
    global _llm_client, _executor
    if not settings.CODING_AGENT_ENABLED:
        return None
    if not configured():
        logger.warning("CODING_AGENT_ENABLED is set but CODING_SANDBOX_URL / CODING_SANDBOX_SECRET (16+ chars) are not both set: the coding agent stays off")
        return None
    _llm_client = llm_client
    _executor = ExecutorClient(settings.CODING_SANDBOX_URL, settings.CODING_SANDBOX_SECRET)
    return CodingAgent()


class CodingAgent(BaseAgent):
    def __init__(self, pg_client: Any = None) -> None:
        self.pg = pg_client

    def attach(self, pg_client: Any) -> None:
        self.pg = pg_client

    async def process_request(self, query: str, session_id: str) -> str:
        principal = current_principal()
        if principal is None or self.pg is None:
            return json.dumps({"type": "error", "message": msg("service.starting")}, ensure_ascii=False)
        if not (principal.roles & set(settings.CODING_AGENT_ROLES)):
            return json.dumps({"type": "error", "message": msg("coding.not_allowed")}, ensure_ascii=False)
        task = unwrap_user_input(query)[0].strip()[:MAX_TASK_CHARS]
        if not task:
            return json.dumps({"type": "error", "message": msg("coding.empty_task")}, ensure_ascii=False)
        chosen = repos.selected_repo.get()
        repo = await repos.resolve(self.pg, principal.tenant_id, chosen)
        if repo is None:  # nothing chosen and no built-in default, or a repository that is gone
            return json.dumps({"type": "error", "message": msg("coding.repo_not_found" if chosen else "coding.no_repo")}, ensure_ascii=False)
        job_id = await jobs.enqueue(self.pg, "coding.task", principal, {"task": task, "session_id": session_id, "repo": repo.public()})
        return json.dumps(
            {"answer": msg("coding.queued", job_id=job_id, repo=repo.name), "job_id": job_id, "verification": {"kind": "code", "status": "queued"}}, ensure_ascii=False)

    def get_metadata(self) -> dict[str, str]:
        return {
            "name": "coding_agent",
            "description": "Software engineer for this repository: changes source code, fixes bugs and adds tests in an isolated copy, "
                           "runs pytest and ruff, then offers the diff to a person who opens a pull request. Never edits the running system.",
        }


@jobs.register("coding.task")
async def run_coding_job(payload: dict[str, Any], data: Optional[bytes]) -> dict[str, Any]:
    if _executor is None or _llm_client is None:
        raise jobs.JobError(msg("coding.not_configured"))
    saved = payload.get("repo")
    if not isinstance(saved, dict):
        raise jobs.JobError(msg("coding.repo_not_found"))
    try:
        publisher = publisher_for_result({"repo": saved})
    except PublishError as exc:
        raise jobs.JobError(str(exc)) from exc
    usage.attribute("coding_agent", "executor", 1)
    try:
        tar = await publisher.make_archive()
    except PublishError as exc:
        raise jobs.JobError(str(exc)) from exc
    result = await run_with_new_session(
        _llm_client, _executor, tar, str(payload.get("task", "")), settings.HEAVY_LLM_MODEL,
        max_steps=settings.CODING_MAX_STEPS, max_usd=settings.CODING_MAX_USD, timeout_seconds=float(settings.CODING_TIMEOUT_SECONDS),
        session_id=str(payload.get("session_id", "CODING")), extra_protected=tuple(settings.CODING_PROTECTED_PATHS),
        self_review=settings.CODING_SELF_REVIEW, review_model=settings.FAST_LLM_MODEL,
        allow_shell=settings.CODING_ALLOW_SHELL, shell_timeout=settings.CODING_SHELL_TIMEOUT_SECONDS, keep_open=True,
    )
    if len(result["patch"]) > MAX_STORED_PATCH_CHARS:
        result["patch"], result["patch_truncated"], result["ready_for_review"] = result["patch"][:MAX_STORED_PATCH_CHARS], True, False
    result["task"] = str(payload.get("task", ""))[:MAX_TASK_CHARS]
    result["repo"] = saved
    return result
