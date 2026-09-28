"""CSV Data Sanitization Pipeline.

Provides a centralised set of utilities for cleaning CSV data before it enters
the Data Analyst Agent Swarm or DuckDB WASM in the frontend.

Capabilities:
  1. Automatic encoding detection via ``chardet`` with UTF-8 conversion.
  2. Column name sanitisation: strip whitespace, remove special characters,
     convert Vietnamese diacritics to ASCII-safe slugs using ``unicodedata``.
  3. Empty/corrupt row and header cleanup.

Usage:
    from src.shared.csv_sanitizer import clean_csv_content, sanitize_column_names

    utf8_str = clean_csv_content(raw_bytes)
    df = sanitize_column_names(df)
"""

import io
import logging
import re
import unicodedata
from typing import Optional

import pandas as pd

from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Maximum allowed column count for dataset sanitization
_MAX_COLUMN_COUNT: int = 100


def _remove_diacritics(text: str) -> str:
    """Remove Vietnamese diacritics and accented characters via NFD decomposition.

    Example: ``"Tên Sản Phẩm"`` → ``"Ten San Pham"``
             ``"Đơn Giá"`` → ``"Don Gia"``

    Args:
        text: Input string potentially containing diacritical marks.

    Returns:
        str: ASCII-safe string with diacritics removed.
    """
    # Handle Vietnamese Đ/đ explicitly (not decomposable via NFD)
    text = text.replace("Đ", "D").replace("đ", "d")
    # Normalize to NFD (decomposed form) — separates base char from combining marks
    nfkd: str = unicodedata.normalize("NFD", text)
    # Filter out combining characters (category 'Mn' = Mark, Nonspacing)
    ascii_chars: str = "".join(
        c for c in nfkd if unicodedata.category(c) != "Mn"
    )
    return ascii_chars


def sanitize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Sanitise DataFrame column names into clean, ASCII-safe snake_case.

    Transformations applied:
      1. Replace numeric, nan, or Unnamed headers with col_N.
      2. Strip leading/trailing whitespace.
      3. Remove Vietnamese diacritics (``Tên`` → ``Ten``).
      4. Replace spaces, hyphens, and dots with underscores.
      5. Remove remaining special characters (keep alphanumeric + underscore).
      6. Collapse consecutive underscores.
      7. Convert to lowercase.

    Args:
        df: Input DataFrame with potentially dirty column names.

    Returns:
        pd.DataFrame: DataFrame with cleaned column names (modified in-place).
    """
    new_columns: list[str] = []

    for idx, col in enumerate(df.columns):
        col_str: str = str(col).strip()
        # Handle nan, all-numeric headers (e.g. 0, 1), and Unnamed: N
        if (
            pd.isna(col)
            or col_str.lower() in ("nan", "none", "null")
            or col_str.isdigit()
            or col_str.startswith("Unnamed:")
        ):
            name = f"col_{idx}"
        else:
            name = col_str
            # Remove diacritics (Vietnamese / accented chars)
            name = _remove_diacritics(name)
            # Replace spaces, hyphens, dots with underscore
            name = re.sub(r"[\s\-\.]+", "_", name)
            # Remove all non-alphanumeric characters except underscore
            name = re.sub(r"[^a-zA-Z0-9_]", "", name)
            # Collapse multiple underscores
            name = re.sub(r"_+", "_", name)
            # Strip leading/trailing underscores and lowercase
            name = name.strip("_").lower()

            # Fallback for empty or purely numeric column names
            if not name or name.isdigit():
                name = f"col_{idx}"

        new_columns.append(name)

    # Handle duplicate column names by appending suffix
    seen: dict[str, int] = {}
    deduplicated: list[str] = []
    for name in new_columns:
        if name in seen:
            seen[name] += 1
            deduplicated.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 0
            deduplicated.append(name)

    df.columns = pd.Index(deduplicated)
    return df


def detect_and_convert_encoding(raw_bytes: bytes) -> str:
    """Detect the encoding of raw bytes and convert to UTF-8 string with BOM stripping.

    Uses ``chardet`` for automatic detection with a confidence threshold.
    Falls back through common encodings if detection fails.

    Args:
        raw_bytes: Raw file content as bytes.

    Returns:
        str: The file content decoded as a UTF-8 string without BOM.
    """
    if not raw_bytes:
        return ""

    # Explicit BOM detection & stripping
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return raw_bytes[3:].decode("utf-8", errors="replace")
    if raw_bytes.startswith(b"\xff\xfe"):
        return raw_bytes[2:].decode("utf-16-le", errors="replace")
    if raw_bytes.startswith(b"\xfe\xff"):
        return raw_bytes[2:].decode("utf-16-be", errors="replace")

    try:
        import chardet
    except ImportError:
        logger.warning("chardet not installed — falling back to utf-8 decode")
        return raw_bytes.decode("utf-8", errors="replace")

    detection: dict = chardet.detect(raw_bytes)
    detected_encoding: Optional[str] = detection.get("encoding")
    confidence: float = detection.get("confidence", 0.0)

    logger.info(
        "Encoding detection: encoding=%s, confidence=%.2f",
        detected_encoding,
        confidence,
    )

    # Try detected encoding first (if confidence is reasonable)
    if detected_encoding and confidence > 0.5:
        try:
            return raw_bytes.decode(detected_encoding)
        except (UnicodeDecodeError, LookupError):
            pass

    # Fallback chain
    fallback_encodings: list[str] = [
        "utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1",
    ]
    for enc in fallback_encodings:
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue

    # Last resort: replace errors
    logger.warning("All encoding attempts failed — using UTF-8 with error replacement")
    return raw_bytes.decode("utf-8", errors="replace")


def clean_csv_content(
    raw_bytes: bytes,
    remove_empty_rows: bool = True,
    max_columns: int = _MAX_COLUMN_COUNT,
) -> str:
    """Full CSV cleaning pipeline: detect encoding → convert → sanitise headers.

    This function produces a clean UTF-8 CSV string suitable for both the
    Python Data Agent (pandas) and the browser DuckDB WASM engine.

    Args:
        raw_bytes: Raw uploaded file content.
        remove_empty_rows: Whether to strip fully-empty rows.
        max_columns: Maximum number of allowed columns (default: _MAX_COLUMN_COUNT).

    Returns:
        str: Cleaned CSV content as a UTF-8 string with sanitised headers.

    Raises:
        ValueError: If CSV column count exceeds max_columns limit.
    """
    # Step 1: Detect encoding and convert to string
    csv_text: str = detect_and_convert_encoding(raw_bytes)

    # Step 2: Read into DataFrame for header sanitisation
    try:
        df: pd.DataFrame = pd.read_csv(io.StringIO(csv_text))
    except Exception:
        # Try with flexible delimiter detection
        try:
            df = pd.read_csv(io.StringIO(csv_text), sep=None, engine="python")
        except Exception as exc:
            logger.error("CSV parsing failed even with flexible delimiter: %s", exc)
            return csv_text

    # Guard against excessively wide CSVs
    if len(df.columns) > max_columns:
        raise ValueError(
            f"CSV contains {len(df.columns)} columns, exceeding the maximum allowed limit of {max_columns} columns."
        )

    # Step 3: Sanitise column names
    df = sanitize_column_names(df)

    # Step 4: Remove fully-empty rows
    if remove_empty_rows:
        original_len: int = len(df)
        df = df.dropna(how="all").reset_index(drop=True)
        removed: int = original_len - len(df)
        if removed > 0:
            logger.info("Removed %d fully-empty rows from CSV", removed)

    # Step 5: Convert back to CSV string
    clean_csv: str = df.to_csv(index=False)

    logger.info(
        "CSV sanitisation complete: %d rows x %d cols, columns=%s",
        len(df),
        len(df.columns),
        list(df.columns),
    )

    return clean_csv
