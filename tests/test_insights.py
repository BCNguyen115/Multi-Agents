"""Insight engine: planted effects must be found, numbers must be right, degenerate data must not crash."""
import json

import numpy as np
import pandas as pd
import pytest

from src.agents.data_agent import compute
from src.agents.data_agent.insights import generate_insights
from src.agents.data_agent.profiler import profile_dataframe_universal


def _planted() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    days = pd.date_range("2022-01-01", "2023-12-31", freq="D")
    n = len(days) * 6
    when = np.repeat(days.values, 6)
    frame = pd.DataFrame({
        "sold_on": when,
        "region": rng.choice(["North", "South", "East", "West"], n, p=[0.55, 0.2, 0.15, 0.1]),
        "channel": rng.choice(["online", "store", "phone"], n),
        "units": rng.integers(1, 6, n),
    })
    growth = 1 + 0.4 * (pd.Series(when).rank(pct=True).to_numpy())
    frame["revenue"] = rng.lognormal(3.2, 0.5, n) * growth
    frame.loc[frame["channel"] == "online", "revenue"] *= 1.5                                   # group effect
    frame.loc[(frame["sold_on"] >= "2022-09-01") & (frame["sold_on"] < "2022-10-01"), "revenue"] *= 3.5  # anomaly month
    frame.loc[(frame["sold_on"] >= "2023-12-01") & (frame["region"] == "East"), "revenue"] *= 4        # driver of the last change
    frame["price"] = rng.uniform(10, 200, n).round(2)
    frame["cost"] = (frame["price"] * 0.6 + rng.normal(0, 25, n)).round(2)                          # correlated pair
    return frame


@pytest.fixture(scope="module")
def planted():
    df = _planted()
    profile = profile_dataframe_universal(df)
    return df, profile, generate_insights(df, profile)


def _by_kind(facts, kind):
    return [f for f in facts if f.kind == kind]


def test_time_axis_and_policies_are_what_the_planted_data_implies(planted):
    _, profile, _ = planted
    assert profile["time"]["primary"] == "sold_on" and profile["time"]["grain"] == "month"
    assert profile["policies"]["revenue"]["agg"] == "sum"


def test_upward_trend_is_found_with_correct_direction(planted):
    _, _, facts = planted
    trend = next(f for f in _by_kind(facts, "trend") if f.refs["measure"] == "revenue")
    assert trend.numbers["direction"] == "up" and trend.numbers["pct_change"] > 0.1
    assert trend.numbers["n_periods"] == 24


def test_anomalous_month_is_flagged(planted):
    _, _, facts = planted
    anomaly = _by_kind(facts, "anomaly")[0]
    assert "2022-09" in [p["period"] for p in anomaly.numbers["points"]]


def test_contribution_names_the_planted_driver(planted):
    _, _, facts = planted
    contribution = next(f for f in _by_kind(facts, "contribution") if f.refs["dimension"] == "region")
    assert contribution.numbers["contributors"][0]["name"] == "East"
    assert contribution.numbers["delta"] > 0 and contribution.numbers["to_period"] == "2023-12"


def test_composition_reports_the_dominant_category(planted):
    _, _, facts = planted
    comp = next(f for f in _by_kind(facts, "composition") if f.refs["dimension"] == "region")
    assert comp.numbers["top1"] == "North" and 0.4 < comp.numbers["top1_share"] < 0.7
    assert comp.numbers["basis"] == "sum"


def test_significant_group_difference_is_found(planted):
    _, _, facts = planted
    diff = next(f for f in _by_kind(facts, "group_difference") if f.refs["dimension"] == "channel")
    assert diff.numbers["best_group"] == "online" and diff.numbers["p_value"] < 0.01


def test_correlated_pair_is_found_and_flagged_as_not_causal(planted):
    _, _, facts = planted
    corr = _by_kind(facts, "correlation")[0]
    assert {corr.refs["a"], corr.refs["b"]} == {"price", "cost"} and corr.numbers["direction"] == "positive"
    assert {"code": "correlation_not_causation"} in corr.caveats


def test_skewed_measure_gets_a_distribution_fact(planted):
    _, _, facts = planted
    dist = next(f for f in _by_kind(facts, "distribution") if f.refs["measure"] == "revenue")
    assert dist.numbers["skew"] > 1.0 and dist.numbers["top10pct_share"] > 0.2


def test_facts_are_ranked_unique_bounded_and_json_safe(planted):
    _, _, facts = planted
    assert [f.id for f in facts] == [f"F{i}" for i in range(1, len(facts) + 1)]
    scores = [f.importance * f.confidence for f in facts]
    assert scores == sorted(scores, reverse=True)
    assert all(sum(1 for f in facts if f.kind == kind) <= 3 for kind in {f.kind for f in facts})
    json.dumps([f.to_dict() for f in facts], allow_nan=False)


def test_generation_is_deterministic(planted):
    df, profile, facts = planted
    again = generate_insights(df, profile)
    assert [f.to_dict() for f in facts] == [f.to_dict() for f in again]


def test_no_time_axis_means_no_time_insights():
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"team": rng.choice(list("abcde"), 300), "score": rng.normal(50, 10, 300)})
    facts = generate_insights(df, profile_dataframe_universal(df))
    assert not {f.kind for f in facts} & {"trend", "period_change", "contribution", "anomaly"}


def test_categorical_only_data_uses_record_counts():
    df = pd.DataFrame({"colour": np.random.default_rng(5).choice(["red", "green", "blue"], 200)})
    comp = _by_kind(generate_insights(df, profile_dataframe_universal(df)), "composition")
    assert comp and comp[0].numbers["basis"] == "count"


def test_tiny_and_empty_inputs_do_not_crash():
    assert generate_insights(pd.DataFrame({"a": []}), profile_dataframe_universal(pd.DataFrame({"a": []}))) == []
    small = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "x"]})
    generate_insights(small, profile_dataframe_universal(small))


# ---------------------------------------------------------------- compute (A1: never zero-fill before averaging)
def test_missing_values_are_ignored_not_zeroed():
    df = pd.DataFrame({"g": ["a", "a", "a", "b"], "v": [10.0, np.nan, 30.0, np.nan]})
    grouped = compute.group_aggregate(df, "g", "v", "avg").set_index("name")
    assert grouped.loc["a", "value"] == 20.0 and "b" not in grouped.index  # all-missing group has no average
    assert compute.aggregate_values(pd.Series([10.0, np.nan, 30.0]), "avg") == 20.0
    assert compute.group_aggregate(df, "g", "v", "sum").set_index("name").loc["a", "value"] == 40.0


def test_small_groups_are_not_ranked_on_averages():
    df = pd.DataFrame({"g": ["a"] * 10 + ["b"], "v": [1.0] * 10 + [100.0]})
    assert compute.group_aggregate(df, "g", "v", "avg", min_group=5)["name"].tolist() == ["a"]


def test_partial_last_period_is_flagged_and_trimmed_for_totals():
    df = pd.DataFrame({"t": pd.date_range("2024-01-01", "2024-04-10"), "v": 1.0})
    series = compute.period_series(df, "t", "v", "sum", "M")
    assert series["label"].tolist() == ["2024-01", "2024-02", "2024-03", "2024-04"]
    assert series["partial"].tolist() == [False, False, False, True]
    assert compute.trim_partial(series, additive=True)["label"].tolist() == ["2024-01", "2024-02", "2024-03"]
    assert len(compute.trim_partial(series, additive=False)) == 4
