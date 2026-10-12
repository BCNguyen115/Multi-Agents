"""Database Agent — SQL question answering over PostgreSQL via MCP.

Inherits from ``BaseAgent``. Two modes:

  * **Company data** (a ``SchemaCatalog`` of schema ``aw`` is available): HR and executives ask about people, sales, purchasing and production.
    The model is shown only the tables of the caller's domains, writes one SELECT, ``validate_sql`` (AST) checks it against the SAME tables,
    row-level security is added for tables that carry tenant columns, and the query runs under the read-only role. A failed query is corrected
    by the model once. The answer is a Markdown table built by code from the returned rows plus a short model-written reading of THOSE rows;
    "tình hình công ty" style requests run the fixed KPI set of ``overview.py`` instead of free-form SQL.
  * **Knowledge-base tables** (no catalog): the original behaviour for ``rag_chunks`` / ``knowledge_documents``.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

from src.agents.base_agent import BaseAgent
from src.agents.db_agent import overview, schema_catalog
from src.agents.db_agent.presenter import markdown_table
from src.agents.db_agent.rls_transformer import inject_row_level_security
from src.agents.db_agent.schema_catalog import SchemaCatalog
from src.shared.auth import current_principal, current_scope
from src.agents.db_agent.validator import parameterize_sql, validate_sql
from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger
from src.shared.mcp_client import MCPClient
from src.shared.security import unwrap_user_input

logger: logging.Logger = get_logger(__name__)

_DB_AGENT_SYSTEM_PROMPT: str = (
    "Bạn là một Database Specialist kiêm SQL Specialist trong hệ thống Enterprise Multi-Agent.\n"
    "Nhiệm vụ: Chuyển đổi câu hỏi của người dùng thành câu lệnh SQL SELECT chính xác trên PostgreSQL database.\n\n"
    "Cấu trúc bảng khả dụng trong CSDL (`agentdb`):\n"
    "1. `rag_chunks`:\n"
    "   - `id` (BIGSERIAL PRIMARY KEY)\n"
    "   - `filename` (VARCHAR(255))\n"
    "   - `file_path` (TEXT)\n"
    "   - `section_title` (TEXT)\n"
    "   - `category` (VARCHAR(100))\n"
    "   - `chunk_index` (INTEGER)\n"
    "   - `content` (TEXT)\n"
    "   - `char_count` (INTEGER)\n"
    "   - `created_at` (TIMESTAMPTZ)\n\n"
    "2. `knowledge_documents`:\n"
    "   - `id` (BIGSERIAL PRIMARY KEY)\n"
    "   - `content` (TEXT)\n\n"
    "QUY TẮC:\n"
    "1. Chỉ sinh câu lệnh SQL SELECT hoặc WITH (Read-Only). Cấm INSERT, UPDATE, DELETE, DROP.\n"
    "2. Trả về JSON theo định dạng duy nhất:\n"
    "```json\n"
    "{\n"
    '  "sql": "<câu lệnh SQL SELECT>",\n'
    '  "explanation": "<Giải thích ngắn gọn ý nghĩa truy vấn>"\n'
    "}\n"
    "```\n"
)

_INSIGHT_PROMPT = (
    "Bạn viết nhận định ngắn cho Ban lãnh đạo / Nhân sự từ kết quả truy vấn dữ liệu công ty.\n"
    "QUY TẮC BẮT BUỘC: tối đa 4 gạch đầu dòng, mỗi dòng một ý, tiếng Việt. CHỈ nêu số có nguyên văn trong dữ liệu được đưa: "
    "chép số đúng như trong dữ liệu (ví dụ 12641672 hoặc 35.7), không làm tính mới, không làm tròn, không đổi đơn vị (không viết 'triệu', 'nghìn'), "
    "không suy diễn nguyên nhân. Nếu dữ liệu quá ít để nhận định, trả lời đúng một dòng: 'Chưa đủ dữ liệu để nhận định.'"
)

_NO_ACCESS = "Bạn chưa được cấp quyền xem dữ liệu công ty. Hãy liên hệ quản trị viên để được gán vai trò phù hợp."
_PLAN_TTL_SECONDS = 120.0


@dataclass
class SqlResult:
    """Outcome of ``DatabaseAgent.execute_sql``."""

    ok: bool
    sql: str = ""          # the statement that ran (validated, row-level security applied), the one shown to the person
    rows: Optional[list[dict[str, Any]]] = None
    row_count: int = 0
    error: str = ""


class DatabaseAgent(BaseAgent):
    """Agent specialized in Database querying and SQL execution via MCP.

    Attributes:
        mcp_client: ``MCPClient`` instance for database execution.
        llm_client: Unified ``LLMClient`` for LLM reasoning.
        model: LLM model identifier (writes the SQL).
        catalog: snapshot of the company schema; ``None`` keeps the knowledge-base-only behaviour.
        summary_model: model that writes the short reading of the rows (``model`` when empty).
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        llm_client: LLMClient,
        model: str = "openai/gpt-4o-mini",
        catalog: Optional[SchemaCatalog] = None,
        summary_model: str = "",
    ) -> None:
        """Initialise the Database Agent.

        Args:
            mcp_client: Pre-configured MCP client.
            llm_client: Unified LLM client.
            model: Model ID to use.
            catalog: Snapshot of schema ``aw`` (see ``SchemaCatalog.load``).
            summary_model: Model ID for the short reading of results.
        """
        self.mcp_client: MCPClient = mcp_client
        self.llm_client: LLMClient = llm_client
        self.model: str = model
        self.catalog: Optional[SchemaCatalog] = catalog
        self.summary_model: str = summary_model or model
        self._planned: dict[tuple[str, str], tuple[float, str, str]] = {}  # SQL the approval gate already looked at, so the same statement runs

    # ------------------------------------------------------------------
    # BaseAgent implementation
    # ------------------------------------------------------------------

    @property
    def _company(self) -> Optional[SchemaCatalog]:
        return self.catalog if self.catalog is not None and self.catalog.available else None

    async def process_request(self, query: str, session_id: str) -> str:
        """Process a natural language database query.

        Args:
            query: Natural language database question.
            session_id: Session correlation ID.

        Returns:
            str: JSON string with ``answer`` (Markdown), ``sql``, ``row_count`` and ``data``.
        """
        logger.info("DatabaseAgent processing query (len=%d)", len(query), extra={"session_id": session_id})
        clean_query, _ = unwrap_user_input(query)
        catalog = self._company
        if catalog is None:
            return await self._process_legacy(clean_query, session_id)
        return await self._process_company(clean_query, session_id, catalog)

    def get_metadata(self) -> dict[str, str]:
        """Return metadata describing DatabaseAgent capabilities."""
        return {
            "name": "db_agent",
            "description": (
                "Agent chuyên thực thi truy vấn SQL SELECT trên PostgreSQL database để khảo sát số liệu công ty: "
                "nhân sự, nhân viên, phòng ban, doanh thu bán hàng, đơn hàng, nhà cung cấp, tồn kho, sản xuất, "
                "cũng như đếm bản ghi và thống kê bảng rag_chunks."
            ),
        }

    async def generate_sql(self, query: str, session_id: str) -> tuple[str, str]:
        """Generate SQL and explanation without executing (the approval gate looks at it). The statement is remembered for a short time so
        that ``process_request`` runs the very statement that was checked, not a second, possibly different, sample."""
        clean_query, _ = unwrap_user_input(query)
        catalog = self._company
        if catalog is None:
            return await self._generate_sql(clean_query, session_id)
        sql, explanation = await self._generate_company_sql(clean_query, session_id, catalog)
        if sql:
            self._planned[(session_id, clean_query)] = (time.monotonic(), sql, explanation)
        return sql, explanation

    def is_sensitive_sql(self, sql: str, query: str = "") -> bool:
        """Check if SQL or query accesses sensitive enterprise assets (salaries, credentials, payments...)."""
        sensitive_pattern = (
            r"\b(salary|salaries|employee_pii|financial_records|credentials|password|users|accounts|payroll|payment|employee_pay_history|pay_history|pay_rate)\b"
        )
        if re.search(sensitive_pattern, sql, re.IGNORECASE):
            return True
        sensitive_vi_pattern = r"(bảng lương|tiền lương|lương nhân viên|mức lương|lương|mật khẩu|tài khoản ngân hàng|chế độ lương|dữ liệu pii)"
        if re.search(sensitive_vi_pattern, query, re.IGNORECASE) or re.search(sensitive_pattern, query, re.IGNORECASE):
            return True
        return False

    async def execute_sql(self, sql: str, session_id: str, tenant_id: Optional[str] = None, department_id: Optional[str] = None) -> SqlResult:
        """Validate, scope and run ``sql`` for the current caller. Used for every statement, including one a person approved: an approval
        decides WHETHER it runs, never lets it skip the checks."""
        principal = current_principal()
        catalog = self._company
        allowed = schema_catalog.allowed_tables(catalog, principal) if catalog is not None else None
        ok, sanitized, error = validate_sql(raw_sql=sql, session_id=session_id, allowed_tables=allowed)
        if not ok:
            return SqlResult(False, sql, error=error)
        if tenant_id is None or department_id is None:
            tenant_id, department_id = current_scope()
        try:
            secured = inject_row_level_security(
                sql=sanitized, tenant_id=tenant_id, department_id=department_id,
                unscoped_tables=frozenset(allowed.get("aw", set())) if allowed else frozenset(),
            )
        except Exception as exc:  # fail closed: never run a query that could not be scoped to the caller
            logger.error("RLS AST injection failed, query NOT executed: %s", exc, extra={"session_id": session_id})
            return SqlResult(False, sanitized, error="Không thể áp dụng chính sách bảo mật theo tenant cho truy vấn này nên truy vấn không được thực thi.")
        parameterized, params = parameterize_sql(secured)
        raw = await self.mcp_client.execute_sql_query(query_sql=parameterized, params=params, session_id=session_id)
        try:
            result: dict[str, Any] = json.loads(raw)
        except Exception:
            result = {"status": "error", "message": raw}
        if result.get("status") != "success":
            return SqlResult(False, secured, error=str(result.get("message", "Lỗi truy vấn không xác định.")))
        rows = result.get("data", [])
        return SqlResult(True, secured, rows, int(result.get("row_count", len(rows))))

    # ------------------------------------------------------------------
    # Company data
    # ------------------------------------------------------------------

    @staticmethod
    def _reply(answer: str, sql: str = "", rows: Optional[list[dict[str, Any]]] = None, row_count: int = 0, refused: bool = False) -> str:
        """``refused``: nothing was run (no access, nothing to answer with, the statement failed): ``type: error`` keeps the verifier from
        judging a refusal as if it were an answer."""
        payload: dict[str, Any] = {"answer": answer, "sql": sql, "data": rows or []}
        if rows is not None:
            payload["row_count"] = row_count
        if refused:
            payload["type"] = "error"
        return json.dumps(payload, ensure_ascii=False)

    async def _process_company(self, query: str, session_id: str, catalog: SchemaCatalog) -> str:
        principal = current_principal()
        domains = schema_catalog.principal_domains(principal)
        allowed = schema_catalog.allowed_tables(catalog, principal)
        if not allowed.get("aw") and not allowed.get("public"):
            return self._reply(_NO_ACCESS, refused=True)

        wanted = overview.snapshot_request(query)
        if wanted is not None:
            usable = wanted & domains
            if not usable:
                return self._reply("Bạn không có quyền xem dữ liệu " + ", ".join(sorted(wanted)) + ". Hãy hỏi về phần dữ liệu thuộc vai trò của bạn.", refused=True)
            return await self._snapshot(query, session_id, usable, allowed.get("aw", set()), catalog)

        feedback = ""
        last = SqlResult(False)
        for attempt in range(2):  # one correction at most
            planned = self._take_planned(session_id, query) if attempt == 0 else None
            sql, explanation = planned or await self._generate_company_sql(query, session_id, catalog, feedback)
            if not sql:
                return self._reply(explanation or "Không thể tạo câu lệnh SQL từ câu hỏi của bạn. Vui lòng thử diễn đạt rõ hơn.", refused=True)
            if self.is_sensitive_sql(sql):
                # the approval gate looks at the statement BEFORE this runs and an approved one runs through execute_sql, never through here:
                # a sensitive statement that reaches this point (a second sample that differs from the one the gate saw) must not run unapproved
                return self._reply("Truy vấn này chạm vào dữ liệu nhạy cảm (ví dụ lương) nên chỉ chạy sau khi người có thẩm quyền phê duyệt. "
                                   "Hãy gửi lại câu hỏi để được chuyển sang bước phê duyệt.", sql, refused=True)
            last = await self.execute_sql(sql, session_id)
            if last.ok:
                return await self._present(query, explanation, last, session_id)
            feedback = last.error
            logger.warning("db_agent attempt %d failed: %s", attempt + 1, last.error[:200], extra={"session_id": session_id})
        return self._reply(f"Truy vấn không thực hiện được: {last.error}", last.sql, refused=True)

    def _take_planned(self, session_id: str, query: str) -> Optional[tuple[str, str]]:
        now = time.monotonic()
        for key in [k for k, (at, _, _) in self._planned.items() if now - at > _PLAN_TTL_SECONDS]:
            del self._planned[key]
        entry = self._planned.pop((session_id, query), None)
        return (entry[1], entry[2]) if entry else None

    async def _present(self, query: str, explanation: str, result: SqlResult, session_id: str) -> str:
        rows = result.rows or []
        parts = [f"**Kết quả truy vấn ({result.row_count} dòng):**"]
        if explanation:
            parts.append(explanation)
        table = markdown_table(rows)
        parts.append(table or "*Không có dòng nào khớp.*")
        insight = await self._insight(query, [("", rows)], session_id) if rows else ""
        if insight:
            parts.append("**Nhận định:**\n" + insight)
        parts.append(f"- **SQL:** `{result.sql}`")
        return self._reply("\n\n".join(parts), result.sql, rows, result.row_count)

    async def _snapshot(self, query: str, session_id: str, domains: set[str], readable: set[str], catalog: SchemaCatalog) -> str:
        kpis = overview.kpis_for(domains, readable)
        if not kpis:
            return self._reply("Chưa có chỉ số tổng quan nào cho phần dữ liệu bạn được xem.", refused=True)
        sections: list[tuple[str, list[dict[str, Any]]]] = []
        failed: list[str] = []
        for kpi in kpis:
            result = await self.execute_sql(schema_catalog.render_as_of(kpi.sql, catalog.as_of), session_id)
            if result.ok:
                sections.append((kpi.title, result.rows or []))
            else:
                failed.append(kpi.title)
                logger.warning("overview KPI '%s' failed: %s", kpi.title, result.error[:200], extra={"session_id": session_id})
        as_of = f" (dữ liệu đến {catalog.as_of})" if catalog.as_of else ""
        parts = [f"**Tổng quan tình hình công ty{as_of}**"]
        flat: list[dict[str, Any]] = []
        for title, rows in sections:
            parts.append(f"### {title}\n\n" + (markdown_table(rows) or "*Không có dữ liệu.*"))
            flat.extend(rows)
        if failed:
            parts.append("*Chưa lấy được: " + "; ".join(failed) + ".*")
        insight = await self._insight(query, sections, session_id) if flat else ""
        if insight:
            parts.append("**Nhận định:**\n" + insight)
        # the date in the heading is a figure of the reply: carrying it in the data lets the number check ground it
        dated = [{"as_of": str(catalog.as_of)}] if catalog.as_of else []
        shown_sql = "; ".join(schema_catalog.render_as_of(k.sql, catalog.as_of) for k in kpis)
        return self._reply("\n\n".join(parts), shown_sql, dated + flat, len(flat))

    async def _insight(self, question: str, sections: list[tuple[str, list[dict[str, Any]]]], session_id: str) -> str:
        """A short reading of the rows by a model; empty on any failure (the table stands on its own)."""
        data = {title or "ket_qua": rows[:25] for title, rows in sections}
        try:
            res: Any = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": _INSIGHT_PROMPT},
                    {"role": "user", "content": f"Câu hỏi: {question}\n\nDữ liệu (JSON):\n{json.dumps(data, ensure_ascii=False, default=str)}"},
                ],
                model=self.summary_model, temperature=0.1, max_tokens=300, metadata={"agent": "db_agent", "step": "insight"}, session_id=session_id,
            )
            return self._grounded_lines((res.choices[0].message.content or "").strip(), [row for _, rows in sections for row in rows])
        except Exception as exc:  # noqa: BLE001
            logger.warning("db_agent insight failed: %s", exc, extra={"session_id": session_id})
            return ""

    @staticmethod
    def _grounded_lines(text: str, rows: list[dict[str, Any]]) -> str:
        """The lines of the model's reading whose every figure appears in the rows (the figure check the orchestrator runs on the whole answer,
        applied per line here): a line with a total or a percentage the model worked out itself is dropped instead of failing the answer."""
        from src.agents.data_agent.grounding import _walk, numbers_grounded

        numbers: list[float] = [float(len(rows))]
        strings: list[str] = []
        _walk(rows, numbers, strings)
        kept = [line for line in text.splitlines() if line.strip() and numbers_grounded(line, [], extra_numbers=numbers, extra_strings=strings, literals=())[0]]
        return "\n".join(kept)

    async def _generate_company_sql(self, query: str, session_id: str, catalog: SchemaCatalog, feedback: str = "") -> tuple[str, str]:
        prompt = schema_catalog.build_prompt(catalog, current_principal())
        user = query if not feedback else f"{query}\n\n[Lần trước câu SQL bị lỗi: {feedback}\nHãy viết lại câu SQL đúng, chỉ dùng các bảng được phép.]"
        return await self._ask_for_sql(prompt, user, session_id, max_tokens=900)

    # ------------------------------------------------------------------
    # Knowledge-base tables (original behaviour)
    # ------------------------------------------------------------------

    async def _process_legacy(self, clean_query: str, session_id: str) -> str:
        # Step 1: Generate SQL from query
        sql_statement, explanation = await self._generate_sql(clean_query, session_id)

        if not sql_statement:
            return json.dumps(
                {
                    "answer": "Không thể tạo câu lệnh SQL từ câu hỏi của bạn. Vui lòng thử diễn đạt rõ hơn.",
                    "sql": "",
                    "data": [],
                },
                ensure_ascii=False,
            )

        # Step 1b: AST SQL Validation & Guardrails
        is_valid, sanitized_sql, validation_error = validate_sql(raw_sql=sql_statement, session_id=session_id)

        if not is_valid:
            logger.warning(
                "SQL Validator REJECTED query: %s | reason: %s",
                sql_statement[:100],
                validation_error,
                extra={"session_id": session_id},
            )
            return json.dumps(
                {
                    "answer": f"Truy vấn SQL bị từ chối bởi hệ thống bảo mật: {validation_error}",
                    "sql": sql_statement,
                    "data": [],
                },
                ensure_ascii=False,
            )

        # Use sanitized SQL (with auto-injected LIMIT if needed)
        sql_statement = sanitized_sql

        # Step 1c: AST Row-Level Security (RLS) Injection via sqlglot
        tenant_id, department_id = current_scope()  # the caller's scope (configured defaults when authentication is off)
        try:
            sql_statement = inject_row_level_security(sql=sql_statement, tenant_id=tenant_id, department_id=department_id)
            logger.info(
                "DatabaseAgent: Successfully applied Row-Level Security (RLS) AST policy",
                extra={"session_id": session_id},
            )
        except Exception as rls_err:  # fail closed: never run a query that could not be scoped to the caller
            logger.error("RLS AST injection failed, query NOT executed: %s", rls_err, extra={"session_id": session_id})
            return json.dumps(
                {"answer": "Không thể áp dụng chính sách bảo mật theo tenant cho truy vấn này nên truy vấn không được thực thi.", "sql": sql_statement, "data": []},
                ensure_ascii=False,
            )

        # Step 1d: Parameterize SQL (AST Literal Extraction into $1, $2, ...)
        parameterized_sql, query_params = parameterize_sql(sql_statement)

        # Step 2: Execute Parameterized SQL via MCP
        mcp_res_raw: str = await self.mcp_client.execute_sql_query(
            query_sql=parameterized_sql,
            params=query_params,
            session_id=session_id,
        )

        try:
            mcp_res: dict[str, Any] = json.loads(mcp_res_raw)
        except Exception:
            mcp_res = {"status": "error", "message": mcp_res_raw}

        # Step 3: Summarize results
        if mcp_res.get("status") == "success":
            data_items: list[dict[str, Any]] = mcp_res.get("data", [])
            row_count: int = mcp_res.get("row_count", len(data_items))

            summary_text: str = (
                f"**Kết quả truy vấn Database ({row_count} dòng):**\n\n"
                f"- **SQL Executed:** `{sql_statement}`\n"
                f"- **Mô tả:** {explanation}\n\n"
            )

            result_payload: dict[str, Any] = {
                "answer": summary_text,
                "sql": sql_statement,
                "row_count": row_count,
                "data": data_items,
            }
            return json.dumps(result_payload, ensure_ascii=False)
        else:
            err_msg: str = mcp_res.get("message", "Lỗi truy vấn không xác định.")
            return json.dumps(
                {
                    "answer": f"Lỗi truy vấn Database: {err_msg}",
                    "sql": sql_statement,
                    "data": [],
                },
                ensure_ascii=False,
            )

    async def _generate_sql(self, query: str, session_id: str) -> tuple[str, str]:
        """Call LLM to translate natural language into SQL SELECT (knowledge-base tables)."""
        return await self._ask_for_sql(_DB_AGENT_SYSTEM_PROMPT, query, session_id, max_tokens=400)

    async def _ask_for_sql(self, system_prompt: str, user_text: str, session_id: str, max_tokens: int) -> tuple[str, str]:
        try:
            res: Any = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                model=self.model,
                temperature=0.1,
                max_tokens=max_tokens,
                metadata={"agent": "db_agent"},
                session_id=session_id,
            )

            raw_text: str = res.choices[0].message.content or ""
            match = re.search(r"```json\s*\n(.*?)\n```", raw_text, re.DOTALL)
            json_str = match.group(1) if match else raw_text

            parsed = json.loads(json_str)
            return parsed.get("sql", "").strip(), parsed.get("explanation", "")

        except Exception as exc:
            logger.error(
                "DatabaseAgent SQL generation error: %s",
                exc,
                extra={"session_id": session_id},
            )
            return "", ""
