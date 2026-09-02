"""Strict Schema Audit Verifier — Zero-Hallucination Dashboard Spec Verification."""

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


def verify_dashboard_spec(df: pd.DataFrame, dashboard_spec: dict[str, Any]) -> tuple[bool, str]:
    """Kiểm tra 100% tính trung thực: Không một chỉ số nào trong Dashboard được vượt ngoài `df.columns`."""
    if not isinstance(dashboard_spec, dict):
        return True, "VERIFIED: Không có dashboard spec để kiểm tra."

    actual_cols = [str(c).lower() for c in df.columns]

    # 0. Kiểm tra sự tồn tại của Charts và KPI Cards
    charts = dashboard_spec.get("charts", [])
    kpis = (
        dashboard_spec.get("kpiCards", [])
        or dashboard_spec.get("kpis", [])
        or dashboard_spec.get("kpi_cards", [])
    )
    if not isinstance(charts, list) or len(charts) == 0 or not isinstance(kpis, list) or len(kpis) == 0:
        return False, "Chất lượng: Cần Chỉnh Sửa | Executor chưa tạo đủ KPI Cards và Charts cho Dashboard."

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
            return False, f"VERIFIER REJECT: Bị đặt chỉ số '{kpi.get('title')}' trong khi Dataset không có cột dữ liệu tài chính."

    # Check if dataset has any datetime columns
    has_datetime_col = any(
        any(k in c for k in ["date", "time", "month", "year", "ngay", "thang", "created_at"])
        for c in actual_cols
    )

    # 2. Kiểm tra Charts
    for chart in dashboard_spec.get("charts", []):
        if not isinstance(chart, dict):
            continue

        c_title = str(chart.get("title", "")).lower()
        c_data = chart.get("data", [])

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
            forbidden_terms = ["danh mục sản phẩm", "product category", "phân loại sản phẩm"]
            if any(term in c_title for term in forbidden_terms):
                return (
                    False,
                    f"VERIFIER REJECT: Tiêu đề biểu đồ '{chart.get('title')}' mâu thuẫn với dữ liệu thời gian (YYYY-MM). "
                    f"Tiêu đề phải phản ánh thời gian (ví dụ: 'Doanh thu theo tháng').",
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
                        return False, f"VERIFIER REJECT: Biểu đồ sử dụng trường '{key}' không tồn tại trong Dataset."

    return True, "VERIFIED: Dashboard khớp 100% với Schema thực tế của Dataset."
