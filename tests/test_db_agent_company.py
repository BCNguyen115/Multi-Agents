"""The SQL agent over the company data (schema ``aw``): cleaning the source files, who may read which domain, the checks every statement passes,
the answer the agent builds, and the same statements against a real PostgreSQL (``RAG_TEST_DSN``)."""
import asyncio
import datetime as dt
import json
import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from sqlglot import exp, parse_one

from scripts import load_adventureworks as loader
from src.agents.db_agent import overview, schema_catalog
from src.agents.db_agent.agent import DatabaseAgent
from src.agents.db_agent.presenter import format_cell, markdown_table
from src.agents.db_agent.rls_transformer import inject_row_level_security
from src.agents.db_agent.schema_catalog import SchemaCatalog
from src.agents.db_agent.validator import check_allowed_tables, parameterize_sql, validate_sql
from src.config import settings
from src.ingestion import aw_catalog as aw
from src.orchestrator.core import Orchestrator
from src.shared.auth import Principal, acting_as

DSN = os.environ.get("RAG_TEST_DSN", "")
ARCHIVE = Path(__file__).resolve().parent.parent / "dataset" / "archive"

HR = Principal("hana", "acme", "people", frozenset({"hr"}), authenticated=True)
SALES = Principal("sam", "acme", "sales", frozenset({"sales"}), authenticated=True)
CEO = Principal("carl", "acme", "board", frozenset({"executive"}), authenticated=True)
ADMIN = Principal("root", "acme", "ops", frozenset({"admin"}), authenticated=True)
NOBODY = Principal("nina", "acme", "misc", frozenset({"member"}), authenticated=True)
PENDING = Principal("pia", settings.REGISTRATION_TENANT_ID, settings.REGISTRATION_DEPARTMENT_ID, frozenset({"hr"}), authenticated=True)


def full_catalog() -> SchemaCatalog:
    return SchemaCatalog(columns={t: [(f"{t}_id", "int"), ("name", "text")] for t in aw.TABLE_DOMAINS}, as_of=dt.date(2014, 6, 30))


# ------------------------------------------------------------------------------------------------- cleaning the source files
def test_names_follow_snake_case_and_the_sensitive_tables_are_never_loaded():
    assert aw.table_name("Sales.SalesOrderHeader") == "sales_order_header" and aw.column_name("BusinessEntityID") == "business_entity_id"
    assert aw.column_name("SalesYTD") == "sales_ytd" and aw.column_name("Group") == "region_group"  # a reserved word is renamed
    for source in ("Person.Password", "Sales.CreditCard", "Sales.PersonCreditCard", "Person.EmailAddress", "Person.PersonPhone"):
        assert aw.table_name(source) in aw.EXCLUDED_TABLES, source
    assert not (aw.EXCLUDED_TABLES & set(aw.TABLE_DOMAINS))
    assert {"national_id_number", "login_id", "credit_card_id", "rowguid", "demographics"} <= aw.DROPPED_COLUMNS
    present = {p.stem for p in ARCHIVE.glob("*.xlsx")} if ARCHIVE.is_dir() else set()
    if present:  # every workbook that is loaded has a domain and a primary key, and nothing else is listed
        loaded = {aw.table_name(s) for s in present} - aw.EXCLUDED_TABLES
        assert loaded == set(aw.TABLE_DOMAINS) and loaded <= set(aw.PRIMARY_KEYS)


def test_the_export_s_null_text_is_a_null_and_excel_s_dates_in_id_columns_become_the_ids_again():
    assert aw.clean_value("NULL") is None and aw.clean_value("  null ") is None and aw.clean_value("Ken") == "Ken"
    assert aw.clean_value("      ") == ""  # an empty key is a real key (the invariant culture), not a missing value
    assert aw.repair_value("sales_order_id", dt.datetime(2019, 7, 13)) == 43659  # Excel showed the id 43659 as this date
    assert aw.repair_value("order_date", dt.datetime(2011, 5, 31)) == dt.datetime(2011, 5, 31)  # only id columns are repaired
    assert aw.serial_from_date(dt.datetime(1900, 1, 1)) == 2


def test_types_are_the_narrowest_that_hold_every_value():
    assert aw.infer_type("hire_date", [dt.datetime(2009, 1, 14), dt.datetime(2008, 1, 31)]) == "date"
    assert aw.infer_type("modified", [dt.datetime(2009, 1, 14, 10, 30)]) == "timestamp"
    assert aw.infer_type("current_flag", [1, 0, 1]) == "smallint" and aw.infer_type("order_qty", [1, 20]) == "integer"
    assert aw.infer_type("big", [2**40]) == "bigint" and aw.infer_type("rate", [125.5, 3]) == "numeric"
    assert aw.infer_type("code", ["a", 1]) == "text" and aw.infer_type("x", [None, None]) == "text"
    assert aw.infer_type("start_time", [dt.time(7, 0)]) == "time"
    assert aw.coerce("numeric", 12.5) == Decimal("12.5") and aw.coerce("date", dt.datetime(2014, 6, 30)) == dt.date(2014, 6, 30)


def test_prepare_drops_columns_repairs_ids_and_types_the_rest():
    header = ["SalesOrderID", "OrderDate", "OnlineOrderFlag", "SubTotal", "Comment", "rowguid", "ModifiedDate"]
    rows = [(dt.datetime(2019, 7, 13), dt.datetime(2011, 5, 31), 0, 20565.6206, "NULL", "x", dt.datetime(2011, 6, 7)),
            (dt.datetime(2019, 7, 14), dt.datetime(2011, 5, 31), 1, 1.5, "ok", "y", dt.datetime(2011, 6, 7))]
    columns, typed = loader.prepare(header, rows)
    assert columns == [("sales_order_id", "integer"), ("order_date", "date"), ("online_order_flag", "smallint"), ("sub_total", "numeric"), ("comment", "text")]
    assert typed[0] == (43659, dt.date(2011, 5, 31), 0, Decimal("20565.6206"), None) and typed[1][0] == 43660
    ddl = aw.create_table_sql("sales_order_header", columns)
    assert ddl.startswith("CREATE TABLE aw.") and 'PRIMARY KEY ("sales_order_id")' in ddl
    assert aw.index_sql("sales_order_header", [c for c, _ in columns], 31465) == ['CREATE INDEX ON aw."sales_order_header" ("order_date")']
    assert aw.index_sql("department", ["department_id"], 16) == []


# ------------------------------------------------------------------------------------------------- who may read what
def test_a_caller_reads_the_domains_of_their_roles_and_nothing_else():
    assert schema_catalog.principal_domains(HR) == {"hr"} and schema_catalog.principal_domains(SALES) == {"sales"}
    assert schema_catalog.principal_domains(CEO) == set(aw.DOMAINS) and schema_catalog.principal_domains(ADMIN) == set(aw.DOMAINS)
    assert schema_catalog.principal_domains(NOBODY) == set() and schema_catalog.principal_domains(PENDING) == set()  # a pending account sees nothing
    assert schema_catalog.principal_domains(None) == set()
    catalog = full_catalog()
    hr_tables = schema_catalog.readable_tables(catalog, HR)
    assert "employee_pay_history" in hr_tables and "sales_order_header" not in hr_tables and "person" in hr_tables  # shared reference tables
    assert "employee" not in schema_catalog.readable_tables(catalog, SALES) and "product" in schema_catalog.readable_tables(catalog, SALES)


def test_the_model_is_only_shown_what_the_caller_may_read_and_the_definitions_that_concern_it():
    catalog = full_catalog()
    hr_prompt = schema_catalog.build_prompt(catalog, HR)
    assert "aw.employee(" in hr_prompt and "aw.sales_order_header" not in hr_prompt and "2014-06-30" in hr_prompt
    assert "Mỗi phòng ban hiện có" in hr_prompt and "Doanh thu từng năm" not in hr_prompt  # examples that fit this caller only
    assert "current_flag" in hr_prompt and "Doanh thu = SUM" not in hr_prompt
    ceo_prompt = schema_catalog.build_prompt(catalog, CEO)
    assert "aw.sales_order_header(" in ceo_prompt and "Doanh thu từng năm" in ceo_prompt and "aw.employee(" in ceo_prompt
    assert "chưa được cấp quyền" in schema_catalog.build_prompt(catalog, NOBODY)
    allowed = schema_catalog.allowed_tables(catalog, HR)
    assert "employee" in allowed["aw"] and "public" not in allowed and "public" in schema_catalog.allowed_tables(catalog, ADMIN)


def test_every_example_and_kpi_uses_only_tables_of_its_domain_and_passes_the_validator():
    catalog = full_catalog()
    everything = {"aw": set(catalog.columns)}
    day = dt.date(2014, 6, 30)
    for _, sql in schema_catalog.EXAMPLES:
        ok, _, error = validate_sql(schema_catalog.render_as_of(sql, day), allowed_tables=everything)
        assert ok, (sql, error)
    for kpi in overview.KPIS:
        ok, sanitized, error = validate_sql(schema_catalog.render_as_of(kpi.sql, day), allowed_tables=everything)
        assert ok, (kpi.title, error)
        domain_tables = set(aw.tables_for([kpi.domain]))
        assert kpi.tables <= domain_tables, (kpi.title, kpi.tables - domain_tables)  # a KPI never needs a table outside its own domain
        parameterize_sql(sanitized)  # must not raise


# ------------------------------------------------------------------------------------------------- the checks every statement passes
def allowed(**tables: set[str]) -> dict[str, set[str]]:
    return tables


def test_tables_outside_the_callers_set_are_refused_whatever_way_they_are_written():
    rules = allowed(aw={"employee", "department"})
    assert validate_sql("SELECT * FROM aw.employee", allowed_tables=rules)[0]
    assert validate_sql("SELECT * FROM employee", allowed_tables=rules)[0]  # the role's search_path resolves it
    for sql in ("SELECT * FROM aw.sales_order_header", "SELECT * FROM sales_order_header", "SELECT * FROM AW.Sales_Order_Header",
                "SELECT * FROM aw.employee e JOIN aw.customer c ON c.customer_id = e.business_entity_id",
                "SELECT * FROM aw.employee WHERE business_entity_id IN (SELECT person_id FROM aw.customer)",
                "WITH x AS (SELECT * FROM aw.customer) SELECT * FROM x",
                "SELECT * FROM public.rag_chunks", "SELECT * FROM rag_chunks"):
        ok, _, error = validate_sql(sql, allowed_tables=rules)
        assert not ok and "not available" in error, sql
    assert validate_sql("WITH x AS (SELECT * FROM aw.employee) SELECT * FROM x", allowed_tables=rules)[0]  # a CTE name is not a table


def test_a_query_never_mixes_company_data_with_the_knowledge_base_tables():
    rules = allowed(aw={"employee"}, public={"knowledge_documents"})
    ok, _, error = validate_sql("SELECT * FROM aw.employee e, knowledge_documents k", allowed_tables=rules)
    assert not ok and "one schema only" in error
    assert validate_sql("SELECT id FROM knowledge_documents", allowed_tables=rules)[0]
    assert check_allowed_tables(parse_one("SELECT 1"), rules) == ""


def test_the_outer_limit_is_what_counts_and_literals_that_must_stay_literal_do():
    ok, sql, _ = validate_sql("SELECT * FROM (SELECT * FROM aw.employee LIMIT 5) x")
    assert ok and sql.upper().rstrip().endswith("LIMIT 1000")  # the inner LIMIT does not bound the result
    ok, sql, _ = validate_sql("SELECT * FROM aw.employee LIMIT 5")
    assert ok and "LIMIT 1000" not in sql.upper()
    parameterized, params = parameterize_sql(
        "SELECT EXTRACT(YEAR FROM order_date)::int AS y, COUNT(*) FROM aw.sales_order_header WHERE status = 5 AND order_date >= '2013-01-01' "
        "AND comment = 'rush' AND order_date >= (SELECT MAX(order_date) FROM aw.sales_order_header) - INTERVAL '12 months' GROUP BY 1 ORDER BY 1 LIMIT 3")
    assert sorted(map(str, params)) == ["5", "rush"]  # a value is a parameter; a date text, an interval, GROUP/ORDER BY positions and a LIMIT stay as written
    assert "'2013-01-01'" in parameterized and "INTERVAL '12 MONTHS'" in parameterized and "GROUP BY 1" in parameterized and "$1" in parameterized and "$2" in parameterized
    params_only = parameterize_sql("SELECT * FROM rag_chunks WHERE category = 'contracts' AND char_count > 500 LIMIT 10")[1]
    assert params_only == ["contracts", 500]


def test_company_data_has_no_tenant_columns_so_only_other_tables_get_the_tenant_predicate():
    assert "tenant_id" not in inject_row_level_security("SELECT * FROM aw.employee", "acme", "people")
    scoped = inject_row_level_security("SELECT * FROM rag_chunks", "acme", "people")
    assert "tenant_id = 'acme'" in scoped and "department_id = 'people'" in scoped
    cte = inject_row_level_security("WITH x AS (SELECT * FROM aw.employee) SELECT * FROM x", "acme", "people")
    assert "tenant_id" not in cte
    mixed = inject_row_level_security("SELECT * FROM aw.employee WHERE business_entity_id IN (SELECT id FROM rag_chunks)", "acme", "people")
    assert mixed.count("tenant_id = 'acme'") == 1  # the subquery over rag_chunks is scoped, the outer select over aw is not
    assert "tenant_id" not in inject_row_level_security("SELECT * FROM employee", "acme", "people", unscoped_tables=frozenset({"employee"}))
    assert "tenant_id" in inject_row_level_security("SELECT * FROM employee", "acme", "people")  # unqualified and not declared: scoped, as before
    assert isinstance(parse_one(inject_row_level_security("SELECT 1", "acme", "people")), exp.Select)


# ------------------------------------------------------------------------------------------------- what the person sees
def test_the_table_is_built_from_the_rows_with_figures_the_verifier_can_read():
    assert format_cell("revenue", 12641672) == "12,641,672" and format_cell("revenue", Decimal("12641672.00")) == "12,641,672"
    assert format_cell("avg_age", 35.7) == "35.7" and format_cell("rate", Decimal("125.5000")) == "125.5"
    assert format_cell("year", 2013) == "2013" and format_cell("sales_order_id", 43659) == "43659"  # years and ids carry no thousands separator
    assert format_cell("x", None) == "–" and format_cell("d", dt.date(2014, 6, 30)) == "2014-06-30" and format_cell("t", "a|b\nc") == "a/b c"
    rows = [{"year": 2011 + i, "revenue": 1000 * (i + 1)} for i in range(25)]
    table = markdown_table(rows)
    assert table.splitlines()[0] == "| year | revenue |" and "| 2011 | 1,000 |" in table and "5 dòng nữa" in table and "2031" not in table
    assert markdown_table([]) == ""


def test_a_snapshot_request_is_recognised_scoped_to_what_it_names_and_not_for_long_specific_questions():
    assert overview.snapshot_request("Tình hình nhân sự hiện tại?") == {"hr"}
    assert overview.snapshot_request("tong quan cong ty") == set(aw.DOMAINS)
    assert overview.snapshot_request("Khảo sát tình hình doanh thu và tồn kho") == {"sales", "production"}
    assert overview.snapshot_request("Doanh thu 2013 theo khu vực?") is None
    assert overview.snapshot_request("tình hình doanh thu của từng khu vực trong từng quý của năm 2013 và so với năm 2012 và 2011 ra sao") is None
    readable = set(schema_catalog.readable_tables(full_catalog(), HR))
    assert {k.domain for k in overview.kpis_for({"hr", "sales"}, readable)} == {"hr"}


# ------------------------------------------------------------------------------------------------- the agent, with a scripted model
class ScriptedLLM:
    """Answers SQL requests from ``sql_replies`` in order and every reading request with ``insight``."""

    def __init__(self, sql_replies: list[dict[str, str]], insight: str = "- Phòng Production đông nhất với 179 nhân viên.") -> None:
        self.sql_replies, self.insight, self.calls = list(sql_replies), insight, []

    async def chat_completion(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if (kwargs.get("metadata") or {}).get("step") == "insight":
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.insight))])
        reply = self.sql_replies.pop(0) if len(self.sql_replies) > 1 else self.sql_replies[0]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="```json\n" + json.dumps(reply) + "\n```"))])

    @property
    def sql_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if (c.get("metadata") or {}).get("step") != "insight"]


class FakeMCP:
    def __init__(self, rows: Optional[list[dict[str, Any]]] = None, errors: Optional[list[str]] = None) -> None:
        self.rows, self.errors, self.executed = rows if rows is not None else [{"department": "Production", "employees": 179}], list(errors or []), []

    async def execute_sql_query(self, query_sql: str, params: Optional[list[Any]] = None, session_id: str = "") -> str:
        self.executed.append(query_sql)
        if self.errors:
            return json.dumps({"status": "error", "message": self.errors.pop(0)})
        return json.dumps({"status": "success", "row_count": len(self.rows), "data": self.rows})


GOOD = {"sql": "SELECT d.name AS department, COUNT(*) AS employees FROM aw.department d JOIN aw.employee_department_history h ON h.department_id = d.department_id GROUP BY d.name",
        "explanation": "Quân số theo phòng ban."}


def ask(agent: DatabaseAgent, who: Principal, question: str) -> dict[str, Any]:
    with acting_as(who):
        return json.loads(asyncio.run(agent.process_request(question, "s1")))


def agent_with(llm: ScriptedLLM, mcp: Optional[FakeMCP] = None) -> DatabaseAgent:
    return DatabaseAgent(mcp or FakeMCP(), llm, model="fake", catalog=full_catalog(), summary_model="fake-fast")


def test_a_question_becomes_a_table_a_short_reading_and_the_sql_that_ran():
    llm, mcp = ScriptedLLM([GOOD]), FakeMCP()
    reply = ask(agent_with(llm, mcp), HR, "Mỗi phòng ban có bao nhiêu nhân viên?")
    assert "| department | employees |" in reply["answer"] and "| Production | 179 |" in reply["answer"] and "Nhận định" in reply["answer"]
    assert reply["row_count"] == 1 and reply["data"] == [{"department": "Production", "employees": 179}] and reply["sql"] in reply["answer"]
    assert mcp.executed and "tenant_id" not in mcp.executed[0]  # company data carries no tenant columns
    assert "aw.sales_order_header" not in llm.sql_calls[0]["messages"][0]["content"]  # the HR caller's prompt
    assert llm.calls[-1]["model"] == "fake-fast"  # the reading is written by the fast model
    assert Orchestrator._db_verdict(reply, 0)["is_verified"] is True


def test_a_line_of_the_reading_with_a_figure_the_model_worked_out_itself_is_dropped():
    llm = ScriptedLLM([GOOD], insight="- Quân số đã tăng 12% so với năm trước.\n- Production có 179 nhân viên, đông nhất.\n- Tổng cộng 290 nhân viên.")
    reply = ask(agent_with(llm), HR, "Quân số theo phòng ban?")
    assert "179 nhân viên" in reply["answer"] and "12%" not in reply["answer"] and "290" not in reply["answer"]
    assert Orchestrator._db_verdict(reply, 0)["is_verified"] is True  # what stays can be checked by the orchestrator's own number check
    nothing_left = ask(agent_with(ScriptedLLM([GOOD], insight="- Tăng 12%."), FakeMCP()), HR, "Quân số theo phòng ban?")
    assert "Nhận định" not in nothing_left["answer"]  # no reading is better than an invented one


def test_a_statement_outside_the_callers_domain_is_refused_and_the_model_gets_one_chance_to_correct_it():
    forbidden = {"sql": "SELECT SUM(sub_total) AS revenue FROM aw.sales_order_header", "explanation": "Doanh thu."}
    llm, mcp = ScriptedLLM([forbidden, GOOD]), FakeMCP()
    ask(agent_with(llm, mcp), HR, "Cho tôi doanh thu")
    assert len(llm.sql_calls) == 2 and "not available" in llm.sql_calls[1]["messages"][1]["content"]  # the refusal went back to the model
    assert len(mcp.executed) == 1 and "sales_order_header" not in mcp.executed[0]  # the forbidden statement never reached the database
    stubborn = ask(agent_with(ScriptedLLM([forbidden]), FakeMCP()), HR, "Cho tôi doanh thu")
    assert "không thực hiện được" in stubborn["answer"] and "not available" in stubborn["answer"] and stubborn["data"] == []
    assert stubborn["type"] == "error"  # a refusal is not judged as an answer


def test_a_database_error_is_fed_back_once_then_reported():
    broken = {"sql": "SELECT nope FROM aw.employee", "explanation": "x"}
    mcp = FakeMCP(errors=['column "nope" does not exist'])
    llm = ScriptedLLM([broken, GOOD])
    reply = ask(agent_with(llm, mcp), HR, "Quân số?")
    assert 'column "nope" does not exist' in llm.sql_calls[1]["messages"][1]["content"] and reply["row_count"] == 1
    twice = ask(agent_with(ScriptedLLM([broken]), FakeMCP(errors=["boom 1", "boom 2"])), HR, "Quân số?")
    assert "boom 2" in twice["answer"] and len(twice["data"]) == 0


def test_nobody_without_a_domain_role_reaches_the_model_or_the_database():
    for who in (NOBODY, PENDING):
        llm, mcp = ScriptedLLM([GOOD]), FakeMCP()
        reply = ask(agent_with(llm, mcp), who, "Quân số?")
        assert "chưa được cấp quyền" in reply["answer"] and not llm.calls and not mcp.executed and reply["type"] == "error"
    with acting_as(NOBODY):
        assert not asyncio.run(agent_with(ScriptedLLM([GOOD])).execute_sql("SELECT * FROM aw.employee", "s1")).ok


def test_a_snapshot_runs_the_fixed_kpis_of_the_callers_domains_and_summarises_their_rows():
    llm, mcp = ScriptedLLM([GOOD], insight="- Phòng Production đông nhất."), FakeMCP([{"department": "Production", "employees": 179}])
    reply = ask(agent_with(llm, mcp), HR, "Tình hình nhân sự hiện tại?")
    hr_kpis = [k for k in overview.KPIS if k.domain == "hr"]
    assert len(mcp.executed) == len(hr_kpis) and not llm.sql_calls  # no model-written SQL for a standard report
    assert reply["answer"].count("### ") == len(hr_kpis) and "dữ liệu đến 2014-06-30" in reply["answer"] and "Nhận định" in reply["answer"]
    assert Orchestrator._db_verdict(reply, 0)["is_verified"] is True  # the date in the heading is grounded by the data
    sales_only = ask(agent_with(ScriptedLLM([GOOD]), FakeMCP()), SALES, "Tình hình nhân sự hiện tại?")
    assert "không có quyền xem dữ liệu hr" in sales_only["answer"] and sales_only["type"] == "error"
    mcp2 = FakeMCP()
    everything = ask(agent_with(ScriptedLLM([GOOD]), mcp2), CEO, "Tổng quan công ty")
    assert len(mcp2.executed) == len(overview.KPIS) and everything["answer"].count("### ") == len(overview.KPIS)


def test_the_statement_the_approval_gate_looked_at_is_the_one_that_runs():
    llm, mcp = ScriptedLLM([GOOD, {"sql": "SELECT 1", "explanation": "other"}]), FakeMCP()
    agent = agent_with(llm, mcp)
    with acting_as(HR):
        sql, _ = asyncio.run(agent.generate_sql("Quân số?", "s1"))
        reply = json.loads(asyncio.run(agent.process_request("Quân số?", "s1")))
    assert sql == GOOD["sql"] and len(llm.sql_calls) == 1 and "department" in reply["answer"]  # one model call for the SQL, not two
    with acting_as(HR):
        asyncio.run(agent.process_request("Quân số?", "s1"))  # a later request plans again
    assert len(llm.sql_calls) == 2


def test_pay_data_goes_through_the_approval_gate_and_an_approved_statement_is_still_checked():
    agent = agent_with(ScriptedLLM([GOOD]))
    assert agent.is_sensitive_sql("SELECT AVG(rate) FROM aw.employee_pay_history", "")
    assert agent.is_sensitive_sql("SELECT 1", "Mức lương trung bình của nhân viên là bao nhiêu?")
    assert agent.is_sensitive_sql("SELECT 1", "Bảng lương tháng này")
    assert not agent.is_sensitive_sql("SELECT COUNT(*) FROM aw.employee", "Số lượng nhân viên đang làm việc?")
    assert not agent.is_sensitive_sql("SELECT SUM(order_qty) FROM aw.work_order", "Tổng số lượng sản xuất?")
    with acting_as(SALES):  # approved, but the requester has no HR domain: the checks still refuse it
        refused = asyncio.run(agent.execute_sql("SELECT AVG(rate) FROM aw.employee_pay_history", "s1", "acme", "sales"))
    assert not refused.ok and "not available" in refused.error
    mcp = FakeMCP([{"avg_rate": 20.5}])
    with acting_as(HR):
        allowed_run = asyncio.run(agent_with(ScriptedLLM([GOOD]), mcp).execute_sql("SELECT AVG(rate) AS avg_rate FROM aw.employee_pay_history", "s1", "acme", "people"))
    assert allowed_run.ok and allowed_run.rows == [{"avg_rate": 20.5}] and mcp.executed


def test_without_company_data_the_agent_behaves_as_before():
    llm = ScriptedLLM([{"sql": "SELECT COUNT(*) FROM knowledge_documents", "explanation": "đếm"}])
    agent = DatabaseAgent(FakeMCP([{"count": 3}]), llm, model="fake")
    with acting_as(ADMIN):
        reply = json.loads(asyncio.run(agent.process_request("Có bao nhiêu tài liệu?", "s1")))
    assert reply["row_count"] == 1 and "SQL Executed" in reply["answer"] and "Nhận định" not in reply["answer"]
    assert len(llm.calls) == 1  # no second call for a reading
    empty = DatabaseAgent(FakeMCP(), llm, model="fake", catalog=SchemaCatalog())
    assert empty._company is None


def test_the_agent_description_names_what_it_is_for():
    description = DatabaseAgent(FakeMCP(), ScriptedLLM([GOOD])).get_metadata()["description"]
    assert "nhân sự" in description and "doanh thu" in description and "rag_chunks" in description


# ------------------------------------------------------------------------------------------------- on a real database
NEEDED = sorted({t for _, sql in schema_catalog.EXAMPLES for t in schema_catalog.sql_tables(sql)} | {t for k in overview.KPIS for t in k.tables} | {"password", "credit_card", "customer"})


@pytest.mark.skipif(not DSN or not ARCHIVE.is_dir(), reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser) and keep dataset/archive")
class TestAgainstPostgres:
    @classmethod
    def setup_class(cls) -> None:
        assert asyncio.run(loader.run(DSN, ARCHIVE, set(NEEDED), reset=True)) == 0

    def run_sql(self, coro_factory: Any) -> Any:
        async def go() -> Any:
            from src.shared.postgres_client import PostgresClient
            pg = PostgresClient(dsn=DSN, ensure_pgvector=False)
            await pg.connect(min_size=1, max_size=2)
            try:
                return await coro_factory(pg)
            finally:
                await pg.disconnect()

        return asyncio.run(go())

    def test_the_load_is_clean(self):
        async def check(pg: Any) -> dict[str, Any]:
            q = pg.fetch
            return {
                "orphans": (await q("SELECT count(*) AS n FROM aw.sales_order_detail d LEFT JOIN aw.sales_order_header h USING (sales_order_id) WHERE h.sales_order_id IS NULL"))[0]["n"],
                "ids": tuple((await q("SELECT min(sales_order_id) AS lo, max(sales_order_id) AS hi FROM aw.sales_order_header"))[0].values()),
                "nulltext": (await q("SELECT count(*) AS n FROM aw.product WHERE color = 'NULL' OR size = 'NULL'"))[0]["n"],
                "sensitive": [r["table_name"] for r in await q("SELECT table_name FROM information_schema.tables WHERE table_schema = 'aw' AND table_name IN ('password', 'credit_card', 'person_credit_card')")],
                "forbidden_columns": [r["column_name"] for r in await q("SELECT column_name FROM information_schema.columns WHERE table_schema = 'aw' AND column_name IN ('national_id_number', 'login_id', 'rowguid', 'credit_card_id')")],
            }

        got = self.run_sql(check)
        assert got["orphans"] == 0 and got["ids"] == (43659, 75123) and got["nulltext"] == 0
        assert got["sensitive"] == [] and got["forbidden_columns"] == []

    def test_every_example_and_every_kpi_runs_for_a_caller_who_may_read_it(self):
        async def run(pg: Any) -> list[tuple[str, bool, str, int]]:
            from src.shared.mcp_client import MCPClient

            catalog = await SchemaCatalog.load(pg)
            agent = DatabaseAgent(MCPClient(pg_client=pg), ScriptedLLM([GOOD]), model="fake", catalog=catalog)
            outcomes = []
            with acting_as(ADMIN):
                for label, sql in [(f"example: {q}", s) for q, s in schema_catalog.EXAMPLES] + [(f"kpi: {k.title}", k.sql) for k in overview.KPIS]:
                    result = await agent.execute_sql(schema_catalog.render_as_of(sql, catalog.as_of), "s1")
                    outcomes.append((label, result.ok, result.error, result.row_count))
            return outcomes

        outcomes = self.run_sql(run)
        assert all(ok for _, ok, _, _ in outcomes), [o for o in outcomes if not o[1]]
        assert all(rows > 0 for label, _, _, rows in outcomes if label.startswith("kpi: ")), [o for o in outcomes if o[3] == 0]

    def test_the_catalog_reads_the_real_columns_and_the_data_s_last_day(self):
        catalog = self.run_sql(lambda pg: SchemaCatalog.load(pg))
        assert catalog.as_of == dt.date(2014, 6, 30) and ("hire_date", "date") in catalog.columns["employee"]
        assert set(catalog.columns) >= {"employee", "sales_order_header"} and "password" not in catalog.columns

    def test_the_read_only_role_reads_company_data_without_the_schema_prefix_and_cannot_write(self):
        import asyncpg

        from src.shared.db_roles import ensure_readonly_role, grant_schema_read, readonly_dsn

        async def go(pg: Any) -> dict[str, Any]:
            await ensure_readonly_role(pg, "aw_reader_test", "x" * 20, ["knowledge_documents"])
            granted = await grant_schema_read(pg, "aw_reader_test", "aw")
            conn = await asyncpg.connect(readonly_dsn(DSN, "aw_reader_test", "x" * 20))
            try:
                seen = await conn.fetchval("SELECT count(*) FROM employee")
                try:
                    await conn.execute("DELETE FROM aw.employee")
                    wrote = True
                except asyncpg.PostgresError:
                    wrote = False
            finally:
                await conn.close()
            await pg.execute("DROP OWNED BY aw_reader_test")
            await pg.execute("DROP ROLE aw_reader_test")
            return {"granted": granted, "seen": seen, "wrote": wrote}

        got = self.run_sql(go)
        assert "employee" in got["granted"] and got["seen"] == 290 and got["wrote"] is False


def test_a_sensitive_statement_that_reaches_the_agent_without_the_approval_path_does_not_run():
    pay = {"sql": "SELECT AVG(rate) AS avg_rate FROM aw.employee_pay_history", "explanation": "x"}  # e.g. a second model sample that differs from the one the gate saw
    mcp = FakeMCP()
    reply = ask(agent_with(ScriptedLLM([pay]), mcp), HR, "Quân số?")
    assert reply["type"] == "error" and "phê duyệt" in reply["answer"] and not mcp.executed
