"""What each LLM call costs, per user and tenant (table ``usage_events``), for the administration page.

One LiteLLM callback sees every async call whatever code made it (chat, fallback, embedding, data agent), so nothing else has
to be touched. The caller is the ``Principal`` of the request being served (``current_principal``); calls made outside a
request (start-up, ingestion scripts) are recorded for ``system``. Writing never breaks a call: a failure is logged and dropped.

Limits worth knowing: only ASYNC LiteLLM calls are seen (a synchronous ``litellm.completion`` is not), and ``cost_usd`` is
LiteLLM's own estimate (0 for a model it has no price for). ``USAGE_BUDGET_USD_PER_USER_DAY`` only MARKS a user over the
budget in the report; with ``USAGE_BUDGET_HARD`` ``enforce_budget`` also refuses the user's requests until midnight.
"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from typing import Any, Optional

import litellm
from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

from src.config import settings
from src.shared import metrics
from src.shared.auth import current_principal
from src.shared.logger import get_logger
from src.shared.messages import msg

logger: logging.Logger = get_logger(__name__)

_pg: Any = None
# (agent, node, attempt) of the PEV step running now: set by the orchestrator's nodes, read when a call finishes. Each LangGraph node runs in its
# own task context, so a value set inside a node does not leak into the next one.
_attribution: ContextVar[tuple[str, str, int]] = ContextVar("usage_attribution", default=("", "", 0))


def attribute(agent: str = "", node: str = "", attempt: int = 0) -> None:
    """Say which agent / PEV step / attempt the LLM calls that follow (in this context) belong to."""
    _attribution.set((agent[:40], node[:40], max(0, int(attempt))))


def configure(pg_client: Any) -> None:
    """Called once by the gateway at start-up; until then (unit tests, scripts) nothing is written."""
    global _pg
    _pg = pg_client


def extract(kwargs: dict[str, Any], response_obj: Any) -> dict[str, Any]:
    """The row for one finished call: who, which model, how many tokens, what it cost."""
    usage = response_obj.get("usage") if isinstance(response_obj, dict) else getattr(response_obj, "usage", None)

    def count(name: str) -> int:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, 0)
        return int(value or 0)

    logged = kwargs.get("standard_logging_object") or {}
    principal = current_principal()
    agent, node, attempt = _attribution.get()
    explicit = ((kwargs.get("litellm_params") or {}).get("metadata") or {}).get("node")  # a caller that names its own step wins
    return {
        "agent": agent,
        "node": str(explicit or node)[:40],
        "attempt": attempt,
        "tenant_id": principal.tenant_id if principal else "",
        "user_id": principal.user_id if principal else "system",
        "model": str(kwargs.get("model") or logged.get("model") or "")[:120],
        "call_type": str(kwargs.get("call_type") or logged.get("call_type") or "")[:40],
        "prompt_tokens": count("prompt_tokens"),
        "completion_tokens": count("completion_tokens"),
        "cost_usd": float(kwargs.get("response_cost") or logged.get("response_cost") or 0.0),
    }


async def record(event: dict[str, Any]) -> bool:
    if _pg is None:
        return False
    try:
        await _pg.execute(
            "INSERT INTO usage_events (tenant_id, user_id, model, call_type, prompt_tokens, completion_tokens, cost_usd, agent, node, attempt)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
            event["tenant_id"], event["user_id"], event["model"], event["call_type"],
            event["prompt_tokens"], event["completion_tokens"], event["cost_usd"],
            event.get("agent", ""), event.get("node", ""), event.get("attempt", 0),
        )
        return True
    except Exception as exc:  # noqa: BLE001 - a lost usage row must never fail the user's request
        logger.warning("Could not record LLM usage: %s", exc or type(exc).__name__)
        return False


class UsageLogger(CustomLogger):
    async def async_log_success_event(self, kwargs: dict[str, Any], response_obj: Any, start_time: Any, end_time: Any) -> None:
        event = extract(kwargs, response_obj)
        metrics.record_llm(event)  # for Prometheus, whether or not the database is there
        await record(event)


def install() -> None:
    """Register the callback once (idempotent)."""
    if not any(isinstance(c, UsageLogger) for c in litellm.callbacks):
        litellm.callbacks.append(UsageLogger())


_SPENT_CACHE: dict[tuple[str, str], tuple[float, float]] = {}
_SPENT_TTL_SECONDS = 30.0


async def spent_today(pg: Any, tenant_id: str, user_id: str) -> float:
    """What this user's LLM calls cost since midnight (server time zone), cached for a few seconds: the check runs on every request."""
    key = (tenant_id, user_id)
    cached = _SPENT_CACHE.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < _SPENT_TTL_SECONDS:
        return cached[1]
    rows = await pg.fetch(
        "SELECT COALESCE(sum(cost_usd), 0) AS cost FROM usage_events WHERE tenant_id = $1 AND user_id = $2 AND ts >= date_trunc('day', now())",
        tenant_id, user_id,
    )
    spent = float(rows[0]["cost"]) if rows else 0.0
    if len(_SPENT_CACHE) > 5000:
        _SPENT_CACHE.clear()  # bounded: a day's active users, not every user ever
    _SPENT_CACHE[key] = (now, spent)
    return spent


async def enforce_budget(principal: Any) -> None:
    """With ``USAGE_BUDGET_HARD`` and a budget set, refuse (429) a signed-in user who has spent it today. Fails open: a database
    hiccup must not take chat down, and the cost report still shows the overspend."""
    budget = settings.USAGE_BUDGET_USD_PER_USER_DAY
    if not (settings.USAGE_BUDGET_HARD and budget > 0 and _pg is not None and getattr(principal, "authenticated", False)):
        return
    try:
        spent = await spent_today(_pg, principal.tenant_id, principal.user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Budget check skipped: %s", exc or type(exc).__name__)
        return
    if spent >= budget:
        raise HTTPException(status_code=429, detail=msg("budget.exceeded", amount=f"{budget:g}"))


async def summary(pg: Any, days: int, tenant: Optional[str] = None) -> dict[str, Any]:
    """Totals of the last ``days`` days by user, tenant, model and day (of one tenant when given). ``today`` = since midnight (server time zone)."""
    window = "ts >= now() - make_interval(days => $1) AND ($2::text IS NULL OR tenant_id = $2)"
    cost = "COALESCE(sum(cost_usd), 0)"
    tokens = "COALESCE(sum(prompt_tokens + completion_tokens), 0)"
    users = await pg.fetch(
        f"SELECT tenant_id, user_id, count(*) AS calls, {tokens} AS tokens, {cost} AS cost,"
        f" COALESCE(sum(cost_usd) FILTER (WHERE ts >= date_trunc('day', now())), 0) AS today"
        f" FROM usage_events WHERE {window} GROUP BY tenant_id, user_id ORDER BY cost DESC, calls DESC LIMIT 200",
        days, tenant,
    )
    tenants = await pg.fetch(
        f"SELECT tenant_id, count(*) AS calls, {tokens} AS tokens, {cost} AS cost FROM usage_events WHERE {window}"
        f" GROUP BY tenant_id ORDER BY cost DESC, calls DESC LIMIT 100",
        days, tenant,
    )
    models = await pg.fetch(
        f"SELECT model, count(*) AS calls, {tokens} AS tokens, {cost} AS cost FROM usage_events WHERE {window}"
        f" GROUP BY model ORDER BY cost DESC, calls DESC LIMIT 30",
        days, tenant,
    )
    per_day = await pg.fetch(
        f"SELECT date_trunc('day', ts)::date AS day, count(*) AS calls, {tokens} AS tokens, {cost} AS cost FROM usage_events"
        f" WHERE {window} GROUP BY 1 ORDER BY 1",
        days, tenant,
    )
    by_agent = await pg.fetch(
        f"SELECT agent, count(*) AS calls, {tokens} AS tokens, {cost} AS cost,"
        f" COALESCE(sum(cost_usd) FILTER (WHERE attempt > 1), 0) AS retry_cost"
        f" FROM usage_events WHERE {window} AND agent <> '' GROUP BY agent ORDER BY cost DESC, calls DESC LIMIT 30",
        days, tenant,
    )
    by_node = await pg.fetch(
        f"SELECT node, count(*) AS calls, {tokens} AS tokens, {cost} AS cost FROM usage_events WHERE {window} AND node <> ''"
        f" GROUP BY node ORDER BY cost DESC, calls DESC LIMIT 30",
        days, tenant,
    )
    budget: Optional[float] = settings.USAGE_BUDGET_USD_PER_USER_DAY or None

    def row(r: Any) -> dict[str, Any]:
        return {k: (float(v) if k in {"cost", "today", "retry_cost"} else int(v) if k in {"calls", "tokens"} else v) for k, v in dict(r).items()}

    user_rows = [row(r) for r in users]
    for u in user_rows:
        u["over_budget"] = bool(budget and u["today"] >= budget)
    tenant_rows = [row(r) for r in tenants]
    return {
        "days": days,
        "budget_usd_per_user_day": budget,
        "budget_hard": bool(budget and settings.USAGE_BUDGET_HARD),  # the budget blocks, it does not only mark
        "totals": {
            "calls": sum(r["calls"] for r in tenant_rows),
            "tokens": sum(r["tokens"] for r in tenant_rows),
            "cost": sum(r["cost"] for r in tenant_rows),
        },
        "users": user_rows,
        "tenants": tenant_rows,
        "models": [row(r) for r in models],
        "agents": [row(r) for r in by_agent],  # cost per agent; retry_cost = what its re-runs (attempt 2 and later) cost
        "nodes": [row(r) for r in by_node],  # cost per PEV step (planner / executor / verifier / rewriter / quality_review)
        "per_day": [{**row(r), "day": r["day"].isoformat()} for r in per_day],
    }
