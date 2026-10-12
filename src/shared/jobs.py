"""A small durable job queue on PostgreSQL, for work that should not hold a request open (document ingestion first).

``enqueue`` writes a row; every gateway replica runs ``worker_forever``, which takes one queued row at a time with
``FOR UPDATE SKIP LOCKED`` (two replicas never take the same job) and runs the handler registered for its ``kind`` as the user
who queued it (same tenant and department scope). A job whose worker died is put back after ``JOB_STALE_MINUTES`` (failed after
``JOB_MAX_ATTEMPTS`` tries); a handler that raises fails the job without a retry (its errors are deterministic: a bad file stays bad).
The uploaded bytes are deleted from the row as soon as the job ends, and finished rows are purged after ``JOB_RETENTION_DAYS``.

Not here: scheduling, priorities, per-kind concurrency limits. ``worker_forever`` runs one job at a time per replica.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from src.config import settings
from src.shared.auth import Principal, acting_as
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

Handler = Callable[[dict[str, Any], Optional[bytes]], Awaitable[dict[str, Any]]]
_handlers: dict[str, Handler] = {}


class JobError(Exception):
    """A failure whose message is fit to show the user who queued the job (anything else is reported as a generic failure)."""


def register(kind: str) -> Callable[[Handler], Handler]:
    def decorator(handler: Handler) -> Handler:
        _handlers[kind] = handler
        return handler

    return decorator


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def enqueue(pg: Any, kind: str, principal: Principal, payload: dict[str, Any], data: Optional[bytes] = None) -> str:
    job_id = uuid.uuid4().hex
    await pg.execute(
        "INSERT INTO jobs (id, kind, tenant_id, user_id, department_id, payload, payload_bytes) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)",
        job_id, kind, principal.tenant_id, principal.user_id, principal.department_id, json.dumps(payload), data,
    )
    return job_id


async def claim(pg: Any) -> Optional[dict[str, Any]]:
    rows = await pg.fetch(
        "UPDATE jobs SET status = 'running', started_at = now(), attempts = attempts + 1 WHERE id = ("
        " SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)"
        " RETURNING id, kind, tenant_id, user_id, department_id, payload, payload_bytes"
    )
    if not rows:
        return None
    row = dict(rows[0])
    row["payload"] = _json(row["payload"])
    return row


async def _finish(pg: Any, job_id: str, status: str, result: Optional[dict[str, Any]] = None, error: str = "") -> None:
    await pg.execute(
        "UPDATE jobs SET status = $2, result = $3::jsonb, error = $4, finished_at = now(), payload_bytes = NULL WHERE id = $1",
        job_id, status, json.dumps(result) if result is not None else None, error[:500],
    )


async def run_one(pg: Any) -> bool:
    """Take and run one queued job; ``False`` when there was none."""
    job = await claim(pg)
    if job is None:
        return False
    handler = _handlers.get(job["kind"])
    if handler is None:
        await _finish(pg, job["id"], "failed", error=f"unknown job kind {job['kind']!r}")
        return True
    who = Principal(job["user_id"], job["tenant_id"], job["department_id"], authenticated=True)
    try:
        with acting_as(who):
            result = await handler(job["payload"], job["payload_bytes"])
        await _finish(pg, job["id"], "done", result)
    except JobError as exc:
        await _finish(pg, job["id"], "failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - one bad job must not stop the worker
        logger.error("Job %s (%s) failed: %s", job["id"], job["kind"], exc or type(exc).__name__)
        await _finish(pg, job["id"], "failed", error="The job failed.")
    return True


async def requeue_stale(pg: Any) -> int:
    """Jobs whose worker vanished (crash, restart): queued again, or failed once they have used up their attempts."""
    rows = await pg.fetch(
        "UPDATE jobs SET status = CASE WHEN attempts >= $2 THEN 'failed' ELSE 'queued' END,"
        " error = CASE WHEN attempts >= $2 THEN 'The worker stopped before the job ended.' ELSE error END,"
        " finished_at = CASE WHEN attempts >= $2 THEN now() END,"
        " payload_bytes = CASE WHEN attempts >= $2 THEN NULL ELSE payload_bytes END"
        " WHERE status = 'running' AND started_at < now() - make_interval(mins => $1) RETURNING id",
        settings.JOB_STALE_MINUTES, settings.JOB_MAX_ATTEMPTS,
    )
    return len(rows)


async def purge_finished(pg: Any) -> None:
    await pg.execute("DELETE FROM jobs WHERE finished_at < now() - make_interval(days => $1)", settings.JOB_RETENTION_DAYS)


async def worker_forever(pg: Any) -> None:
    """The loop every replica runs: work while there is work, otherwise sleep ``JOB_POLL_SECONDS``; housekeeping on the side."""
    last_stale = last_purge = 0.0
    while True:
        try:
            now = time.monotonic()
            if now - last_stale > 60:
                last_stale = now
                if await requeue_stale(pg):
                    logger.warning("Put back jobs whose worker stopped")
            if now - last_purge > 3600:
                last_purge = now
                await purge_finished(pg)
            if not await run_one(pg):
                await asyncio.sleep(settings.JOB_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the database being away for a moment must not end the worker
            logger.warning("Job worker error: %s", exc or type(exc).__name__)
            await asyncio.sleep(max(settings.JOB_POLL_SECONDS, 5))
