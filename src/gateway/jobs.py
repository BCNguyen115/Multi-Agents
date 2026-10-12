"""Status of queued jobs (``GET /api/jobs/{id}``): only the user who queued a job can read it."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.shared.auth import Principal, authenticate
from src.shared.messages import msg

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobStatus(BaseModel):
    id: str
    kind: str
    status: str  # queued | running | done | failed
    result: Optional[dict[str, Any]] = None
    error: str = ""
    created_at: datetime
    finished_at: Optional[datetime] = None


@router.get("/{job_id}", response_model=JobStatus, summary="Where a queued job stands (its result when done, the reason when failed)")
async def job_status(job_id: str, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    if not ID_PATTERN.match(job_id):
        raise HTTPException(status_code=422, detail=msg("job.bad_id"))
    pg = getattr(request.app.state, "pg_client", None)
    if pg is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    rows = await pg.fetch(
        "SELECT id, kind, status, result, error, created_at, finished_at FROM jobs WHERE id = $1 AND tenant_id = $2 AND user_id = $3",
        job_id, principal.tenant_id, principal.user_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail=msg("job.not_found"))
    row = dict(rows[0])
    if isinstance(row["result"], str):
        row["result"] = json.loads(row["result"])
    return row
