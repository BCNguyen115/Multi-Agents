"""Deterministic reading of what the user asked for (chart type, columns, Top-N).

Replaces the LLM "intent parser": the chart request is read from the query text and matched against the
*actual* column labels of the uploaded dataset, so it cannot invent a column.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

# First match wins, so specific chart words come before generic ones.
_CHART_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scatter", ("scatter", "phân tán", "tương quan", "correlation")),
    ("heatmap", ("heatmap", "bản đồ nhiệt")),
    ("treemap", ("treemap",)),
    ("waterfall", ("waterfall", "thác nước")),
    ("histogram", ("histogram", "phân phối", "distribution")),
    ("donut", ("donut", "pie", "biểu đồ tròn", "hình tròn", "tỷ trọng", "tỷ lệ", "cơ cấu", "share")),
    ("area", ("biểu đồ miền", "area chart", "area")),
    ("line", ("line", "biểu đồ đường", "xu hướng", "trend", "theo thời gian", "over time")),
    ("horizontal_bar", ("thanh ngang", "horizontal")),
    ("bar", ("biểu đồ cột", "bar", "cột", "top", "xếp hạng", "ranking", "rank")),
)
_TOP_N = re.compile(r"\btop\s*(\d{1,3})\b|\b(\d{1,3})\s*(?:hàng đầu|đầu tiên|first|best|leading)\b", re.IGNORECASE)


@dataclass
class QueryHints:
    chart_type: Optional[str] = None
    mentions: list[str] = field(default_factory=list)  # column identifiers in order of appearance
    top_n: Optional[int] = None

    def pick(self, profile: dict[str, Any], roles: tuple[str, ...]) -> Optional[str]:
        """First mentioned column whose profile role is one of ``roles``."""
        role_map = profile["role_map"]
        return next((c for c in self.mentions if role_map.get(c) in roles), None)


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D").lower())
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    return " " + re.sub(r"[^\w]+", " ", folded).strip() + " "


def parse_query_hints(query: str, profile: dict[str, Any]) -> QueryHints:
    """Chart type words, mentioned columns and Top-N found in ``query``."""
    hints = QueryHints()
    lowered = (query or "").lower()
    for chart_type, words in _CHART_WORDS:
        if any(w in lowered for w in words):
            hints.chart_type = chart_type
            break

    match = _TOP_N.search(lowered)
    if match:
        hints.top_n = int(match.group(1) or match.group(2))

    haystack = _norm(query or "")
    found: list[tuple[int, str]] = []
    for col in profile["role_map"]:
        for text in {profile["labels"].get(col, col), col}:
            needle = _norm(text)
            if len(needle.strip()) < 3:
                continue
            at = haystack.find(needle)
            if at >= 0:
                found.append((at, col))
                break
    hints.mentions = [col for _, col in sorted(found)]
    return hints
