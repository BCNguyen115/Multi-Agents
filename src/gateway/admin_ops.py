"""The operating side of the administration console (``/api/admin``, administrators only): the audit trail, the actions waiting for
approval, the job queue, the configuration in force, the alerts firing, the newest backup and what users thought of the answers.

Everything here READS, except cancelling a queued job (audited first, like every administrator's change). The configuration is a
whitelist: a setting is shown because someone chose to show it, and a secret is only ever reported as set or not set.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response

from src.config import settings
from src.gateway.admin import SCOPE_ID, _pg, require_admin
from src.shared import audit
from src.shared.auth import Principal
from src.shared.logger import get_logger
from src.shared.messages import msg

logger: logging.Logger = get_logger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

AUDIT_PAGE = 50
AUDIT_MAX_PAGE = 200
AUDIT_EXPORT_ROWS = 10_000
JOB_ID = r"^[A-Za-z0-9_-]{1,64}$"

# ---------------------------------------------------------------------------------------------- audit trail


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)  # a date typed in the console carries no zone: read it as UTC, like the stored times
    return value


def _audit_filter(
    actor: Optional[str], action: Optional[str], tenant: Optional[str], outcome: Optional[str], q: Optional[str],
    since: Optional[datetime], until: Optional[datetime], before: Optional[int],
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    args: list[Any] = []

    def add(clause: str, value: Any) -> None:
        args.append(value)
        clauses.append(clause.format(n=len(args)))

    if actor:
        add("actor = ${n}", actor)
    if action:
        add("starts_with(action, ${n})", action)  # `hitl.` = every approval event, `admin.user_update` = exactly that one
    if tenant is not None:
        add("tenant_id = ${n}", tenant)
    if outcome:
        add("outcome = ${n}", outcome)
    if q:
        add("position(lower(${n}) in lower(target)) > 0", q)
    if since:
        add("at >= ${n}", _utc(since))
    if until:
        add("at < ${n}", _utc(until))
    if before:
        add("id < ${n}", before)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


@router.get("/audit", summary="The append-only audit trail, newest first, filtered; page with `before` = the last id seen")
async def audit_trail(
    request: Request,
    actor: Optional[str] = Query(default=None, max_length=64),
    action: Optional[str] = Query(default=None, max_length=64, description="a prefix: `hitl.`, `admin.`, `kb.delete`..."),
    tenant: Optional[str] = Query(default=None, max_length=64),
    outcome: Optional[str] = Query(default=None, max_length=40),
    q: Optional[str] = Query(default=None, max_length=100, description="part of the target"),
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    before: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=AUDIT_PAGE, ge=1, le=AUDIT_MAX_PAGE),
    _admin: Principal = Depends(require_admin),
) -> dict[str, Any]:
    if since and until and _utc(since) >= _utc(until):  # type: ignore[operator]
        raise HTTPException(status_code=422, detail=msg("admin.bad_range"))
    where, args = _audit_filter(actor, action, tenant, outcome, q, since, until, before)
    rows = await _pg(request).fetch(
        f"SELECT id, at, tenant_id, actor, action, target, outcome, detail FROM audit_log{where} ORDER BY id DESC LIMIT ${len(args) + 1}",
        *args, limit + 1,
    )
    page = [dict(r) for r in rows[:limit]]
    for row in page:
        if isinstance(row["detail"], str):  # asyncpg hands JSONB back as text unless a codec is set
            row["detail"] = json.loads(row["detail"])
    return {"rows": page, "next_before": page[-1]["id"] if len(rows) > limit and page else None}


def _csv_cell(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text  # a spreadsheet must not run a cell as a formula


@router.get("/audit/export", summary="The same filter as CSV (at most 10,000 rows); the export itself is recorded")
async def audit_export(
    request: Request,
    actor: Optional[str] = Query(default=None, max_length=64),
    action: Optional[str] = Query(default=None, max_length=64),
    tenant: Optional[str] = Query(default=None, max_length=64),
    outcome: Optional[str] = Query(default=None, max_length=40),
    q: Optional[str] = Query(default=None, max_length=100),
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    admin: Principal = Depends(require_admin),
) -> Response:
    if since and until and _utc(since) >= _utc(until):  # type: ignore[operator]
        raise HTTPException(status_code=422, detail=msg("admin.bad_range"))
    where, args = _audit_filter(actor, action, tenant, outcome, q, since, until, None)
    rows = await _pg(request).fetch(
        f"SELECT id, at, tenant_id, actor, action, target, outcome, detail FROM audit_log{where} ORDER BY id DESC LIMIT ${len(args) + 1}",
        *args, AUDIT_EXPORT_ROWS,
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "at", "tenant", "actor", "action", "target", "outcome", "detail"])
    for r in rows:
        writer.writerow([r["id"], r["at"].isoformat(), *(_csv_cell(r[k]) for k in ("tenant_id", "actor", "action", "target", "outcome", "detail"))])
    await audit.record("admin.audit_export", "audit_log", detail={"rows": len(rows), "actor": actor, "action": action, "tenant": tenant}, principal=admin)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Response(
        content="\ufeff" + out.getvalue(),  # a BOM so Excel reads the Vietnamese as UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="audit-{stamp}.csv"', "Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------------------------- approvals waiting


@router.get("/approvals", summary="Sensitive actions waiting for a decision, system-wide (the decision history is the audit trail, `hitl.`)")
async def pending_approvals(request: Request, _admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    """What is waiting and since when. The request itself (SQL, URL) is not shown: deciding is the approvers' job, this is the overview."""
    found: dict[str, tuple[dict[str, Any], float]] = {}
    available = False
    client = getattr(getattr(request.app.state, "redis_client", None), "client", None)
    if client is not None:
        try:
            async for key in client.scan_iter(match="hitl:pending:*", count=200):
                action_id = str(key).split(":", 2)[-1]
                raw = await client.get(key)
                if raw:
                    found[action_id] = (json.loads(raw), max(float(await client.ttl(key)), 0.0))
                if len(found) >= 100:
                    break
            available = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not list pending approvals: %s", exc or type(exc).__name__)
    orchestrator = getattr(request.app.state, "orchestrator", None)
    local = getattr(orchestrator, "pending_approvals", None) or {}
    ttl, now = float(settings.HITL_APPROVAL_TTL_SECONDS), time.monotonic()
    for action_id, record in dict(local).items():  # this replica's own, in case Redis could not be read
        found.setdefault(action_id, (record, max(ttl - (now - record.get("created_at", now)), 0.0)))
    items = []
    for action_id, (record, left) in found.items():
        payload = record.get("payload") or {}
        requester = payload.get("requester") or {}
        items.append({
            "action_id": action_id, "agent": payload.get("agent"), "action_type": payload.get("action_type"),
            "description": payload.get("description"), "risk_level": payload.get("risk_level"),
            "requested_by": requester.get("user"), "tenant_id": requester.get("tenant"), "department_id": requester.get("department"),
            "expires_in": int(left),
        })
    items.sort(key=lambda i: i["expires_in"], reverse=True)  # the longest left = the newest request first
    return {"available": available or bool(local), "two_person": settings.HITL_REQUIRE_OTHER_APPROVER, "ttl_seconds": int(ttl), "items": items}


# ---------------------------------------------------------------------------------------------- job queue


@router.get("/jobs", summary="Background jobs, newest first")
async def job_list(
    request: Request,
    status: Optional[str] = Query(default=None, pattern=r"^(queued|running|done|failed)$"),
    kind: Optional[str] = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    _admin: Principal = Depends(require_admin),
) -> dict[str, Any]:
    pg = _pg(request)
    rows = await pg.fetch(
        "SELECT id, kind, tenant_id, user_id, status, attempts, error, created_at, started_at, finished_at FROM jobs"
        " WHERE ($1::text IS NULL OR status = $1) AND ($2::text IS NULL OR kind = $2) ORDER BY created_at DESC LIMIT $3",
        status, kind, limit,
    )
    counts = await pg.fetch("SELECT status, count(*) AS n FROM jobs GROUP BY status")
    return {"jobs": [dict(r) for r in rows], "counts": {r["status"]: int(r["n"]) for r in counts}, "retention_days": settings.JOB_RETENTION_DAYS}


@router.post("/jobs/{job_id}/cancel", summary="Cancel a job still waiting in the queue (a running one cannot be stopped safely)")
async def job_cancel(request: Request, job_id: str = Path(pattern=JOB_ID), admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    pg = _pg(request)
    rows = await pg.fetch("SELECT status FROM jobs WHERE id = $1", job_id)
    if not rows:
        raise HTTPException(status_code=404, detail=msg("admin.job_unknown"))
    if rows[0]["status"] != "queued":
        raise HTTPException(status_code=409, detail=msg("admin.job_not_queued"))
    await audit.record("admin.job_cancel", job_id, principal=admin, required=True)
    done = await pg.fetch(  # the uploaded bytes go with it: a cancelled job keeps nothing
        "UPDATE jobs SET status = 'failed', error = $2, finished_at = now(), payload_bytes = NULL WHERE id = $1 AND status = 'queued' RETURNING id",
        job_id, f"Cancelled by {admin.user_id}",
    )
    if not done:  # a worker took it between the check and the update
        raise HTTPException(status_code=409, detail=msg("admin.job_not_queued"))
    return {"cancelled": True}


# ---------------------------------------------------------------------------------------------- configuration in force

_PLAIN: dict[str, tuple[str, ...]] = {
    "access": ("APP_ENV", "AUTH_MODE", "AUTH_ALLOW_REGISTRATION", "ADMIN_ROLES", "HITL_APPROVER_ROLES", "HITL_REQUIRE_OTHER_APPROVER", "HITL_APPROVAL_TTL_SECONDS", "KNOWLEDGE_UPLOAD_ROLES", "RAG_TENANT_IDS", "ORG_ENFORCE_REGISTRY"),
    "limits": ("RATE_LIMIT_CHAT_PER_MINUTE", "RATE_LIMIT_CHAT_PER_DAY", "RATE_LIMIT_ANALYZE_PER_MINUTE", "RATE_LIMIT_LOGIN_PER_MINUTE", "AUTH_MAX_FAILURES", "USAGE_BUDGET_USD_PER_USER_DAY", "USAGE_BUDGET_HARD", "KNOWLEDGE_MAX_FILE_MB", "DATA_MAX_FILE_MB", "DATA_MAX_ROWS"),
    "models": ("FAST_LLM_MODEL", "HEAVY_LLM_MODEL", "EMBEDDING_MODEL"),
    "features": ("CHECKPOINT_ENABLED", "JOB_WORKER_ENABLED", "JOB_MAX_ATTEMPTS", "LANGFUSE_ENABLED", "LANGFUSE_MASK_PII", "PEV_MAX_ATTEMPTS", "PEV_MAX_ATTEMPTS_BY_AGENT", "VERIFIER_FAIL_CLOSED", "QUALITY_SAMPLE_RATE", "QUALITY_RETENTION_DAYS", "MEMORY_EXTRACT_MODE", "MEMORY_IN_ANSWERS", "FOLLOWUP_REWRITE"),
}
_SECRETS = ("OPENROUTER_API_KEY", "TAVILY_API_KEY", "AUTH_JWT_SECRET", "METRICS_TOKEN", "OIDC_CLIENT_SECRET", "REDIS_PASSWORD", "DB_AGENT_PASSWORD")
_ENDPOINTS = ("SANDBOX_URL", "OIDC_ISSUER", "ALERTMANAGER_URL")


def _origin(url: str) -> str:
    """scheme://host:port only: a URL in the environment may carry credentials or a token in its path."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.rsplit('@', 1)[-1]}" if parts.scheme and parts.netloc else "set"


@router.get("/config", summary="The settings in force (a chosen list; secrets only as set / not set)")
async def effective_config(_admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    groups = [
        {"group": name, "items": [{"key": key, "value": getattr(settings, key)} for key in keys if hasattr(settings, key)]}
        for name, keys in _PLAIN.items()
    ]
    groups.append({"group": "endpoints", "items": [{"key": key, "value": _origin(str(getattr(settings, key))) if getattr(settings, key, "") else ""} for key in _ENDPOINTS]})
    groups.append({"group": "secrets", "items": [{"key": key, "value": bool(getattr(settings, key, ""))} for key in _SECRETS]})
    return {"groups": groups}


# ---------------------------------------------------------------------------------------------- alerts and backups


@router.get("/alerts", summary="Alerts firing right now (needs ALERTMANAGER_URL)")
async def active_alerts(_admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    if not settings.ALERTMANAGER_URL:
        return {"configured": False, "alerts": []}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{settings.ALERTMANAGER_URL.rstrip('/')}/api/v2/alerts", params={"active": "true", "silenced": "false", "inhibited": "false"})
            response.raise_for_status()
            raw = response.json()
    except Exception as exc:  # noqa: BLE001 - the console must still open when Alertmanager is down
        return {"configured": True, "error": type(exc).__name__, "alerts": []}
    return {
        "configured": True,
        "alerts": [
            {
                "name": a.get("labels", {}).get("alertname", ""), "severity": a.get("labels", {}).get("severity", ""),
                "summary": a.get("annotations", {}).get("summary") or a.get("annotations", {}).get("description", ""), "since": a.get("startsAt"),
            }
            for a in raw[:50]
        ],
    }


def _newest_backup(directory: str) -> dict[str, Any]:
    entries = []
    with os.scandir(directory) as scan:
        for entry in scan:
            if entry.is_file(follow_symlinks=False):
                info = entry.stat()
                entries.append((info.st_mtime, entry.name, info.st_size))
    if not entries:
        return {"count": 0, "total_bytes": 0, "latest": None}
    newest = max(entries)
    return {
        "count": len(entries), "total_bytes": sum(e[2] for e in entries),
        "latest": {"name": newest[1], "size": newest[2], "at": datetime.fromtimestamp(newest[0], timezone.utc), "age_seconds": max(int(time.time() - newest[0]), 0)},
    }


@router.get("/backup", summary="The newest backup file and its age (needs BACKUP_STATUS_DIR: the backup volume mounted read-only)")
async def backup_status(_admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    if not settings.BACKUP_STATUS_DIR:
        return {"configured": False}
    try:
        return {"configured": True, **await asyncio.to_thread(_newest_backup, settings.BACKUP_STATUS_DIR)}
    except OSError as exc:
        return {"configured": True, "error": type(exc).__name__}


# ---------------------------------------------------------------------------------------------- answer quality


@router.get("/feedback", summary="Thumbs up and down on answers: per day, per tenant, and the latest down-votes with their question")
async def feedback_report(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    tenant: Optional[str] = Query(default=None, pattern=SCOPE_ID),
    _admin: Principal = Depends(require_admin),
) -> dict[str, Any]:
    pg = _pg(request)
    window = "at >= now() - make_interval(days => $1) AND ($2::text IS NULL OR tenant_id = $2)"
    totals = (await pg.fetch(f"SELECT count(*) FILTER (WHERE rating > 0) AS up, count(*) FILTER (WHERE rating < 0) AS down FROM rag_feedback WHERE {window}", days, tenant))[0]
    per_day = await pg.fetch(
        f"SELECT date_trunc('day', at)::date AS day, count(*) FILTER (WHERE rating > 0) AS up, count(*) FILTER (WHERE rating < 0) AS down"
        f" FROM rag_feedback WHERE {window} GROUP BY 1 ORDER BY 1", days, tenant,
    )
    per_tenant = await pg.fetch(
        f"SELECT tenant_id, count(*) FILTER (WHERE rating > 0) AS up, count(*) FILTER (WHERE rating < 0) AS down"
        f" FROM rag_feedback WHERE {window} GROUP BY 1 ORDER BY down DESC, up DESC LIMIT 50", days, tenant,
    )
    low = await pg.fetch(
        f"SELECT at, tenant_id, user_id, left(query, 300) AS query, left(comment, 300) AS comment, agent, left(answer, 600) AS answer, run_id, verified, retries, reasons"
        f" FROM rag_feedback WHERE rating < 0 AND {window} ORDER BY id DESC LIMIT 20",
        days, tenant,
    )
    per_agent = await pg.fetch(
        f"SELECT agent, count(*) FILTER (WHERE rating > 0) AS up, count(*) FILTER (WHERE rating < 0) AS down"
        f" FROM rag_feedback WHERE {window} GROUP BY 1 ORDER BY down DESC, up DESC LIMIT 20", days, tenant,
    )
    reasons = await pg.fetch(
        f"SELECT reason, count(*) AS n FROM rag_feedback, unnest(reasons) AS reason WHERE rating < 0 AND {window} GROUP BY 1 ORDER BY n DESC", days, tenant,
    )
    review_window = "at >= now() - make_interval(days => $1) AND ($2::text IS NULL OR tenant_id = $2)"
    graded = (await pg.fetch(f"SELECT count(*) AS n, avg(score)::float AS avg, count(*) FILTER (WHERE score <= 2) AS low FROM answer_reviews WHERE {review_window}", days, tenant))[0]
    review_agents = await pg.fetch(
        f"SELECT agent, count(*) AS n, avg(score)::float AS avg FROM answer_reviews WHERE {review_window} GROUP BY 1 ORDER BY avg LIMIT 20", days, tenant,
    )
    review_low = await pg.fetch(
        f"SELECT at, tenant_id, agent, left(query, 300) AS query, left(answer, 600) AS answer, score, reason, verified, retries"
        f" FROM answer_reviews WHERE score <= 2 AND {review_window} ORDER BY id DESC LIMIT 20", days, tenant,
    )
    up, down = int(totals["up"]), int(totals["down"])
    return {
        "reviews": {
            "graded": int(graded["n"]), "average": graded["avg"], "low": int(graded["low"]), "sample_rate": settings.QUALITY_SAMPLE_RATE,
            "agents": [{"agent": r["agent"], "graded": int(r["n"]), "average": r["avg"]} for r in review_agents],
            "recent_low": [dict(r) for r in review_low],
        },
        "days": days, "up": up, "down": down, "satisfaction": (up / (up + down)) if up + down else None,
        "per_day": [{"day": r["day"].isoformat(), "up": int(r["up"]), "down": int(r["down"])} for r in per_day],
        "tenants": [{"tenant_id": r["tenant_id"], "up": int(r["up"]), "down": int(r["down"])} for r in per_tenant],
        "agents": [{"agent": r["agent"], "up": int(r["up"]), "down": int(r["down"])} for r in per_agent],
        "reasons": [{"reason": r["reason"], "count": int(r["n"])} for r in reasons],
        "recent_down": [{**dict(r), "reasons": list(r["reasons"] or [])} for r in low],
    }
