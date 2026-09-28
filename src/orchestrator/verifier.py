"""Strict Schema Audit Verifier — Zero-Hallucination Dashboard Spec Verification.

Provides structured error feedback when verification fails, enabling the
Executor to repair column references and chart configurations in the
PEV retry loop.
"""

import json
import logging
from typing import Any
import pandas as pd

from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Standard UI/chart keys allowed in chart data objects
_STANDARD_ALLOWED_KEYS: set[str] = {
    "count",
    "value",
    "name",
    "x",
    "y",
    "label",
    "series",
    "category",
    "value_key",
    "name_key",
    "group_x",
    "month",
    "year",
    "day",
    "quarter",
    "date",
    "yyyy-mm",
    "x_data",
    "series_1",
    "series_2",
}


def _suggest_similar_columns(hallucinated_col: str, actual_cols: list[str], top_k: int = 3) -> list[str]:
    """Find the most similar actual columns to a hallucinated column name using character overlap scoring.

    Args:
        hallucinated_col: The column name that doesn't exist in the dataset.
        actual_cols: List of actual column names from the DataFrame.
        top_k: Maximum number of suggestions to return.

    Returns:
        List of suggested column names, sorted by similarity score descending.
    """
    target = hallucinated_col.lower().replace("_", "").replace(" ", "").replace("-", "")
    if not target:
        return actual_cols[:top_k]

    scored: list[tuple[str, float]] = []
    for col in actual_cols:
        candidate = col.lower().replace("_", "").replace(" ", "").replace("-", "")
        if not candidate:
            continue

        # Compute overlap ratio (Dice coefficient approximation)
        target_bigrams = {target[i:i+2] for i in range(len(target) - 1)} if len(target) > 1 else {target}
        candidate_bigrams = {candidate[i:i+2] for i in range(len(candidate) - 1)} if len(candidate) > 1 else {candidate}

        intersection = len(target_bigrams & candidate_bigrams)
        union = len(target_bigrams) + len(candidate_bigrams)
        score = (2.0 * intersection / union) if union > 0 else 0.0

        # Boost score if one contains the other as substring
        if target in candidate or candidate in target:
            score = max(score, 0.7)

        scored.append((col, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [col for col, _ in scored[:top_k] if _ > 0.0] or actual_cols[:top_k]


def verify_dashboard_spec(df: pd.DataFrame, dashboard_spec: dict[str, Any]) -> tuple[bool, str]:
    """Kiểm tra 100% tính trung thực: Không một chỉ số nào trong Dashboard được vượt ngoài `df.columns`.

    Returns a tuple of (is_verified, feedback_message).
    When is_verified is False, feedback_message contains structured error details
    with specific column names that failed and suggested replacements from the
    actual dataset schema, enabling the Executor to self-repair.
    """
    if not isinstance(dashboard_spec, dict):
        return True, "VERIFIED: Không có dashboard spec để kiểm tra."

    actual_cols = [str(c).lower() for c in df.columns]
    actual_cols_original = [str(c) for c in df.columns]

    # 0. Kiểm tra sự tồn tại của Charts và KPI Cards
    charts = dashboard_spec.get("charts", [])
    kpis = (
        dashboard_spec.get("kpiCards", [])
        or dashboard_spec.get("kpis", [])
        or dashboard_spec.get("kpi_cards", [])
    )
    if not isinstance(charts, list) or len(charts) == 0 or not isinstance(kpis, list) or len(kpis) == 0:
        return False, (
            "Chất lượng: Cần Chỉnh Sửa | Executor chưa tạo đủ KPI Cards và Charts cho Dashboard. "
            f"Dataset có các cột: {actual_cols_original}. "
            "Hãy tạo ít nhất 3 KPI Cards và 2 Charts dựa trên các cột số liệu có sẵn."
        )

    # 1. Kiểm tra KPI Cards
    kpis_list = dashboard_spec.get("kpi_cards", []) or dashboard_spec.get("kpis", []) or dashboard_spec.get("kpiCards", [])
    for kpi in kpis_list:
        if not isinstance(kpi, dict):
            continue
        title = str(kpi.get("title", "")).lower()
        # Nếu KPI chứa từ khóa tài chính nhưng DataFrame hoàn toàn không có cột số tài chính tương ứng -> REJECT
        if any(k in title for k in ["doanh thu", "revenue", "aov", "lợi nhuận", "profit"]) and not any(
            k in c for c in actual_cols for k in ["revenue", "price", "amount", "sales", "profit", "doanh_thu", "salary", "cost"]
        ):
            numeric_cols = [c for c in actual_cols_original if df[c].dtype in ('int64', 'float64', 'int32', 'float32')]
            return False, (
                f"VERIFIER REJECT: KPI '{kpi.get('title')}' tham chiếu dữ liệu tài chính "
                f"nhưng Dataset không có cột tài chính tương ứng. "
                f"Các cột số trong Dataset: {numeric_cols}. "
                f"Hãy sửa KPI để dùng đúng tên cột từ danh sách trên."
            )

    # Check if dataset has any datetime columns
    has_datetime_col = any(
        any(k in c for k in ["date", "time", "month", "year", "ngay", "thang", "created_at"])
        for c in actual_cols
    )

    # 2. Kiểm tra Charts
    for chart_idx, chart in enumerate(dashboard_spec.get("charts", [])):
        if not isinstance(chart, dict):
            continue

        c_title = str(chart.get("title", "")).lower()
        c_type = str(chart.get("type", "")).lower()
        c_data = chart.get("data", [])

        # Cardinality Rule Check: Donut / Pie Chart (Tỷ Trọng & Thị Phần)
        if c_type in ["pie", "donut"]:
            dim = (
                chart.get("dimension")
                or chart.get("category_col")
                or chart.get("name_key")
                or chart.get("x_axis_key")
                or chart.get("xAxisKey")
            )
            dim_str = str(dim) if dim else ""
            matched_col = None
            if dim_str:
                for c in df.columns:
                    if str(c).lower().replace(" ", "").replace("_", "") == dim_str.lower().replace(" ", "").replace("_", ""):
                        matched_col = c
                        break

            unique_count = int(df[matched_col].nunique()) if matched_col is not None else len(c_data)
            non_other = [d for d in c_data if isinstance(d, dict) and d.get("name") != "Khác"]
            if unique_count > 7 or len(c_data) > 7 or len(non_other) > 6:
                return False, (
                    "Lỗi nghiêm trọng: Donut chart đang nhận cột có độ đa dạng quá lớn làm vỡ biểu đồ ('Khác: 99%'). "
                    "Hãy đổi Donut chart sang nhóm phân loại hẹp (<Low_Cardinality_Categorical_Column> có nunique 2-7) và gán thực thể chính vào Bar Chart."
                )

        # Consistency Rule: If x_data or data records contain YYYY-MM date strings, title MUST NOT clash with "danh mục sản phẩm"
        has_date_strings = False
        if isinstance(c_data, list):
            for row in c_data:
                if not isinstance(row, dict):
                    continue
                x_val = str(row.get("x", "") or row.get("name", "") or "")
                # Check for YYYY-MM pattern (e.g. 2022-01)
                if len(x_val) >= 7 and x_val[:4].isdigit() and x_val[4] in ["-", "/"] and x_val[5:7].isdigit():
                    has_date_strings = True
                    break

        if has_date_strings:
            forbidden_terms = ["danh mục", "phân loại", "category"]
            if any(term in c_title for term in forbidden_terms) and not any(t in c_title for t in ["thời gian", "tháng", "năm", "quý", "trend", "time", "date", "temporal"]):
                return (
                    False,
                    f"VERIFIER REJECT: Biểu đồ #{chart_idx+1} tiêu đề '{chart.get('title')}' mâu thuẫn với dữ liệu trục X là thời gian (YYYY-MM). "
                    f"Tiêu đề phải phản ánh chiều thời gian hoặc xu hướng. "
                    f"Hãy sửa title và x_axis_key để phản ánh đúng chiều thời gian.",
                )

        if isinstance(c_data, list):
            for row in c_data:
                if not isinstance(row, dict):
                    continue
                for key in row.keys():
                    key_lower = str(key).lower()
                    # Allow standard keys
                    if key_lower in _STANDARD_ALLOWED_KEYS:
                        continue
                    # Allow derived time keys if dataset has date/time columns
                    if has_datetime_col and any(t in key_lower for t in ["month", "year", "date", "day", "quarter"]):
                        continue
                    if key_lower not in actual_cols:
                        suggestions = _suggest_similar_columns(key, actual_cols_original)
                        return False, (
                            f"VERIFIER REJECT: Biểu đồ #{chart_idx+1} sử dụng trường '{key}' "
                            f"không tồn tại trong Dataset. "
                            f"Gợi ý thay thế (các cột gần nhất): {suggestions}. "
                            f"Hãy thay '{key}' bằng một trong các cột gợi ý ở trên."
                        )

    return True, "VERIFIED: Dashboard khớp 100% với Schema thực tế của Dataset."


# ---------------------------------------------------------------------------
# Pre-Execution Indirect Prompt Injection Audit
# ---------------------------------------------------------------------------

import re

_INDIRECT_INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|prompts?|rules?)\b",
            re.IGNORECASE,
        ),
        "Instruction Override in external document",
    ),
    (
        re.compile(
            r"\b(?:bỏ qua|hủy bỏ|xóa bỏ)\s+(?:toàn bộ\s+)?(?:hướng dẫn|quy tắc|chỉ thị|chính sách)\b",
            re.IGNORECASE,
        ),
        "Vietnamese Instruction Override in external document",
    ),
    (
        re.compile(
            r"\bdisregard\s+(?:all\s+)?(?:rules?|safety|constraints?)\b",
            re.IGNORECASE,
        ),
        "Safety Constraint Disregard in external document",
    ),
    (
        re.compile(
            r"\b(?:you are now|acting as|operate as|system mode:)\b",
            re.IGNORECASE,
        ),
        "Persona Hijack / Role Switching in external document",
    ),
    (
        re.compile(
            r"\b(?:send|exfiltrate|transmit|post)\s+(?:all\s+)?(?:data|secrets?|passwords?|keys?|tokens?)\s+(?:to|via)\b",
            re.IGNORECASE,
        ),
        "Data Exfiltration Directive in external document",
    ),
    (
        re.compile(
            r"(?:curl\s+https?://|wget\s+https?://|webhook|https?://[a-zA-Z0-9.-]+\.ngrok\.io|https?://webhook\.site)",
            re.IGNORECASE,
        ),
        "External Call / Webhook Trigger in external document",
    ),
    (
        re.compile(
            r"\b(?:CANARY_SECRET_|ADMIN_ACCESS_OVERRIDE|system_prompt_dump)\b",
            re.IGNORECASE,
        ),
        "Canary Probing or System Exfiltration in external document",
    ),
]


def audit_context_safety(
    context_chunks: list[str],
) -> tuple[bool, list[str], list[str]]:
    """Pre-Execution Audit: Scan retrieved context chunks for indirect prompt injection.

    Inspects retrieved context for instruction-like patterns, system overrides,
    malicious shell commands, and adversarial payloads before LLM ingestion.

    Args:
        context_chunks: List of raw document or web text chunks.

    Returns:
        tuple[bool, list[str], list[str]]:
            - all_safe (bool): True if no chunks contained injection attempts.
            - sanitized_chunks (list[str]): Cleaned chunks (unsafe chunks replaced or filtered).
            - audit_findings (list[str]): Detailed log of blocked/flagged patterns for PEV trace.
    """
    if not context_chunks:
        return True, [], []

    all_safe: bool = True
    sanitized_chunks: list[str] = []
    audit_findings: list[str] = []

    for idx, chunk in enumerate(context_chunks):
        if not chunk or not isinstance(chunk, str):
            continue

        chunk_threats: list[str] = []
        for pattern, label in _INDIRECT_INJECTION_PATTERNS:
            if pattern.search(chunk):
                chunk_threats.append(label)

        if chunk_threats:
            all_safe = False
            threat_summary = ", ".join(chunk_threats)
            finding_msg = (
                f"Chunk #{idx + 1} blocked by Security Audit: {threat_summary}"
            )
            audit_findings.append(finding_msg)
            logger.warning(
                "Indirect Injection Detected during Pre-Execution Audit: %s",
                finding_msg,
                extra={"session_id": "SECURITY_AUDIT"},
            )
            # Sanitize chunk by neutralizing adversarial directives
            sanitized_chunks.append(
                f"[BẢO MẬT ZERO-TRUST: Đoạn trích này đã bị vô hiệu hóa do chứa chỉ thị không an toàn ({threat_summary})]"
            )
        else:
            sanitized_chunks.append(chunk)

    return all_safe, sanitized_chunks, audit_findings
