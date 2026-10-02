"""Strict schema & truth audit for dashboard specs (zero-hallucination gate).

A dashboard is only "verified" when independent recomputation from the actual data agrees with it:

1. every referenced column exists and has a role that allows the requested aggregation;
2. each chart, recompiled from its own ``spec``, reproduces the shipped numbers;
3. each KPI card equals the aggregate recomputed from the data;
4. every number in the story exists in the fact table.

Nothing here looks at column *names*; roles and aggregation policies come from the profiler.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

import pandas as pd

from src.agents.data_agent import compute
from src.agents.data_agent.charts import ChartContext, ChartSpec, compile_chart
from src.agents.data_agent.insights import Insight
from src.agents.data_agent.profiler import (
    AGG_AVG,
    AGG_SUM,
    ROLE_IDENTIFIER,
    ROLE_RATIO,
    profile_dataframe_universal,
)
from src.agents.data_agent.grounding import numbers_grounded
from src.agents.data_agent.story import evidence_extras, story_is_grounded
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

_REL_TOL = 1e-4
_ABS_TOL = 1e-6


def _close(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), rel_tol=_REL_TOL, abs_tol=_ABS_TOL)


def _suggest(missing: str, columns: list[str], top_k: int = 3) -> list[str]:
    """Closest real column identifiers (bigram overlap) for a column that does not exist."""
    def grams(text: str) -> set[str]:
        text = text.lower().replace("_", "")
        return {text[i : i + 2] for i in range(len(text) - 1)} or {text}

    target = grams(missing)
    scored = sorted(columns, key=lambda c: -(2 * len(target & grams(c)) / (len(target) + len(grams(c)) or 1)))
    return scored[:top_k]


def _profile_from_spec(df: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    labels = {c["field"]: c.get("headerName", c["field"]) for c in (spec.get("table", {}) or {}).get("columns", [])}
    return profile_dataframe_universal(df, labels, (spec.get("analysis") or {}).get("hints"))


def _chart_column_errors(chart: dict[str, Any], df: pd.DataFrame, profile: dict[str, Any], index: int) -> Optional[str]:
    spec = chart.get("spec") or {}
    columns = [spec.get(k) for k in ("dimension", "measure", "x", "y", "color")] + list(spec.get("columns", []))
    for column in filter(None, columns):
        if column not in df.columns:
            return (
                f"Chart #{index} '{chart.get('title')}' uses column '{column}' which does not exist in the dataset. "
                f"Closest real columns: {_suggest(str(column), list(map(str, df.columns)))}."
            )
    measure, agg = spec.get("measure"), spec.get("aggregation", "sum")
    if measure and agg in ("sum", "avg", "median", "min", "max"):
        info = profile["columns"][measure]
        if info["role"] == ROLE_IDENTIFIER:
            return f"Chart #{index} '{chart.get('title')}' applies {agg.upper()} to identifier column '{measure}'; identifiers may only be counted."
        policy = profile["policies"].get(measure, {}).get("agg")
        if agg == "sum" and policy != AGG_SUM:
            kind = "a ratio" if info["role"] == ROLE_RATIO else "not additive"
            return f"Chart #{index} '{chart.get('title')}' sums '{measure}', which is {kind}; use an average instead."
    return None


def _values_match(shipped: list[dict[str, Any]], recomputed: list[dict[str, Any]]) -> Optional[str]:
    if len(shipped) != len(recomputed):
        return f"{len(shipped)} data points shipped but {len(recomputed)} recomputed"
    for a, b in zip(shipped, recomputed):
        for key in ("x", "y", "name", "value", "share", "count", "from", "to"):
            va, vb = a.get(key), b.get(key)
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool):
                if not _close(va, vb):
                    return f"'{key}' differs at {a.get('name', a.get('x'))!r}: shipped {va}, recomputed {vb}"
            elif va != vb:
                return f"'{key}' differs: shipped {va!r}, recomputed {vb!r}"
    return None


def verify_dashboard_spec(df: pd.DataFrame, dashboard_spec: dict[str, Any], profile: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
    """Verify a dashboard spec against the real data. Returns ``(is_verified, feedback)``.

    ``feedback`` on failure names the exact chart/column so a retry (or a human) can repair it.
    """
    if not isinstance(dashboard_spec, dict):
        return True, "VERIFIED: no dashboard spec to check."

    charts = dashboard_spec.get("charts", [])
    kpis = dashboard_spec.get("kpis", []) or dashboard_spec.get("kpiCards", [])
    if not isinstance(charts, list) or not charts or not isinstance(kpis, list) or not kpis:
        return False, (
            "VERIFIER REJECT: the dashboard needs at least one chart and one KPI card. "
            f"Dataset columns: {list(map(str, df.columns))}."
        )

    profile = profile or _profile_from_spec(df, dashboard_spec)
    facts = {f["id"]: Insight.from_dict(f) for f in dashboard_spec.get("facts", [])}
    ctx = ChartContext(df=df, profile=profile, lang=dashboard_spec.get("language", "en"), facts=facts)

    for index, chart in enumerate(charts, start=1):
        problem = _chart_column_errors(chart, df, profile, index)
        if problem:
            return False, f"VERIFIER REJECT: {problem}"

        spec_dict = chart.get("spec")
        if not spec_dict:
            return False, f"VERIFIER REJECT: chart #{index} '{chart.get('title')}' carries no spec, so its numbers cannot be verified."
        recompiled = compile_chart(ChartSpec(**spec_dict), ctx)
        if recompiled is None:
            return False, f"VERIFIER REJECT: chart #{index} '{chart.get('title')}' cannot be reproduced from the data."
        mismatch = _values_match(chart.get("data", []), recompiled["data"])
        if mismatch:
            return False, f"VERIFIER REJECT: chart #{index} '{chart.get('title')}' does not match the data ({mismatch})."
        for row in chart.get("data", []):
            for key in ("y", "value"):
                value = row.get(key)
                if isinstance(value, float) and not math.isfinite(value):
                    return False, f"VERIFIER REJECT: chart #{index} '{chart.get('title')}' contains a non-finite value."
        if chart.get("type") == "donut":
            shares = [r.get("share") for r in chart["data"] if r.get("share") is not None]
            if len(chart["data"]) > 7 or not math.isclose(sum(shares), 1.0, abs_tol=1e-3):
                return False, f"VERIFIER REJECT: donut chart #{index} '{chart.get('title')}' has invalid slices."
        if chart.get("type") in ("line", "area") and [r["x"] for r in chart["data"]] != sorted(r["x"] for r in chart["data"]):
            return False, f"VERIFIER REJECT: time series chart #{index} '{chart.get('title')}' is not in chronological order."

    for card in kpis:
        measure, agg = card.get("measure"), card.get("aggregation")
        if agg is None:
            continue
        if agg == "COUNT":
            expected: Optional[float] = float(len(df))
        elif measure in df.columns:
            expected = compute.aggregate_values(df[measure], agg.lower())
        else:
            return False, f"VERIFIER REJECT: KPI '{card.get('title')}' references column '{measure}' which does not exist."
        if not _close(card.get("raw_value"), expected):
            return False, f"VERIFIER REJECT: KPI '{card.get('title')}' shows {card.get('raw_value')} but the data gives {expected}."

    meta = {"notes": (dashboard_spec.get("analysis") or {}).get("notes", [])}
    story = dashboard_spec.get("story")
    if story:
        grounded, unmatched = story_is_grounded(story, list(facts.values()), profile, meta)
        if not grounded:
            return False, f"VERIFIER REJECT: the story contains numbers that no verified fact supports: {unmatched}."

    extra_numbers, extra_strings = evidence_extras(profile, meta)
    for index, chart in enumerate(charts, start=1):
        grounded, unmatched = numbers_grounded(chart.get("insight") or "", list(facts.values()), extra_numbers, extra_strings)
        if not grounded:
            return False, f"VERIFIER REJECT: the insight of chart #{index} '{chart.get('title')}' contains numbers that no verified fact supports: {unmatched}."

    return True, "VERIFIED: every chart, KPI and story number matches the dataset."


def auto_remediate_chart_specs(df: pd.DataFrame, dashboard_spec: dict[str, Any]) -> dict[str, Any]:
    """Deterministic repair: recompile each chart from its spec (fixing aggregations against the profile)
    and drop charts the data cannot support."""
    if not isinstance(dashboard_spec, dict):
        return dashboard_spec

    profile = _profile_from_spec(df, dashboard_spec)
    facts = {f["id"]: Insight.from_dict(f) for f in dashboard_spec.get("facts", [])}
    ctx = ChartContext(df=df, profile=profile, lang=dashboard_spec.get("language", "en"), facts=facts)

    repaired: list[dict[str, Any]] = []
    for chart in dashboard_spec.get("charts", []):
        spec_dict = dict(chart.get("spec") or {})
        if not spec_dict or any(spec_dict.get(k) not in df.columns for k in ("dimension", "measure", "x", "y") if spec_dict.get(k)):
            continue
        measure = spec_dict.get("measure")
        if measure and spec_dict.get("aggregation") == "sum" and profile["policies"].get(measure, {}).get("agg") != AGG_SUM:
            spec_dict["aggregation"] = "avg" if profile["policies"].get(measure, {}).get("agg") == AGG_AVG else "count"
        rebuilt = compile_chart(ChartSpec(**spec_dict), ctx)
        if rebuilt is not None:
            rebuilt["insight"] = chart.get("insight", "")
            repaired.append(rebuilt)

    return {**dashboard_spec, "charts": repaired}
