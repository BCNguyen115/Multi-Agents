"""Saved dashboards (``/api/dashboards``): a verified ``dashboard_spec`` plus the normalised file it was built from.

A dashboard belongs to ``(tenant, user)`` of the caller. ``shared`` lets the other signed-in users of the SAME tenant open it
read-only, which also hands them the stored file (the filter and grid routes need it): the UI says so before it is switched on.
Opening one puts the file back into the viewer's own Redis session (``open``), so ``/api/analyze/filter|rows|export`` work
unchanged; ``refresh`` analyses the stored file again (same pipeline as ``/api/analyze``) and replaces the spec.

Not here on purpose: a schedule. With a fixed file a re-run gives the same dashboard; it earns its place once a source that
changes (a database query, a URL) exists.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.config import settings
from src.shared import audit
from src.shared.auth import Principal, authenticate
from src.shared.logger import get_logger
from src.shared.messages import msg
from src.shared.rate_limit import enforce as enforce_rate_limit
from src.shared.security import wrap_user_input

logger: logging.Logger = get_logger(__name__)

MAX_DASHBOARDS_PER_USER: int = 100
MAX_SPEC_BYTES: int = 4 * 1024 * 1024
REFRESH_QUERY: str = "Hãy phân tích dữ liệu và dựng dashboard cho file này"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])


class DashboardSummary(BaseModel):
    id: str
    title: str
    filename: str
    shared: bool
    mine: bool
    updated_at: datetime


class DashboardOpened(DashboardSummary):
    spec: dict[str, Any]


class DashboardIn(BaseModel):
    title: str = Field(default="", max_length=200)
    session_id: str = Field(min_length=1, max_length=200, description="the analysis session the dashboard came from (its file is read from there)")
    spec: dict[str, Any]


class DashboardPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    shared: Optional[bool] = None


def _pg(request: Request) -> Any:
    pg = getattr(request.app.state, "pg_client", None)
    if pg is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    return pg


def _check_id(dashboard_id: str) -> None:
    if not ID_PATTERN.match(dashboard_id):
        raise HTTPException(status_code=422, detail=msg("dash.bad_id"))


def _summary(row: Any, principal: Principal) -> dict[str, Any]:
    return {
        "id": row["id"], "title": row["title"], "filename": row["filename"], "shared": row["shared"],
        "mine": row["user_id"] == principal.user_id, "updated_at": row["updated_at"],
    }


def _spec(row: Any) -> dict[str, Any]:
    spec = row["spec"]
    return json.loads(spec) if isinstance(spec, str) else spec


def _fit(spec: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """The spec without ``sessionId`` as JSON; over the limit the table preview goes (the grid asks the server for rows, the file is stored)."""
    spec = {k: v for k, v in spec.items() if k != "sessionId"}
    payload = json.dumps(spec, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_SPEC_BYTES and isinstance(spec.get("table"), dict):
        spec["table"] = {k: v for k, v in spec["table"].items() if k != "rows"}
        payload = json.dumps(spec, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_SPEC_BYTES:
        raise HTTPException(status_code=413, detail=msg("dash.too_big", mb=MAX_SPEC_BYTES // (1024 * 1024)))
    return spec, payload


async def _readable(request: Request, principal: Principal, dashboard_id: str) -> Any:
    """The caller's own dashboard, or a shared one of the same tenant (never for a not-yet-assigned account)."""
    _check_id(dashboard_id)
    rows = await _pg(request).fetch(
        "SELECT user_id, id, title, filename, spec, csv_gz, shared, updated_at FROM dashboards"
        " WHERE tenant_id = $1 AND id = $2 AND (user_id = $3 OR (shared AND $4::boolean))",
        principal.tenant_id, dashboard_id, principal.user_id, not principal.unassigned,
    )
    # an id is unique per owner, not per tenant: prefer the caller's own row when both exist
    rows = sorted(rows, key=lambda r: r["user_id"] != principal.user_id)
    if not rows:
        raise HTTPException(status_code=404, detail=msg("dash.not_found"))
    return rows[0]


@router.get("", response_model=list[DashboardSummary], summary="The caller's dashboards and the ones shared in the tenant, newest first")
async def list_dashboards(request: Request, principal: Principal = Depends(authenticate)) -> list[dict[str, Any]]:
    rows = await _pg(request).fetch(
        "SELECT user_id, id, title, filename, shared, updated_at FROM dashboards"
        " WHERE tenant_id = $1 AND (user_id = $2 OR (shared AND $3::boolean)) ORDER BY updated_at DESC LIMIT $4",
        principal.tenant_id, principal.user_id, not principal.unassigned, MAX_DASHBOARDS_PER_USER * 2,
    )
    return [_summary(r, principal) for r in rows]


@router.post("", response_model=DashboardSummary, status_code=201, summary="Save the dashboard of an analysis session")
async def save_dashboard(body: DashboardIn, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    active = await request.app.state.redis_client.get_active_file(session_id=principal.session(body.session_id))
    if not active or not active.get("csv_content"):
        raise HTTPException(status_code=404, detail=msg("dash.no_file"))
    _spec_dict, payload = _fit(body.spec)
    csv_gz = gzip.compress(active["csv_content"].encode("utf-8"))
    async with _pg(request).transaction() as conn:
        # serialise this user's saves so the count check cannot be raced
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"dashboards:{principal.tenant_id}:{principal.user_id}")
        count = await conn.fetchval("SELECT count(*) FROM dashboards WHERE tenant_id = $1 AND user_id = $2", principal.tenant_id, principal.user_id)
        if count >= MAX_DASHBOARDS_PER_USER:
            raise HTTPException(status_code=409, detail=msg("dash.too_many", limit=MAX_DASHBOARDS_PER_USER))
        row = await conn.fetchrow(
            "INSERT INTO dashboards (tenant_id, user_id, id, title, filename, spec, csv_gz) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)"
            " RETURNING user_id, id, title, filename, shared, updated_at",
            principal.tenant_id, principal.user_id, uuid.uuid4().hex,
            (body.title or active.get("filename") or "")[:200], active.get("filename", ""), payload, csv_gz,
        )
    return _summary(row, principal)


@router.post("/{dashboard_id}/open", response_model=DashboardOpened, summary="Open a dashboard: restores its file into a new session of the caller")
async def open_dashboard(dashboard_id: str, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    row = await _readable(request, principal, dashboard_id)
    session = uuid.uuid4().hex
    await request.app.state.redis_client.set_active_file(
        session_id=principal.session(session), filename=row["filename"], csv_content=gzip.decompress(row["csv_gz"]).decode("utf-8")
    )
    return {**_summary(row, principal), "spec": {**_spec(row), "sessionId": session}}


@router.post("/{dashboard_id}/refresh", response_model=DashboardOpened, summary="Analyse the stored file again and replace the saved spec (owner only)")
async def refresh_dashboard(dashboard_id: str, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    await enforce_rate_limit(request.app.state.redis_client, principal, request, "analyze", settings.RATE_LIMIT_ANALYZE_PER_MINUTE)
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    row = await _readable(request, principal, dashboard_id)
    if row["user_id"] != principal.user_id:
        raise HTTPException(status_code=403, detail=msg("dash.owner_only"))
    session = uuid.uuid4().hex
    wrapped, _nonce = wrap_user_input(REFRESH_QUERY)
    try:
        raw = await orchestrator.handle_request(
            query=wrapped, session_id=principal.session(session),
            csv_content=gzip.decompress(row["csv_gz"]).decode("utf-8"), csv_filename=row["filename"] or None,
        )
        spec = json.loads(raw).get("dashboard_spec")
    except Exception as exc:  # noqa: BLE001 - any failure leaves the saved version untouched
        logger.warning("Dashboard refresh failed id=%s: %s", dashboard_id, exc or type(exc).__name__)
        spec = None
    if not isinstance(spec, dict):
        raise HTTPException(status_code=422, detail=msg("dash.refresh_failed"))
    spec, payload = _fit(spec)
    updated = await _pg(request).fetch(
        "UPDATE dashboards SET spec = $4::jsonb, updated_at = clock_timestamp() WHERE tenant_id = $1 AND user_id = $2 AND id = $3"
        " RETURNING user_id, id, title, filename, shared, updated_at",
        principal.tenant_id, principal.user_id, dashboard_id, payload,
    )
    if not updated:  # deleted while the analysis ran
        raise HTTPException(status_code=404, detail=msg("dash.not_found"))
    return {**_summary(updated[0], principal), "spec": {**spec, "sessionId": session}}


@router.patch("/{dashboard_id}", response_model=DashboardSummary, summary="Rename or (un)share a dashboard (owner only)")
async def patch_dashboard(dashboard_id: str, body: DashboardPatch, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    _check_id(dashboard_id)
    rows = await _pg(request).fetch(
        "UPDATE dashboards SET title = COALESCE($4, title), shared = COALESCE($5, shared), updated_at = clock_timestamp()"
        " WHERE tenant_id = $1 AND user_id = $2 AND id = $3 RETURNING user_id, id, title, filename, shared, updated_at",
        principal.tenant_id, principal.user_id, dashboard_id, body.title, body.shared,
    )
    if not rows:
        raise HTTPException(status_code=404, detail=msg("dash.not_found"))
    if body.shared is not None:
        await audit.record("dash.share", dashboard_id, detail={"shared": body.shared}, principal=principal)
    return _summary(rows[0], principal)


@router.delete("/{dashboard_id}", status_code=204, summary="Delete a dashboard (owner only)")
async def delete_dashboard(dashboard_id: str, request: Request, principal: Principal = Depends(authenticate)) -> None:
    _check_id(dashboard_id)
    await _pg(request).execute(
        "DELETE FROM dashboards WHERE tenant_id = $1 AND user_id = $2 AND id = $3", principal.tenant_id, principal.user_id, dashboard_id
    )
    await audit.record("dash.delete", dashboard_id, principal=principal)
