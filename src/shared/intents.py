"""Query-intent vocabulary shared by the orchestrator and the data agent.

One definition of "does the user want a dashboard / a single chart / text only / a summary" replaces the
copies that used to drift apart. Matching is accent-aware: Vietnamese typed *with* diacritics is matched
exactly (so ``vẽ`` "draw" is not confused with ``về`` "about"), Vietnamese typed *without* diacritics is
matched on folded text using unambiguous phrases only.
"""

from __future__ import annotations

import re
import unicodedata

_VIZ_KEYWORDS: tuple[str, ...] = (
    "dashboard", "biểu đồ", "chart", "graph", "plot", "visualiz", "visualis", "vẽ", "trực quan hóa",
    "dựng báo cáo", "phân bố", "tỷ trọng", "xu hướng", "trend", "biến động",
)
_TEXT_ONLY_KEYWORDS: tuple[str, ...] = (
    "không cần biểu đồ", "không dựng dashboard", "không vẽ chart", "dạng văn bản", "chỉ tóm tắt", "dạng text",
    "tóm tắt văn bản", "không sinh cấu trúc dashboard_spec", "no chart", "without chart", "text only", "just summar",
)
_SUMMARY_KEYWORDS: tuple[str, ...] = (
    "tóm tắt", "tổng quan", "mô tả dữ liệu", "thông tin về dữ liệu", "summary", "summarize", "summarise", "overview", "describe",
)
_SINGLE_CHART_KEYWORDS: tuple[str, ...] = (
    "single_chart", "single chart", "one chart", "tạo biểu đồ", "vẽ biểu đồ", "biểu đồ đường", "biểu đồ cột", "biểu đồ tròn",
    "biểu đồ miền", "biểu đồ xu hướng", "1 biểu đồ", "một biểu đồ", "chỉ vẽ", "chỉ tạo",
)
_FULL_DASHBOARD_KEYWORDS: tuple[str, ...] = (
    "full_dashboard", "dashboard", "executive dashboard", "báo cáo tổng quan", "báo cáo quản trị", "tất cả biểu đồ",
    "nhiều biểu đồ", "toàn bộ", "all charts", "full report",
)

_VI_ACCENT = re.compile(r"[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _matches(query: str, keywords: tuple[str, ...]) -> bool:
    lowered = query.lower()
    if any(k in lowered for k in keywords):
        return True
    if _VI_ACCENT.search(lowered):
        return False  # accented text was matched exactly above; folding would confuse "vẽ"/"về"
    folded = _fold(lowered)
    return any(len(folded_kw) > 2 and folded_kw in folded for folded_kw in map(_fold, keywords))


def is_text_only_request(query: str) -> bool:
    return _matches(query or "", _TEXT_ONLY_KEYWORDS)


def is_dashboard_request(query: str) -> bool:
    """True when the query asks for charts/dashboard and does not explicitly opt out of them."""
    query = query or ""
    return _matches(query, _VIZ_KEYWORDS) and not is_text_only_request(query)


def is_summary_request(query: str) -> bool:
    return _matches(query or "", _SUMMARY_KEYWORDS)


def wants_single_chart(query: str) -> bool:
    """A specific chart was requested (and the query is not asking for a whole dashboard)."""
    query = query or ""
    if _matches(query, _FULL_DASHBOARD_KEYWORDS):
        return False
    return _matches(query, _SINGLE_CHART_KEYWORDS)
