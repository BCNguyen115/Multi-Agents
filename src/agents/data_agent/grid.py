"""The dashboard's data grid on the server: EVERY row of the upload, paged, searched, filtered and sorted.

The browser never holds the whole table (an 8.8k-row text file is 3.6 MB of JSON, a 100k-row one is tens of MB, and a
conversation saved in the browser keeps only a preview). The grid asks for the page it shows; search, column filters,
slicers and sorting run here over all rows, so any single row can be found, and "export CSV" can include them all.

Everything is data, never code: column ids are checked against the table, text is matched literally (no regular
expressions), operators come from a fixed list.
"""

from __future__ import annotations

import functools
import operator
from typing import Any, Optional

import numpy as np
import pandas as pd

MAX_PAGE = 1000
_MAX_CONDITIONS = 4
_SEPARATOR = "\x1f"  # between cells in the search text: cannot be typed into a search box


def _is_date(series: pd.Series) -> bool:
    return pd.api.types.is_datetime64_any_dtype(series)


def text_of(series: pd.Series) -> pd.Series:
    """The cell text the grid shows: dates as ISO text (no 00:00:00), missing values as empty."""
    if _is_date(series):
        return series.dt.strftime("%Y-%m-%d %H:%M:%S").str.replace(" 00:00:00", "", regex=False).fillna("")
    return series.replace([np.inf, -np.inf], np.nan).astype("string").fillna("")


def records(part: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows as JSON-safe records (dates as ISO text, missing values as null)."""
    shown = part.copy()
    for column in shown.columns:
        if _is_date(shown[column]):
            shown[column] = text_of(shown[column]).where(shown[column].notna(), None)
    shown = shown.replace([np.inf, -np.inf], np.nan).astype(object)
    return shown.where(shown.notna(), None).to_dict(orient="records")


def build_haystack(df: pd.DataFrame) -> pd.Series:
    """Lower-cased text of every cell of a row, joined: one pass, reused by every search of the same table."""
    cells = [text_of(df[column]).str.lower() for column in df.columns]
    haystack = cells[0]
    for cell in cells[1:]:
        haystack = haystack + _SEPARATOR + cell
    return haystack


# ---------------------------------------------------------------------------------------------- column filters (AG Grid models)


def _text_mask(text: pd.Series, op: str, value: Any) -> pd.Series:
    low, needle = text.str.lower(), ("" if value is None else str(value)).lower()
    masks = {
        "contains": lambda: low.str.contains(needle, regex=False),
        "notContains": lambda: ~low.str.contains(needle, regex=False),
        "equals": lambda: low == needle,
        "notEqual": lambda: low != needle,
        "startsWith": lambda: low.str.startswith(needle),
        "endsWith": lambda: low.str.endswith(needle),
        "blank": lambda: text == "",
        "notBlank": lambda: text != "",
    }
    if op not in masks:
        raise ValueError(f"unsupported text filter '{op}'")
    return masks[op]().astype(bool)


def _number_mask(series: pd.Series, op: str, value: Any, value_to: Any) -> pd.Series:
    if op in ("blank", "notBlank"):
        return series.isna() if op == "blank" else series.notna()
    try:
        low = float(value)
        high = float(value_to) if op == "inRange" else None
    except (TypeError, ValueError):
        raise ValueError(f"'{value}' is not a number") from None
    masks = {
        "equals": lambda: series == low,
        "notEqual": lambda: series != low,
        "greaterThan": lambda: series > low,
        "greaterThanOrEqual": lambda: series >= low,
        "lessThan": lambda: series < low,
        "lessThanOrEqual": lambda: series <= low,
        "inRange": lambda: (series >= low) & (series <= high),
    }
    if op not in masks:
        raise ValueError(f"unsupported number filter '{op}'")
    return masks[op]().astype(bool)


def _condition(df: pd.DataFrame, column: str, model: dict[str, Any]) -> pd.Series:
    """One column's AG Grid filter model: a single condition or ``{operator, conditions: [...]}``."""
    if not isinstance(model, dict):
        raise ValueError(f"invalid filter for '{column}'")
    if "conditions" in model:
        masks = [_condition(df, column, c) for c in list(model["conditions"])[:_MAX_CONDITIONS]]
        if not masks:
            raise ValueError(f"invalid filter for '{column}'")
        return functools.reduce(operator.or_ if str(model.get("operator", "AND")).upper() == "OR" else operator.and_, masks)
    kind = model.get("filterType")
    if kind == "number":
        if not pd.api.types.is_numeric_dtype(df[column]):
            raise ValueError(f"'{column}' is not a number column")
        return _number_mask(df[column], str(model.get("type")), model.get("filter"), model.get("filterTo"))
    if kind == "text":
        return _text_mask(text_of(df[column]), str(model.get("type")), model.get("filter"))
    raise ValueError(f"unsupported filter type '{kind}'")


# ---------------------------------------------------------------------------------------------- the view


def filter_and_sort(df: pd.DataFrame, dimensions: list[str], query: dict[str, Any], haystack: Optional[pd.Series] = None) -> pd.DataFrame:
    """The rows matching ``query`` in the requested order.

    ``query`` keys (all optional): ``search`` (every word must appear in the row), ``slicers`` ({dimension: [values]}),
    ``column_filters`` ({column: AG Grid filter model}), ``sort`` ([{field, dir}]).

    Raises:
        ValueError: an unknown column, a column that cannot be a slicer, an unsupported operator or a malformed value.
    """
    mask = pd.Series(True, index=df.index)
    for column, values in (query.get("slicers") or {}).items():
        if column not in dimensions:
            raise ValueError(f"'{column}' is not a filterable column")
        mask &= df[column].astype("string").isin([str(v) for v in values])
    for column, model in (query.get("column_filters") or {}).items():
        if column not in df.columns:
            raise ValueError(f"unknown column '{column}'")
        mask &= _condition(df, column, model)
    terms = str(query.get("search") or "").lower().split()
    if terms:
        haystack = build_haystack(df) if haystack is None else haystack
        for term in terms:
            mask &= haystack.str.contains(term, regex=False)
    view = df[mask]

    fields, ascending = [], []
    for item in query.get("sort") or []:
        field = item.get("field") if isinstance(item, dict) else None
        if field not in df.columns:
            raise ValueError(f"unknown column '{field}'")
        fields.append(field)
        ascending.append(item.get("dir", "asc") != "desc")
    if fields:
        try:
            view = view.sort_values(fields, ascending=ascending, kind="stable", na_position="last")
        except TypeError:  # a text column mixing numbers and words: sort by what the grid shows
            shown = pd.DataFrame({field: text_of(view[field]) for field in fields})
            view = view.loc[shown.sort_values(fields, ascending=ascending, kind="stable").index]
    return view


def page(view: pd.DataFrame, start: int, limit: int) -> list[dict[str, Any]]:
    start, limit = max(0, int(start)), max(1, min(int(limit), MAX_PAGE))
    return records(view.iloc[start : start + limit])


def to_csv(view: pd.DataFrame, labels: dict[str, str]) -> str:
    """Every row of the view as CSV text with the column labels as header; the BOM makes Excel read it as UTF-8."""
    shown = view.copy()
    for column in shown.columns:
        if _is_date(shown[column]):
            shown[column] = text_of(shown[column]).where(shown[column].notna(), None)
    return "﻿" + shown.rename(columns={c: labels.get(c, c) for c in shown.columns}).to_csv(index=False)
