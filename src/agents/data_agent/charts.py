"""Chart specs, compilation, planning and KPI cards.

- ``ChartSpec``       typed description of one chart (what to aggregate, not what numbers to show)
- ``compile_chart``   the ONLY place chart data is computed; the verifier and the browser re-use its semantics
- ``plan_dashboard``  chooses charts by analytic question (what happened / where / why / related / distribution)
- ``build_kpis``      headline numbers with period-over-period deltas

Nothing here inspects column *names*: choices come from profile roles, aggregation policies and insight facts.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy import stats

from src.agents.data_agent import compute
from src.agents.data_agent.i18n import agg_phrase, format_number, format_pct, grain_word, tr
from src.agents.data_agent.insights import Insight
from src.agents.data_agent.intent import QueryHints
from src.agents.data_agent.profiler import (
    AGG_SUM,
    ROLE_HIGH_CARDINALITY,
    ROLE_IDENTIFIER,
    ROLE_LOW_CARDINALITY,
    ROLE_MEASURE,
    ROLE_ORDINAL,
    ROLE_RATIO,
    UNIT_CURRENCY,
    UNIT_PERCENT,
)
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

ChartType = Literal["line", "area", "bar", "horizontal_bar", "donut", "scatter", "histogram", "heatmap", "treemap", "waterfall"]
Aggregation = Literal["sum", "avg", "median", "min", "max", "count", "nunique"]
Grain = Literal["day", "week", "month", "quarter", "year"]

_FREQ = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
_MAX_POINTS = 1500
_STAT_SAMPLE = 20_000
_DONUT_SLICES = 6
_TREEMAP_ITEMS = 30
_PREFERRED_SPAN = {"line": 8, "area": 8, "donut": 4, "bar": 6, "horizontal_bar": 6, "treemap": 6, "scatter": 6, "histogram": 6, "heatmap": 6, "waterfall": 6}


class ChartSpec(BaseModel):
    """What one chart shows. Numbers never live here — ``compile_chart`` derives them from the data."""

    id: str
    type: ChartType
    dimension: Optional[str] = None
    measure: Optional[str] = None
    aggregation: Aggregation = "sum"
    x: Optional[str] = None
    y: Optional[str] = None
    color: Optional[str] = None
    columns: list[str] = Field(default_factory=list)
    grain: Optional[Grain] = None
    limit: int = 15
    note_measure: Optional[str] = None  # measure that is averaged, shown as record counts here
    insight_ids: list[str] = Field(default_factory=list)
    col_span: int = 6


@dataclass
class ChartContext:
    df: pd.DataFrame
    profile: dict[str, Any]
    lang: str = "en"
    facts: dict[str, Insight] = field(default_factory=dict)

    def label(self, column: Optional[str]) -> str:
        return self.profile["labels"].get(column, column) if column else ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _r(value: Any, digits: int = 6) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if math.isfinite(value) else None


def min_group_size(df: pd.DataFrame, agg: str) -> int:
    """Averaged/median groups smaller than this are hidden (a group of one row is not a ranking)."""
    return max(5, int(0.005 * len(df))) if agg in ("avg", "median") else 1


def _value_format(ctx: ChartContext, measure: Optional[str], agg: str) -> dict[str, Any]:
    if measure is None or agg in ("count", "nunique"):
        return {"format": "plain", "isMonetary": False, "unit": ""}
    kind = ctx.profile["columns"].get(measure, {}).get("unit_kind", "plain")
    return {"format": kind, "isMonetary": kind == UNIT_CURRENCY, "unit": "%" if kind == UNIT_PERCENT else ""}


def _title_measure(ctx: ChartContext, spec: ChartSpec) -> str:
    return agg_phrase(ctx.lang, spec.aggregation, ctx.label(spec.measure))


def _envelope(spec: ChartSpec, ctx: ChartContext, title: str, subtitle: str, data: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    chart = {
        "id": spec.id,
        "type": spec.type,
        "title": title,
        "subtitle": subtitle,
        "dimension": spec.dimension,
        "measure": spec.measure or "count",
        "aggregation": spec.aggregation.upper(),
        "grain": spec.grain,
        "limit": spec.limit,
        "min_group": min_group_size(ctx.df, spec.aggregation),
        "is_temporal": spec.type in ("line", "area"),
        "col_span": spec.col_span,
        "fact_ids": spec.insight_ids,
        "insight": "",
        "highlights": [],
        "data": data,
        "spec": spec.model_dump(exclude_none=True),
        **_value_format(ctx, spec.measure, spec.aggregation),
    }
    chart.update(extra)
    return chart


def _subtitle(*parts: str) -> str:
    return " · ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Compilers
# ---------------------------------------------------------------------------


def _compile_trend(spec: ChartSpec, ctx: ChartContext) -> Optional[dict[str, Any]]:
    time = ctx.profile["time"]
    freq = _FREQ[spec.grain] if spec.grain else time["freq"]
    grain = spec.grain or time["grain"]
    raw = compute.period_series(ctx.df, time["primary"], spec.measure, spec.aggregation, freq)
    series = compute.trim_partial(raw, additive=spec.aggregation in ("sum", "count"))
    if len(series) < 2:
        return None
    dropped = raw.loc[~raw["label"].isin(series["label"]), "label"].tolist()
    data = [{"x": row.label, "y": _r(row.value), "name": row.label, "value": _r(row.value)} for row in series.itertuples()]

    highlights: list[dict[str, Any]] = []
    if len(series) >= 4:
        top, bottom = series["value"].idxmax(), series["value"].idxmin()
        highlights += [
            {"type": "max", "x": series["label"][top], "y": _r(series["value"][top])},
            {"type": "min", "x": series["label"][bottom], "y": _r(series["value"][bottom])},
        ]
    labels = set(series["label"])
    for fact_id in spec.insight_ids:
        fact = ctx.facts.get(fact_id)
        if fact and fact.kind == "anomaly":
            highlights += [{"type": "anomaly", "x": p["period"], "y": p["value"]} for p in fact.numbers["points"] if p["period"] in labels]

    title = tr(ctx.lang, "chart.trend", am=_title_measure(ctx, spec), grain=grain_word(ctx.lang, grain))
    subtitle = tr(ctx.lang, "sub.partial", periods=", ".join(dropped)) if dropped else ""
    return _envelope(spec, ctx, title, subtitle, data, grain=grain, sort="chronological", x_data=[d["x"] for d in data], highlights=highlights)


def _compile_rank(spec: ChartSpec, ctx: ChartContext) -> Optional[dict[str, Any]]:
    agg = spec.aggregation
    min_group = min_group_size(ctx.df, agg)
    grouped = compute.group_aggregate(ctx.df, spec.dimension, spec.measure if agg != "count" else None, agg, min_group=min_group)
    if grouped.empty:
        return None
    shown = grouped.head(spec.limit)
    total = float(grouped["value"].sum()) if agg in ("sum", "count") else None
    data = [
        {"x": r.name, "y": _r(r.value), "name": r.name, "value": _r(r.value), "count": int(r.count), "share": _r(r.value / total) if total else None}
        for r in shown.itertuples()
    ]
    hidden = int(ctx.df[spec.dimension].nunique()) - len(grouped)
    subtitle = _subtitle(
        tr(ctx.lang, "sub.top_of", shown=len(shown), total=len(grouped)) if len(grouped) > len(shown) else "",
        tr(ctx.lang, "sub.min_group", n=min_group) if agg in ("avg", "median") and hidden > 0 else "",
    )
    key = "chart.rank" if spec.type == "horizontal_bar" or len(grouped) > len(shown) else "chart.compare"
    title = tr(ctx.lang, key, n=len(shown), dim=ctx.label(spec.dimension), am=_title_measure(ctx, spec))
    return _envelope(spec, ctx, title, subtitle, data, sort="desc", x_data=[d["x"] for d in data], total_groups=len(grouped))


def _compile_share(spec: ChartSpec, ctx: ChartContext) -> Optional[dict[str, Any]]:
    """Donut / treemap: share of a total (sum) or of the records (count) by category."""
    basis_sum = spec.aggregation == "sum" and spec.measure is not None
    grouped = compute.group_aggregate(ctx.df, spec.dimension, spec.measure if basis_sum else None, "sum" if basis_sum else "count")
    grouped = grouped[grouped["value"] > 0]
    if len(grouped) < 2:
        return None
    total = float(grouped["value"].sum())
    limit = _DONUT_SLICES if spec.type == "donut" else _TREEMAP_ITEMS
    head = grouped.head(limit)
    rows = [{"name": r.name, "value": _r(r.value), "share": _r(r.value / total)} for r in head.itertuples()]
    rest = float(grouped["value"].iloc[limit:].sum())
    if rest > 0 and spec.type == "donut":
        rows.append({"name": tr(ctx.lang, "other"), "value": _r(rest), "share": _r(rest / total)})

    if spec.type == "treemap":
        title = tr(ctx.lang, "chart.treemap", m=ctx.label(spec.measure) if basis_sum else tr(ctx.lang, "records").lower(), dim=ctx.label(spec.dimension))
    else:
        title = tr(ctx.lang, "chart.share" if basis_sum else "chart.share_count", m=ctx.label(spec.measure), dim=ctx.label(spec.dimension))
    subtitle = tr(ctx.lang, "sub.count_basis", m=ctx.label(spec.note_measure)) if spec.note_measure else ""
    return _envelope(spec, ctx, title, subtitle, rows, sort="desc", total=_r(total))


def _compile_histogram(spec: ChartSpec, ctx: ChartContext) -> Optional[dict[str, Any]]:
    values = compute.as_numeric(ctx.df[spec.measure]).dropna()
    if len(values) < 10 or values.nunique() < 2:
        return None
    clipped = 0
    shown = values
    if abs(float(values.skew())) > 2 and len(values) >= 100:
        low, high = float(values.quantile(0.005)), float(values.quantile(0.995))
        shown = values[(values >= low) & (values <= high)]
        clipped = len(values) - len(shown)
    if shown.nunique() < 2:
        return None
    edges = np.histogram_bin_edges(shown, bins="fd")
    bins = len(edges) - 1
    if bins > 40 or bins < 5:
        edges = np.histogram_bin_edges(shown, bins=30 if bins > 40 else 10)
    counts, edges = np.histogram(shown, bins=edges)
    data = [
        {"x": f"{format_number(a)}–{format_number(b)}", "y": int(c), "value": int(c), "name": f"{format_number(a)}–{format_number(b)}", "from": _r(a), "to": _r(b)}
        for c, a, b in zip(counts, edges[:-1], edges[1:])
    ]
    title = tr(ctx.lang, "chart.hist", m=ctx.label(spec.measure))
    subtitle = tr(ctx.lang, "sub.clipped", n=clipped) if clipped else ""
    return _envelope(spec, ctx, title, subtitle, data, aggregation="COUNT", x_data=[d["x"] for d in data],
                     meta={"n": len(values), "median": _r(values.median()), "mean": _r(values.mean())})


def _compile_scatter(spec: ChartSpec, ctx: ChartContext) -> Optional[dict[str, Any]]:
    columns = [spec.x, spec.y] + ([spec.color] if spec.color else [])
    pair = ctx.df[columns].copy()
    pair[spec.x], pair[spec.y] = compute.as_numeric(pair[spec.x]), compute.as_numeric(pair[spec.y])
    pair = pair.dropna(subset=[spec.x, spec.y])
    if len(pair) < 20:
        return None
    basis = pair if len(pair) <= _STAT_SAMPLE else pair.sample(n=_STAT_SAMPLE, random_state=0)
    rho = stats.spearmanr(basis[spec.x], basis[spec.y])[0]
    points = pair if len(pair) <= _MAX_POINTS else pair.sample(n=_MAX_POINTS, random_state=0)
    data = [{"x": _r(r[0]), "y": _r(r[1]), "name": str(r[2]) if spec.color else None} for r in points[columns].itertuples(index=False)]
    slope, intercept = stats.theilslopes(points[spec.y], points[spec.x])[:2]
    subtitle = _subtitle(
        tr(ctx.lang, "sub.rho", rho=format_number(_r(rho, 3)), n=len(pair)) if math.isfinite(rho) else "",
        tr(ctx.lang, "sub.sample_points", shown=len(points), total=len(pair)) if len(pair) > len(points) else "",
    )
    return _envelope(spec, ctx, tr(ctx.lang, "chart.scatter", x=ctx.label(spec.x), y=ctx.label(spec.y)), subtitle, data,
                     aggregation="NONE", measure=spec.y, dimension=spec.x,
                     meta={"x_label": ctx.label(spec.x), "y_label": ctx.label(spec.y), "rho": _r(rho, 4), "n": len(pair),
                           "trend_line": {"slope": _r(slope), "intercept": _r(intercept)}})


def _compile_heatmap(spec: ChartSpec, ctx: ChartContext) -> Optional[dict[str, Any]]:
    if spec.aggregation == "nunique" or not spec.measure:  # correlation matrix of numeric columns
        cols = [c for c in spec.columns if c in ctx.df.columns][:8]
        if len(cols) < 3:
            return None
        frame = ctx.df[cols] if len(ctx.df) <= _STAT_SAMPLE else ctx.df[cols].sample(n=_STAT_SAMPLE, random_state=0)
        corr = frame.apply(compute.as_numeric).corr(method="spearman", min_periods=20)
        labels = [ctx.label(c) for c in cols]
        data = [{"x": labels[j], "y": labels[i], "value": _r(corr.iloc[i, j], 4)} for i in range(len(cols)) for j in range(len(cols)) if math.isfinite(corr.iloc[i, j])]
        return _envelope(spec, ctx, tr(ctx.lang, "chart.corr"), "Spearman ρ", data, aggregation="CORR", measure="correlation",
                         x_data=labels, y_data=labels, meta={"kind": "correlation", "min": -1, "max": 1})

    row_dim, col_dim = spec.columns[:2]
    frame = pd.DataFrame({"a": ctx.df[row_dim].astype("string"), "b": ctx.df[col_dim].astype("string"), "v": compute.as_numeric(ctx.df[spec.measure])})
    frame = frame.dropna(subset=["a", "b"])
    keep_a, keep_b = frame["a"].value_counts().head(8).index, frame["b"].value_counts().head(8).index
    frame = frame[frame["a"].isin(keep_a) & frame["b"].isin(keep_b)]
    if frame.empty:
        return None
    grouped = frame.groupby(["a", "b"])["v"]
    table = grouped.size() if spec.aggregation == "count" else grouped.agg({"sum": "sum", "avg": "mean", "median": "median"}[spec.aggregation])
    data = [{"x": str(b), "y": str(a), "value": _r(v)} for (a, b), v in table.dropna().items()]
    title = tr(ctx.lang, "chart.crosstab", a=ctx.label(row_dim), b=ctx.label(col_dim))
    return _envelope(spec, ctx, title, _title_measure(ctx, spec), data,
                     x_data=[str(v) for v in keep_b], y_data=[str(v) for v in keep_a], meta={"kind": "crosstab"})


def _compile_waterfall(spec: ChartSpec, ctx: ChartContext) -> Optional[dict[str, Any]]:
    fact = ctx.facts.get(spec.insight_ids[0]) if spec.insight_ids else None
    if fact is None or fact.kind != "contribution":
        return None
    n = fact.numbers
    rows = [{"name": n["from_period"], "value": n["from_total"], "kind": "total"}]
    shown = 0.0
    for contributor in n["contributors"]:
        rows.append({"name": contributor["name"], "value": contributor["delta"], "kind": "delta"})
        shown += contributor["delta"]
    rest = n["delta"] - shown
    if abs(rest) > 1e-9 * max(abs(n["delta"]), 1.0):
        rows.append({"name": tr(ctx.lang, "other"), "value": _r(rest), "kind": "delta"})
    rows.append({"name": n["to_period"], "value": n["to_total"], "kind": "total"})
    title = tr(ctx.lang, "chart.waterfall", m=ctx.label(spec.measure), p0=n["from_period"], p1=n["to_period"])
    subtitle = tr(ctx.lang, "sub.change", delta=format_number(n["delta"]), pct=format_pct(n["delta_pct"], signed=True))
    return _envelope(spec, ctx, title, subtitle, rows, grain=n["grain"], x_data=[r["name"] for r in rows])


_COMPILERS = {
    "line": _compile_trend, "area": _compile_trend,
    "bar": _compile_rank, "horizontal_bar": _compile_rank,
    "donut": _compile_share, "treemap": _compile_share,
    "histogram": _compile_histogram, "scatter": _compile_scatter,
    "heatmap": _compile_heatmap, "waterfall": _compile_waterfall,
}


def compile_chart(spec: ChartSpec, ctx: ChartContext) -> Optional[dict[str, Any]]:
    """Compute one chart from its spec; ``None`` when the data cannot support it."""
    try:
        return _COMPILERS[spec.type](spec, ctx)
    except Exception as exc:  # noqa: BLE001 - one broken chart must not sink the dashboard
        logger.warning("Chart '%s' (%s) skipped: %s", spec.id, spec.type, exc)
        return None


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

_NUMERIC_ROLES = (ROLE_MEASURE, ROLE_RATIO, ROLE_ORDINAL)


def _agg_of(profile: dict[str, Any], measure: Optional[str]) -> str:
    if measure is None:
        return "count"
    return "sum" if profile["policies"].get(measure, {}).get("agg") == AGG_SUM else "avg"


def _usable_dims(profile: dict[str, Any]) -> list[str]:
    return [d for d in profile["dimensions"] if profile["columns"][d]["role"] != ROLE_IDENTIFIER and 2 <= profile["columns"][d]["nunique"] <= 200]


def _pack_layout(specs: list[ChartSpec]) -> None:
    """Assign col_spans so every row of the 12-column grid is exactly full."""
    row: list[ChartSpec] = []
    used = 0
    for spec in specs:
        span = _PREFERRED_SPAN[spec.type]
        if used + span > 12:
            row[-1].col_span += 12 - used
            row, used = [], 0
        spec.col_span = span
        row.append(spec)
        used += span
        if used == 12:
            row, used = [], 0
    if row and used < 12:
        row[-1].col_span += 12 - used


def _fact_ids(facts: list[Insight], kinds: tuple[str, ...], **refs: Any) -> list[str]:
    return [f.id for f in facts if f.kind in kinds and all(f.refs.get(k) == v for k, v in refs.items())]


def plan_dashboard(profile: dict[str, Any], facts: list[Insight], hints: Optional[QueryHints] = None, max_charts: int = 6) -> list[ChartSpec]:
    """Choose charts by analytic question, avoiding redundant charts (same type + columns)."""
    hints = hints or QueryHints()
    columns = profile["columns"]
    specs: list[ChartSpec] = []
    seen: set[tuple[Any, ...]] = set()

    def add(spec: ChartSpec) -> bool:
        key = (spec.type, spec.dimension, spec.measure, spec.aggregation, spec.x, spec.y, tuple(spec.columns))
        if key in seen or len(specs) >= max_charts:
            return False
        seen.add(key)
        spec.id = f"chart_{len(specs) + 1}_{spec.type}"
        specs.append(spec)
        return True

    numeric = profile["measures"] + profile["ratio_cols"] + profile["ordinal_cols"]
    measure = hints.pick(profile, _NUMERIC_ROLES) or (profile["measures"][0] if profile["measures"] else (numeric[0] if numeric else None))
    agg = _agg_of(profile, measure)
    dims = _usable_dims(profile)
    hinted_dim = hints.pick(profile, (ROLE_LOW_CARDINALITY, ROLE_HIGH_CARDINALITY, ROLE_ORDINAL))
    if hinted_dim in dims:
        dims.insert(0, dims.pop(dims.index(hinted_dim)))
    low = [d for d in dims if columns[d]["nunique"] <= 7]
    high = [d for d in dims if columns[d]["nunique"] > 7]
    limit = hints.top_n or 12

    # 1. What happened?
    if profile["time"].get("primary"):
        ids = _fact_ids(facts, ("trend", "period_change", "anomaly"), measure=measure)
        add(ChartSpec(id="", type="area" if agg in ("sum", "count") else "line", measure=measure, aggregation=agg, grain=profile["time"]["grain"], insight_ids=ids))

    # 2. Where / who?  (composition of a total, or of the records when the measure is averaged)
    share_dim = next((d for d in low), None) or next((d for d in dims if columns[d]["nunique"] <= 12), None)
    if share_dim:
        basis_sum = agg == "sum"
        add(ChartSpec(id="", type="donut", dimension=share_dim, measure=measure if basis_sum else None, aggregation="sum" if basis_sum else "count",
                      note_measure=None if basis_sum else measure, insight_ids=_fact_ids(facts, ("composition",), dimension=share_dim)))
    rank_dim = next((d for d in high if d != share_dim), None) or next((d for d in dims if d != share_dim), None)
    if rank_dim and (measure or hints.chart_type):
        many = columns[rank_dim]["nunique"] > 12
        add(ChartSpec(id="", type="horizontal_bar" if many else "bar", dimension=rank_dim, measure=measure, aggregation=agg, limit=limit,
                      insight_ids=_fact_ids(facts, ("ranking",), dimension=rank_dim, measure=measure)))

    # 3. Why?  (what drove the last change, else where groups genuinely differ)
    contributions = [f for f in facts if f.kind == "contribution" and f.refs.get("measure") == measure]
    if contributions:
        best = contributions[0]
        add(ChartSpec(id="", type="waterfall", dimension=best.refs["dimension"], measure=measure, aggregation="sum", insight_ids=[best.id]))
    else:
        for fact in (f for f in facts if f.kind == "group_difference"):
            add(ChartSpec(id="", type="bar", dimension=fact.refs["dimension"], measure=fact.refs["measure"], aggregation="avg", limit=limit, insight_ids=[fact.id]))
            break

    # 4. What is related?
    correlations = [f for f in facts if f.kind == "correlation"]
    if correlations:
        best = correlations[0]
        add(ChartSpec(id="", type="scatter", x=best.refs["a"], y=best.refs["b"], color=next((d for d in low), None), insight_ids=[best.id]))
    if len(numeric) >= 4 and correlations:
        add(ChartSpec(id="", type="heatmap", columns=numeric[:8], aggregation="nunique", insight_ids=[f.id for f in correlations]))

    # 5. How is it distributed?
    dist = [f for f in facts if f.kind == "distribution"]
    hist_measure = dist[0].refs["measure"] if dist else (measure if measure in profile["measures"] else None)
    if hist_measure and len(specs) < max_charts:
        add(ChartSpec(id="", type="histogram", measure=hist_measure, aggregation="count", insight_ids=[f.id for f in dist if f.refs["measure"] == hist_measure]))

    # 6. Fill remaining slots with the most informative extras
    if len(specs) < max_charts and agg == "sum":
        tree_dim = next((d for d in dims if columns[d]["nunique"] >= 15), None)
        if tree_dim:
            add(ChartSpec(id="", type="treemap", dimension=tree_dim, measure=measure, aggregation="sum"))
    if len(specs) < max_charts:
        pair = [d for d in dims if columns[d]["nunique"] <= 10][:2]
        if len(pair) == 2:
            add(ChartSpec(id="", type="heatmap", columns=pair, measure=measure, aggregation=agg))
    if len(specs) < 3:  # tiny/odd datasets: at least show category counts
        for dim in dims:
            add(ChartSpec(id="", type="bar", dimension=dim, aggregation="count", limit=limit))
            if len(specs) >= 3:
                break

    _pack_layout(specs)
    return specs


def plan_single_chart(profile: dict[str, Any], hints: QueryHints) -> list[ChartSpec]:
    """One chart of the requested type built from the mentioned (or best) columns."""
    columns = profile["columns"]
    numeric = profile["measures"] + profile["ratio_cols"] + profile["ordinal_cols"]
    measure = hints.pick(profile, _NUMERIC_ROLES) or (profile["measures"][0] if profile["measures"] else (numeric[0] if numeric else None))
    agg = _agg_of(profile, measure)
    dims = _usable_dims(profile)
    dim = hints.pick(profile, (ROLE_LOW_CARDINALITY, ROLE_HIGH_CARDINALITY, ROLE_ORDINAL))
    dim = dim if dim in dims else (dims[0] if dims else None)
    kind = hints.chart_type or ("area" if profile["time"].get("primary") else "bar")
    limit = hints.top_n or 12

    spec: Optional[ChartSpec] = None
    if kind in ("line", "area") and profile["time"].get("primary"):
        spec = ChartSpec(id="chart_1", type=kind, measure=measure, aggregation=agg, grain=profile["time"]["grain"])
    elif kind in ("donut", "treemap") and dim:
        spec = ChartSpec(id="chart_1", type=kind, dimension=dim, measure=measure if agg == "sum" else None, aggregation="sum" if agg == "sum" else "count", note_measure=None if agg == "sum" else measure)
    elif kind == "scatter" and len(numeric) >= 2:
        mentioned = [c for c in hints.mentions if c in numeric]
        x, y = (mentioned + [c for c in numeric if c not in mentioned])[:2]
        spec = ChartSpec(id="chart_1", type="scatter", x=x, y=y)
    elif kind == "histogram" and measure:
        spec = ChartSpec(id="chart_1", type="histogram", measure=measure, aggregation="count")
    elif kind == "heatmap" and len(numeric) >= 3:
        spec = ChartSpec(id="chart_1", type="heatmap", columns=numeric[:8], aggregation="nunique")
    if spec is None and dim:  # requested type not possible with this data: fall back to a ranking
        spec = ChartSpec(id="chart_1", type="horizontal_bar" if columns[dim]["nunique"] > 12 else "bar", dimension=dim, measure=measure, aggregation=agg if measure else "count", limit=limit)
    if spec is None:
        return []
    spec.col_span = 12
    return [spec]


# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------


def _kpi(kpi_id: str, title: str, raw: Optional[float], kind: str, subtitle: str = "", icon: str = "Hash", **extra: Any) -> dict[str, Any]:
    return {"id": kpi_id, "title": title, "value": format_number(raw), "raw_value": _r(raw), "type": kind, "unit": "%" if kind == "percent" else "",
            "subtitle": subtitle, "icon": icon, "delta": None, "measure": None, "aggregation": None, **extra}


def build_kpis(ctx: ChartContext, facts: list[Insight], max_cards: int = 4, focus: Optional[str] = None) -> list[dict[str, Any]]:
    """Headline numbers: records, the main measure (total or average per its policy) with a period delta, and context.

    ``focus`` is a numeric column the user asked about; it leads the measure cards."""
    df, profile, lang = ctx.df, ctx.profile, ctx.lang
    cards = [_kpi("kpi_records", tr(lang, "kpi.records"), float(len(df)), "count", tr(lang, "kpi.records_sub", n=format_number(float(len(df)))), "Database", aggregation="COUNT")]

    def measure_card(measure: str, index: int) -> dict[str, Any]:
        info = profile["columns"][measure]
        values = compute.as_numeric(df[measure]).dropna()
        additive = _agg_of(profile, measure) == "sum"
        kind = "currency" if info["unit_kind"] == UNIT_CURRENCY else ("percent" if info["unit_kind"] == UNIT_PERCENT else "number")
        title_key, value = ("kpi.total", float(values.sum())) if additive else ("kpi.avg", float(values.mean()))
        card = _kpi(f"kpi_{index}_{'sum' if additive else 'avg'}", tr(lang, title_key, m=ctx.label(measure)), value, kind,
                    tr(lang, "kpi.median_sub", v=format_number(float(values.median()))), "TrendingUp",
                    measure=measure, aggregation="SUM" if additive else "AVG")
        change = next((f for f in facts if f.kind == "period_change" and f.refs.get("measure") == measure), None)
        if change and change.numbers.get("delta_pct") is not None:
            pct = change.numbers["delta_pct"]
            card["delta"] = {"pct": _r(pct, 4), "direction": "up" if pct > 0.005 else ("down" if pct < -0.005 else "flat"),
                             "label": tr(lang, "kpi.vs_prev", period=change.numbers["prev_period"]), "period": change.numbers["last_period"]}
        return card

    measures = profile["measures"] or profile["ratio_cols"] or profile["ordinal_cols"]
    if focus in profile["policies"]:
        measures = [focus] + [m for m in measures if m != focus]
    if measures:
        cards.append(measure_card(measures[0], 1))
        if len(cards) < max_cards and _agg_of(profile, measures[0]) == "sum":
            values = compute.as_numeric(df[measures[0]]).dropna()
            kind = "currency" if profile["columns"][measures[0]]["unit_kind"] == UNIT_CURRENCY else "number"
            cards.append(_kpi("kpi_1_avg", tr(lang, "kpi.avg", m=ctx.label(measures[0])), float(values.mean()), kind,
                              tr(lang, "kpi.median_sub", v=format_number(float(values.median()))), "Hash", measure=measures[0], aggregation="AVG"))
        elif len(measures) > 1:
            cards.append(measure_card(measures[1], 2))

    entity = next((d for d in _usable_dims(profile) if profile["columns"][d]["nunique"] >= 8 and profile["role_map"][d] in (ROLE_LOW_CARDINALITY, ROLE_HIGH_CARDINALITY)), None)
    if entity and len(cards) < max_cards:
        cards.append(_kpi("kpi_entity", tr(lang, "kpi.distinct", d=ctx.label(entity)), float(profile["columns"][entity]["nunique"]), "count",
                          tr(lang, "kpi.distinct_sub", d=ctx.label(entity)), "Layers", measure=entity, aggregation="NUNIQUE"))
    if profile["time"].get("primary") and len(cards) < max_cards:
        span = profile["time"]
        card = _kpi("kpi_time", tr(lang, "kpi.range"), float(span["span_days"]), "text", f"{span['min']} → {span['max']}", "Calendar")
        card["value"] = f"{span['min']} → {span['max']}"
        cards.append(card)
    return cards[:max_cards]
