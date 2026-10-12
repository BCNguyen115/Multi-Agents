"""The company snapshot: a fixed set of KPI queries per business domain, written and tested by hand.

When a manager asks "tình hình công ty" / "tổng quan nhân sự" the agent does not improvise SQL: it runs these queries (through the same validator,
table rules and read-only role as any other query), shows each as a table and lets a model write a short summary of THEIR rows. Only the domains the
caller may read are run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.agents.db_agent.schema_catalog import sql_tables


@dataclass(frozen=True)
class Kpi:
    domain: str
    title: str
    sql: str

    @property
    def tables(self) -> set[str]:
        return sql_tables(self.sql)


KPIS: list[Kpi] = [
    Kpi("hr", "Quân số theo phòng ban (đang làm việc)",
        "SELECT d.name AS department, COUNT(*) AS employees FROM aw.employee_department_history h JOIN aw.department d ON d.department_id = h.department_id "
        "JOIN aw.employee e ON e.business_entity_id = h.business_entity_id WHERE h.end_date IS NULL AND e.current_flag = 1 GROUP BY d.name ORDER BY employees DESC"),
    Kpi("hr", "Cơ cấu giới tính, thâm niên và tuổi trung bình",
        "SELECT gender, COUNT(*) AS employees, ROUND(AVG(({as_of} - hire_date) / 365.25), 1) AS avg_tenure_years, "
        "ROUND(AVG(({as_of} - birth_date) / 365.25), 1) AS avg_age FROM aw.employee WHERE current_flag = 1 GROUP BY gender"),
    Kpi("hr", "Chức danh đông nhân viên nhất",
        "SELECT job_title, COUNT(*) AS employees FROM aw.employee WHERE current_flag = 1 GROUP BY job_title ORDER BY employees DESC, job_title LIMIT 10"),
    Kpi("hr", "Lượt chuyển phòng ban (đã rời phòng ban cũ)",
        "SELECT d.name AS department, COUNT(*) AS left_department FROM aw.employee_department_history h JOIN aw.department d ON d.department_id = h.department_id "
        "WHERE h.end_date IS NOT NULL GROUP BY d.name ORDER BY left_department DESC, department"),
    Kpi("sales", "Doanh thu theo năm",
        "SELECT EXTRACT(YEAR FROM order_date)::int AS year, COUNT(*) AS orders, ROUND(SUM(sub_total), 0) AS revenue FROM aw.sales_order_header GROUP BY 1 ORDER BY 1"),
    Kpi("sales", "Doanh thu 12 tháng gần nhất theo khu vực",
        "SELECT t.name AS territory, ROUND(SUM(h.sub_total), 0) AS revenue FROM aw.sales_order_header h JOIN aw.sales_territory t ON t.territory_id = h.territory_id "
        "WHERE h.order_date >= {as_of} - INTERVAL '12 months' GROUP BY t.name ORDER BY revenue DESC"),
    Kpi("sales", "5 sản phẩm có doanh thu cao nhất",
        "SELECT p.name AS product, ROUND(SUM(d.line_total), 0) AS revenue FROM aw.sales_order_detail d JOIN aw.product p ON p.product_id = d.product_id "
        "GROUP BY p.name ORDER BY revenue DESC LIMIT 5"),
    Kpi("sales", "Kênh bán: online và cửa hàng",
        "SELECT CASE WHEN online_order_flag = 1 THEN 'online' ELSE 'store' END AS channel, COUNT(*) AS orders, ROUND(SUM(sub_total), 0) AS revenue "
        "FROM aw.sales_order_header GROUP BY 1 ORDER BY revenue DESC"),
    Kpi("purchasing", "Đơn mua hàng theo trạng thái",
        "SELECT status, COUNT(*) AS orders, ROUND(SUM(total_due), 0) AS total FROM aw.purchase_order_header GROUP BY status ORDER BY status"),
    Kpi("purchasing", "5 nhà cung cấp có giá trị mua lớn nhất",
        "SELECT v.name AS vendor, ROUND(SUM(h.total_due), 0) AS total FROM aw.purchase_order_header h JOIN aw.vendor v ON v.business_entity_id = h.vendor_id "
        "GROUP BY v.name ORDER BY total DESC LIMIT 5"),
    Kpi("production", "Sản phẩm tồn kho dưới mức an toàn (10 thiếu nhiều nhất)",
        "SELECT p.name AS product, SUM(i.quantity) AS on_hand, p.safety_stock_level FROM aw.product p JOIN aw.product_inventory i ON i.product_id = p.product_id "
        "GROUP BY p.product_id, p.name, p.safety_stock_level HAVING SUM(i.quantity) < p.safety_stock_level ORDER BY p.safety_stock_level - SUM(i.quantity) DESC LIMIT 10"),
    Kpi("production", "Tỷ lệ phế phẩm sản xuất theo năm",
        "SELECT EXTRACT(YEAR FROM start_date)::int AS year, SUM(order_qty) AS planned, SUM(scrapped_qty) AS scrapped, "
        "ROUND(100.0 * SUM(scrapped_qty) / NULLIF(SUM(order_qty), 0), 2) AS scrap_pct FROM aw.work_order GROUP BY 1 ORDER BY 1"),
]

_TRIGGER = re.compile(r"(tổng quan|tình hình|khảo sát|hiện trạng|báo cáo (nhanh|tổng hợp)|overview|snapshot|tong quan|tinh hinh|khao sat|hien trang)", re.IGNORECASE)
_DOMAIN_WORDS: dict[str, re.Pattern[str]] = {
    "hr": re.compile(r"(nhân sự|nhân viên|nhan su|nhan vien|\bhr\b|phòng ban|phong ban)", re.IGNORECASE),
    "sales": re.compile(r"(doanh số|doanh thu|bán hàng|khách hàng|doanh so|ban hang|khach hang|\bsales\b)", re.IGNORECASE),
    "purchasing": re.compile(r"(mua hàng|nhà cung cấp|mua hang|nha cung cap|purchas)", re.IGNORECASE),
    "production": re.compile(r"(sản xuất|tồn kho|kho hàng|san xuat|ton kho|production|inventory)", re.IGNORECASE),
}
MAX_WORDS = 14  # a longer question is a specific one ("tình hình doanh thu 2013 theo từng khu vực và kênh") and goes through the SQL path


def snapshot_request(query: str) -> Optional[set[str]]:
    """The domains a snapshot request names (all of them when it names none); ``None`` when the text is not a snapshot request."""
    if not _TRIGGER.search(query) or len(query.split()) > MAX_WORDS:
        return None
    named = {domain for domain, pattern in _DOMAIN_WORDS.items() if pattern.search(query)}
    return named or set(_DOMAIN_WORDS)


def kpis_for(domains: set[str], readable: set[str]) -> list[Kpi]:
    """The KPIs of ``domains`` whose tables the caller may read, in catalogue order."""
    return [k for k in KPIS if k.domain in domains and k.tables <= readable]
