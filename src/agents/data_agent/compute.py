"""Single source of truth for aggregation semantics.

Insights, chart compilation and the verifier all aggregate through these helpers, so a number can never
differ between "what the story says", "what the chart shows" and "what the verifier recomputes".

Rules that matter for correctness:
- Missing values are *ignored*, never turned into zero before averaging.
- ``avg``/``median`` groups smaller than ``min_group`` rows are dropped (a group of 1 is not a ranking).
- Time series are resampled to calendar periods; gaps are 0 for additive measures (no rows = no activity)
  and stay missing for averaged ones; a partially observed first/last period is flagged, not silently used.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from src.agents.data_agent.profiler import parse_datetimes

AGGREGATIONS = ("sum", "avg", "median", "min", "max", "count", "nunique")


def as_numeric(series: pd.Series) -> pd.Series:
    """Numeric view of a column (non-numeric -> NaN, inf -> NaN). Never fills."""
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)


def as_datetime(df: pd.DataFrame, column: str) -> pd.Series:
    """Datetime view of a column (already parsed by ingest, or parsed here)."""
    series = df[column]
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    parsed, _ = parse_datetimes(series)
    return parsed if parsed is not None else pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")


def aggregate_values(values: pd.Series, agg: str) -> Optional[float]:
    """Aggregate one series; ``None`` when there is nothing to aggregate."""
    if agg == "count":
        return float(len(values))
    vals = values.dropna()
    if vals.empty:
        return None
    if agg == "nunique":
        return float(vals.nunique())
    vals = as_numeric(vals).dropna()
    if vals.empty:
        return None
    return float({"sum": vals.sum, "avg": vals.mean, "median": vals.median, "min": vals.min, "max": vals.max}[agg]())


def group_aggregate(
    df: pd.DataFrame,
    dimension: str,
    measure: Optional[str],
    agg: str,
    limit: Optional[int] = None,
    min_group: int = 1,
    ascending: bool = False,
) -> pd.DataFrame:
    """Aggregate ``measure`` by ``dimension`` -> columns ``name``, ``value``, ``count`` (sorted, ties by name)."""
    keys = df[dimension].astype("string").str.strip()
    valid = keys.notna() & (keys != "")
    if measure is None or agg in ("count", "nunique"):
        source = df[measure] if (measure and agg == "nunique") else None
        if source is not None:
            frame = pd.DataFrame({"name": keys[valid], "v": source[valid]})
            grouped = frame.groupby("name", sort=False)["v"].nunique()
        else:
            grouped = keys[valid].groupby(keys[valid], sort=False).size()
        result = grouped.rename("value").to_frame()
        result["count"] = keys[valid].groupby(keys[valid], sort=False).size()
        result.index.name = "name"
    else:
        values = as_numeric(df[measure])
        frame = pd.DataFrame({"name": keys[valid], "v": values[valid]})
        grouped = frame.groupby("name", sort=False)["v"]
        pandas_agg = {"sum": "sum", "avg": "mean", "median": "median", "min": "min", "max": "max"}[agg]
        result = grouped.agg(pandas_agg).rename("value").to_frame()
        if agg == "sum":  # a group whose values are all missing has no total, not a total of 0
            result.loc[grouped.count() == 0, "value"] = np.nan
        result["count"] = grouped.count()
        if agg in ("avg", "median") and min_group > 1:
            result = result[result["count"] >= min_group]
    result = result.dropna(subset=["value"]).reset_index()
    result["count"] = result["count"].astype(int)
    result = result.sort_values(["value", "name"], ascending=[ascending, True], kind="mergesort")
    return result.head(limit).reset_index(drop=True) if limit else result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------


def period_label(period: pd.Period, freq: str) -> str:
    """Stable, sortable, human readable period name (``2024-03``, ``2024-Q2``, ``2024``, ``2024-03-18``)."""
    if freq == "M":
        return period.strftime("%Y-%m")
    if freq == "Q":
        return f"{period.year}-Q{period.quarter}"
    if freq == "Y":
        return str(period.year)
    return period.start_time.strftime("%Y-%m-%d")


def period_series(
    df: pd.DataFrame,
    time_col: str,
    measure: Optional[str],
    agg: str,
    freq: str,
) -> pd.DataFrame:
    """Resample to calendar periods -> columns ``period`` (Period), ``label``, ``value`` (+ ``partial`` flags).

    Returns an empty frame when the column has no usable dates.
    """
    dates = as_datetime(df, time_col)
    frame = pd.DataFrame({"t": dates})
    frame["v"] = as_numeric(df[measure]) if measure else 1.0
    frame = frame.dropna(subset=["t"])
    if frame.empty:
        return pd.DataFrame(columns=["period", "label", "value", "partial"])

    frame["p"] = frame["t"].dt.to_period(freq)
    grouped = frame.groupby("p")["v"]
    if measure is None or agg == "count":
        values = grouped.size().astype(float)
    else:
        values = grouped.agg({"sum": "sum", "avg": "mean", "median": "median", "min": "min", "max": "max"}[agg]).astype(float)
        if agg == "sum":
            values[grouped.count() == 0] = np.nan

    full = pd.period_range(values.index.min(), values.index.max(), freq=freq)
    values = values.reindex(full)
    if agg in ("sum", "count") or measure is None:
        values = values.fillna(0.0)  # no rows in a period = no activity

    out = pd.DataFrame({"period": values.index, "value": values.to_numpy()})
    out["label"] = [period_label(p, freq) for p in out["period"]]
    out["partial"] = _partial_flags(out["period"], frame["t"].min(), frame["t"].max(), freq)
    return out.dropna(subset=["value"]).reset_index(drop=True)


def _partial_flags(periods: pd.Series, first_seen: pd.Timestamp, last_seen: pd.Timestamp, freq: str) -> list[bool]:
    """Flag first/last periods that the data only partially covers (< 90 % of the period's days)."""
    flags = [False] * len(periods)
    if freq == "D" or len(periods) < 2:
        return flags

    def days(p: pd.Period) -> int:
        return (p.end_time - p.start_time).days + 1

    first, last = periods.iloc[0], periods.iloc[-1]
    if ((first.end_time - first_seen).days + 1) / days(first) < 0.9:
        flags[0] = True
    if ((last_seen - last.start_time).days + 1) / days(last) < 0.9:
        flags[-1] = True
    return flags


def trim_partial(series: pd.DataFrame, additive: bool) -> pd.DataFrame:
    """Drop partially covered edge periods for additive measures (their totals are artificially low)."""
    if not additive or series.empty or not series["partial"].any():
        return series
    return series[~series["partial"]].reset_index(drop=True)
