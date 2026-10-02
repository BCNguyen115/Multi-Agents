"""Universal dataset profiler (v2).

Column semantics come from *values and statistics*. The only place column names are consulted is a
small, documented lexicon that decides a measure's aggregation policy and currency unit — a number's
"summability" cannot be read from its values alone (``unit_price`` and ``quantity`` look alike).

Roles
-----
- ROLE_IDENTIFIER        keys / codes / uuids — never aggregated arithmetically
- ROLE_TEMPORAL          parseable dates (>= 90 % valid, >= 5 distinct values)
- ROLE_MEASURE           continuous numeric quantity
- ROLE_RATIO             numeric fraction in [0, 1] (or percent-formatted)
- ROLE_ORDINAL           small-range integers (ratings, years, counts of categories)
- ROLE_BOOLEAN           two-valued flags
- ROLE_LOW_CARDINALITY   2..7 categories   (donut / slicer candidates)
- ROLE_HIGH_CARDINALITY  8+ categories     (ranking / treemap candidates)
- ROLE_TEXT              free text
- ROLE_CONSTANT          <= 1 distinct value (ignored)
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional

import numpy as np
import pandas as pd

ROLE_IDENTIFIER = "ROLE_IDENTIFIER"
ROLE_TEMPORAL = "ROLE_TEMPORAL"
ROLE_MEASURE = "ROLE_MEASURE"
ROLE_RATIO = "ROLE_RATIO"
ROLE_ORDINAL = "ROLE_ORDINAL"
ROLE_BOOLEAN = "ROLE_BOOLEAN"
ROLE_LOW_CARDINALITY = "ROLE_LOW_CARDINALITY"
ROLE_HIGH_CARDINALITY = "ROLE_HIGH_CARDINALITY"
ROLE_TEXT = "ROLE_TEXT"
ROLE_CONSTANT = "ROLE_CONSTANT"
ROLE_UNKNOWN = "ROLE_UNKNOWN"

AGG_SUM = "sum"
AGG_AVG = "avg"

UNIT_CURRENCY = "currency"
UNIT_PERCENT = "percent"
UNIT_PLAIN = "plain"

# ---------------------------------------------------------------------------
# Name lexicons (token based, never substring based: "smartphone" is not "phone")
# ---------------------------------------------------------------------------

_STRONG_ID_TOKENS = frozenset({"id", "uuid", "guid", "sku", "stt", "pk", "fk", "uid", "barcode", "token", "hash", "idx", "index", "ssn", "cccd"})
_CODE_ID_TOKENS = frozenset({"code", "key", "phone", "zip", "zipcode", "postal", "number", "no", "num"})

# Aggregation-policy tiers, evaluated in order (see agg_policy)
_INTENSIVE_EXPLICIT = frozenset({"avg", "average", "mean", "median", "rate", "ratio", "pct", "percent", "per", "unit"})
_ADDITIVE_EXPLICIT = frozenset({"total", "sum", "count", "qty", "quantity", "units", "volume", "tong", "soluong"})
_INTENSIVE_WEAK = frozenset({"price", "rating", "score", "age", "temperature", "temp", "margin", "discount", "level", "grade", "gia", "diem", "tuoi"})
_ADDITIVE_WEAK = frozenset({"amount", "revenue", "sales", "cost", "profit", "streams", "views", "clicks", "spend", "spent", "income", "expense", "fee", "tax", "doanh", "thu", "tien", "luot"})
_MONETARY_TOKENS = frozenset({"price", "cost", "amount", "revenue", "sales", "salary", "fee", "spend", "spent", "profit", "usd", "eur", "gbp", "jpy", "cny", "inr", "krw", "vnd", "income", "expense", "tax", "tien", "gia"})

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
_BOOL_TEXT = frozenset({"true", "false", "yes", "no", "y", "n", "t", "f", "1", "0", "có", "co", "không", "khong"})


def name_tokens(name: str) -> list[str]:
    """Lower-case word tokens of a column name (``unit_price`` -> ``["unit", "price"]``)."""
    return [t for t in re.split(r"[^\w]+|_+", str(name).lower()) if t]


def is_monetary_name(col_name: str) -> bool:
    """Currency hint from the column name (token based; the only non-value signal for units)."""
    toks = name_tokens(col_name)
    return bool(_MONETARY_TOKENS.intersection(toks)) or "doanhthu" in "".join(toks)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_YEARISH_RE = re.compile(r"(?<!\d)(?:1[89]|20)\d{2}(?!\d)")
_SEP_DATE_RE = re.compile(r"^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}")


def _min_unique(total_rows: int) -> int:
    return 5 if total_rows >= 5 else max(2, total_rows)


def _infer_dayfirst(sample: pd.Series) -> tuple[bool, bool]:
    """Return ``(dayfirst, ambiguous)`` for ``a/b/yyyy`` style dates."""
    parts = sample.str.extract(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-]\d{2,4}")
    if parts.notna().all(axis=1).any():
        first, second = pd.to_numeric(parts[0]), pd.to_numeric(parts[1])
        if (first > 12).any():
            return True, False
        if (second > 12).any():
            return False, False
        return False, True
    return False, False


def _to_datetime(values: pd.Series, dayfirst: bool) -> pd.Series:
    """Parse text to naive datetimes: strict ISO first, then permissive mixed formats."""
    parsed = pd.to_datetime(values, errors="coerce", format="ISO8601", utc=True)
    if parsed.notna().mean() < 0.9:
        parsed = pd.to_datetime(values, errors="coerce", format="mixed", dayfirst=dayfirst, utc=True)
    return parsed.dt.tz_localize(None)


def _parse_compact_dates(non_null: pd.Series) -> Optional[pd.Series]:
    """Integer ``YYYYMMDD`` columns (e.g. 20240131)."""
    if not (non_null % 1 == 0).all() or not non_null.between(19000101, 21001231).all():
        return None
    parsed = pd.to_datetime(non_null.astype("int64").astype(str), format="%Y%m%d", errors="coerce")
    return parsed if parsed.notna().mean() >= 0.95 else None


def parse_datetimes(ser: pd.Series) -> tuple[Optional[pd.Series], dict[str, Any]]:
    """Parse a column as datetimes if (and only if) its *values* are dates.

    Requires a year component (so a ``month_name`` column is not "dates"), >= 90 % valid values and
    >= 5 distinct dates. Returns ``(series or None, info)`` where ``info['ambiguous']`` flags ``dd/mm`` vs
    ``mm/dd`` columns that could not be disambiguated (month-first is then assumed).
    """
    info: dict[str, Any] = {"ambiguous": False}
    total_rows = len(ser)
    if pd.api.types.is_datetime64_any_dtype(ser):
        return (ser, info) if ser.nunique() >= _min_unique(total_rows) else (None, info)

    non_null = ser.dropna()
    if len(non_null) < 2:
        return None, info

    if pd.api.types.is_bool_dtype(ser):
        return None, info
    if pd.api.types.is_numeric_dtype(ser):
        parsed = _parse_compact_dates(non_null)
        if parsed is None:
            return None, info
        full = pd.Series(pd.NaT, index=ser.index, dtype="datetime64[ns]")
        full.loc[parsed.index] = parsed
        return (full, info) if parsed.nunique() >= _min_unique(total_rows) else (None, info)

    text = non_null.astype(str).str.strip()
    sample = text.iloc[:: max(1, len(text) // 500)].head(500)
    if not (sample.str.contains(_YEARISH_RE) | sample.str.match(_SEP_DATE_RE)).mean() >= 0.9:
        return None, info

    dayfirst, info["ambiguous"] = _infer_dayfirst(sample)
    if _to_datetime(sample, dayfirst).notna().mean() < 0.9:
        return None, info

    parsed = _to_datetime(text, dayfirst)
    if parsed.notna().mean() < 0.9 or parsed.nunique() < _min_unique(total_rows):
        return None, info
    full = pd.Series(pd.NaT, index=ser.index, dtype="datetime64[ns]")
    full.loc[parsed.index] = parsed
    return full, info


def is_temporal_series(ser: pd.Series) -> bool:
    return parse_datetimes(ser)[0] is not None


def temporal_columns(df: pd.DataFrame) -> list[str]:
    """Columns whose *values* parse as dates — never decided by name."""
    return [str(c) for c in df.columns if is_temporal_series(df[c])]


_GRAINS: tuple[tuple[str, str, float], ...] = (("day", "D", 1.0), ("week", "W", 7.0), ("month", "M", 30.44), ("quarter", "Q", 91.31), ("year", "Y", 365.25))


def choose_time_grain(dates: pd.Series) -> dict[str, Any]:
    """Pick the finest resampling grain that yields a readable series (<= 48 periods, not finer than the data)."""
    valid = dates.dropna().sort_values()
    if valid.empty:
        return {"grain": "month", "freq": "M", "span_days": 0, "min": None, "max": None}
    span_days = max(int((valid.iloc[-1] - valid.iloc[0]).days), 0)
    unique = valid.drop_duplicates()
    gap = float(unique.diff().dt.days.median()) if len(unique) > 2 else 1.0
    chosen = _GRAINS[-1]
    for grain in _GRAINS:
        if grain[2] < min(gap, 28.0) * 0.9 and grain[0] != "day":
            continue
        if span_days / grain[2] + 1 <= 48:
            chosen = grain
            break
    return {
        "grain": chosen[0],
        "freq": chosen[1],
        "span_days": span_days,
        "min": str(valid.iloc[0].date()),
        "max": str(valid.iloc[-1].date()),
    }


# ---------------------------------------------------------------------------
# Identifier detection
# ---------------------------------------------------------------------------


def _is_sequence(values: pd.Series) -> bool:
    diffs = values.diff().dropna()
    return bool(len(diffs) > 0 and ((diffs == 1).mean() > 0.9 or (diffs == -1).mean() > 0.9))


def is_identifier_column(col_name: str, ser: Optional[pd.Series] = None, total_rows: int = 0) -> bool:
    """Identify keys/codes from name tokens *and* value evidence.

    A name token alone is not enough: ``country_code`` (few distinct text values) is a dimension, whereas
    a numeric ``zip`` or a text ``order_ref`` that is unique per row is an identifier.
    """
    toks = set(name_tokens(col_name))
    if ser is None:
        return bool(toks & _STRONG_ID_TOKENS) or toks == {"code"} or any(t.endswith("id") and len(t) > 3 for t in toks)

    non_null = ser.dropna()
    n = len(non_null)
    if n == 0:
        return False
    nunique = int(non_null.nunique())
    uniq_ratio = nunique / n
    numeric = pd.api.types.is_numeric_dtype(ser) and not pd.api.types.is_bool_dtype(ser)
    integer_valued = numeric and bool((non_null % 1 == 0).all())

    if toks & _STRONG_ID_TOKENS:
        return numeric or uniq_ratio >= 0.5 or nunique > 50
    if toks & _CODE_ID_TOKENS:
        if numeric:
            return integer_valued and uniq_ratio >= 0.5
        return uniq_ratio >= 0.9
    if integer_valued and total_rows > 20 and any(t.endswith("id") and len(t) > 3 for t in toks) and uniq_ratio >= 0.05:
        return True

    if total_rows > 20 and nunique == n:
        if integer_valued:
            return _is_sequence(non_null.sort_index())
        strings = non_null.astype(str)
        if strings.iloc[:200].str.match(_UUID_RE).mean() >= 0.9:
            return True
        hexlike = strings.iloc[:200].str.fullmatch(r"[0-9a-fA-F]{16,}")
        return bool(hexlike.mean() >= 0.9)
    return False


# ---------------------------------------------------------------------------
# Aggregation policy & role classification
# ---------------------------------------------------------------------------


def agg_policy(name: str, role: str, stats: dict[str, Any], unit_kind: str) -> str:
    """``sum`` only with evidence of additivity, otherwise ``avg`` (an average is never nonsensical)."""
    if role in (ROLE_RATIO, ROLE_ORDINAL):
        return AGG_AVG
    toks = set(name_tokens(name))
    if toks & _INTENSIVE_EXPLICIT:
        return AGG_AVG
    if toks & _ADDITIVE_EXPLICIT:
        return AGG_SUM
    if toks & _INTENSIVE_WEAK:
        return AGG_AVG
    if toks & _ADDITIVE_WEAK:
        return AGG_SUM
    if unit_kind == UNIT_CURRENCY:
        return AGG_SUM
    if stats.get("min", 0.0) < 0 and abs(stats.get("mean", 0.0)) < stats.get("std", 0.0):
        return AGG_AVG  # centred quantities (z-scores, deltas, temperatures)
    if stats.get("integer_share", 0.0) >= 0.999 and stats.get("min", 0.0) >= 0:
        return AGG_SUM  # counts
    return AGG_AVG


def _numeric_stats(vals: pd.Series) -> dict[str, Any]:
    mean = float(vals.mean())
    std = float(vals.std()) if len(vals) > 1 else 0.0
    return {
        "min": float(vals.min()),
        "max": float(vals.max()),
        "mean": mean,
        "median": float(vals.median()),
        "std": std,
        "sum": float(vals.sum()),
        "skew": float(vals.skew()) if len(vals) > 2 else 0.0,
        "cv": abs(std / mean) if mean else 0.0,
        "integer_share": float((vals % 1 == 0).mean()),
        "negative_share": float((vals < 0).mean()),
    }


def _classify_numeric(name: str, vals: pd.Series, hints: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    stats = _numeric_stats(vals)
    nunique = int(vals.nunique())
    integer_valued = stats["integer_share"] >= 0.999
    toks = set(name_tokens(name))

    if nunique <= 1:
        return ROLE_CONSTANT, stats
    if nunique == 2 and set(vals.unique()) <= {0, 1}:
        return ROLE_BOOLEAN, stats
    if name in hints.get("percent", ()) or (0.0 <= stats["min"] and stats["max"] <= 1.0 and not integer_valued):
        return ROLE_RATIO, stats
    if integer_valued and stats["min"] >= 1900 and stats["max"] <= 2100 and nunique <= 150:
        return ROLE_ORDINAL, stats  # calendar years behave like an ordered category
    additive_hint = bool(toks & (_ADDITIVE_EXPLICIT | _ADDITIVE_WEAK))
    if integer_valued and nunique <= 10 and not additive_hint:
        return ROLE_ORDINAL, stats  # ratings, star levels, small counts of categories
    return ROLE_MEASURE, stats


def _classify_text(strings: pd.Series, n_rows: int) -> tuple[str, dict[str, Any]]:
    nunique = int(strings.nunique())
    avg_len = float(strings.str.len().mean()) if len(strings) else 0.0
    uniq_ratio = nunique / max(len(strings), 1)
    stats: dict[str, Any] = {"avg_len": avg_len}
    if nunique <= 1:
        return ROLE_CONSTANT, stats
    if nunique <= 2 and set(strings.str.lower().unique()) <= _BOOL_TEXT:
        return ROLE_BOOLEAN, stats
    if avg_len > 60 or (avg_len > 30 and uniq_ratio > 0.5):
        return ROLE_TEXT, stats
    return (ROLE_LOW_CARDINALITY if nunique <= 7 else ROLE_HIGH_CARDINALITY), stats


def classify_column_role(col_name: str, ser: pd.Series, total_rows: int, hints: Optional[dict[str, Any]] = None) -> str:
    """Role of a single column (see module docstring)."""
    return _profile_column(str(col_name), ser, total_rows, hints or {})["role"]


def _top_values(ser: pd.Series, k: int = 5) -> list[dict[str, Any]]:
    counts = ser.astype(str).value_counts().head(k)
    total = max(int(ser.notna().sum()), 1)
    return [{"value": str(v), "count": int(c), "share": float(c) / total} for v, c in counts.items()]


def _profile_column(name: str, ser: pd.Series, total_rows: int, hints: dict[str, Any]) -> dict[str, Any]:
    non_null = ser.dropna()
    info: dict[str, Any] = {
        "dtype": str(ser.dtype),
        "nunique": int(non_null.nunique()),
        "null_count": int(ser.isna().sum()),
        "missing_pct": float(ser.isna().mean()) if total_rows else 0.0,
    }
    if non_null.empty:
        return {**info, "role": ROLE_CONSTANT}

    if pd.api.types.is_bool_dtype(ser):
        return {**info, "role": ROLE_BOOLEAN}

    is_numeric = pd.api.types.is_numeric_dtype(ser)
    dates, date_info = parse_datetimes(ser)
    if dates is not None and not (is_numeric and is_identifier_column(name, ser, total_rows)):
        valid = dates.dropna()
        info.update({"min_date": str(valid.min().date()), "max_date": str(valid.max().date()), "ambiguous_dates": date_info["ambiguous"]})
        return {**info, "role": ROLE_TEMPORAL}

    if is_identifier_column(name, ser, total_rows):
        return {**info, "role": ROLE_IDENTIFIER}

    if is_numeric:
        vals = pd.to_numeric(non_null, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if vals.empty:
            return {**info, "role": ROLE_CONSTANT}
        role, stats = _classify_numeric(name, vals, hints)
        info.update(stats)
        if role in (ROLE_ORDINAL, ROLE_BOOLEAN):
            info["top_values"] = _top_values(non_null)
        return {**info, "role": role}

    role, stats = _classify_text(non_null.astype(str), total_rows)
    info.update(stats)
    if role in (ROLE_LOW_CARDINALITY, ROLE_HIGH_CARDINALITY, ROLE_BOOLEAN):
        info["top_values"] = _top_values(non_null)
        counts = non_null.astype(str).value_counts(normalize=True)
        info["entropy"] = float(-(counts * np.log(counts)).sum() / math.log(len(counts))) if len(counts) > 1 else 0.0
    return {**info, "role": role}


# ---------------------------------------------------------------------------
# Public profile
# ---------------------------------------------------------------------------


def _measure_score(name: str, col: dict[str, Any]) -> float:
    """Which measure to feature first: covered, varied, and additive/monetary quantities win."""
    coverage = 1.0 - col.get("missing_pct", 0.0)
    variation = min(col.get("cv", 0.0), 3.0) / 3.0
    bonus = 0.0
    toks = set(name_tokens(name))
    if col.get("agg") == AGG_SUM:
        bonus += 0.6
    if col.get("unit_kind") == UNIT_CURRENCY:
        bonus += 0.4
    if toks & (_ADDITIVE_EXPLICIT | _ADDITIVE_WEAK):
        bonus += 0.4
    return 2.0 * coverage + variation + bonus


def _dimension_score(col: dict[str, Any], total_rows: int) -> float:
    """Prefer balanced, well-covered categories with a readable number of distinct values."""
    coverage = 1.0 - col.get("missing_pct", 0.0)
    balance = col.get("entropy", 0.5)
    nunique = col.get("nunique", 0)
    readable = 1.0 if 2 <= nunique <= 30 else (0.6 if nunique <= 200 else 0.2)
    return coverage + balance + readable


def profile_dataframe_universal(
    df: pd.DataFrame,
    labels: Optional[dict[str, str]] = None,
    hints: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Profile a DataFrame into roles, aggregation policies, time grain and quality warnings.

    Args:
        df: Data with safe column identifiers.
        labels: ``{identifier: display label}``; defaults to the identifiers themselves.
        hints: Ingest findings ``{"percent": [...], "currency": [...]}`` for percent/currency-formatted text.
    """
    hints = hints or {}
    total_rows, total_cols = len(df), len(df.columns)
    labels = {str(c): (labels or {}).get(str(c), str(c)) for c in df.columns}

    columns: dict[str, dict[str, Any]] = {}
    for col in df.columns:
        name = str(col)
        columns[name] = _profile_column(name, df[col], total_rows, hints)
        columns[name]["label"] = labels[name]

    by_role: dict[str, list[str]] = {}
    for name, info in columns.items():
        by_role.setdefault(info["role"], []).append(name)

    # Units and aggregation policy for numeric roles
    currency_hint = set(hints.get("currency", ()))
    for name in by_role.get(ROLE_MEASURE, []) + by_role.get(ROLE_RATIO, []) + by_role.get(ROLE_ORDINAL, []):
        info = columns[name]
        if info["role"] == ROLE_RATIO:
            info["unit_kind"] = UNIT_PERCENT
        elif name in currency_hint or is_monetary_name(name):
            info["unit_kind"] = UNIT_CURRENCY
        else:
            info["unit_kind"] = UNIT_PLAIN
        info["agg"] = agg_policy(name, info["role"], info, info["unit_kind"])

    measures = sorted(by_role.get(ROLE_MEASURE, []), key=lambda m: -_measure_score(m, columns[m]))
    ratio_cols = sorted(by_role.get(ROLE_RATIO, []), key=lambda m: -(1.0 - columns[m]["missing_pct"]))
    low = sorted(by_role.get(ROLE_LOW_CARDINALITY, []), key=lambda c: -_dimension_score(columns[c], total_rows))
    high = sorted(by_role.get(ROLE_HIGH_CARDINALITY, []), key=lambda c: -_dimension_score(columns[c], total_rows))
    ordinal = by_role.get(ROLE_ORDINAL, [])
    boolean = by_role.get(ROLE_BOOLEAN, [])
    temporal = by_role.get(ROLE_TEMPORAL, [])

    # Time axis: the temporal column with the widest, best covered span
    time: dict[str, Any] = {"primary": None}
    if temporal:
        def span_key(c: str) -> tuple[float, float]:
            info = columns[c]
            return (pd.Timestamp(info["max_date"]) - pd.Timestamp(info["min_date"])).days, -info["missing_pct"]

        primary = max(temporal, key=span_key)
        dates, _ = parse_datetimes(df[primary])
        time = {"primary": primary, **choose_time_grain(dates)}

    quality = _quality(df, columns, by_role)
    grain_key = next((c for c in df.columns if total_rows > 1 and columns[str(c)]["nunique"] == total_rows and columns[str(c)]["role"] in (ROLE_IDENTIFIER, ROLE_HIGH_CARDINALITY)), None)

    return {
        "total_rows": total_rows,
        "total_cols": total_cols,
        "labels": labels,
        "role_map": {c: i["role"] for c, i in columns.items()},
        "columns": columns,
        "column_stats": columns,
        "id_cols": by_role.get(ROLE_IDENTIFIER, []),
        "temporal_cols": temporal,
        "has_temporal": bool(temporal),
        "time": time,
        "measures": measures,
        "valid_measures": measures,
        "numeric_measures": measures,
        "ratio_cols": ratio_cols,
        "ordinal_cols": ordinal,
        "boolean_cols": boolean,
        "text_cols": by_role.get(ROLE_TEXT, []),
        "constant_cols": by_role.get(ROLE_CONSTANT, []),
        "low_card_dims": low,
        "high_card_dims": high,
        "categorical_low": low,
        "categorical_high": high,
        "dimensions": low + ordinal + high + boolean,
        "policies": {m: {"agg": columns[m]["agg"], "unit_kind": columns[m]["unit_kind"]} for m in measures + ratio_cols + ordinal},
        "quality": quality,
        "grain_key": str(grain_key) if grain_key is not None else None,
    }


def _quality(df: pd.DataFrame, columns: dict[str, dict[str, Any]], by_role: dict[str, list[str]]) -> dict[str, Any]:
    """Data-quality signals that later become caveats in the story (codes + params, never prose)."""
    warnings: list[dict[str, Any]] = []
    missing = {c: i["missing_pct"] for c, i in columns.items() if i["missing_pct"] >= 0.2}
    if missing:
        warnings.append({"code": "missing_high", "columns": missing})
    dup = int(df.duplicated().sum()) if len(df) else 0
    if len(df) and dup / len(df) >= 0.01:
        warnings.append({"code": "duplicate_rows", "count": dup, "share": dup / len(df)})
    if by_role.get(ROLE_CONSTANT):
        warnings.append({"code": "constant_columns", "columns": by_role[ROLE_CONSTANT]})
    ambiguous = [c for c, i in columns.items() if i.get("ambiguous_dates")]
    if ambiguous:
        warnings.append({"code": "ambiguous_dates", "columns": ambiguous})
    return {"warnings": warnings, "duplicate_rows": dup, "missing_cols": missing}


profile_dataframe = profile_dataframe_universal
