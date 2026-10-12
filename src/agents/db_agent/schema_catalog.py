"""What the SQL agent knows about the company database, and who may ask about which part of it.

``SchemaCatalog`` is a snapshot of schema ``aw`` (columns come from the database, so the prompt never drifts from the real tables; descriptions,
code meanings and metric definitions come from ``src/ingestion/aw_catalog.py``). Access is decided per business DOMAIN
(``DB_AGENT_DOMAIN_ROLES``: hr, sales, purchasing, production; administrators have all):

  * the model is only shown the tables of the domains the caller may read, so it cannot even ask for the others;
  * ``allowed_tables`` hands the validator the same set, and the validator refuses anything else, whatever the model wrote.

The boundary between domains is therefore enforced by the application (prompt + AST validator); the database role itself can read every loaded
``aw`` table (see ``docs/DB_AGENT.md``).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from src.config import settings
from src.ingestion import aw_catalog as aw
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

_SHORT_TYPES = {"integer": "int", "smallint": "smallint", "bigint": "bigint", "timestamp without time zone": "timestamp", "time without time zone": "time"}

# (question, SQL): shown to the model when the caller may read every table the SQL uses. Every one of them runs against the real data (tests).
EXAMPLES: list[tuple[str, str]] = [
    ("Mỗi phòng ban hiện có bao nhiêu nhân viên?",
     "SELECT d.name AS department, COUNT(*) AS employees FROM aw.employee_department_history h JOIN aw.department d ON d.department_id = h.department_id "
     "JOIN aw.employee e ON e.business_entity_id = h.business_entity_id WHERE h.end_date IS NULL AND e.current_flag = 1 GROUP BY d.name ORDER BY employees DESC"),
    ("Cơ cấu giới tính, tuổi và thâm niên trung bình của nhân viên?",
     "SELECT gender, COUNT(*) AS employees, ROUND(AVG(({as_of} - hire_date) / 365.25), 1) AS avg_tenure_years, "
     "ROUND(AVG(({as_of} - birth_date) / 365.25), 1) AS avg_age FROM aw.employee WHERE current_flag = 1 GROUP BY gender"),
    ("10 nhân viên có thâm niên lâu nhất?",
     "SELECT p.first_name, p.last_name, e.job_title, e.hire_date FROM aw.employee e JOIN aw.person p ON p.business_entity_id = e.business_entity_id "
     "WHERE e.current_flag = 1 ORDER BY e.hire_date LIMIT 10"),
    ("Mức lương theo giờ hiện tại trung bình theo chức danh?",
     "SELECT e.job_title, ROUND(AVG(p.rate), 2) AS avg_hourly_rate FROM aw.employee e JOIN aw.employee_pay_history p ON p.business_entity_id = e.business_entity_id "
     "WHERE p.rate_change_date = (SELECT MAX(x.rate_change_date) FROM aw.employee_pay_history x WHERE x.business_entity_id = e.business_entity_id) "
     "GROUP BY e.job_title ORDER BY avg_hourly_rate DESC LIMIT 15"),
    ("Doanh thu từng năm?",
     "SELECT EXTRACT(YEAR FROM order_date)::int AS year, COUNT(*) AS orders, ROUND(SUM(sub_total), 0) AS revenue FROM aw.sales_order_header GROUP BY 1 ORDER BY 1"),
    ("Doanh thu 12 tháng gần nhất theo khu vực?",
     "SELECT t.name AS territory, ROUND(SUM(h.sub_total), 0) AS revenue FROM aw.sales_order_header h JOIN aw.sales_territory t ON t.territory_id = h.territory_id "
     "WHERE h.order_date >= (SELECT MAX(order_date) FROM aw.sales_order_header) - INTERVAL '12 months' GROUP BY t.name ORDER BY revenue DESC"),
    ("5 sản phẩm bán chạy nhất theo doanh thu?",
     "SELECT p.name AS product, ROUND(SUM(d.line_total), 0) AS revenue FROM aw.sales_order_detail d JOIN aw.product p ON p.product_id = d.product_id "
     "GROUP BY p.name ORDER BY revenue DESC LIMIT 5"),
    ("Đơn mua hàng theo trạng thái và nhà cung cấp lớn nhất?",
     "SELECT v.name AS vendor, COUNT(*) AS orders, ROUND(SUM(h.total_due), 0) AS total FROM aw.purchase_order_header h JOIN aw.vendor v ON v.business_entity_id = h.vendor_id "
     "GROUP BY v.name ORDER BY total DESC LIMIT 10"),
    ("Sản phẩm nào đang tồn kho dưới mức an toàn?",
     "SELECT p.name AS product, SUM(i.quantity) AS on_hand, p.safety_stock_level FROM aw.product p JOIN aw.product_inventory i ON i.product_id = p.product_id "
     "GROUP BY p.product_id, p.name, p.safety_stock_level HAVING SUM(i.quantity) < p.safety_stock_level ORDER BY p.safety_stock_level - SUM(i.quantity) DESC LIMIT 10"),
    ("Tỷ lệ phế phẩm sản xuất theo năm?",
     "SELECT EXTRACT(YEAR FROM start_date)::int AS year, SUM(order_qty) AS planned, SUM(scrapped_qty) AS scrapped, "
     "ROUND(100.0 * SUM(scrapped_qty) / NULLIF(SUM(order_qty), 0), 2) AS scrap_pct FROM aw.work_order GROUP BY 1 ORDER BY 1"),
]
_TABLE_REF = re.compile(r"\baw\.([a-z_]+)")


def sql_tables(sql: str) -> set[str]:
    return set(_TABLE_REF.findall(sql))


def as_of_literal(as_of: Optional[dt.date]) -> str:
    """The SQL for "today" in the data: its last day as a date literal (the agent never uses now(): the data stops in 2014)."""
    return f"DATE '{as_of.isoformat()}'" if as_of else "CURRENT_DATE"


def render_as_of(sql: str, as_of: Optional[dt.date]) -> str:
    """``{as_of}`` in a catalogue statement -> the date literal. It is a date literal and not a subquery on purpose: the HR domain may not read
    the sales tables the last order date would come from."""
    return sql.replace("{as_of}", as_of_literal(as_of))


@dataclass
class SchemaCatalog:
    """Columns of schema ``aw`` (``{table: [(column, type), ...]}``) and the date the data runs up to."""

    columns: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    as_of: Optional[dt.date] = None

    @property
    def available(self) -> bool:
        return bool(self.columns)

    @classmethod
    async def load(cls, pg: Any) -> "SchemaCatalog":
        """Read the snapshot with the application's pool; an empty catalog (no schema ``aw``) makes the agent behave as before."""
        columns: dict[str, list[tuple[str, str]]] = {}
        try:
            rows = await pg.fetch(
                "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = $1 ORDER BY table_name, ordinal_position", aw.SCHEMA
            )
            for row in rows:
                columns.setdefault(row["table_name"], []).append((row["column_name"], _SHORT_TYPES.get(row["data_type"], row["data_type"])))
            as_of = None
            if "sales_order_header" in columns:
                as_of = (await pg.fetch("SELECT MAX(order_date) AS as_of FROM aw.sales_order_header"))[0]["as_of"]
        except Exception as exc:  # noqa: BLE001 - no company data is a normal state, not an error
            logger.warning("SQL agent: could not read the company schema (%s); it answers about the knowledge-base tables only", exc)
            return cls()
        return cls(columns=columns, as_of=as_of)


def principal_domains(principal: Any) -> set[str]:
    """The business domains the caller may ask about: none for nobody / a pending account, all for an administrator, else by role."""
    if principal is None or getattr(principal, "unassigned", False):
        return set()
    if principal.can_admin:
        return set(aw.DOMAINS)
    roles = set(principal.roles)
    return {domain for domain, allowed in settings.DB_AGENT_DOMAIN_ROLES.items() if domain in aw.DOMAINS and roles & set(allowed)}


def readable_tables(catalog: SchemaCatalog, principal: Any) -> set[str]:
    """Loaded ``aw`` tables of the caller's domains."""
    return set(aw.tables_for(principal_domains(principal))) & set(catalog.columns)


def allowed_tables(catalog: SchemaCatalog, principal: Any) -> dict[str, set[str]]:
    """What ``validate_sql(allowed_tables=...)`` takes: ``{"aw": {...}}`` plus the knowledge-base tables for an administrator."""
    allowed: dict[str, set[str]] = {aw.SCHEMA: readable_tables(catalog, principal)}
    if principal is not None and principal.can_admin:
        allowed["public"] = {t.lower() for t in settings.DB_AGENT_TABLES}
    return allowed


def build_prompt(catalog: SchemaCatalog, principal: Any) -> str:
    """The system prompt for this caller: only the tables of their domains, the definitions that concern them, and examples that fit."""
    tables = readable_tables(catalog, principal)
    lines = [
        "Bạn là chuyên gia dữ liệu doanh nghiệp (PostgreSQL) phục vụ Nhân sự và Ban lãnh đạo: biến câu hỏi tiếng Việt thành MỘT câu SQL SELECT chính xác.",
        f"Dữ liệu là của công ty AdventureWorks, schema `{aw.SCHEMA}`. Ngày hiện tại của dữ liệu là {catalog.as_of or 'không rõ'}: "
        f"dùng {as_of_literal(catalog.as_of)} thay cho now()/CURRENT_DATE khi nói 'hiện tại', 'năm nay', '12 tháng gần nhất'.",
        "",
        "BẢNG ĐƯỢC PHÉP (chỉ dùng các bảng này, luôn viết `aw.<bảng>`):",
    ]
    for table in sorted(tables):
        cols = ", ".join(f"{name} {kind}" for name, kind in catalog.columns[table])
        doc = aw.table_doc(table)
        lines.append(f"- aw.{table}({cols})" + (f" -- {doc}" if doc else ""))
    if not tables:
        lines.append("- (không có bảng nào: người dùng này chưa được cấp quyền xem dữ liệu công ty)")
    for title, items in (("Ý NGHĨA MÃ", aw.CODE_MEANINGS), ("ĐỊNH NGHĨA CHỈ SỐ", aw.METRICS), ("QUAN HỆ GIỮA CÁC BẢNG", aw.JOIN_HINTS)):
        found = aw.relevant(items, tables)
        if found:
            lines += ["", f"{title}:", *[f"- {text}" for text in found]]
    examples = [(q, s) for q, s in EXAMPLES if sql_tables(s) <= tables]
    if examples:
        lines += ["", "VÍ DỤ (câu hỏi -> SQL):", *[f"Q: {q}\nSQL: {render_as_of(s, catalog.as_of)}" for q, s in examples]]
    lines += [
        "",
        "QUY TẮC:",
        "1. Chỉ một câu SELECT hoặc WITH ... SELECT. Cấm INSERT, UPDATE, DELETE, DROP và mọi thay đổi dữ liệu.",
        "2. Tính tỷ lệ, phần trăm, trung bình bằng SQL (ROUND(..., 2)); không để người đọc phải tự tính.",
        "3. Luôn đặt tên cột kết quả bằng AS (tiếng Anh, snake_case), sắp xếp có ý nghĩa và thêm LIMIT khi liệt kê.",
        "4. Không đưa thông tin cá nhân không cần thiết (ngày sinh, tên) khi câu hỏi chỉ cần số liệu tổng hợp.",
        "5. Nếu câu hỏi không thể trả lời bằng các bảng ở trên, trả về JSON với sql rỗng và nói rõ lý do trong explanation.",
        "6. Trả về DUY NHẤT một khối JSON: ```json\n{\"sql\": \"<SELECT>\", \"explanation\": \"<giải thích ngắn bằng tiếng Việt>\"}\n```",
    ]
    return "\n".join(lines)
