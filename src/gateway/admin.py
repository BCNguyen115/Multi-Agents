"""Account administration (``/api/admin``): who may sign in, in which tenant and department, with which roles.

Only callers with a role in ``ADMIN_ROLES`` (anonymous dev mode too); an administrator sees every account of the system.
Self-registered accounts (table ``app_users``) can be changed here; the accounts of ``AUTH_USERS`` live in the environment and
are listed read-only. Every change is written to the append-only ``audit_log`` BEFORE it is made (no record, no change) and
ends the account's open sessions, so the new scope reaches it at once instead of at its next sign-in.
An administrator cannot lock themselves out: no disabling their own account, no dropping their own admin role.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from datetime import datetime, timezone
import secrets
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, Field

from src.config import settings
from src.shared import audit, health, metrics, usage
from src.shared import policy as department_policy
from src.shared.auth import Principal, authenticate, hash_password, hash_recovery_key, new_recovery_key, revoke_user_sessions
from src.shared.logger import get_logger
from src.shared.messages import msg
from src.shared.migrations import head_revision
from src.shared.user_store import create_user, get_user, list_users, move_users, set_password, update_user

logger: logging.Logger = get_logger(__name__)

SCOPE_ID = r"^[A-Za-z0-9_.:-]{1,64}$"   # tenant / department ids
ROLE_NAME = r"^[a-z][a-z0-9_-]{0,31}$"
USERNAME = re.compile(r"^[^\s/]{1,64}$")

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminUser(BaseModel):
    username: str
    display_name: str
    roles: list[str]
    tenant_id: str
    department_id: str
    disabled: bool
    created_at: Optional[datetime]
    source: str = Field(description="`registered` = editable here, `env` = AUTH_USERS (read-only)")
    pending: bool = Field(description="still in the pending tenant: nothing of the knowledge base or the database is visible to it")


class AdminUsers(BaseModel):
    users: list[AdminUser]
    tenants: list[str]
    departments: list[str]
    roles: list[str]


class AdminUserPatch(BaseModel):
    tenant_id: Optional[str] = Field(default=None, pattern=SCOPE_ID)
    department_id: Optional[str] = Field(default=None, pattern=SCOPE_ID)
    roles: Optional[list[str]] = Field(default=None, max_length=10)
    disabled: Optional[bool] = None


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")  # the same rule as self-registration
    display_name: str = Field(default="", max_length=64)
    tenant_id: str = Field(pattern=SCOPE_ID)
    department_id: str = Field(pattern=SCOPE_ID)
    roles: list[str] = Field(default_factory=list, max_length=10)


class IssuedCredentials(BaseModel):
    """What a created or reset account gets. Shown ONCE: only scrypt hashes are stored, so nobody can read them again."""

    user: AdminUser
    temporary_password: str
    recovery_key: str


class BulkAction(BaseModel):
    usernames: list[str] = Field(max_length=100)
    action: Literal["lock", "unlock", "move", "sign_out"]
    tenant_id: Optional[str] = Field(default=None, pattern=SCOPE_ID)
    department_id: Optional[str] = Field(default=None, pattern=SCOPE_ID)


class NameIn(BaseModel):
    name: str = Field(default="", max_length=100)


class OrgDepartment(BaseModel):
    id: str
    name: str
    users: int
    registered: bool = Field(description="created here; a department that only exists because an account uses it is not registered")


class OrgTenant(BaseModel):
    id: str
    name: str
    users: int
    registered: bool
    pending: bool = Field(description="the pending tenant every new sign-up starts in")
    departments: list[OrgDepartment]


class TenantIn(BaseModel):
    id: str = Field(pattern=SCOPE_ID)
    name: str = Field(default="", max_length=100)


class DepartmentIn(BaseModel):
    id: str = Field(pattern=SCOPE_ID)
    name: str = Field(default="", max_length=100)


async def require_admin(principal: Principal = Depends(authenticate)) -> Principal:
    if not principal.can_admin:
        raise HTTPException(status_code=403, detail=msg("admin.forbidden"))
    return principal


def _pg(request: Request) -> Any:
    pg = getattr(request.app.state, "pg_client", None)
    if pg is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    return pg


def _env_users() -> list[dict[str, Any]]:
    return [
        {
            "username": str(u.get("username", "")).lower(), "display_name": str(u.get("display_name", "")),
            "roles": [str(r) for r in (u.get("roles") or [])], "tenant_id": str(u.get("tenant_id") or settings.RLS_TENANT_ID),
            "department_id": str(u.get("department_id") or settings.RLS_DEPARTMENT_ID), "disabled": False, "created_at": None,
        }
        for u in settings.AUTH_USERS
        if u.get("username")
    ]


def _view(user: dict[str, Any], source: str = "registered") -> dict[str, Any]:
    return {
        "username": user["username"], "display_name": user.get("display_name", ""), "roles": list(user.get("roles") or []),
        "tenant_id": user["tenant_id"], "department_id": user["department_id"], "disabled": bool(user.get("disabled")),
        "created_at": user.get("created_at"), "source": source, "pending": user["tenant_id"] == settings.REGISTRATION_TENANT_ID,
    }


async def _everyone(pg: Any) -> list[dict[str, Any]]:
    return [_view(u) for u in await list_users(pg)] + [_view(u, "env") for u in _env_users()]


def _org(everyone: list[dict[str, Any]], tenants: list[Any], departments: list[Any]) -> list[dict[str, Any]]:
    """The registry merged with what the accounts use: a tenant or department only an account refers to is listed too, as not registered."""
    found: dict[str, dict[str, Any]] = {}

    def tenant(tenant_id: str) -> dict[str, Any]:
        return found.setdefault(tenant_id, {"id": tenant_id, "name": "", "users": 0, "registered": False, "departments": {}})

    def department(tenant_id: str, department_id: str) -> dict[str, Any]:
        return tenant(tenant_id)["departments"].setdefault(department_id, {"id": department_id, "name": "", "users": 0, "registered": False})

    for row in tenants:
        entry = tenant(row["id"])
        entry.update(name=row["name"], registered=True)
    for row in departments:
        entry = department(row["tenant_id"], row["id"])
        entry.update(name=row["name"], registered=True)
    for user in everyone:
        tenant(user["tenant_id"])["users"] += 1
        department(user["tenant_id"], user["department_id"])["users"] += 1
    tenant(settings.REGISTRATION_TENANT_ID)
    result = []
    for tenant_id in sorted(found, key=lambda t: (t == settings.REGISTRATION_TENANT_ID, t)):  # the pending tenant last
        entry = found[tenant_id]
        result.append({**entry, "pending": tenant_id == settings.REGISTRATION_TENANT_ID, "departments": [entry["departments"][d] for d in sorted(entry["departments"])]})
    return result


async def _registry(pg: Any) -> tuple[list[Any], list[Any]]:
    return await pg.fetch("SELECT id, name FROM tenants"), await pg.fetch("SELECT tenant_id, id, name FROM departments")


async def _check_registry(pg: Any, tenant_id: str, department_id: str) -> None:
    """With ``ORG_ENFORCE_REGISTRY`` an account may only be put in a tenant and department created in the console (the pending pair excepted)."""
    if not settings.ORG_ENFORCE_REGISTRY or tenant_id == settings.REGISTRATION_TENANT_ID:
        return
    tenants, departments = await _registry(pg)
    if tenant_id not in {t["id"] for t in tenants} or (tenant_id, department_id) not in {(d["tenant_id"], d["id"]) for d in departments}:
        raise HTTPException(status_code=422, detail=msg("admin.not_registered"))


def _valid_roles(roles: list[str]) -> list[str]:
    cleaned = sorted(set(roles))
    if not all(re.match(ROLE_NAME, r) for r in cleaned):
        raise HTTPException(status_code=422, detail=msg("admin.bad_role"))
    return cleaned


def _temporary_password() -> str:
    return secrets.token_urlsafe(12)  # 16 characters, 96 bits: over the 10-character minimum of a chosen password


async def _issue_credentials(pg: Any, username: str) -> tuple[str, str]:
    """A new random password and recovery key for a self-registered account (the old ones stop working); returned once, stored hashed."""
    password, key = _temporary_password(), new_recovery_key()
    password_hash = await asyncio.to_thread(hash_password, password)  # scrypt: off the event loop
    recovery_hash = await asyncio.to_thread(hash_recovery_key, key)
    await set_password(pg, username, password_hash, recovery_hash)
    return password, key


@router.get("/users", response_model=AdminUsers, summary="Every account with its tenant, department and roles")
async def users(request: Request, _admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    pg = _pg(request)
    everyone = await _everyone(pg)
    tenants, departments = await _registry(pg)
    known_roles = {*settings.ADMIN_ROLES, *settings.HITL_APPROVER_ROLES, *settings.KNOWLEDGE_UPLOAD_ROLES}
    return {
        "users": everyone,
        "tenants": sorted({u["tenant_id"] for u in everyone} | {t["id"] for t in tenants} | {settings.REGISTRATION_TENANT_ID}),
        "departments": sorted({u["department_id"] for u in everyone} | {d["id"] for d in departments} | {settings.REGISTRATION_DEPARTMENT_ID}),
        "roles": sorted(known_roles | {r for u in everyone for r in u["roles"]}),
    }


@router.get("/org", response_model=list[OrgTenant], summary="Tenants with their departments and how many accounts use each")
async def org(request: Request, _admin: Principal = Depends(require_admin)) -> list[dict[str, Any]]:
    pg = _pg(request)
    return _org(await _everyone(pg), *await _registry(pg))


async def _one_tenant(pg: Any, tenant_id: str) -> dict[str, Any]:
    return next(t for t in _org(await _everyone(pg), *await _registry(pg)) if t["id"] == tenant_id)


@router.post("/tenants", response_model=OrgTenant, status_code=201, summary="Create a tenant")
async def create_tenant(body: TenantIn, request: Request, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    pg = _pg(request)
    if body.id == settings.REGISTRATION_TENANT_ID:
        raise HTTPException(status_code=409, detail=msg("admin.reserved"))
    if await pg.fetch("SELECT 1 FROM tenants WHERE id = $1", body.id):
        raise HTTPException(status_code=409, detail=msg("admin.tenant_exists"))
    await audit.record("admin.tenant_create", body.id, detail={"name": body.name}, principal=admin, required=True)  # traced first, like every admin change
    if not await pg.fetch("INSERT INTO tenants (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING RETURNING id", body.id, body.name.strip()):
        raise HTTPException(status_code=409, detail=msg("admin.tenant_exists"))  # created by someone else a moment ago
    logger.info("Admin %s created tenant %s", admin.user_id, body.id)
    return await _one_tenant(pg, body.id)


@router.post("/tenants/{tenant_id}/departments", response_model=OrgTenant, status_code=201, summary="Create a department in a tenant")
async def create_department(
    body: DepartmentIn, request: Request, tenant_id: str = Path(pattern=SCOPE_ID), admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    pg = _pg(request)
    if tenant_id == settings.REGISTRATION_TENANT_ID:
        raise HTTPException(status_code=409, detail=msg("admin.reserved"))
    parent = next((t for t in _org(await _everyone(pg), *await _registry(pg)) if t["id"] == tenant_id), None)
    if parent is None:  # neither created here nor used by any account
        raise HTTPException(status_code=404, detail=msg("admin.tenant_unknown"))
    if any(d["id"] == body.id and d["registered"] for d in parent["departments"]):
        raise HTTPException(status_code=409, detail=msg("admin.department_exists"))
    await audit.record("admin.department_create", f"{tenant_id}/{body.id}", detail={"name": body.name}, principal=admin, required=True)
    if not await pg.fetch(
        "INSERT INTO departments (tenant_id, id, name) VALUES ($1, $2, $3) ON CONFLICT (tenant_id, id) DO NOTHING RETURNING id", tenant_id, body.id, body.name.strip()
    ):
        raise HTTPException(status_code=409, detail=msg("admin.department_exists"))
    logger.info("Admin %s created department %s in tenant %s", admin.user_id, body.id, tenant_id)
    return await _one_tenant(pg, tenant_id)


async def _pending_approvals(redis: Any) -> Optional[int]:
    """How many sensitive actions wait for a decision, system-wide (Redis ``hitl:pending:*``); ``None`` when Redis cannot be asked."""
    client = getattr(redis, "client", None)
    if client is None:
        return None
    try:
        count = 0
        async for _key in client.scan_iter(match="hitl:pending:*", count=200):
            count += 1
            if count >= 1000:  # a number worth acting on, not worth counting further
                break
        return count
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not count pending approvals: %s", exc or type(exc).__name__)
        return None


@router.get("/overview", summary="What an administrator opens the console for: accounts, work waiting, jobs, cost, content, recent activity")
async def overview(request: Request, _admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    pg = _pg(request)
    everyone = await _everyone(pg)
    org = _org(everyone, *await _registry(pg))
    content = (await pg.fetch(
        "SELECT (SELECT count(*) FROM conversations) AS conversations, (SELECT count(*) FROM dashboards) AS dashboards,"
        " (SELECT count(DISTINCT doc_key) FROM rag_chunks) AS documents,"
        " (SELECT count(*) FROM rag_feedback WHERE at >= now() - interval '7 days' AND rating > 0) AS feedback_up,"
        " (SELECT count(*) FROM rag_feedback WHERE at >= now() - interval '7 days' AND rating < 0) AS feedback_down"
    ))[0]
    jobs = (await pg.fetch(
        "SELECT count(*) FILTER (WHERE status = 'queued') AS queued, count(*) FILTER (WHERE status = 'running') AS running,"
        " count(*) FILTER (WHERE status = 'done' AND created_at >= now() - interval '24 hours') AS done_24h,"
        " count(*) FILTER (WHERE status = 'failed' AND created_at >= now() - interval '24 hours') AS failed_24h FROM jobs"
    ))[0]
    today = (await pg.fetch("SELECT COALESCE(sum(cost_usd), 0) AS cost FROM usage_events WHERE ts >= date_trunc('day', now())"))[0]["cost"]
    week = await usage.summary(pg, 7)
    activity = await pg.fetch("SELECT at, actor, action, target, outcome FROM audit_log ORDER BY id DESC LIMIT 10")
    return {
        "accounts": {
            "total": len(everyone), "pending": sum(1 for u in everyone if u["pending"]), "locked": sum(1 for u in everyone if u["disabled"]),
            "env": sum(1 for u in everyone if u["source"] == "env"),
        },
        "organization": {"tenants": sum(1 for t in org if not t["pending"]), "departments": sum(len(t["departments"]) for t in org if not t["pending"])},
        "approvals_pending": await _pending_approvals(request.app.state.redis_client),
        "jobs": dict(jobs),
        "cost": {"today": float(today), "week_total": week["totals"]["cost"], "week_calls": week["totals"]["calls"], "per_day": week["per_day"]},
        "content": dict(content),
        "activity": [dict(row) for row in activity],
    }


@router.get("/health", summary="Is every service up, which database revision runs, how this instance's requests fare, what the job queue holds")
async def system_health(request: Request, _admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    pg = _pg(request)
    redis = request.app.state.redis_client
    checks = {
        "postgres": lambda: health.check_postgres(pg),
        "redis": lambda: health.check_redis(redis),
        "reranker": lambda: health.check_reranker(),
    }
    if settings.SANDBOX_URL:
        checks["sandbox"] = lambda: health.check_sandbox()
    results = await asyncio.gather(*(health.probe_timed(check) for check in checks.values()))
    services: dict[str, dict[str, Any]] = dict(zip(checks, results))
    if not settings.SANDBOX_URL:
        services["sandbox"] = {"status": "off", "ms": 0}  # analysis code runs in a child process (development setup)
    llm = getattr(request.app.state, "llm_client", None)
    services["langfuse"] = {"status": "ok" if getattr(llm, "langfuse_enabled", settings.LANGFUSE_ENABLED) else "off", "ms": 0}
    failing = [name for name, result in services.items() if result["status"] not in ("ok", "off")]
    revision = await pg.fetch("SELECT version_num FROM alembic_version")
    current = revision[0]["version_num"] if revision else None
    head = head_revision()
    queue = (await pg.fetch(
        "SELECT count(*) FILTER (WHERE status = 'queued') AS queued, count(*) FILTER (WHERE status = 'running') AS running,"
        " count(*) FILTER (WHERE status = 'failed' AND created_at >= now() - interval '24 hours') AS failed_24h,"
        " COALESCE(EXTRACT(EPOCH FROM now() - min(created_at) FILTER (WHERE status = 'queued')), 0)::int AS oldest_queued_seconds FROM jobs"
    ))[0]
    failures = await pg.fetch("SELECT id, kind, user_id, error, finished_at FROM jobs WHERE status = 'failed' ORDER BY finished_at DESC NULLS LAST LIMIT 10")
    snapshot = metrics.snapshot()
    return {
        "checked_at": datetime.now(timezone.utc),
        "status": "down" if any(name in ("postgres", "redis") for name in failing) else ("degraded" if failing else "ok"),
        "services": services,
        "instance": {"hostname": socket.gethostname(), "uptime_seconds": snapshot["uptime_seconds"], "db_revision": current, "db_head": head, "db_current": current == head},
        "http": snapshot,
        "queue": {**dict(queue), "recent_failures": [dict(row) for row in failures]},
    }


@router.get("/usage", summary="What the LLM calls of the last N days cost, by user, tenant, model and day")
async def usage_report(
    request: Request, days: int = Query(30, ge=1, le=365), tenant: Optional[str] = Query(default=None, pattern=SCOPE_ID), _admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    return await usage.summary(_pg(request), days, tenant)


@router.patch("/users/{username}", response_model=AdminUser, summary="Change the scope, roles or lock of a self-registered account")
async def patch_user(username: str, body: AdminUserPatch, request: Request, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    if not USERNAME.match(username):
        raise HTTPException(status_code=422, detail=msg("admin.bad_name"))
    name = username.lower()
    if any(u["username"] == name for u in _env_users()):
        raise HTTPException(status_code=409, detail=msg("admin.env_managed"))
    roles = None if body.roles is None else sorted(set(body.roles))
    if roles is not None and not all(re.match(ROLE_NAME, r) for r in roles):
        raise HTTPException(status_code=422, detail=msg("admin.bad_role"))
    pg = _pg(request)
    before = await get_user(pg, name)
    if before is None:
        raise HTTPException(status_code=404, detail=msg("admin.not_found"))
    is_self = name == admin.user_id.lower()
    if is_self and (body.disabled or (roles is not None and not set(roles) & set(settings.ADMIN_ROLES))):
        raise HTTPException(status_code=409, detail=msg("admin.self_lockout"))
    changes = {k: v for k, v in {"tenant_id": body.tenant_id, "department_id": body.department_id, "roles": roles, "disabled": body.disabled}.items() if v is not None}
    scope = (changes.get("tenant_id", before["tenant_id"]), changes.get("department_id", before["department_id"]))
    if scope != (before["tenant_id"], before["department_id"]):
        await _check_registry(pg, *scope)  # only a MOVE is checked: an account already in an unregistered tenant keeps its roles editable
    if changes:
        # the record comes first and is required: an administrator's change that cannot be traced does not happen
        await audit.record(
            "admin.user_update", name, detail={"before": {k: before[k] for k in changes}, "after": changes}, principal=admin, required=True
        )
        await update_user(pg, name, **changes)
        if not is_self:
            await revoke_user_sessions(request.app.state.redis_client, name)  # the new scope applies now, not at the next sign-in
        logger.info("Admin %s changed %s: %s", admin.user_id, name, sorted(changes))
    after = await get_user(pg, name) or before
    return _view(after)


def _name_of(username: str) -> str:
    if not USERNAME.match(username):
        raise HTTPException(status_code=422, detail=msg("admin.bad_name"))
    return username.lower()


async def _managed_account(pg: Any, name: str, admin: Principal) -> dict[str, Any]:
    """The self-registered account an administrator may reset: not one of ``AUTH_USERS``, not an SSO account, not their own."""
    if any(u["username"] == name for u in _env_users()):
        raise HTTPException(status_code=409, detail=msg("admin.env_managed"))
    user = await get_user(pg, name)
    if user is None:
        raise HTTPException(status_code=404, detail=msg("admin.not_found"))
    if user["password_hash"] == "sso":
        raise HTTPException(status_code=409, detail=msg("admin.sso_account"))
    if name == admin.user_id.lower():
        raise HTTPException(status_code=409, detail=msg("admin.self_action"))  # your own password: change-password, which asks for the current one
    return user


@router.post("/users", response_model=IssuedCredentials, status_code=201, summary="Create an account: it comes back with a temporary password and a recovery key, shown once")
async def create_account(body: AdminUserCreate, request: Request, response: Response, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    if not settings.AUTH_ALLOW_REGISTRATION:  # sign-in only reads database accounts with this switch on: the account would be useless
        raise HTTPException(status_code=409, detail=msg("admin.accounts_off"))
    pg = _pg(request)
    name = body.username.lower()
    if any(u["username"] == name for u in _env_users()):
        raise HTTPException(status_code=409, detail=msg("admin.name_taken"))
    roles = _valid_roles(body.roles)
    await _check_registry(pg, body.tenant_id, body.department_id)
    await audit.record("admin.user_create", name, detail={"tenant_id": body.tenant_id, "department_id": body.department_id, "roles": roles}, principal=admin, required=True)
    password, key = _temporary_password(), new_recovery_key()
    password_hash = await asyncio.to_thread(hash_password, password)
    recovery_hash = await asyncio.to_thread(hash_recovery_key, key)
    if not await create_user(pg, name, body.display_name.strip(), password_hash, recovery_hash, body.tenant_id, body.department_id):
        raise HTTPException(status_code=409, detail=msg("admin.name_taken"))
    if roles:
        await update_user(pg, name, roles=roles)
    logger.info("Admin %s created account %s", admin.user_id, name)
    response.headers["Cache-Control"] = "no-store"  # the response carries secrets
    return {"user": _view(await get_user(pg, name) or {}), "temporary_password": password, "recovery_key": key}


@router.post("/users/bulk", summary="Lock, unlock, move or sign out several self-registered accounts at once")
async def bulk_users(body: BulkAction, request: Request, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    pg = _pg(request)
    names = sorted({u.lower() for u in body.usernames if USERNAME.match(u)})
    if not names:
        raise HTTPException(status_code=422, detail=msg("admin.bulk_empty"))
    if body.action == "move":
        if not body.tenant_id or not body.department_id:
            raise HTTPException(status_code=422, detail=msg("admin.bulk_target"))
        await _check_registry(pg, body.tenant_id, body.department_id)
    env = {u["username"] for u in _env_users()}
    done: list[str] = []
    skipped: list[dict[str, str]] = []
    for name in names:
        if name in env:
            skipped.append({"username": name, "reason": "env_managed"})
            continue
        if name == admin.user_id.lower() and body.action in ("lock", "sign_out"):
            skipped.append({"username": name, "reason": "self"})  # no locking or signing out the administrator who is doing it
            continue
        before = await get_user(pg, name)
        if before is None:
            skipped.append({"username": name, "reason": "not_found"})
            continue
        changes: dict[str, Any] = {"lock": {"disabled": True}, "unlock": {"disabled": False}, "move": {"tenant_id": body.tenant_id, "department_id": body.department_id}}.get(body.action, {})
        try:
            if changes:
                await audit.record("admin.user_update", name, detail={"before": {k: before[k] for k in changes}, "after": changes, "bulk": True}, principal=admin, required=True)
                await update_user(pg, name, **changes)
            else:
                await audit.record("admin.user_signout", name, detail={"bulk": True}, principal=admin, required=True)
            if name != admin.user_id.lower():
                await revoke_user_sessions(request.app.state.redis_client, name)
        except Exception as exc:  # noqa: BLE001 - one account's failure must not stop the others, and is reported
            logger.warning("Bulk %s on %s failed: %s", body.action, name, exc or type(exc).__name__)
            skipped.append({"username": name, "reason": "failed"})
            continue
        done.append(name)
    logger.info("Admin %s bulk %s: %d done, %d skipped", admin.user_id, body.action, len(done), len(skipped))
    return {"done": done, "skipped": skipped}


@router.post("/users/{username}/sign-out", summary="End every open session of an account now")
async def sign_out_user(username: str, request: Request, admin: Principal = Depends(require_admin)) -> dict[str, bool]:
    name = _name_of(username)
    if name == admin.user_id.lower():
        raise HTTPException(status_code=409, detail=msg("admin.self_action"))
    pg = _pg(request)
    if not any(u["username"] == name for u in _env_users()) and await get_user(pg, name) is None:
        raise HTTPException(status_code=404, detail=msg("admin.not_found"))
    await audit.record("admin.user_signout", name, principal=admin, required=True)
    await revoke_user_sessions(request.app.state.redis_client, name)
    return {"signed_out": True}


@router.post("/users/{username}/reset-credentials", response_model=IssuedCredentials, summary="New temporary password and recovery key for a self-registered account (shown once)")
async def reset_credentials(username: str, request: Request, response: Response, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    name = _name_of(username)
    pg = _pg(request)
    await _managed_account(pg, name, admin)
    await audit.record("admin.user_reset", name, principal=admin, required=True)  # the secrets themselves are never recorded
    password, key = await _issue_credentials(pg, name)
    await revoke_user_sessions(request.app.state.redis_client, name)  # whoever held the old password is out
    logger.info("Admin %s reset the credentials of %s", admin.user_id, name)
    response.headers["Cache-Control"] = "no-store"
    return {"user": _view(await get_user(pg, name) or {}), "temporary_password": password, "recovery_key": key}


@router.patch("/tenants/{tenant_id}", response_model=OrgTenant, summary="Name a tenant (this also registers one only the accounts use)")
async def rename_tenant(body: NameIn, request: Request, tenant_id: str = Path(pattern=SCOPE_ID), admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    pg = _pg(request)
    if tenant_id == settings.REGISTRATION_TENANT_ID:
        raise HTTPException(status_code=409, detail=msg("admin.reserved"))
    if not any(t["id"] == tenant_id for t in _org(await _everyone(pg), *await _registry(pg))):
        raise HTTPException(status_code=404, detail=msg("admin.tenant_unknown"))
    await audit.record("admin.tenant_rename", tenant_id, detail={"name": body.name}, principal=admin, required=True)
    await pg.execute("INSERT INTO tenants (id, name) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name", tenant_id, body.name.strip())
    return await _one_tenant(pg, tenant_id)


def _place_exists(org: list[dict[str, Any]], tenant_id: str, department_id: str) -> bool:
    """Somewhere accounts may be moved to: the pending pair, or a department the registry or the accounts know."""
    if (tenant_id, department_id) == (settings.REGISTRATION_TENANT_ID, settings.REGISTRATION_DEPARTMENT_ID):
        return True
    return any(t["id"] == tenant_id and any(d["id"] == department_id for d in t["departments"]) for t in org)


async def _move_out(pg: Any, request: Request, admin: Principal, who: list[str], source: str, tenant_id: str, department_id: Optional[str], target: tuple[str, str]) -> None:
    """Move the self-registered accounts out of a tenant / department that is being deleted: the audit record first (it names them), then the move,
    then their sessions end so the new scope applies now."""
    await audit.record("admin.org_move_users", source, detail={"to": f"{target[0]}/{target[1]}", "users": who}, principal=admin, required=True)
    await move_users(pg, tenant_id, department_id, *target)
    for name in who:
        if name != admin.user_id.lower():
            await revoke_user_sessions(request.app.state.redis_client, name)


@router.delete("/tenants/{tenant_id}", status_code=204, summary="Delete a tenant (its departments and policies go with it); accounts still in it are moved to `move_to` (tenant/department)")
async def delete_tenant(
    request: Request, tenant_id: str = Path(pattern=SCOPE_ID), move_to: Optional[str] = Query(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,64}/[A-Za-z0-9_.:-]{1,64}$"),
    admin: Principal = Depends(require_admin),
) -> Response:
    pg = _pg(request)
    if tenant_id == settings.REGISTRATION_TENANT_ID:
        raise HTTPException(status_code=409, detail=msg("admin.reserved"))
    everyone = await _everyone(pg)
    org = _org(everyone, *await _registry(pg))
    if not any(t["id"] == tenant_id for t in org):
        raise HTTPException(status_code=404, detail=msg("admin.org_missing"))
    inside = [u for u in everyone if u["tenant_id"] == tenant_id]
    if any(u["source"] == "env" for u in inside):
        raise HTTPException(status_code=409, detail=msg("admin.org_env_users"))
    who = [u["username"] for u in inside]
    target: Optional[tuple[str, str]] = None
    if who:
        if move_to is None:
            raise HTTPException(status_code=409, detail=msg("admin.org_in_use"))
        target = (move_to.split("/")[0], move_to.split("/")[1])
        if target[0] == tenant_id or not _place_exists(org, *target):
            raise HTTPException(status_code=422, detail=msg("admin.move_target"))
        await _check_registry(pg, *target)
    if target is not None:
        await _move_out(pg, request, admin, who, tenant_id, tenant_id, None, target)
    await audit.record("admin.tenant_delete", tenant_id, detail={"moved": len(who)}, principal=admin, required=True)
    await pg.execute("DELETE FROM department_policies WHERE tenant_id = $1", tenant_id)
    await pg.execute("DELETE FROM departments WHERE tenant_id = $1", tenant_id)
    await pg.execute("DELETE FROM tenants WHERE id = $1", tenant_id)
    department_policy.invalidate()
    return Response(status_code=204)


@router.patch("/tenants/{tenant_id}/departments/{department_id}", response_model=OrgTenant, summary="Name a department (this also registers one only the accounts use)")
async def rename_department(
    body: NameIn, request: Request, tenant_id: str = Path(pattern=SCOPE_ID), department_id: str = Path(pattern=SCOPE_ID), admin: Principal = Depends(require_admin)
) -> dict[str, Any]:
    pg = _pg(request)
    if tenant_id == settings.REGISTRATION_TENANT_ID:
        raise HTTPException(status_code=409, detail=msg("admin.reserved"))
    parent = next((t for t in _org(await _everyone(pg), *await _registry(pg)) if t["id"] == tenant_id), None)
    if parent is None or not any(d["id"] == department_id for d in parent["departments"]):
        raise HTTPException(status_code=404, detail=msg("admin.org_missing"))
    await audit.record("admin.department_rename", f"{tenant_id}/{department_id}", detail={"name": body.name}, principal=admin, required=True)
    await pg.execute(
        "INSERT INTO departments (tenant_id, id, name) VALUES ($1, $2, $3) ON CONFLICT (tenant_id, id) DO UPDATE SET name = EXCLUDED.name",
        tenant_id, department_id, body.name.strip(),
    )
    return await _one_tenant(pg, tenant_id)


@router.delete("/tenants/{tenant_id}/departments/{department_id}", status_code=204, summary="Delete a department (and its policy); accounts still in it are moved to the department `move_to` of the same tenant")
async def delete_department(
    request: Request, tenant_id: str = Path(pattern=SCOPE_ID), department_id: str = Path(pattern=SCOPE_ID),
    move_to: Optional[str] = Query(default=None, pattern=SCOPE_ID), admin: Principal = Depends(require_admin),
) -> Response:
    pg = _pg(request)
    everyone = await _everyone(pg)
    org = _org(everyone, *await _registry(pg))
    if not any(t["id"] == tenant_id and any(d["id"] == department_id for d in t["departments"]) for t in org):
        raise HTTPException(status_code=404, detail=msg("admin.org_missing"))
    inside = [u for u in everyone if u["tenant_id"] == tenant_id and u["department_id"] == department_id]
    if any(u["source"] == "env" for u in inside):
        raise HTTPException(status_code=409, detail=msg("admin.org_env_users"))
    who = [u["username"] for u in inside]
    if who:
        if move_to is None:
            raise HTTPException(status_code=409, detail=msg("admin.org_in_use"))
        if move_to == department_id or not _place_exists(org, tenant_id, move_to):
            raise HTTPException(status_code=422, detail=msg("admin.move_target"))
        await _check_registry(pg, tenant_id, move_to)
        await _move_out(pg, request, admin, who, f"{tenant_id}/{department_id}", tenant_id, department_id, (tenant_id, move_to))
    await audit.record("admin.department_delete", f"{tenant_id}/{department_id}", detail={"moved": len(who)}, principal=admin, required=True)
    await pg.execute("DELETE FROM department_policies WHERE tenant_id = $1 AND department_id = $2", tenant_id, department_id)
    await pg.execute("DELETE FROM departments WHERE tenant_id = $1 AND id = $2", tenant_id, department_id)
    department_policy.invalidate()
    return Response(status_code=204)


class PolicyIn(BaseModel):
    """`null` for a field = no restriction from here (a department then follows its tenant's default, and a tenant default means everything)."""

    allowed_agents: Optional[list[str]] = Field(default=None, max_length=10)
    can_upload_knowledge: Optional[bool] = None


@router.get("/policies", summary="What each department (and each tenant's default, department `*`) may use: agents and the knowledge upload")
async def list_policies(request: Request, _admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    rows = await _pg(request).fetch(
        "SELECT tenant_id, department_id, allowed_agents, can_upload_knowledge, updated_at, updated_by FROM department_policies ORDER BY tenant_id, department_id"
    )
    return {
        "agents": list(department_policy.KNOWN_AGENTS),
        "upload_roles": list(settings.KNOWLEDGE_UPLOAD_ROLES),
        "policies": [{**dict(r), "allowed_agents": list(r["allowed_agents"]) if r["allowed_agents"] is not None else None} for r in rows],
    }


@router.put("/policies/{tenant_id}/{department_id}", summary="Set what a department (or `*`, the tenant's default) may use; both fields empty removes the policy")
async def set_policy(
    body: PolicyIn, request: Request, tenant_id: str = Path(pattern=SCOPE_ID), department_id: str = Path(pattern=r"^(\*|[A-Za-z0-9_.:-]{1,64})$"),
    admin: Principal = Depends(require_admin),
) -> dict[str, Any]:
    pg = _pg(request)
    if tenant_id == settings.REGISTRATION_TENANT_ID:
        raise HTTPException(status_code=409, detail=msg("admin.reserved"))
    org = _org(await _everyone(pg), *await _registry(pg))
    tenant = next((t for t in org if t["id"] == tenant_id), None)
    if tenant is None or (department_id != department_policy.TENANT_DEFAULT and not any(d["id"] == department_id for d in tenant["departments"])):
        raise HTTPException(status_code=422, detail=msg("admin.policy_scope"))
    agents: Optional[list[str]] = None
    if body.allowed_agents is not None:
        agents = sorted(set(body.allowed_agents))
        if not agents or not set(agents) <= set(department_policy.KNOWN_AGENTS):
            raise HTTPException(status_code=422, detail=msg("admin.policy_agents"))
    before = await pg.fetch("SELECT allowed_agents, can_upload_knowledge FROM department_policies WHERE tenant_id = $1 AND department_id = $2", tenant_id, department_id)
    await audit.record(
        "admin.policy_set", f"{tenant_id}/{department_id}",
        detail={"before": dict(before[0]) if before else None, "after": {"allowed_agents": agents, "can_upload_knowledge": body.can_upload_knowledge}},
        principal=admin, required=True,
    )
    if agents is None and body.can_upload_knowledge is None:
        await pg.execute("DELETE FROM department_policies WHERE tenant_id = $1 AND department_id = $2", tenant_id, department_id)
    else:
        await pg.execute(
            "INSERT INTO department_policies (tenant_id, department_id, allowed_agents, can_upload_knowledge, updated_by) VALUES ($1, $2, $3, $4, $5)"
            " ON CONFLICT (tenant_id, department_id) DO UPDATE SET allowed_agents = EXCLUDED.allowed_agents,"
            " can_upload_knowledge = EXCLUDED.can_upload_knowledge, updated_at = now(), updated_by = EXCLUDED.updated_by",
            tenant_id, department_id, agents, body.can_upload_knowledge, admin.user_id,
        )
    department_policy.invalidate()  # this replica sees it at once, the others within the cache's few seconds
    return {"tenant_id": tenant_id, "department_id": department_id, "allowed_agents": agents, "can_upload_knowledge": body.can_upload_knowledge}
