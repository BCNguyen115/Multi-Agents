"""The verifier recomputes every chart, KPI and insight from the data: nothing a spec claims is taken on trust."""
import copy

import pandas as pd
import pytest

from src.agents.data_agent.charts import ChartContext, ChartSpec, build_kpis, compile_chart
from src.agents.data_agent.profiler import profile_dataframe_universal
from src.orchestrator.verifier import auto_remediate_chart_specs, verify_dashboard_spec

VERIFIED = "VERIFIED"


@pytest.fixture()
def df() -> pd.DataFrame:
    return pd.DataFrame({
        "order_id": range(1001, 1013),
        "customer_id": [501, 502, 503, 504, 505, 506, 507, 508, 509, 510, 511, 512],
        "quantity": [2, 5, 1, 3, 4, 2, 6, 3, 2, 5, 1, 4],
        "unit_price": [10.0, 20.0, 15.0, 30.0, 25.0, 12.0, 18.0, 22.0, 16.0, 28.0, 11.0, 24.0],
        "revenue": [20.0, 100.0, 15.0, 90.0, 100.0, 24.0, 108.0, 66.0, 32.0, 140.0, 11.0, 96.0],
        "order_date": pd.date_range("2024-01-01", periods=12, freq="MS"),
        "category": ["Electronics", "Fashion", "Home"] * 4,
    })


def _spec(df: pd.DataFrame, *chart_specs: ChartSpec) -> dict:
    profile = profile_dataframe_universal(df)
    ctx = ChartContext(df=df, profile=profile, lang="en")
    return {
        "language": "en",
        "kpis": build_kpis(ctx, []),
        "charts": [compile_chart(spec, ctx) for spec in chart_specs],
        "table": {"columns": [{"field": c, "headerName": c} for c in df.columns]},
    }


def _bar(**kw) -> ChartSpec:
    return ChartSpec(id="c1", type="bar", dimension="category", measure="revenue", aggregation="sum", **kw)


def test_honest_spec_is_verified(df):
    ok, msg = verify_dashboard_spec(df, _spec(df, _bar(), ChartSpec(id="c2", type="area", measure="revenue", aggregation="sum", grain="month")))
    assert ok and msg.startswith(VERIFIED)


def test_changed_chart_value_is_rejected_with_the_offending_point(df):
    spec = _spec(df, _bar())
    spec["charts"][0]["data"][0]["y"] += 5
    ok, msg = verify_dashboard_spec(df, spec)
    assert not ok and "does not match the data" in msg


def test_forged_kpi_is_rejected(df):
    spec = _spec(df, _bar())
    spec["kpis"][0]["raw_value"] = 999
    ok, msg = verify_dashboard_spec(df, spec)
    assert not ok and "KPI" in msg


def test_summing_an_identifier_is_rejected_and_named(df):
    spec = _spec(df, _bar())
    spec["charts"][0]["spec"] = {**spec["charts"][0]["spec"], "measure": "customer_id"}
    ok, msg = verify_dashboard_spec(df, spec)
    assert not ok and "customer_id" in msg and "identifier" in msg


def test_summing_a_ratio_or_price_is_rejected(df):
    spec = _spec(df, _bar())
    spec["charts"][0]["spec"] = {**spec["charts"][0]["spec"], "measure": "unit_price"}
    ok, msg = verify_dashboard_spec(df, spec)
    assert not ok and "not additive" in msg and "average" in msg


def test_invented_column_is_rejected_with_the_closest_real_ones(df):
    spec = _spec(df, _bar())
    spec["charts"][0]["spec"] = {**spec["charts"][0]["spec"], "dimension": "categry"}
    ok, msg = verify_dashboard_spec(df, spec)
    assert not ok and "does not exist" in msg and "category" in msg


def test_chart_without_a_spec_cannot_be_verified(df):
    spec = _spec(df, _bar())
    del spec["charts"][0]["spec"]
    ok, msg = verify_dashboard_spec(df, spec)
    assert not ok and "carries no spec" in msg


def test_unordered_time_series_is_rejected(df):
    spec = _spec(df, ChartSpec(id="c2", type="area", measure="revenue", aggregation="sum", grain="month"))
    spec["charts"][0]["data"].reverse()
    ok, _ = verify_dashboard_spec(df, spec)
    assert not ok


def test_dashboard_needs_charts_and_kpis(df):
    ok, msg = verify_dashboard_spec(df, {"charts": [], "kpis": []})
    assert not ok and "at least one chart" in msg


def test_insight_and_story_numbers_must_come_from_facts(df):
    spec = _spec(df, _bar())
    spec["charts"][0]["insight"] = "Revenue grew 4321% last month."
    ok, msg = verify_dashboard_spec(df, spec)
    assert not ok and "insight of chart #1" in msg and "4321" in msg


def test_remediation_repairs_an_illegal_aggregation_and_the_result_verifies(df):
    df = pd.concat([df] * 3, ignore_index=True).assign(order_id=range(36))  # averaged groups need >= 5 rows each
    spec = _spec(df, _bar())
    spec["charts"][0]["spec"] = {**spec["charts"][0]["spec"], "measure": "unit_price"}  # SUM of a price
    repaired = auto_remediate_chart_specs(df, spec)
    assert repaired["charts"][0]["spec"]["aggregation"] == "avg"
    assert verify_dashboard_spec(df, repaired)[0]


def test_remediation_drops_charts_that_reference_missing_columns(df):
    spec = _spec(df, _bar(), ChartSpec(id="c2", type="area", measure="revenue", aggregation="sum", grain="month"))
    bad = copy.deepcopy(spec["charts"][0])
    bad["spec"]["dimension"] = "nonexistent"
    repaired = auto_remediate_chart_specs(df, {**spec, "charts": [bad, spec["charts"][1]]})
    assert len(repaired["charts"]) == 1 and repaired["charts"][0]["type"] == "area"


def test_a_spec_cannot_vouch_for_its_own_data(df):
    """Auditing against a different dataset than the one the spec was built from fails."""
    spec = _spec(df, _bar())
    other = df.assign(revenue=df["revenue"] * 2)
    assert not verify_dashboard_spec(other, spec)[0]
