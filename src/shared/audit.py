"""Append-only audit trail (table ``audit_log``): who did what to which target, in which tenant, with what outcome.

Written for the actions that matter after the fact: a sensitive operation being requested, approved or rejected and what came
of it, and changes to the knowledge base. The table is append-only in the DATABASE (a trigger refuses UPDATE, DELETE and
TRUNCATE, migration 0006), so a bug or an injected statement in the application cannot rewrite history.

``record(...)`` never raises unless ``required=True``: an approval is only executed after its decision row was written, so
"no audit, no action" holds for the one thing that must not happen unrecorded.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.shared.auth import Principal, current_principal
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

MAX_DETAIL_CHARS: int = 4000

_pg: Any = None


def configure(pg_client: Any) -> None:
    """Called once by the gateway at start-up; until then (unit tests) nothing is written."""
    global _pg
    _pg = pg_client


def _trim(detail: dict[str, Any]) -> str:
    text = json.dumps(detail, ensure_ascii=False, default=str)
    if len(text) <= MAX_DETAIL_CHARS:
        return text
    return json.dumps({"truncated": text[:MAX_DETAIL_CHARS]}, ensure_ascii=False)


async def record(
    action: str,
    target: str = "",
    outcome: str = "ok",
    detail: Optional[dict[str, Any]] = None,
    *,
    principal: Optional[Principal] = None,
    required: bool = False,
) -> bool:
    """Append one row. ``True`` when written; with ``required=True`` a failure raises instead of returning ``False``."""
    who = principal or current_principal()
    actor = who.user_id if who else "system"
    tenant = who.tenant_id if who else ""
    try:
        if _pg is None:
            raise RuntimeError("audit is not configured")
        await _pg.execute(
            "INSERT INTO audit_log (tenant_id, actor, action, target, outcome, detail) VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            tenant, actor, action, target[:200], outcome[:40], _trim(detail or {}),
        )
        return True
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        logger.error("AUDIT WRITE FAILED action=%s actor=%s target=%s: %s", action, actor, target, exc or type(exc).__name__)
        if required:
            raise
        return False
