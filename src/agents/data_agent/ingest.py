"""Dataset ingestion for the data agent.

read -> safe identifiers + display labels -> typed columns (numbers, currency, percent, dates) -> bounded sample.

Everything the pipeline later shows the user about *how* the file was interpreted (delimiter, sampled rows,
ambiguous dates, ...) is recorded in ``Dataset.meta['notes']`` as machine readable codes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Union

import numpy as np
import pandas as pd

from src.agents.data_agent.profiler import parse_datetimes
from src.config import settings
from src.shared.csv_sanitizer import sanitize_columns
from src.shared.dataset_reader import read_table
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

_CURRENCY_RE = re.compile(r"[$€£¥₫₹₩₽฿]|\b(?:USD|EUR|GBP|VND|JPY|CNY|INR|KRW)\b", re.IGNORECASE)
_US_GROUPED = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_EU_GROUPED = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$")
_COMMA_DECIMAL = re.compile(r"^-?\d+,\d{1,2}$")
_LEADING_ZERO = re.compile(r"^0\d+$")
_SPACES = re.compile(r"[\s ]")
_PARENS = re.compile(r"^\((.*)\)$")
_ACCEPT_RATIO = 0.95


@dataclass
class Dataset:
    """A loaded table: safe column identifiers, their original labels and how the file was read."""

    df: pd.DataFrame
    labels: dict[str, str]
    meta: dict[str, Any] = field(default_factory=dict)

    def hints(self) -> dict[str, Any]:
        """Ingest findings the profiler needs (percent/currency formatted columns)."""
        return {"percent": self.meta.get("percent_cols", []), "currency": self.meta.get("currency_cols", [])}


def _normalise_number_text(text: pd.Series, european: bool) -> pd.Series:
    cleaned = text.str.replace(_CURRENCY_RE, "", regex=True).str.replace(_SPACES, "", regex=True)
    cleaned = cleaned.str.rstrip("%").str.replace(_PARENS, r"-\1", regex=True)
    if european:
        cleaned = cleaned.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    else:
        cleaned = cleaned.str.replace(",", "", regex=False)
    return pd.to_numeric(cleaned, errors="coerce").replace([np.inf, -np.inf], np.nan)


def _to_numeric_column(series: pd.Series) -> tuple[Optional[pd.Series], dict[str, bool]]:
    """Convert a text column to numbers when >= 95 % of its values are numeric-looking.

    Understands ``$1,200``, ``1.234,56`` (European), ``12%`` (returned as a 0..1 fraction) and ``(500)``
    negatives. Zero-padded codes (``00123``) are deliberately left as text.
    """
    text = series.dropna().astype(str).str.strip()
    if text.empty:
        return None, {}
    sample = text.iloc[:: max(1, len(text) // 2000)].head(2000)
    if sample.str.match(_LEADING_ZERO).mean() > 0.3:
        return None, {}

    stripped = sample.str.replace(_CURRENCY_RE, "", regex=True).str.replace(_SPACES, "", regex=True)
    core = stripped.str.rstrip("%").str.replace(_PARENS, r"-\1", regex=True)
    european = (core.str.match(_EU_GROUPED) | core.str.match(_COMMA_DECIMAL)).sum() > core.str.match(_US_GROUPED).sum()

    if _normalise_number_text(sample, european).notna().mean() < _ACCEPT_RATIO:
        return None, {}

    numbers = _normalise_number_text(text, european)
    flags = {
        "percent": bool(stripped.str.endswith("%").mean() >= 0.5),
        "currency": bool(sample.str.contains(_CURRENCY_RE).mean() >= 0.5),
    }
    if flags["percent"]:
        numbers = numbers / 100.0
    result = pd.Series(np.nan, index=series.index, dtype="float64")
    result.loc[numbers.index] = numbers
    return result, flags


def coerce_types(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Give text columns their real type: numbers (incl. currency/percent text) and dates."""
    info: dict[str, list[str]] = {"percent_cols": [], "currency_cols": [], "ambiguous_date_cols": []}
    for col in df.columns:
        series = df[col]
        if not (series.dtype == object or pd.api.types.is_string_dtype(series)):
            continue
        numbers, flags = _to_numeric_column(series)
        if numbers is not None:
            df[col] = numbers
            if flags["percent"]:
                info["percent_cols"].append(str(col))
            if flags["currency"]:
                info["currency_cols"].append(str(col))
            continue
        dates, date_info = parse_datetimes(series)
        if dates is not None:
            df[col] = dates
            if date_info["ambiguous"]:
                info["ambiguous_date_cols"].append(str(col))
    return df, info


def load_dataset(
    content: Union[bytes, str],
    filename: str = "",
    max_rows: Optional[int] = None,
    seed: int = 0,
) -> Dataset:
    """Load any supported upload into a typed, bounded :class:`Dataset`.

    Raises:
        DatasetReadError: unreadable, unsupported or empty input.
    """
    df, read_meta = read_table(content, filename)
    ids, labels = sanitize_columns(df.columns)
    df.columns = pd.Index(ids)
    df, type_info = coerce_types(df)

    limit = max_rows or settings.DATA_MAX_ROWS
    rows_total = len(df)
    sampled = rows_total > limit
    if sampled:
        df = df.sample(n=limit, random_state=seed).sort_index().reset_index(drop=True)

    notes = list(read_meta.notes)
    if sampled:
        notes.append({"code": "sampled", "rows_used": len(df), "rows_total": rows_total})
    if type_info["ambiguous_date_cols"]:
        notes.append({"code": "ambiguous_dates", "columns": type_info["ambiguous_date_cols"]})

    meta = {
        "format": read_meta.format,
        "encoding": read_meta.encoding,
        "delimiter": read_meta.delimiter,
        "sheet": read_meta.sheet,
        "sheets": read_meta.sheets,
        "rows_total": rows_total,
        "rows_used": len(df),
        "sampled": sampled,
        "notes": notes,
        "percent_cols": type_info["percent_cols"],
        "currency_cols": type_info["currency_cols"],
    }
    logger.info("Dataset loaded: %d/%d rows x %d cols (%s)", len(df), rows_total, len(df.columns), read_meta.format)
    return Dataset(df=df, labels=labels, meta=meta)


def safe_read_csv(csv_content: Union[str, bytes], max_rows: Optional[int] = None) -> pd.DataFrame:
    """Parse a table into a typed DataFrame with safe identifiers, sampled exactly as the data agent samples it
    (so a verifier reloading the same content sees the same rows)."""
    return load_dataset(csv_content, max_rows=max_rows).df
