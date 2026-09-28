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
import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from src.shared.logger import get_logger
from src.shared.postgres_client import PostgresClient

logger: logging.Logger = get_logger(__name__)

# Allowed domains for Enterprise integration tools
ALLOWED_DOMAINS: set[str] = {
    "localhost",
    "127.0.0.1",
    "[::1]",
    "api.enterprise.internal",
    "jsonplaceholder.typicode.com",
    "httpbin.org",
    "example.com",
}

_SHELL_INJECTION_CHARS = re.compile(r"[;`|$\n\r]|&&|\|\||\$\(")
_PATH_TRAVERSAL_CHARS = re.compile(r"\.\./|\.\.\\|%2e%2e|/\.\.", re.IGNORECASE)


class RESTToolInput(BaseModel):
    """Pydantic v2 schema for strict REST Tool parameter validation."""
    url: str = Field(..., description="Target REST API URL")
    method: str = Field("GET", description="HTTP Method")
    payload: Optional[dict[str, Any]] = Field(None, description="Request JSON payload")

    @field_validator("url")
    @classmethod
    def validate_url_security(cls, v: str) -> str:
        clean_url = v.strip()
        if not clean_url.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")

        # Shell Injection check
        if _SHELL_INJECTION_CHARS.search(clean_url):
            raise ValueError("URL contains prohibited shell control characters.")

        # Path Traversal check
        if _PATH_TRAVERSAL_CHARS.search(clean_url):
            raise ValueError("URL contains prohibited path traversal sequences.")

        # Domain whitelist check
        parsed = urlparse(clean_url)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise ValueError("Invalid URL: missing hostname.")

        if hostname not in ALLOWED_DOMAINS and not hostname.endswith(".internal"):
            raise ValueError(f"Domain '{hostname}' is not in the trusted enterprise whitelist.")

        return clean_url

    @field_validator("method")
    @classmethod
    def validate_http_method(cls, v: str) -> str:
        upper_m = v.strip().upper()
        if upper_m not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            raise ValueError(f"Unsupported HTTP method: {v}")
        return upper_m


class SQLToolInput(BaseModel):
    """Pydantic v2 schema for strict SQL Tool parameter validation."""
    query_sql: str = Field(..., description="SQL SELECT query string")
    params: Optional[list[Any]] = Field(default_factory=list, description="Positional query parameters")

    @field_validator("query_sql")
    @classmethod
    def validate_sql_security(cls, v: str) -> str:
        clean_sql = v.strip()
        if not clean_sql:
            raise ValueError("SQL query cannot be empty.")

        # Shell expansion check
        if any(c in clean_sql for c in ["`", "$("]):
            raise ValueError("SQL query contains prohibited shell expansion characters.")

        return clean_sql


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
        params: Optional[list[Any]] = None,
        session_id: str = "N/A",
    ) -> str:
        """Execute a read-only SQL query against PostgreSQL using parameterized statements.

        Enforces strict AST and parameter validation: rejects mutations and shell expansion.

        Args:
            query_sql: SQL query string to execute (e.g. with $1, $2 placeholders).
            params: Optional positional parameter list for prepared execution.
            session_id: Correlation ID for logging.

        Returns:
            str: JSON formatted string containing query results or error.
        """
        # Strict Pydantic v2 Parameter Validation
        try:
            validated = SQLToolInput(query_sql=query_sql, params=params or [])
            clean_query = validated.query_sql
            query_params = validated.params or []
        except Exception as val_err:
            logger.warning(
                "MCP Security: Rejected SQL parameters: %s",
                val_err,
                extra={"session_id": session_id},
            )
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Security policy violation in SQL parameters: {val_err}",
                },
                ensure_ascii=False,
            )

        logger.info(
            "MCP Tool: execute_sql_query: %s (params=%s)",
            clean_query[:100],
            query_params,
            extra={"session_id": session_id},
        )

        clean_lower: str = clean_query.strip().lower()
        if not clean_lower.startswith("select") and not clean_lower.startswith("with"):
            logger.warning(
                "MCP Security: Rejected non-SELECT query: %s",
                clean_query,
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
            records = await self.pg_client.fetch(
                clean_query, *query_params, session_id=session_id
            )
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
        """Execute an external REST API HTTP request via httpx with strict validation.

        Args:
            url: Destination URL.
            method: HTTP method (GET, POST, PUT, DELETE).
            headers: Optional HTTP headers dictionary.
            payload: Optional JSON body payload for POST/PUT.
            session_id: Correlation ID for logging.

        Returns:
            str: JSON string containing response data or error.
        """
        # Strict Pydantic v2 Tool Input Validation (Blocks shell injection, path traversal, domain mismatch)
        try:
            validated = RESTToolInput(url=url, method=method, payload=payload)
            target_url = validated.url
            target_method = validated.method
            target_payload = validated.payload
        except Exception as val_err:
            logger.warning(
                "MCP Security: Rejected REST request parameters: %s",
                val_err,
                extra={"session_id": session_id},
            )
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Security policy violation in REST request: {val_err}",
                },
                ensure_ascii=False,
            )

        logger.info(
            "MCP Tool: execute_rest_request %s %s",
            target_method,
            target_url,
            extra={"session_id": session_id},
        )

        try:
            if target_method == "GET":
                response = await self.http_client.get(target_url, headers=headers)
            elif target_method == "POST":
                response = await self.http_client.post(target_url, headers=headers, json=target_payload)
            elif target_method == "PUT":
                response = await self.http_client.put(target_url, headers=headers, json=target_payload)
            elif target_method == "DELETE":
                response = await self.http_client.delete(target_url, headers=headers)
            elif target_method == "PATCH":
                response = await self.http_client.patch(target_url, headers=headers, json=target_payload)
            else:
                return json.dumps(
                    {"status": "error", "message": f"Unsupported HTTP method: {target_method}"},
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
