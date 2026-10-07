"""The dashboard grid reaches EVERY row of the upload, and the row cap of the spec never limits the numbers.

Reported: a 8,807-row file showed "5,000 / 8,807" and, after a reload, "2,000 / 8,807": a row beyond those could not be found.
The grid now pages through all rows on the server (search, column filters, slicers, sort, CSV export over all of them).
"""
import asyncio
import io
import json

import numpy as np
import pandas as pd
import pytest

from src.agents.data_agent import grid
from src.agents.data_agent.agent import DataAnalystAgent
from src.agents.data_agent.ingest import safe_read_csv
from src.config import settings
from src.orchestrator.verifier import verify_dashboard_spec
from tests.test_agent_e2e import FakeLLM

ROWS = 8807


def make_csv(rows: int) -> tuple[str, pd.DataFrame]:
    rng = np.random.default_rng(3)
    df = pd.DataFrame(
        {
            "order_date": (pd.Timestamp("2000-01-01") + pd.to_timedelta(np.arange(rows), unit="D")).strftime("%Y-%m-%d"),  # one per row
            "region": rng.choice(["North", "South", "East", "West"], rows),
            "revenue": rng.integers(10, 5000, rows),
            "quantity": rng.integers(1, 20, rows),
        }
    )
    return df.to_csv(index=False), df


@pytest.fixture(scope="module")
def loaded():
    csv_text, df = make_csv(ROWS)
    agent = DataAnalystAgent(FakeLLM(), model="fake")
    reply = json.loads(asyncio.run(agent.process_csv_request("Build a dashboard of this data", csv_text, "sales.csv", "s1")))
    return agent, df, reply["dashboard_spec"], csv_text


def rows_of(agent, start=0, limit=100, session="s1", **query) -> dict:
    return asyncio.run(agent.table_page(session, start, limit, query))


def test_the_spec_carries_a_preview_while_every_number_uses_all_rows(loaded):
    _, df, spec, csv_text = loaded
    assert len(spec["table"]["rows"]) == settings.DATA_TABLE_ROWS < ROWS and spec["table"]["totalRows"] == ROWS and spec["table"]["truncated"]
    assert spec["analysis"]["rows_used"] == spec["analysis"]["rows_total"] == ROWS and not spec["analysis"]["sampled"]
    assert next(k["raw_value"] for k in spec["kpis"] if k["title"] == "Records") == ROWS
    assert any(k["raw_value"] == pytest.approx(float(df["revenue"].sum())) for k in spec["kpis"])
    assert verify_dashboard_spec(safe_read_csv(csv_text), spec)[0]


def test_the_pages_cover_every_row_exactly_once(loaded):
    agent, df, _, _ = loaded
    seen = []
    for start in range(0, ROWS, 1000):
        page = rows_of(agent, start, 1000)
        assert page["total"] == page["total_all"] == ROWS
        seen += [r["order_date"] for r in page["rows"]]
    assert seen == df["order_date"].tolist()
    assert rows_of(agent, ROWS, 100)["rows"] == []  # past the end


def test_any_single_row_can_be_found_wherever_it_is(loaded):
    agent, df, _, _ = loaded
    for index in (0, 4999, 5000, 8806):  # first, either side of the old 5,000 cut, last
        page = rows_of(agent, search=df["order_date"][index])
        assert page["total"] == 1 and page["rows"][0]["revenue"] == int(df["revenue"][index])
    day = df["order_date"][8500]
    assert rows_of(agent, search=day.upper())["total"] == 1  # case does not matter
    assert rows_of(agent, search=f"{day} {df['region'][8500]}")["total"] == 1  # every word must match
    assert rows_of(agent, search=f"{day} not-a-region")["total"] == 0
    assert rows_of(agent, search="[(.*")["total"] == 0  # matched literally: a regex does not blow up


def test_sorting_runs_over_all_rows(loaded):
    agent, df, _, _ = loaded
    top = rows_of(agent, limit=50, sort=[{"field": "revenue", "dir": "desc"}, {"field": "order_date", "dir": "asc"}])
    expected = df.sort_values(["revenue", "order_date"], ascending=[False, True], kind="stable").head(50)
    assert [r["order_date"] for r in top["rows"]] == expected["order_date"].tolist()
    assert top["rows"][0]["revenue"] == int(df["revenue"].max())


def test_column_filters_slicers_and_search_combine_over_all_rows(loaded):
    agent, df, _, _ = loaded
    north = df["region"] == "North"
    assert rows_of(agent, column_filters={"region": {"filterType": "text", "type": "equals", "filter": "north"}})["total"] == int(north.sum())
    assert rows_of(agent, column_filters={"region": {"filterType": "text", "type": "startsWith", "filter": "so"}})["total"] == int((df["region"] == "South").sum())
    between = {"revenue": {"filterType": "number", "type": "inRange", "filter": 100, "filterTo": 200}}
    assert rows_of(agent, column_filters=between)["total"] == int(df["revenue"].between(100, 200).sum())
    both = {"revenue": {"operator": "AND", "conditions": [{"filterType": "number", "type": "greaterThan", "filter": 4000}, {"filterType": "number", "type": "lessThan", "filter": 4100}]}}
    assert rows_of(agent, column_filters=both)["total"] == int(((df["revenue"] > 4000) & (df["revenue"] < 4100)).sum())
    either = {"region": {"operator": "OR", "conditions": [{"filterType": "text", "type": "equals", "filter": "North"}, {"filterType": "text", "type": "equals", "filter": "East"}]}}
    assert rows_of(agent, column_filters=either)["total"] == int(df["region"].isin(["North", "East"]).sum())
    assert rows_of(agent, slicers={"region": ["North", "South"]})["total"] == int(df["region"].isin(["North", "South"]).sum())
    combined = rows_of(agent, slicers={"region": ["North"]}, column_filters=between, search="2005")
    assert combined["total"] == int((north & df["revenue"].between(100, 200) & df["order_date"].str.contains("2005")).sum())


@pytest.mark.parametrize(
    "query",
    [
        {"slicers": {"revenue": ["1"]}},  # a measure is not a slicer
        {"column_filters": {"nope": {"filterType": "text", "type": "equals", "filter": "x"}}},
        {"column_filters": {"region": {"filterType": "text", "type": "drop table", "filter": "x"}}},
        {"column_filters": {"region": {"filterType": "number", "type": "equals", "filter": 1}}},  # not a number column
        {"column_filters": {"revenue": {"filterType": "number", "type": "equals", "filter": "abc"}}},
        {"column_filters": {"revenue": {"filterType": "date", "type": "equals", "filter": "x"}}},
        {"sort": [{"field": "nope", "dir": "asc"}]},
    ],
)
def test_malformed_queries_are_refused_not_executed(loaded, query):
    agent, _, _, _ = loaded
    with pytest.raises(ValueError):
        rows_of(agent, **query)


def test_the_csv_export_has_every_matching_row(loaded):
    agent, df, _, _ = loaded
    everything = asyncio.run(agent.table_csv("s1", {}))
    assert everything.startswith("﻿")
    exported = pd.read_csv(io.StringIO(everything.lstrip("﻿")))
    assert len(exported) == ROWS and exported["order_date"].tolist() == df["order_date"].tolist()
    assert exported["revenue"].sum() == df["revenue"].sum()

    south = pd.read_csv(io.StringIO(asyncio.run(agent.table_csv("s1", {"slicers": {"region": ["South"]}, "sort": [{"field": "revenue", "dir": "asc"}]})).lstrip("﻿")))
    assert len(south) == int((df["region"] == "South").sum()) and south["revenue"].is_monotonic_increasing


def test_another_session_cannot_page_this_dataset(loaded):
    agent, _, _, _ = loaded
    with pytest.raises(LookupError):
        rows_of(agent, session="somebody-else")
    with pytest.raises(LookupError):
        asyncio.run(agent.table_csv("somebody-else", {}))


def test_missing_values_dates_and_mixed_columns_are_handled():
    df = pd.DataFrame(
        {
            "when": pd.to_datetime(["2024-01-02", None, "2024-03-04 05:06:07"], format="ISO8601"),
            "mixed": [3, "word", None],
            "n": [1.5, np.inf, np.nan],
        }
    )
    assert grid.records(df) == [
        {"when": "2024-01-02", "mixed": 3, "n": 1.5},
        {"when": None, "mixed": "word", "n": None},
        {"when": "2024-03-04 05:06:07", "mixed": None, "n": None},
    ]
    view = grid.filter_and_sort(df, [], {"sort": [{"field": "mixed", "dir": "asc"}]})  # ints and words together: no crash
    assert len(view) == 3
    assert grid.filter_and_sort(df, [], {"search": "05:06"}).index.tolist() == [2]
    assert grid.to_csv(df, {"when": "Ngày"}).splitlines()[0] == "﻿Ngày,mixed,n"
