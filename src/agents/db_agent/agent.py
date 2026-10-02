"""Database Agent — SQL query execution and database Q&A via MCP.

Inherits from ``BaseAgent``.
Uses ``LLMClient`` to translate natural language user questions into read-only
SQL SELECT queries, validates them via AST-based ``SqlValidator``, and
executes them via ``MCPClient``.
"""

import json
import logging
import re
from typing import Any, Optional

from src.agents.base_agent import BaseAgent
from src.agents.db_agent.rls_transformer import inject_row_level_security
from src.shared.auth import current_scope
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


class DatabaseAgent(BaseAgent):
    """Agent specialized in Database querying and SQL execution via MCP.

    Attributes:
        mcp_client: ``MCPClient`` instance for database execution.
        llm_client: Unified ``LLMClient`` for LLM reasoning.
        model: LLM model identifier.
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        llm_client: LLMClient,
        model: str = "openai/gpt-4o-mini",
    ) -> None:
        """Initialise the Database Agent.

        Args:
            mcp_client: Pre-configured MCP client.
            llm_client: Unified LLM client.
            model: Model ID to use.
        """
        self.mcp_client: MCPClient = mcp_client
        self.llm_client: LLMClient = llm_client
        self.model: str = model

    # ------------------------------------------------------------------
    # BaseAgent implementation
    # ------------------------------------------------------------------

    async def process_request(self, query: str, session_id: str) -> str:
        """Process a natural language database query.

        Steps:
          1. Generate SQL via LLM.
          2. Execute SQL via MCPClient.
          3. Format and summarize the results.

        Args:
            query: Natural language database question.
            session_id: Session correlation ID.

        Returns:
            str: JSON string or formatted natural language answer.
        """
        logger.info(
            "DatabaseAgent processing query (len=%d)",
            len(query),
            extra={"session_id": session_id},
        )

        # Unwrap clean query for SQL generation
        clean_query, _ = unwrap_user_input(query)

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
        is_valid, sanitized_sql, validation_error = validate_sql(
            raw_sql=sql_statement, session_id=session_id
        )

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

    def get_metadata(self) -> dict[str, str]:
        """Return metadata describing DatabaseAgent capabilities."""
        return {
            "name": "db_agent",
            "description": (
                "Agent chuyên thực thi truy vấn SQL SELECT trên PostgreSQL database "
                "để đếm số lượng, liệt kê bản ghi, tra cứu bảng rag_chunks "
                "hoặc thống kê cấu trúc dữ liệu lưu trữ."
            ),
        }

    async def generate_sql(self, query: str, session_id: str) -> tuple[str, str]:
        """Public accessor to generate SQL and explanation without executing."""
        return await self._generate_sql(query, session_id)

    def is_sensitive_sql(self, sql: str, query: str = "") -> bool:
        """Check if SQL or query accesses sensitive enterprise assets."""
        sensitive_pattern = r"\b(salary|salaries|employee_pii|financial_records|credentials|password|users|accounts|payroll|payment)\b"
        if re.search(sensitive_pattern, sql, re.IGNORECASE):
            return True
        sensitive_vi_pattern = r"(bảng lương|tiền lương|lương nhân viên|mật khẩu|tài khoản ngân hàng|chế độ lương|dữ liệu pii)"
        if re.search(sensitive_vi_pattern, query, re.IGNORECASE) or re.search(sensitive_pattern, query, re.IGNORECASE):
            return True
        return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _generate_sql(self, query: str, session_id: str) -> tuple[str, str]:
        """Call LLM to translate natural language into SQL SELECT."""
        try:
            res: Any = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": _DB_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                model=self.model,
                temperature=0.1,
                max_tokens=400,
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
