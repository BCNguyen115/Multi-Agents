"""Integration Agent — External REST API invocation via MCP.

Inherits from ``BaseAgent``.
Uses ``LLMClient`` to parse natural language integration requests into HTTP
requests (method, URL, payload), executes them via ``MCPClient``, and formats
the response.
"""

import json
import logging
import re
from typing import Any, Optional

from src.agents.base_agent import BaseAgent
from src.shared.llm_client import LLMClient
from src.shared.mcp_client import MCPClient
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

_INTEGRATION_SYSTEM_PROMPT: str = (
    "Bạn là một Integration Specialist trong hệ thống Multi-Agent.\n"
    "Nhiệm vụ: Phân tích yêu cầu gọi API và sinh ra thông tin HTTP request tương ứng.\n\n"
    "CÁC ENDPOINT MẶC ĐỊNH KHẢ DỤNG:\n"
    "1. `http://localhost:8000/health` (GET) — Health check endpoint của Gateway API\n\n"
    "Trả về định dạng JSON duy nhất:\n"
    "```json\n"
    "{\n"
    '  "url": "<URL API>",\n'
    '  "method": "<GET | POST | PUT | DELETE>",\n'
    '  "payload": null hoặc JSON object,\n'
    '  "explanation": "<Mô tả ngắn gọn mục đích gọi API>"\n'
    "}\n"
    "```\n"
)


class IntegrationAgent(BaseAgent):
    """Agent specialized in External REST API integrations via MCP.

    Attributes:
        mcp_client: ``MCPClient`` instance for HTTP REST execution.
        llm_client: Unified ``LLMClient`` for LLM reasoning.
        model: LLM model identifier.
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        llm_client: LLMClient,
        model: str = "openai/gpt-4o-mini",
    ) -> None:
        """Initialise the Integration Agent.

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
        """Process a natural language REST API request.

        Args:
            query: User's integration request.
            session_id: Session correlation ID.

        Returns:
            str: Response JSON string summarizing API result.
        """
        logger.info(
            "IntegrationAgent processing request (len=%d)",
            len(query),
            extra={"session_id": session_id},
        )

        url, method, payload, explanation = await self._parse_request(
            query, session_id
        )

        if not url:
            return json.dumps(
                {
                    "answer": "Không thể xác định URL API cần gọi từ yêu cầu. Vui lòng cung cấp URL hoặc endpoint cụ thể.",
                    "status": "error",
                },
                ensure_ascii=False,
            )

        # Execute HTTP call via MCPClient
        mcp_res_raw: str = await self.mcp_client.execute_rest_request(
            url=url,
            method=method,
            payload=payload,
            session_id=session_id,
        )

        try:
            mcp_res: dict[str, Any] = json.loads(mcp_res_raw)
        except Exception:
            mcp_res = {"status": "error", "data": mcp_res_raw}

        status: str = mcp_res.get("status", "unknown")
        status_code: Any = mcp_res.get("status_code", "N/A")
        data: Any = mcp_res.get("data", {})

        summary: str = (
            f"**Kết quả tích hợp API ({method} {url}):**\n\n"
            f"- **Trạng thái:** HTTP {status_code} ({status.upper()})\n"
            f"- **Mục đích:** {explanation}\n"
            f"- **Response Data:**\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"
        )

        return json.dumps(
            {
                "answer": summary,
                "url": url,
                "method": method,
                "status_code": status_code,
                "data": data,
            },
            ensure_ascii=False,
        )

    def get_metadata(self) -> dict[str, str]:
        """Return metadata describing IntegrationAgent capabilities."""
        return {
            "name": "integration_agent",
            "description": (
                "Agent chuyên gọi REST API ngõ ngoài (GET, POST, PUT, DELETE), "
                "kết nối hệ thống bên ngoài, health check endpoint, hoặc tích hợp dịch vụ HTTP."
            ),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _parse_request(
        self, query: str, session_id: str
    ) -> tuple[str, str, Optional[dict[str, Any]], str]:
        """Parse natural language query into HTTP request spec."""
        try:
            res: Any = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": _INTEGRATION_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                model=self.model,
                temperature=0.1,
                max_tokens=400,
                metadata={"agent": "integration_agent"},
                session_id=session_id,
            )

            raw_text: str = res.choices[0].message.content or ""
            match = re.search(r"```json\s*\n(.*?)\n```", raw_text, re.DOTALL)
            json_str = match.group(1) if match else raw_text

            parsed = json.loads(json_str)
            return (
                parsed.get("url", ""),
                parsed.get("method", "GET"),
                parsed.get("payload"),
                parsed.get("explanation", ""),
            )

        except Exception as exc:
            logger.error(
                "IntegrationAgent parsing error: %s",
                exc,
                extra={"session_id": session_id},
            )
            return "", "GET", None, ""
