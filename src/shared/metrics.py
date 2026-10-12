"""Prometheus metrics (``GET /metrics``): how the API behaves (requests, errors, latency) and what the LLM calls cost.

Labels stay low-cardinality on purpose: ``route`` is the route TEMPLATE (``/api/conversations/{conversation_id}``), never the URL
with ids; ``model`` is whatever model names the deployment uses. The default registry also exposes process CPU/memory/GC.
"""

from __future__ import annotations

import time
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

CONTENT_TYPE = CONTENT_TYPE_LATEST

HTTP_REQUESTS = Counter("agent_http_requests_total", "HTTP requests handled", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "agent_http_request_duration_seconds", "Time until the response starts (a stream counts until its first byte)", ["method", "route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
LLM_CALLS = Counter("agent_llm_calls_total", "Finished LLM calls", ["model"])
LLM_TOKENS = Counter("agent_llm_tokens_total", "LLM tokens", ["kind"])
LLM_COST = Counter("agent_llm_cost_usd_total", "Estimated LLM cost in USD (LiteLLM's price table)")


PEV_RUNS = Counter("agent_pev_runs_total", "Finished PEV runs by the agent that answered and whether the Verifier passed the answer", ["agent", "outcome"])
PEV_RETRIES = Counter("agent_pev_retries_total", "Times the Verifier sent an answer back to the Executor", ["agent"])


def record_pev(agent: str, verified: bool, retries: int) -> None:
    """One finished PEV run: who answered, whether it passed, how many times the Executor was sent back."""
    agent = agent or "unknown"
    PEV_RUNS.labels(agent, "verified" if verified else "unverified").inc()
    if retries > 0:
        PEV_RETRIES.labels(agent).inc(retries)


def pev_snapshot() -> list[dict[str, Any]]:
    """Per agent since this process started: runs, how many passed, how many did not, how many retries they took."""
    agents: dict[str, dict[str, int]] = {}
    for family in PEV_RUNS.collect():
        for sample in family.samples:
            if sample.name == "agent_pev_runs_total":
                row = agents.setdefault(sample.labels["agent"], {"verified": 0, "unverified": 0, "retries": 0})
                row[sample.labels["outcome"]] = int(sample.value)
    for family in PEV_RETRIES.collect():
        for sample in family.samples:
            if sample.name == "agent_pev_retries_total":
                agents.setdefault(sample.labels["agent"], {"verified": 0, "unverified": 0, "retries": 0})["retries"] = int(sample.value)
    return [
        {"agent": name, "runs": row["verified"] + row["unverified"], "verified": row["verified"], "unverified": row["unverified"], "retries": row["retries"]}
        for name, row in sorted(agents.items(), key=lambda item: -(item[1]["verified"] + item[1]["unverified"]))
    ]


def record_request(method: str, route: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_LATENCY.labels(method, route).observe(seconds)


def record_llm(event: dict[str, Any]) -> None:
    """One finished LLM call (the same dict ``usage.extract`` builds for the cost report)."""
    LLM_CALLS.labels(event.get("model") or "unknown").inc()
    LLM_TOKENS.labels("prompt").inc(event.get("prompt_tokens") or 0)
    LLM_TOKENS.labels("completion").inc(event.get("completion_tokens") or 0)
    LLM_COST.inc(event.get("cost_usd") or 0.0)


def render() -> bytes:
    return generate_latest()


STARTED_AT: float = time.time()  # this module is imported when the process starts


def snapshot(top: int = 10) -> dict[str, Any]:
    """This process's HTTP numbers since it started, as JSON: ONE replica's counters, not the cluster's (Prometheus adds them up)."""
    by_class = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
    rate_limited = 0
    routes: dict[tuple[str, str], dict[str, float]] = {}
    for family in HTTP_REQUESTS.collect():
        for sample in family.samples:
            if sample.name != "agent_http_requests_total":
                continue
            count, status = int(sample.value), sample.labels["status"]
            by_class[f"{status[:1]}xx"] = by_class.get(f"{status[:1]}xx", 0) + count
            rate_limited += count if status == "429" else 0
            route = routes.setdefault((sample.labels["method"], sample.labels["route"]), {"count": 0, "errors": 0, "seconds": 0.0, "observed": 0})
            route["count"] += count
            route["errors"] += count if status.startswith("5") else 0
    for family in HTTP_LATENCY.collect():
        for sample in family.samples:
            route = routes.get((sample.labels.get("method", ""), sample.labels.get("route", "")))
            if route is None:
                continue
            if sample.name.endswith("_sum"):
                route["seconds"] = sample.value
            elif sample.name.endswith("_count"):
                route["observed"] = sample.value
    total = sum(by_class.values())
    busiest = sorted(routes.items(), key=lambda item: item[1]["count"], reverse=True)[:top]
    return {
        "uptime_seconds": int(time.time() - STARTED_AT),
        "total": total,
        "by_class": by_class,
        "rate_limited": rate_limited,
        "error_rate": round(by_class["5xx"] / total, 4) if total else 0.0,
        "pev": pev_snapshot(),
        "routes": [
            {
                "method": method, "route": route_name, "count": int(data["count"]), "errors": int(data["errors"]),
                "avg_ms": round(data["seconds"] / data["observed"] * 1000) if data["observed"] else 0,
            }
            for (method, route_name), data in busiest
        ],
    }
