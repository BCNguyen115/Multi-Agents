"""Model Context Protocol (MCP) Client module.

Standardises external tool execution (Database SQL queries, REST API requests)
following the Model Context Protocol abstractions (Layer 3).

Provides:
  1. ``execute_sql_query``: Secure PostgreSQL query execution via PostgresClient.
  2. ``execute_rest_request``: Async HTTP requests via httpx.
  3. ``list_tools``: Self-describing tool registry for LLM agents.
"""

import json
import logging
from typing import Any, Optional

import httpx

from src.shared.logger import get_logger
from src.shared.postgres_client import PostgresClient

logger: logging.Logger = get_logger(__name__)


class MCPClient:
    """Model Context Protocol Client wrapper.

    Acts as the standard integration hub between AI Agents and external
    data/service tools (PostgreSQL DB, REST endpoints).

    Attributes:
        pg_client: Pre-connected ``PostgresClient`` instance.
        http_client: Async ``httpx.AsyncClient`` instance for REST calls.
    """

    def __init__(self, pg_client: Optional[PostgresClient] = None) -> None:
        """Initialise the MCP Client.

        Args:
            pg_client: Optional pre-connected PostgresClient.
        """
        self.pg_client: Optional[PostgresClient] = pg_client
        self.http_client: httpx.AsyncClient = httpx.AsyncClient(timeout=30.0)

    # ------------------------------------------------------------------
    # MCP Database Tool Execution
    # ------------------------------------------------------------------

    async def execute_sql_query(
        self,
        query_sql: str,
        session_id: str = "N/A",
    ) -> str:
        """Execute a read-only SQL query against PostgreSQL.

        Enforces basic security: rejects non-SELECT queries to prevent
        unintended mutation or data loss.

        Args:
            query_sql: SQL query string to execute.
            session_id: Correlation ID for logging.

        Returns:
            str: JSON formatted string containing query results or error.
        """
        logger.info(
            "MCP Tool: execute_sql_query: %s",
            query_sql[:100],
            extra={"session_id": session_id},
        )

        clean_sql: str = query_sql.strip().lower()
        if not clean_sql.startswith("select") and not clean_sql.startswith("with"):
            logger.warning(
                "MCP Security: Rejected non-SELECT query: %s",
                query_sql,
                extra={"session_id": session_id},
            )
            return json.dumps(
                {
                    "status": "error",
                    "message": "Security policy: Only read-only SELECT queries are allowed.",
                },
                ensure_ascii=False,
            )

        if self.pg_client is None:
            return json.dumps(
                {"status": "error", "message": "PostgreSQL client is not configured."},
                ensure_ascii=False,
            )

        try:
            records = await self.pg_client.fetch(query_sql, session_id=session_id)
            # Convert Record objects to list of dicts
            results: list[dict[str, Any]] = [dict(record) for record in records]

            # Serialize datetime and special types if any
            clean_results: list[dict[str, Any]] = []
            for row in results:
                clean_row: dict[str, Any] = {}
                for k, v in row.items():
                    if hasattr(v, "isoformat"):
                        clean_row[k] = v.isoformat()
                    elif isinstance(v, (bytes, bytearray)):
                        clean_row[k] = str(v)
                    else:
                        clean_row[k] = v
                clean_results.append(clean_row)

            logger.info(
                "MCP execute_sql_query returned %d rows",
                len(clean_results),
                extra={"session_id": session_id},
            )

            return json.dumps(
                {
                    "status": "success",
                    "row_count": len(clean_results),
                    "data": clean_results[:50],  # Limit max rows in context
                },
                ensure_ascii=False,
            )

        except Exception as exc:
            logger.error(
                "MCP execute_sql_query error: %s",
                exc,
                extra={"session_id": session_id},
            )
            return json.dumps(
                {"status": "error", "message": f"Database query error: {exc}"},
                ensure_ascii=False,
            )

    # ------------------------------------------------------------------
    # MCP REST Tool Execution
    # ------------------------------------------------------------------

    async def execute_rest_request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict[str, str]] = None,
        payload: Optional[dict[str, Any]] = None,
        session_id: str = "N/A",
    ) -> str:
        """Execute an external REST API HTTP request via httpx.

        Args:
            url: Destination URL.
            method: HTTP method (GET, POST, PUT, DELETE).
            headers: Optional HTTP headers dictionary.
            payload: Optional JSON body payload for POST/PUT.
            session_id: Correlation ID for logging.

        Returns:
            str: JSON string containing response data or error.
        """
        logger.info(
            "MCP Tool: execute_rest_request %s %s",
            method.upper(),
            url,
            extra={"session_id": session_id},
        )

        try:
            req_method: str = method.upper()
            if req_method == "GET":
                response = await self.http_client.get(url, headers=headers)
            elif req_method == "POST":
                response = await self.http_client.post(url, headers=headers, json=payload)
            elif req_method == "PUT":
                response = await self.http_client.put(url, headers=headers, json=payload)
            elif req_method == "DELETE":
                response = await self.http_client.delete(url, headers=headers)
            else:
                return json.dumps(
                    {"status": "error", "message": f"Unsupported HTTP method: {method}"},
                    ensure_ascii=False,
                )

            status_code: int = response.status_code
            try:
                data: Any = response.json()
            except Exception:
                data = response.text[:1000]

            logger.info(
                "MCP execute_rest_request returned HTTP %d",
                status_code,
                extra={"session_id": session_id},
            )

            return json.dumps(
                {
                    "status": "success" if response.is_success else "error",
                    "status_code": status_code,
                    "data": data,
                },
                ensure_ascii=False,
            )

        except Exception as exc:
            logger.error(
                "MCP execute_rest_request error: %s",
                exc,
                extra={"session_id": session_id},
            )
            return json.dumps(
                {"status": "error", "message": f"HTTP request error: {exc}"},
                ensure_ascii=False,
            )

    # ------------------------------------------------------------------
    # MCP Tool Registry Listing
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        """Return descriptions of all available MCP tools."""
        return [
            {
                "name": "execute_sql_query",
                "description": "Chạy câu lệnh SQL SELECT trên PostgreSQL database để lấy dữ liệu.",
                "parameters": {
                    "query_sql": "Chuỗi SQL SELECT (VD: SELECT * FROM rag_chunks LIMIT 5)"
                },
            },
            {
                "name": "execute_rest_request",
                "description": "Gọi REST API ngõ ngoài (GET, POST, PUT, DELETE).",
                "parameters": {
                    "url": "Đường dẫn URL của API",
                    "method": "Phương thức HTTP (GET/POST)",
                    "payload": "Dữ liệu body JSON (nếu có)",
                },
            },
        ]

    async def close(self) -> None:
        """Close underlying HTTP client resources."""
        await self.http_client.aclose()
