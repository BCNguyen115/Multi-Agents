"""What a department may do: which agents its members can use, and whether they may add documents to the knowledge base.

A policy lives in ``department_policies`` (migration 0014), per (tenant, department), with ``department_id = '*'`` as the tenant's default.
Every field falls back separately: a department's own value, else the tenant default, else "no restriction" (every agent; the upload stays
with ``KNOWLEDGE_UPLOAD_ROLES``). Administrators (``ADMIN_ROLES``) are never restricted by a policy: they are the ones who set it.

``resolve`` is read on every authenticated request, so the answer is cached for a few seconds; a change made in the console is seen at once by
the replica that took it and within ``TTL_SECONDS`` by the others. A database failure never locks anybody out (fail open, logged).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

KNOWN_AGENTS: tuple[str, ...] = ("rag_agent", "data_agent", "search_agent", "db_agent", "integration_agent", "coding_agent")
TENANT_DEFAULT = "*"
TTL_SECONDS = 20.0

_pg: Any = None
_cache: dict[tuple[str, str], tuple[float, "Policy"]] = {}


@dataclass(frozen=True)
class Policy:
    """``None`` in a field = no restriction coming from here."""

    allowed_agents: Optional[frozenset[str]] = None
    can_upload_knowledge: Optional[bool] = None


def configure(pg_client: Any) -> None:
    """Called once by the gateway at start-up; until then (unit tests, scripts) nobody is restricted."""
    global _pg
    _pg = pg_client
    _cache.clear()


def invalidate() -> None:
    """Forget what was read (this process only): the next request asks the database again."""
    _cache.clear()


def merge(department: Optional[dict[str, Any]], tenant: Optional[dict[str, Any]]) -> Policy:
    """Field by field: the department's value if it has one, else the tenant default's."""
    def pick(field: str) -> Any:
        for row in (department, tenant):
            if row is not None and row.get(field) is not None:
                return row[field]
        return None

    agents = pick("allowed_agents")
    return Policy(frozenset(agents) if agents is not None else None, pick("can_upload_knowledge"))


async def resolve(tenant_id: str, department_id: str) -> Policy:
    key = (tenant_id, department_id)
    cached = _cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < TTL_SECONDS:
        return cached[1]
    if _pg is None:
        return Policy()
    try:
        rows = await _pg.fetch(
            "SELECT department_id, allowed_agents, can_upload_knowledge FROM department_policies WHERE tenant_id = $1 AND department_id IN ($2, $3)",
            tenant_id, department_id, TENANT_DEFAULT,
        )
    except Exception as exc:  # noqa: BLE001 - fail open: a database hiccup must not take every user's chat down
        logger.warning("Department policy not read: %s", exc or type(exc).__name__)
        return Policy()
    by_department = {r["department_id"]: dict(r) for r in rows}
    policy = merge(by_department.get(department_id) if department_id != TENANT_DEFAULT else None, by_department.get(TENANT_DEFAULT))
    if len(_cache) > 2000:
        _cache.clear()
    _cache[key] = (now, policy)
    return policy
