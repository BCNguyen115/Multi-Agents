"""Table sanitisation pipeline for uploaded datasets.

Capabilities:
  1. Format-agnostic reading (CSV with any delimiter, Excel, Parquet, JSON) and encoding detection.
  2. Column-name sanitisation into stable, query-safe identifiers. Latin diacritics are folded
     (``Tên Sản Phẩm`` -> ``ten_san_pham``) but letters of every other script are preserved, and the
     original header is kept as a display label so nothing is lost for CJK/Cyrillic/Arabic/... data.
  3. Empty/corrupt row and column cleanup.

Usage:
    from src.shared.csv_sanitizer import clean_csv_content, sanitize_columns

    csv_text = clean_csv_content(raw_bytes, filename="sales.xlsx", sanitize_headers=False)
    ids, labels = sanitize_columns(df.columns)
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Iterable

import pandas as pd

from src.shared.dataset_reader import (  # noqa: F401  (detect_and_convert_encoding is re-exported)
    DatasetReadError,
    detect_and_convert_encoding,
    read_table,
)
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Maximum allowed column count for dataset sanitization
_MAX_COLUMN_COUNT: int = 100


def _remove_diacritics(text: str) -> str:
    """Fold Latin diacritics to ASCII; leave every other script untouched.

    Example: ``"Tên Sản Phẩm"`` -> ``"Ten San Pham"``, ``"Đơn Giá"`` -> ``"Don Gia"``.
    Combining marks are only dropped when they follow an ASCII letter, so Cyrillic ``й``,
    Thai tone marks, Devanagari vowel signs, etc. survive.
    """
    text = text.replace("Đ", "D").replace("đ", "d")
    kept: list[str] = []
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.category(ch) == "Mn" and kept and kept[-1].isascii() and kept[-1].isalpha():
            continue
        kept.append(ch)
    return unicodedata.normalize("NFC", "".join(kept))


def _slug(text: str) -> str:
    """Lower-case identifier keeping letters/digits of any script, underscores and combining marks."""
    text = re.sub(r"[\s\-\.]+", "_", _remove_diacritics(text))
    kept = "".join(
        ch for ch in text if ch == "_" or ch.isalnum() or unicodedata.category(ch) in ("Mn", "Mc")
    )
    return re.sub(r"_+", "_", kept).strip("_").lower()


def sanitize_columns(columns: Iterable[object]) -> tuple[list[str], dict[str, str]]:
    """Turn raw headers into unique safe identifiers plus a ``{identifier: original label}`` map.

    Numeric, NaN and ``Unnamed:`` headers become ``col_N``; duplicates get numeric suffixes.
    """
    ids: list[str] = []
    labels: dict[str, str] = {}
    used: set[str] = set()
    label_counts: dict[str, int] = {}

    for idx, col in enumerate(columns):
        raw = "" if pd.isna(col) else str(col).strip()
        auto = (not raw) or raw.lower() in ("nan", "none", "null") or raw.isdigit() or raw.startswith("Unnamed:")
        name = f"col_{idx}" if auto else (_slug(raw) or f"col_{idx}")
        if name.isdigit():
            name = f"col_{idx}"

        base, suffix = name, 0
        while name in used:
            suffix += 1
            name = f"{base}_{suffix}"
        used.add(name)

        label = name if auto else raw
        label_counts[label] = label_counts.get(label, 0) + 1
        if label_counts[label] > 1:
            label = f"{label} ({label_counts[label]})"

        ids.append(name)
        labels[name] = label
    return ids, labels


def sanitize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Rename DataFrame columns to safe identifiers (in place) — see :func:`sanitize_columns`."""
    ids, _ = sanitize_columns(df.columns)
    df.columns = pd.Index(ids)
    return df


def clean_csv_content(
    raw_bytes: bytes,
    max_columns: int = _MAX_COLUMN_COUNT,
    filename: str = "",
    sanitize_headers: bool = True,
) -> str:
    """Normalise an upload into a UTF-8, comma separated CSV string.

    Args:
        raw_bytes: Raw uploaded file content (CSV/TSV/Excel/Parquet/JSON).
        max_columns: Maximum number of allowed columns.
        filename: Original file name; helps format detection.
        sanitize_headers: ``True`` folds headers to identifiers (legacy behaviour, also used for the
            browser DuckDB engine); ``False`` keeps the original headers so display labels survive.

    Raises:
        ValueError: If the table exceeds ``max_columns`` (``DatasetReadError`` for unreadable files).
    """
    df, _meta = read_table(raw_bytes, filename)

    if len(df.columns) > max_columns:
        raise ValueError(
            f"CSV contains {len(df.columns)} columns, exceeding the maximum allowed limit of {max_columns} columns."
        )

    if sanitize_headers:
        df = sanitize_column_names(df)

    logger.info("Table normalisation complete: %d rows x %d cols", len(df), len(df.columns))
    return df.to_csv(index=False)
