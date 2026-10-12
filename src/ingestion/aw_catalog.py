"""The AdventureWorks sample company (``dataset/archive``: one xlsx per table) as the SQL agent sees it: what is loaded into schema ``aw``,
how it is cleaned, which business domain each table belongs to, and what the codes mean.

One place for every rule, used by the loader (``scripts/load_adventureworks.py``) and by the agent (``src/agents/db_agent/schema_catalog.py``):

  * names: ``Sales.SalesOrderHeader`` -> ``aw.sales_order_header``, ``OrderDate`` -> ``order_date``;
  * what is NOT loaded: credentials, card numbers, contact details, national ids, XML/spatial blobs, ``rowguid`` and ``ModifiedDate``;
  * repairs of the files themselves: a literal ``'NULL'`` text is a NULL, and Excel turned the ``SalesOrderID`` of three sheets into dates
    (43659 became 2019-07-13), so an id column holding dates is turned back into the serial number;
  * domains (``hr``, ``sales``, ``purchasing``, ``production``): who may ask about a table is decided by domain, never by table by table lists.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Any, Iterable, Optional

SCHEMA = "aw"
SOURCE_PREFIXES = ("HumanResources", "Person", "Production", "Purchasing", "Sales")
DOMAINS = ("hr", "sales", "purchasing", "production")
EXCEL_EPOCH = dt.date(1899, 12, 30)

# Sensitive by nature: never loaded.
EXCLUDED_TABLES = frozenset({"password", "credit_card", "person_credit_card", "email_address", "person_phone"})  # names as table_name() gives them
DROPPED_COLUMNS = frozenset({
    "rowguid", "modified_date", "organization_node", "national_id_number", "login_id", "demographics", "additional_contact_info", "resume",
    "spatial_location", "credit_card_id", "credit_card_approval_code", "name_style", "email_promotion", "password_hash", "password_salt",
})
RENAMED_COLUMNS = {"group": "region_group"}  # a reserved word

_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def snake(name: str) -> str:
    """``BusinessEntityID`` -> ``business_entity_id``, ``SalesYTD`` -> ``sales_ytd``."""
    return _SPLIT.sub("_", name.strip()).lower()


def table_name(source: str) -> str:
    """``Sales.SalesOrderHeader`` (a file name without extension) -> ``sales_order_header``."""
    return snake(source.split(".", 1)[-1])


def column_name(source: str) -> str:
    name = snake(source)
    return RENAMED_COLUMNS.get(name, name)


PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "department": ("department_id",), "employee": ("business_entity_id",), "employee_department_history": ("business_entity_id", "start_date", "department_id", "shift_id"),
    "employee_pay_history": ("business_entity_id", "rate_change_date"), "job_candidate": ("job_candidate_id",), "shift": ("shift_id",),
    "address": ("address_id",), "address_type": ("address_type_id",), "business_entity": ("business_entity_id",),
    "business_entity_address": ("business_entity_id", "address_id", "address_type_id"), "business_entity_contact": ("business_entity_id", "person_id", "contact_type_id"),
    "contact_type": ("contact_type_id",), "country_region": ("country_region_code",), "person": ("business_entity_id",), "state_province": ("state_province_id",),
    "bill_of_materials": ("bill_of_materials_id",), "culture": ("culture_id",), "location": ("location_id",), "product": ("product_id",),
    "product_category": ("product_category_id",), "product_cost_history": ("product_id", "start_date"), "product_description": ("product_description_id",),
    "product_inventory": ("product_id", "location_id"), "product_subcategory": ("product_subcategory_id",), "transaction_history": ("transaction_id",),
    "unit_measure": ("unit_measure_code",), "work_order": ("work_order_id",), "work_order_routing": ("work_order_id", "product_id", "operation_sequence"),
    "product_vendor": ("product_id", "business_entity_id"), "purchase_order_detail": ("purchase_order_id", "purchase_order_detail_id"),
    "purchase_order_header": ("purchase_order_id",), "ship_method": ("ship_method_id",), "vendor": ("business_entity_id",),
    "country_region_currency": ("country_region_code", "currency_code"), "currency": ("currency_code",), "currency_rate": ("currency_rate_id",),
    "customer": ("customer_id",), "sales_order_detail": ("sales_order_id", "sales_order_detail_id"), "sales_order_header": ("sales_order_id",),
    "sales_order_header_sales_reason": ("sales_order_id", "sales_reason_id"), "sales_person": ("business_entity_id",), "sales_tax_rate": ("sales_tax_rate_id",),
    "sales_territory": ("territory_id",), "sales_territory_history": ("business_entity_id", "start_date", "territory_id"),
    "shopping_cart_item": ("shopping_cart_item_id",), "special_offer": ("special_offer_id",), "special_offer_product": ("special_offer_id", "product_id"),
    "store": ("business_entity_id",),
}

_REFERENCE = {"hr", "sales", "purchasing", "production"}
_PRODUCT_REFERENCE = {"sales", "purchasing", "production"}
TABLE_DOMAINS: dict[str, frozenset[str]] = {
    **{t: frozenset({"hr"}) for t in ("department", "employee", "employee_department_history", "employee_pay_history", "job_candidate", "shift")},
    **{t: frozenset({"sales"}) for t in (
        "sales_order_header", "sales_order_detail", "sales_order_header_sales_reason", "sales_person", "sales_territory", "sales_territory_history",
        "sales_tax_rate", "special_offer", "special_offer_product", "customer", "store", "currency", "currency_rate", "country_region_currency", "shopping_cart_item")},
    **{t: frozenset({"purchasing"}) for t in ("purchase_order_header", "purchase_order_detail", "vendor", "product_vendor", "ship_method")},
    **{t: frozenset({"production"}) for t in (
        "product_cost_history", "product_description", "product_inventory", "location", "transaction_history", "unit_measure", "bill_of_materials",
        "work_order", "work_order_routing", "culture")},
    **{t: frozenset(_PRODUCT_REFERENCE) for t in ("product", "product_category", "product_subcategory")},
    **{t: frozenset(_REFERENCE) for t in ("person", "business_entity", "address", "state_province", "country_region", "address_type", "contact_type", "business_entity_address")},
    "business_entity_contact": frozenset({"sales", "purchasing"}),
}


def domains_of(table: str) -> frozenset[str]:
    return TABLE_DOMAINS.get(table, frozenset())


def tables_for(domains: Iterable[str]) -> list[str]:
    """Every table that at least one of ``domains`` may read, sorted."""
    wanted = set(domains)
    return sorted(t for t, d in TABLE_DOMAINS.items() if d & wanted)


# ------------------------------------------------------------------------------------------------- cleaning the files
def clean_value(value: Any) -> Any:
    """A literal ``'NULL'`` (the export wrote NULLs as text) is a NULL. An empty string is kept: it is a real key (the invariant culture's id)."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return None if text.upper() == "NULL" else text
    return value


def serial_from_date(value: dt.datetime | dt.date) -> int:
    """Excel's serial number of a date: the id 43659 that Excel displayed as 2019-07-13."""
    day = value.date() if isinstance(value, dt.datetime) else value
    return (day - EXCEL_EPOCH).days


def repair_value(column: str, value: Any) -> Any:
    value = clean_value(value)
    if column.endswith("_id") and isinstance(value, (dt.datetime, dt.date)):
        return serial_from_date(value)
    return value


def infer_type(column: str, values: Iterable[Any]) -> str:
    """The narrowest PostgreSQL type that holds every non-null value of a column."""
    present = [v for v in values if v is not None]
    if not present:
        return "text"
    if all(isinstance(v, dt.time) and not isinstance(v, dt.datetime) for v in present):
        return "time"
    if all(isinstance(v, dt.datetime) for v in present):
        return "date" if all(v.time() == dt.time(0) for v in present) else "timestamp"
    if all(isinstance(v, bool) for v in present):
        return "boolean"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        if column.endswith("flag") and {int(v) for v in present} <= {0, 1}:
            return "smallint"
        return "integer" if max(abs(v) for v in present) < 2**31 else "bigint"
    if all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in present):
        return "numeric"
    return "text"


def coerce(pg_type: str, value: Any) -> Any:
    """The Python value asyncpg's COPY expects for a column type."""
    if value is None:
        return None
    if pg_type == "date" and isinstance(value, dt.datetime):
        return value.date()
    if pg_type == "numeric":
        return Decimal(str(value))
    if pg_type in ("integer", "bigint", "smallint"):
        return int(value)
    if pg_type == "text":
        return value if isinstance(value, str) else str(value)
    return value


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def create_table_sql(table: str, columns: list[tuple[str, str]]) -> str:
    """``CREATE TABLE aw.<table> (...)`` with the primary key of ``PRIMARY_KEYS`` when all its columns were loaded."""
    names = {name for name, _ in columns}
    lines = [f"{quote_ident(name)} {pg_type}" for name, pg_type in columns]
    key = PRIMARY_KEYS.get(table)
    if key and set(key) <= names:
        lines.append("PRIMARY KEY (" + ", ".join(quote_ident(k) for k in key) + ")")
    return f"CREATE TABLE {SCHEMA}.{quote_ident(table)} (\n  " + ",\n  ".join(lines) + "\n)"


def index_sql(table: str, columns: list[str], rows: int) -> list[str]:
    """Indexes on join columns of the big tables: foreign-key style ``*_id`` columns that are not the whole primary key, and order dates."""
    if rows < 1000:
        return []
    key = set(PRIMARY_KEYS.get(table, ()))
    wanted = [c for c in columns if (c.endswith("_id") and c not in key) or c in ("order_date", "transaction_date", "start_date")]
    return [f"CREATE INDEX ON {SCHEMA}.{quote_ident(table)} ({quote_ident(c)})" for c in wanted]


# ------------------------------------------------------------------------------------------------- what the agent is told
TABLE_DOCS: dict[str, str] = {
    "employee": "Nhân viên (1 dòng/người). current_flag=1: đang làm việc. job_title, birth_date, gender (M/F), marital_status (M/S), hire_date, vacation_hours, sick_leave_hours.",
    "department": "Phòng ban (department_id, name, group_name).",
    "employee_department_history": "Lịch sử nhân viên-phòng ban. end_date IS NULL: đang ở phòng ban đó; end_date có giá trị: đã chuyển đi.",
    "employee_pay_history": "Lịch sử mức lương theo giờ (rate) của nhân viên; pay_frequency 1=hàng tháng, 2=hai tuần/lần. DỮ LIỆU NHẠY CẢM.",
    "job_candidate": "Ứng viên (business_entity_id NULL nếu chưa thành nhân viên).",
    "shift": "Ca làm việc (name, start_time, end_time).",
    "person": "Họ tên người (nhân viên, khách hàng, liên hệ nhà cung cấp): business_entity_id, person_type (EM nhân viên, IN khách cá nhân, SC liên hệ cửa hàng, VC liên hệ nhà cung cấp...), first_name, last_name.",
    "sales_order_header": "Đơn bán hàng (1 dòng/đơn): order_date, ship_date, status, online_order_flag (1=đặt online), customer_id, sales_person_id, territory_id, sub_total, tax_amt, freight, total_due.",
    "sales_order_detail": "Dòng chi tiết đơn bán: sales_order_id, product_id, order_qty, unit_price, unit_price_discount, line_total.",
    "sales_person": "Nhân viên kinh doanh: territory_id, sales_quota, bonus, commission_pct, sales_ytd, sales_last_year.",
    "sales_territory": "Khu vực bán hàng: name, country_region_code, region_group (North America/Europe/Pacific), sales_ytd, sales_last_year, cost_ytd, cost_last_year.",
    "customer": "Khách hàng: person_id (khách cá nhân) hoặc store_id (cửa hàng bán lẻ), territory_id.",
    "store": "Cửa hàng bán lẻ là khách hàng: name, sales_person_id.",
    "special_offer": "Chương trình khuyến mãi: discount_pct, type, category, start_date, end_date.",
    "purchase_order_header": "Đơn mua hàng: status, employee_id, vendor_id, order_date, ship_date, sub_total, tax_amt, freight, total_due.",
    "purchase_order_detail": "Dòng chi tiết đơn mua: order_qty, product_id, unit_price, line_total, received_qty, rejected_qty, stocked_qty.",
    "vendor": "Nhà cung cấp: name, credit_rating (1 tốt nhất..5), preferred_vendor_status, active_flag.",
    "product_vendor": "Sản phẩm-nhà cung cấp: average_lead_time (ngày), standard_price, last_receipt_cost, min/max_order_qty.",
    "product": "Sản phẩm: name, product_number, color, standard_cost, list_price, safety_stock_level, reorder_point, finished_goods_flag, make_flag, product_subcategory_id, sell_start_date, sell_end_date, discontinued_date.",
    "product_category": "Nhóm sản phẩm (Bikes, Components, Clothing, Accessories).",
    "product_subcategory": "Nhóm con của sản phẩm.",
    "product_inventory": "Tồn kho theo kho/vị trí: product_id, location_id, quantity.",
    "location": "Vị trí kho/xưởng: name, cost_rate, availability.",
    "work_order": "Lệnh sản xuất: product_id, order_qty, stocked_qty, scrapped_qty (phế phẩm), start_date, end_date, due_date.",
    "work_order_routing": "Công đoạn của lệnh sản xuất: planned_cost, actual_cost, actual_resource_hrs.",
    "transaction_history": "Giao dịch kho: transaction_type (W xuất cho sản xuất, S bán, P mua), quantity, actual_cost, transaction_date.",
    "bill_of_materials": "Định mức vật tư: product_assembly_id, component_id, per_assembly_qty.",
    "address": "Địa chỉ: city, postal_code, state_province_id.",
    "state_province": "Bang/tỉnh: name, country_region_code, territory_id.",
    "country_region": "Quốc gia: country_region_code, name.",
    "currency_rate": "Tỷ giá theo ngày: from_currency_code, to_currency_code, average_rate, end_of_day_rate.",
}

# (tables the statement is about, text): shown to the model only when the caller may read ALL of those tables.
CODE_MEANINGS: list[tuple[frozenset[str], str]] = [
    (frozenset({"sales_order_header"}), "sales_order_header.status: 1 đang xử lý, 2 đã duyệt, 3 chờ hàng, 4 bị từ chối, 5 hoàn tất, 6 đã hủy."),
    (frozenset({"purchase_order_header"}), "purchase_order_header.status: 1 đang xử lý, 2 đã duyệt, 3 bị từ chối, 4 hoàn tất."),
    (frozenset({"employee"}), "employee.gender: M nam, F nữ; marital_status: M có gia đình, S độc thân."),
    (frozenset({"employee_pay_history"}), "employee_pay_history.pay_frequency: 1 hàng tháng, 2 hai tuần một lần; rate là mức lương THEO GIỜ."),
]

METRICS: list[tuple[frozenset[str], str]] = [
    (frozenset({"sales_order_header"}), "Doanh thu = SUM(sales_order_header.sub_total) (chưa thuế/vận chuyển); tổng thu = SUM(total_due). Mọi đơn trong dữ liệu đã hoàn tất (status = 5)."),
    (frozenset({"sales_order_detail"}), "Doanh thu theo sản phẩm = SUM(sales_order_detail.line_total)."),
    (frozenset({"employee"}), "Nhân viên đang làm = employee.current_flag = 1. Thâm niên (năm) = (ngày hiện tại của dữ liệu - hire_date) / 365.25; tuổi tương tự với birth_date."),
    (frozenset({"employee", "employee_department_history", "department"}),
     "Phòng ban hiện tại của nhân viên: employee_department_history có end_date IS NULL. Chuyển phòng ban = dòng có end_date IS NOT NULL (nguồn không có ngày nghỉ việc riêng)."),
    (frozenset({"work_order"}), "Phế phẩm % = 100.0 * SUM(scrapped_qty) / NULLIF(SUM(order_qty), 0)."),
]

JOIN_HINTS: list[tuple[frozenset[str], str]] = [
    (frozenset({"employee", "person"}), "employee.business_entity_id = person.business_entity_id (tên nhân viên)."),
    (frozenset({"employee", "employee_department_history", "department"}), "employee_department_history(business_entity_id, department_id) nối employee và department."),
    (frozenset({"sales_order_header", "sales_order_detail"}), "sales_order_header.sales_order_id = sales_order_detail.sales_order_id."),
    (frozenset({"sales_order_detail", "product"}), "sales_order_detail.product_id = product.product_id."),
    (frozenset({"product", "product_subcategory", "product_category"}), "product.product_subcategory_id -> product_subcategory -> product_category.product_category_id."),
    (frozenset({"sales_order_header", "customer"}), "sales_order_header.customer_id = customer.customer_id (customer.person_id -> person, customer.store_id -> store)."),
    (frozenset({"sales_order_header", "sales_territory"}), "sales_order_header.territory_id = sales_territory.territory_id."),
    (frozenset({"sales_order_header", "sales_person"}), "sales_order_header.sales_person_id = sales_person.business_entity_id."),
    (frozenset({"purchase_order_header", "vendor"}), "purchase_order_header.vendor_id = vendor.business_entity_id."),
    (frozenset({"purchase_order_header", "purchase_order_detail"}), "purchase_order_detail.purchase_order_id = purchase_order_header.purchase_order_id."),
    (frozenset({"product_inventory", "product", "location"}), "product_inventory(product_id, location_id) -> product, location."),
    (frozenset({"work_order", "product"}), "work_order.product_id = product.product_id."),
]


def relevant(items: list[tuple[frozenset[str], str]], tables: set[str]) -> list[str]:
    """The texts of ``items`` whose tables the caller may all read."""
    return [text for needed, text in items if needed <= tables]


def table_doc(table: str) -> Optional[str]:
    return TABLE_DOCS.get(table)
