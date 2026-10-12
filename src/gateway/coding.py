"""Repositories, review and publish for the coding agent: ``/api/coding``.

The agent's work is a ``coding.task`` job whose result holds the patch, the checks and what each changed file looked like before and after.
Nothing reaches a repository until a PERSON with an approver role publishes it here. Rules, all enforced by the server:
  * everything is scoped to the caller's tenant; only a task's owner or an approver may read or edit it;
  * a reviewer's edits (``revise``) go to the finished work's sandbox session, the checks run again, and the work is judged on THOSE results;
  * only an approver may publish, and with ``HITL_REQUIRE_OTHER_APPROVER`` not the person who asked;
  * the work must be ``ready_for_review`` (checks passed after the last edit, no protected file, no credential, patch complete), and the
    publisher checks the patch again itself;
  * the decision is written to ``audit_log`` BEFORE anything is pushed (no record, no push); a job is published once.
Repositories: any coding user may add a GitHub link; only an administrator may add a local folder, and only one under the allowed roots.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.agents.coding_agent import agent as coding_agent
from src.agents.coding_agent import repos
from src.agents.coding_agent.controller import revise as revise_work
from src.agents.coding_agent.publisher import PublishError
from src.config import settings
from src.shared import audit
from src.shared.auth import Principal, authenticate
from src.shared.logger import get_logger
from src.shared.messages import msg

logger: logging.Logger = get_logger(__name__)

router = APIRouter(prefix="/api/coding", tags=["coding"])
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MAX_REVISED_FILES = 25
MAX_REVISED_CHARS = 256 * 1024
REVISION_KEYS = ("patch", "patch_truncated", "files_changed", "files_detail", "files_detail_truncated", "checks", "tests_passed", "ruff_clean",
                 "protected_touched", "secrets_found", "risk_findings", "auto_checks", "ready_for_review")


def pr_body(result: dict[str, Any], requester: str, approver: str) -> str:
    """Summary and test plan, the way a pull request description should read, plus what the reviewer should look at first."""
    checks = result.get("checks", {})
    plan = [f"- `{name}` after the last edit: {'passed' if check.get('ok') else 'FAILED'}" for name, check in sorted(checks.items())] or ["- no check was run"]
    notes = [f"- {f['severity']} `{f['rule']}` {f['file']}" + (f":{f['line']}" if f.get("line") else "") for f in result.get("risk_findings", [])[:10]]
    notes += [f"- review ({f['state'].lower()}, {f['severity']}) {f['file']}" + (f":{f['line']}" if f.get("line") else "") + f": {f['summary']}"
              for f in (result.get("review") or {}).get("findings", [])[:10]]
    parts = ["## Summary", str(result.get("summary", "")).strip() or "(no summary)", "", "Files: " + ", ".join(f"`{f}`" for f in result.get("files_changed", [])),
             "", "## Test plan", *plan]
    if result.get("revisions"):
        parts += ["", f"Edited by a reviewer {result['revisions']} time(s) after the agent finished; the checks above were run again on the edited files."]
    if notes:
        parts += ["", "## Look at first", *notes]
    parts += ["", f"Written by the coding agent for {requester}; reviewed and published by {approver}. Draft: a person merges it."]
    return "\n".join(parts)


def _can_code(principal: Principal) -> bool:
    return bool(settings.CODING_AGENT_ENABLED and principal.roles & set(settings.CODING_AGENT_ROLES))


def _pg(request: Request) -> Any:
    pg = getattr(request.app.state, "pg_client", None)
    if pg is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    return pg


# ---------------------------------------------------------------------------------------------------------------- repositories
class RepoIn(BaseModel):
    kind: str = Field(pattern="^(github|local)$")
    location: str = Field(min_length=1, max_length=500, description="a https://github.com/<owner>/<repo> link, or a folder from the discovered list")
    name: str = Field(min_length=1, max_length=60)
    branch: str = Field(default="", max_length=100)


def _refuse(exc: repos.RepoError) -> HTTPException:
    return HTTPException(status_code=422, detail=msg(exc.key, **exc.values))


@router.get("/repos", summary="The repositories the coding agent can work on (the built-in default first)")
async def list_repositories(request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    if not _can_code(principal):
        raise HTTPException(status_code=403, detail=msg("coding.not_allowed"))
    found = await repos.list_repos(_pg(request), principal.tenant_id)
    return {"repos": [{**r.public(), "mine": r.owner == principal.user_id or principal.can_admin, "builtin": r.id == repos.DEFAULT_ID} for r in found],
            "can_add_local": principal.can_admin, "has_roots": bool(repos.roots())}


@router.get("/repos/discover", summary="Git folders under the allowed roots, to pick a local repository from (administrators)")
async def discover_folders(principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    if not _can_code(principal) or not principal.can_admin:
        raise HTTPException(status_code=403, detail=msg("coding.repo_need_admin"))
    return {"folders": repos.discover(), "roots": [str(r) for r in repos.roots()]}


@router.post("/repos", status_code=201, summary="Add a GitHub link or a local folder")
async def add_repository(body: RepoIn, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    if not _can_code(principal):
        raise HTTPException(status_code=403, detail=msg("coding.not_allowed"))
    pg = _pg(request)
    try:
        # validate first (nothing is stored), record the decision, then store: no record, no change
        if body.kind == "local":
            if not principal.can_admin:
                raise repos.RepoError("coding.repo_need_admin")
            repos.allowed_folder(body.location)
        await audit.record("coding.repo_add", f"{body.kind}:{body.location}", "ok", {"name": body.name}, principal=principal, required=True)
        repo = await repos.add_repo(pg, tenant_id=principal.tenant_id, owner=principal.user_id, is_admin=principal.can_admin,
                                    kind=body.kind, location=body.location, name=body.name, branch=body.branch)
    except repos.RepoError as exc:
        raise _refuse(exc) from exc
    return repo.public()


@router.delete("/repos/{repo_id}", status_code=204, summary="Remove a repository from the list (its owner or an administrator)")
async def remove_repository(repo_id: str, request: Request, principal: Principal = Depends(authenticate)) -> None:
    if not _can_code(principal):
        raise HTTPException(status_code=403, detail=msg("coding.not_allowed"))
    await audit.record("coding.repo_remove", repo_id, "ok", principal=principal, required=True)
    if not await repos.remove_repo(_pg(request), tenant_id=principal.tenant_id, user_id=principal.user_id, is_admin=principal.can_admin, repo_id=repo_id):
        raise HTTPException(status_code=404, detail=msg("coding.repo_not_found"))


# ---------------------------------------------------------------------------------------------------------------- tasks
async def _job(request: Request, job_id: str, principal: Principal) -> dict[str, Any]:
    pg = _pg(request)
    if not JOB_ID.match(job_id):
        raise HTTPException(status_code=404, detail=msg("coding.not_found"))
    rows = await pg.fetch("SELECT id, kind, tenant_id, user_id, status, result, error FROM jobs WHERE id = $1", job_id)
    if not rows or rows[0]["kind"] != "coding.task" or rows[0]["tenant_id"] != principal.tenant_id:
        raise HTTPException(status_code=404, detail=msg("coding.not_found"))
    job = dict(rows[0])
    if job["user_id"] != principal.user_id and not principal.can_approve:
        raise HTTPException(status_code=404, detail=msg("coding.not_found"))
    result = job["result"]
    job["result"] = json.loads(result) if isinstance(result, str) else result
    return job


def _target(result: dict[str, Any]) -> str:
    override = coding_agent._publisher
    if override is not None:
        return getattr(override, "target", "github")
    return str((result.get("repo") or {}).get("kind") or "github")


@router.get("/{job_id}/review", summary="The checks and the summary of a coding task (its owner, or an approver of the same tenant)")
async def review(job_id: str, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    job = await _job(request, job_id, principal)
    result = dict(job["result"] or {})
    result["files_detail_count"] = len(result.pop("files_detail", None) or [])  # the contents come from /files: this endpoint is polled
    done = bool(result.get("pr_url") or result.get("branch"))
    return {"id": job["id"], "status": job["status"], "requester": job["user_id"], "error": job["error"], "result": result,
            "target": _target(result), "repo": result.get("repo"),
            "editable": bool(job["status"] == "done" and result.get("sandbox_session") and not done),
            "can_publish": bool(principal.can_approve and (not settings.HITL_REQUIRE_OTHER_APPROVER or job["user_id"] != principal.user_id))}


@router.get("/{job_id}/files", summary="What each changed file looked like before and after, for the diff editor")
async def files(job_id: str, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    job = await _job(request, job_id, principal)
    result = job["result"] or {}
    return {"id": job["id"], "files": result.get("files_detail") or [], "truncated": bool(result.get("files_detail_truncated"))}


class ReviseIn(BaseModel):
    files: dict[str, str] = Field(min_length=1, max_length=MAX_REVISED_FILES, description="path -> the whole new content of a file the agent changed")


@router.post("/{job_id}/revise", summary="Edit files of a finished task; the checks run again on the edited files")
async def revise(job_id: str, body: ReviseIn, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    job = await _job(request, job_id, principal)
    result = job["result"] or {}
    session = result.get("sandbox_session")
    client = coding_agent.executor()
    if job["status"] != "done" or not session or client is None:
        raise HTTPException(status_code=409, detail=msg("coding.not_editable"))
    if result.get("pr_url") or result.get("branch") or result.get("publishing"):
        raise HTTPException(status_code=409, detail=msg("coding.already_published"))
    if any(len(content) > MAX_REVISED_CHARS for content in body.files.values()):
        raise HTTPException(status_code=413, detail=msg("coding.too_large"))
    await audit.record("coding.revise", job_id, "ok", {"files": sorted(body.files)[:MAX_REVISED_FILES], "requester": job["user_id"]}, principal=principal, required=True)
    try:
        state = await revise_work(client, str(session), dict(body.files), tuple(settings.CODING_PROTECTED_PATHS))
    except Exception as exc:  # noqa: BLE001 - the sandbox is unreachable or the session is gone
        logger.warning("Revising coding job %s failed: %s", job_id, exc or type(exc).__name__)
        raise HTTPException(status_code=502, detail=msg("coding.sandbox_unreachable")) from exc
    if "errors" in state:
        expired = any("expired" in text for text in state["errors"].values())
        raise HTTPException(status_code=409 if expired else 422, detail={"message": msg("coding.not_editable" if expired else "coding.edit_refused"), "errors": state["errors"]})
    update = {key: state[key] for key in REVISION_KEYS if key in state}
    update["revisions"] = int(result.get("revisions", 0)) + 1
    update["revised_by"] = sorted(set(result.get("revised_by", [])) | {principal.user_id})
    update["review"] = {**(result.get("review") or {}), "stale": True}  # the second model's advice was about the agent's version
    await _pg(request).execute("UPDATE jobs SET result = result || $2::jsonb WHERE id = $1", job_id, json.dumps(update))
    return {"ready_for_review": update.get("ready_for_review"), "checks": update.get("checks"), "risk_findings": update.get("risk_findings"),
            "files_changed": update.get("files_changed"), "revisions": update["revisions"], "auto_checks": update.get("auto_checks")}


@router.post("/{job_id}/publish", summary="Push the branch (and open a draft pull request on GitHub); approvers only")
async def publish(job_id: str, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    if not principal.can_approve:
        raise HTTPException(status_code=403, detail=msg("forbidden.approve"))
    job = await _job(request, job_id, principal)
    if settings.HITL_REQUIRE_OTHER_APPROVER and job["user_id"] == principal.user_id:
        raise HTTPException(status_code=403, detail=msg("coding.self_approval"))
    result = job["result"] or {}
    if job["status"] != "done" or not result.get("ready_for_review"):
        raise HTTPException(status_code=409, detail=msg("coding.not_ready"))
    try:
        publisher = coding_agent.publisher_for_result(result)
    except PublishError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    pg = _pg(request)
    claimed = await pg.fetch(
        "UPDATE jobs SET result = result || '{\"publishing\": true}'::jsonb WHERE id = $1 AND NOT (result ? 'publishing') AND NOT (result ? 'pr_url') AND NOT (result ? 'branch') RETURNING id", job_id
    )
    if not claimed:
        raise HTTPException(status_code=409, detail=msg("coding.already_published"))
    title = (str(result.get("task", "")).splitlines() or ["Coding agent change"])[0][:72] or "Coding agent change"
    body = pr_body(result, job["user_id"], principal.user_id)
    try:
        await audit.record("coding.publish", job_id, "approved", {"files": result.get("files_changed", [])[:25], "requester": job["user_id"],
                                                                 "repo": (result.get("repo") or {}).get("name"), "revisions": result.get("revisions", 0)}, principal=principal, required=True)
        published = await publisher.publish(str(result["patch"]), title, body, job_id)
    except PublishError as exc:
        await pg.execute("UPDATE jobs SET result = result - 'publishing' WHERE id = $1", job_id)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - release the claim so a person can retry; the detail stays in the log
        await pg.execute("UPDATE jobs SET result = result - 'publishing' WHERE id = $1", job_id)
        logger.error("Publishing coding job %s failed: %s", job_id, exc or type(exc).__name__)
        raise HTTPException(status_code=502, detail=msg("coding.publish_failed")) from exc
    await pg.execute("UPDATE jobs SET result = (result - 'publishing' - 'sandbox_session') || $2::jsonb WHERE id = $1", job_id, json.dumps(published))
    client = coding_agent.executor()
    if client is not None and result.get("sandbox_session"):
        await client.close(str(result["sandbox_session"]))  # nothing left to edit: free the sandbox
    return published
