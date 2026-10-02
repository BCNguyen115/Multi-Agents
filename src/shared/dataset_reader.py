"""Format-agnostic tabular reader: raw bytes/text -> DataFrame plus how it was read.

Handles CSV/TSV with any common delimiter, Excel (.xlsx), Parquet and JSON so every
caller (gateway, data agent, sanitizer) shares one code path. Column names are returned
exactly as found in the file; renaming to safe identifiers happens in the layer above.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Union

import pandas as pd

from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

_CANDIDATE_DELIMITERS: tuple[str, ...] = (",", ";", "\t", "|")
_SNIFF_CHARS: int = 100_000
_CHARDET_SAMPLE_BYTES: int = 200_000


class DatasetReadError(ValueError):
    """Raised when an upload cannot be turned into a non-empty table.

    ``code`` is machine readable (``empty``, ``unsupported``, ``parse``) so callers can
    localise the message; ``str(exc)`` stays an English description for logs.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class ReadMeta:
    """How a table was read; surfaced to users so silent guesses become visible."""

    format: str = "csv"
    encoding: Optional[str] = None
    delimiter: Optional[str] = None
    sheet: Optional[str] = None
    sheets: list[str] = field(default_factory=list)
    # Machine-readable notes ({"code": ..., **params}) so the UI layer can localise them.
    notes: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Text decoding
# ---------------------------------------------------------------------------


def decode_bytes(raw_bytes: bytes) -> tuple[str, str]:
    """Decode bytes to text, returning ``(text, encoding_name)``.

    BOMs are honoured and stripped; otherwise ``chardet`` (on a bounded sample) proposes an
    encoding and a fallback chain is tried.
    """
    if not raw_bytes:
        return "", "utf-8"

    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return raw_bytes[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if raw_bytes.startswith(b"\xff\xfe"):
        return raw_bytes[2:].decode("utf-16-le", errors="replace"), "utf-16-le"
    if raw_bytes.startswith(b"\xfe\xff"):
        return raw_bytes[2:].decode("utf-16-be", errors="replace"), "utf-16-be"

    try:
        return raw_bytes.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    detected: Optional[str] = None
    try:
        import chardet

        detection = chardet.detect(raw_bytes[:_CHARDET_SAMPLE_BYTES])
        if detection.get("encoding") and detection.get("confidence", 0.0) > 0.5:
            detected = detection["encoding"]
    except ImportError:
        logger.warning("chardet not installed — falling back to the built-in encoding chain")

    for encoding in filter(None, [detected, "cp1252", "latin-1"]):
        try:
            return raw_bytes.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue

    return raw_bytes.decode("utf-8", errors="replace"), "utf-8"


def detect_and_convert_encoding(raw_bytes: bytes) -> str:
    """Decode raw bytes to a UTF-8 string with BOM stripped (text only)."""
    return decode_bytes(raw_bytes)[0]


# ---------------------------------------------------------------------------
# Delimiter sniffing
# ---------------------------------------------------------------------------


def sniff_delimiter(text: str) -> str:
    """Pick the delimiter that splits the leading lines into the most consistent field count."""
    lines = [ln for ln in text[:_SNIFF_CHARS].splitlines() if ln.strip()][:60]
    if not lines:
        return ","

    best, best_score = ",", (0.0, 0)
    for delim in _CANDIDATE_DELIMITERS:
        counts: list[int] = []
        for line in lines:
            try:
                counts.append(len(next(csv.reader([line], delimiter=delim))))
            except csv.Error:
                counts.append(1)
        mode = max(set(counts), key=counts.count)
        if mode < 2:
            continue
        score = (counts.count(mode) / len(counts), mode)
        if score > best_score:
            best, best_score = delim, score
    return best


# ---------------------------------------------------------------------------
# Format detection & readers
# ---------------------------------------------------------------------------


def _detect_format(raw: bytes, filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if raw[:4] == b"PAR1":
        return "parquet"
    if raw[:4] == b"PK\x03\x04" and ext in ("xlsx", "xlsm", ""):
        return "excel"
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise DatasetReadError("unsupported", "Legacy .xls files are not supported; save as .xlsx or CSV.")
    if ext in ("json", "jsonl", "ndjson"):
        return "json"
    stripped = raw[:2000].lstrip(b"\xef\xbb\xbf \t\r\n")
    if ext not in ("csv", "tsv", "txt") and stripped[:1] in (b"[", b"{"):
        return "json"
    return "csv"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten headers, trim header whitespace, and drop rows/columns that are entirely empty."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(p) for p in col if str(p) != "nan" and not str(p).startswith("Unnamed")).strip() for col in df.columns]
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    return df.reset_index(drop=True)


def _read_csv_text(text: str, meta: ReadMeta) -> pd.DataFrame:
    meta.delimiter = sniff_delimiter(text)
    # Everything is read as text so identifiers keep leading zeros ("007"); numeric/date/currency
    # inference is a deliberate, column-level step in the ingest layer.
    # The header row is read as data so duplicate/blank headers reach the sanitiser verbatim
    # (pandas would otherwise silently rename ``a, a`` to ``a, a.1``).
    options = {"sep": meta.delimiter, "skipinitialspace": True, "dtype": str, "header": None}
    try:
        frame = pd.read_csv(io.StringIO(text), **options)
    except pd.errors.ParserError:
        meta.notes.append({"code": "bad_lines_skipped"})
        frame = pd.read_csv(io.StringIO(text), on_bad_lines="skip", engine="python", **options)
    if frame.empty:
        raise pd.errors.EmptyDataError("no data")
    header = frame.iloc[0].fillna("").astype(str).tolist()
    frame = frame.iloc[1:].reset_index(drop=True)
    frame.columns = header
    return frame


def _read_excel(raw: bytes, meta: ReadMeta) -> pd.DataFrame:
    try:
        sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None, engine="openpyxl")
    except Exception as exc:
        raise DatasetReadError("parse", f"Cannot read Excel workbook: {exc}") from exc
    non_empty = {name: _clean(frame) for name, frame in sheets.items()}
    non_empty = {name: frame for name, frame in non_empty.items() if not frame.empty}
    meta.sheets = list(sheets.keys())
    if not non_empty:
        raise DatasetReadError("empty", "The workbook has no data.")
    chosen = max(non_empty, key=lambda n: non_empty[n].shape[0] * non_empty[n].shape[1])
    meta.sheet = chosen
    if len(sheets) > 1:
        meta.notes.append({"code": "multi_sheet", "count": len(sheets), "sheet": chosen})
    return non_empty[chosen]


def _read_json(text: str) -> pd.DataFrame:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            return pd.read_json(io.StringIO(text), lines=True)
        except ValueError as exc:
            raise DatasetReadError("parse", f"Invalid JSON: {exc}") from exc
    if isinstance(payload, dict):
        list_values = [v for v in payload.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        payload = list_values[0] if list_values else [payload]
    if not isinstance(payload, list) or not payload:
        raise DatasetReadError("empty", "The JSON document has no records.")
    return pd.json_normalize(payload)


def read_table(content: Union[bytes, str], filename: str = "") -> tuple[pd.DataFrame, ReadMeta]:
    """Read an uploaded file into a DataFrame, returning what was detected along the way."""
    meta = ReadMeta()
    try:
        if isinstance(content, str):
            meta.format = "json" if filename.lower().endswith((".json", ".jsonl", ".ndjson")) else "csv"
            text = content.lstrip("﻿")
            df = _read_json(text) if meta.format == "json" else _read_csv_text(text, meta)
        else:
            meta.format = _detect_format(content, filename)
            if meta.format == "parquet":
                df = pd.read_parquet(io.BytesIO(content))
            elif meta.format == "excel":
                df = _read_excel(content, meta)
            else:
                text, meta.encoding = decode_bytes(content)
                df = _read_json(text) if meta.format == "json" else _read_csv_text(text, meta)
    except DatasetReadError:
        raise
    except pd.errors.EmptyDataError as exc:
        raise DatasetReadError("empty", "The file is empty.") from exc
    except Exception as exc:
        raise DatasetReadError("parse", f"Cannot parse the file as {meta.format}: {exc}") from exc

    df = _clean(df)
    if df.shape[0] == 0 or df.shape[1] == 0:
        raise DatasetReadError("empty", "The file has no data rows.")
    return df, meta
