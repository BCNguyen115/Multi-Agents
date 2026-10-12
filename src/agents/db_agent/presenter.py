"""Query rows as a Markdown table, built by code and not by a model: every figure shown is a value the database returned.

The chat renders Markdown tables (ReactMarkdown + remark-gfm), so the table travels inside the reply's ``answer`` field. Numbers use a comma
for thousands (``12,641,672``) because the verifier's number check reads that form; years and ids are left bare.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Any

MAX_TABLE_ROWS = 20
MAX_CELL_CHARS = 60
_BARE = re.compile(r"(^|_)(year|month|day|id|code|number|no)$|_id$")


def format_cell(column: str, value: Any) -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "có" if value else "không"
    if isinstance(value, (int, float, Decimal)):
        if _BARE.search(column.lower()):
            return str(int(value)) if float(value).is_integer() else str(value)
        number = Decimal(str(value))
        if number == number.to_integral_value():
            return f"{int(number):,}"
        return f"{number:,.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    text = re.sub(r"\s+", " ", str(value)).strip().replace("|", "/")
    return text if len(text) <= MAX_CELL_CHARS else text[: MAX_CELL_CHARS - 1] + "…"


def markdown_table(rows: list[dict[str, Any]], limit: int = MAX_TABLE_ROWS) -> str:
    """A table of the first ``limit`` rows, with a note of how many more there are; ``""`` when there are no rows."""
    if not rows:
        return ""
    columns = list(rows[0].keys())
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(" --- " for _ in columns) + "|"]
    for row in rows[:limit]:
        lines.append("| " + " | ".join(format_cell(c, row.get(c)) for c in columns) + " |")
    if len(rows) > limit:
        lines.append(f"\n*… và {len(rows) - limit} dòng nữa (đủ {len(rows)} dòng trong kết quả).*")
    return "\n".join(lines)
