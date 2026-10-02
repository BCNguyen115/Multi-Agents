"""Regression tests for problems found while using the running system with real-looking files."""
import numpy as np
import pandas as pd

from src.agents.data_agent.charts import ChartContext, build_kpis
from src.agents.data_agent.insights import generate_insights
from src.agents.data_agent.profiler import profile_dataframe_universal
from src.agents.data_agent.story import build_story
from tests.test_insights import _planted

RNG = np.random.default_rng(3)


def test_currency_codes_in_a_column_name_make_it_an_additive_money_measure():
    df = pd.DataFrame({"stadt": RNG.choice(list("abc"), 100), "umsatz_eur": RNG.uniform(1000, 9000, 100)})
    info = profile_dataframe_universal(df)["columns"]["umsatz_eur"]
    assert info["unit_kind"] == "currency" and info["agg"] == "sum"


def test_kpis_lead_with_the_column_the_user_asked_about():
    df = _planted()
    ctx = ChartContext(df=df, profile=profile_dataframe_universal(df), lang="en")
    default = [k["measure"] for k in build_kpis(ctx, []) if k["aggregation"] in ("SUM", "AVG")]
    focused = build_kpis(ctx, [], focus="price")
    assert default[0] == "revenue"
    lead = next(k for k in focused if k["aggregation"] in ("SUM", "AVG"))
    assert lead["measure"] == "price" and lead["aggregation"] == "AVG"


def test_an_ordinal_column_is_not_counted_as_an_entity():
    n = 300
    df = pd.DataFrame({"rating": RNG.integers(1, 10, n), "amount": RNG.uniform(1, 100, n), "shop": RNG.choice(list("abcdefghij"), n)})
    profile = profile_dataframe_universal(df)
    assert profile["role_map"]["rating"] == "ROLE_ORDINAL"
    entity = next(k for k in build_kpis(ChartContext(df=df, profile=profile), []) if k["id"] == "kpi_entity")
    assert entity["measure"] == "shop"
    only_ordinal = df.drop(columns="shop")
    kpis = build_kpis(ChartContext(df=only_ordinal, profile=profile_dataframe_universal(only_ordinal)), [])
    assert all(k["id"] != "kpi_entity" for k in kpis)


def test_yes_no_groups_name_their_column_in_the_story():
    n = 200
    df = pd.DataFrame({"remote": RNG.choice(["yes", "no"], n, p=[0.3, 0.7]), "salary": RNG.normal(60000, 9000, n).round(0)})
    profile = profile_dataframe_universal(df)
    story = build_story(generate_insights(df, profile), profile, {"notes": []}, "en")
    text = " ".join(f["text"] for f in story["findings"])
    assert "remote = no" in text.lower() and story["grounded"]
