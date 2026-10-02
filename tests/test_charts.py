"""Chart compilation, planning, KPI cards and query hints."""
import json

import numpy as np
import pandas as pd
import pytest

from src.agents.data_agent.charts import ChartContext, ChartSpec, build_kpis, compile_chart, plan_dashboard, plan_single_chart
from src.agents.data_agent.insights import generate_insights
from src.agents.data_agent.intent import parse_query_hints
from src.agents.data_agent.profiler import profile_dataframe_universal
from tests.test_insights import _planted


@pytest.fixture(scope="module")
def world():
    df = _planted()
    profile = profile_dataframe_universal(df)
    facts = generate_insights(df, profile)
    ctx = ChartContext(df=df, profile=profile, lang="en", facts={f.id: f for f in facts})
    return df, profile, facts, ctx


def _compile(ctx, **kwargs):
    return compile_chart(ChartSpec(id="t", **kwargs), ctx)


def test_trend_is_chronological_and_marks_extremes_and_anomalies(world):
    _, profile, facts, ctx = world
    anomaly = next(f for f in facts if f.kind == "anomaly")
    chart = _compile(ctx, type="area", measure="revenue", aggregation="sum", grain="month", insight_ids=[anomaly.id])
    labels = [d["x"] for d in chart["data"]]
    assert labels == sorted(labels) and len(labels) == 24 and chart["is_temporal"]
    kinds = {h["type"] for h in chart["highlights"]}
    assert {"max", "min", "anomaly"} <= kinds
    assert chart["title"] == "Total revenue by month"


def test_ranking_is_sorted_limited_and_shares_are_consistent(world):
    _, _, _, ctx = world
    chart = _compile(ctx, type="bar", dimension="region", measure="revenue", aggregation="sum", limit=3)
    values = [d["y"] for d in chart["data"]]
    assert values == sorted(values, reverse=True) and len(values) == 3
    assert chart["subtitle"] == "Showing top 3 of 4" and chart["measure"] == "revenue" and chart["aggregation"] == "SUM"


def test_donut_shares_add_up_and_small_slices_become_other(world):
    _, _, _, ctx = world
    chart = _compile(ctx, type="donut", dimension="region", measure="revenue", aggregation="sum")
    assert sum(d["share"] for d in chart["data"]) == pytest.approx(1.0, abs=1e-4)
    many = ctx.df.assign(bucket=np.arange(len(ctx.df)) % 20)
    many_ctx = ChartContext(df=many, profile=profile_dataframe_universal(many), lang="en")
    chart = compile_chart(ChartSpec(id="t", type="donut", dimension="bucket", aggregation="count"), many_ctx)
    assert chart["data"][-1]["name"] == "Other" and len(chart["data"]) == 7


def test_histogram_counts_every_value(world):
    _, _, _, ctx = world
    chart = _compile(ctx, type="histogram", measure="price", aggregation="count")
    assert sum(d["y"] for d in chart["data"]) == len(ctx.df) and 5 <= len(chart["data"]) <= 40


def test_heavy_tailed_histogram_clips_and_says_so(world):
    _, _, _, ctx = world
    chart = _compile(ctx, type="histogram", measure="revenue", aggregation="count")
    assert "extreme values are not drawn" in chart["subtitle"]


def test_scatter_reports_rank_correlation_and_caps_points(world):
    _, _, _, ctx = world
    chart = _compile(ctx, type="scatter", x="price", y="cost")
    assert len(chart["data"]) <= 1500 and chart["meta"]["rho"] > 0.5
    assert "Spearman" in chart["subtitle"] and "Random sample" in chart["subtitle"]


def test_correlation_heatmap_has_unit_diagonal_and_symmetry(world):
    _, profile, _, ctx = world
    cols = (profile["measures"] + profile["ordinal_cols"])[:4]
    chart = _compile(ctx, type="heatmap", columns=cols, aggregation="nunique")
    cells = {(d["x"], d["y"]): d["value"] for d in chart["data"]}
    labels = chart["x_data"]
    assert all(cells[(l, l)] == 1.0 for l in labels)
    assert all(cells[(a, b)] == cells[(b, a)] for a in labels for b in labels)


def test_crosstab_heatmap(world):
    _, _, _, ctx = world
    chart = _compile(ctx, type="heatmap", columns=["region", "channel"], measure="revenue", aggregation="sum")
    assert len(chart["data"]) == 12 and chart["meta"]["kind"] == "crosstab"


def test_waterfall_bridges_start_to_end_exactly(world):
    _, _, facts, ctx = world
    fact = next(f for f in facts if f.kind == "contribution")
    chart = _compile(ctx, type="waterfall", dimension=fact.refs["dimension"], measure="revenue", aggregation="sum", insight_ids=[fact.id])
    start, *deltas, end = chart["data"]
    assert start["value"] + sum(d["value"] for d in deltas) == pytest.approx(end["value"], rel=1e-6)


def test_unsupported_chart_returns_none_instead_of_raising(world):
    _, _, _, ctx = world
    assert _compile(ctx, type="scatter", x="price", y="region") is None  # non-numeric axis
    assert _compile(ctx, type="waterfall", measure="revenue", aggregation="sum") is None  # no evidence fact


def test_planner_builds_a_complete_non_redundant_grid(world):
    _, profile, facts, ctx = world
    specs = plan_dashboard(profile, facts)
    assert 4 <= len(specs) <= 6
    assert len({(s.type, s.dimension, s.measure, s.aggregation, s.x, s.y, tuple(s.columns)) for s in specs}) == len(specs)
    used = 0
    for spec in specs:
        used += spec.col_span
        assert used <= 12
        if used == 12:
            used = 0
    assert used == 0, "the last row must be full"
    types = {s.type for s in specs}
    assert {"area", "donut", "waterfall", "scatter"} <= types
    compiled = [compile_chart(s, ctx) for s in specs]
    assert all(c is not None for c in compiled)
    json.dumps(compiled, allow_nan=False)


def test_averaged_measures_are_never_summed_in_planned_charts():
    rng = np.random.default_rng(2)
    df = pd.DataFrame({"team": rng.choice(list("abcdef"), 400), "score_rating": rng.uniform(1, 10, 400), "city": rng.choice(list("wxyz"), 400)})
    profile = profile_dataframe_universal(df)
    assert profile["policies"]["score_rating"]["agg"] == "avg"
    specs = plan_dashboard(profile, generate_insights(df, profile))
    assert all(s.aggregation != "sum" for s in specs)
    donut = next(s for s in specs if s.type == "donut")
    assert donut.aggregation == "count" and donut.note_measure == "score_rating"
    chart = compile_chart(donut, ChartContext(df=df, profile=profile, lang="en"))
    assert "averaged, not added" in chart["subtitle"]


def test_kpis_carry_period_delta_and_recomputable_definitions(world):
    _, _, facts, ctx = world
    cards = build_kpis(ctx, facts)
    assert cards[0]["aggregation"] == "COUNT" and cards[0]["raw_value"] == len(ctx.df)
    revenue = next(c for c in cards if c["measure"] == "revenue")
    assert revenue["aggregation"] == "SUM" and revenue["delta"]["direction"] in ("up", "down", "flat")
    assert revenue["delta"]["label"].startswith("vs ")
    assert len(cards) <= 4 and all("raw_value" in c for c in cards)


def test_vietnamese_titles_follow_the_language():
    df = _planted()
    profile = profile_dataframe_universal(df)
    ctx = ChartContext(df=df, profile=profile, lang="vi")
    chart = compile_chart(ChartSpec(id="t", type="donut", dimension="region", measure="revenue", aggregation="sum"), ctx)
    assert chart["title"] == "Tỷ trọng revenue theo region"


# ---------------------------------------------------------------- query hints
def test_query_hints_read_chart_type_columns_and_top_n(world):
    _, profile, _, _ = world
    hints = parse_query_hints("Vẽ biểu đồ tròn tỷ trọng revenue theo region, top 5", profile)
    assert hints.chart_type == "donut" and hints.top_n == 5
    assert hints.mentions[:2] == ["revenue", "region"]
    assert parse_query_hints("phân tích tương quan giữa price và cost", profile).chart_type == "scatter"
    assert parse_query_hints("hello", profile).mentions == []


def test_single_chart_plan_honours_the_request(world):
    _, profile, _, ctx = world
    hints = parse_query_hints("scatter price cost", profile)
    (spec,) = plan_single_chart(profile, hints)
    assert (spec.type, spec.x, spec.y, spec.col_span) == ("scatter", "price", "cost", 12)
    assert compile_chart(spec, ctx) is not None
    no_time = {**profile, "time": {"primary": None}}  # a line chart is impossible without a time axis
    (fallback,) = plan_single_chart(no_time, parse_query_hints("line chart", no_time))
    assert fallback.type in ("bar", "horizontal_bar")
