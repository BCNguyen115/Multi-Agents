"""Unit & Integration tests for Backend Audit & Optimization Upgrades.

Covers:
  1. POST /api/chat/title behavior (fast model, timeout fallback intact without ellipsis).
  2. DataAgent non-dashboard routing (requires_dashboard=False for text queries).
  3. RAGAgent fallback when TEI Reranker is unavailable.
  4. SQL security guardrails with sqlglot (rejecting mutation queries).
  5. Infrastructure configurations (Postgres pool 5-20, Redis TTL 86400s).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

def _passthrough_dec(*args, **kwargs):
    def _inner(fn):
        return fn
    return _inner

if "fastapi" not in sys.modules:
    mock_fastapi = MagicMock()
    mock_app = MagicMock()
    mock_app.get = _passthrough_dec
    mock_app.post = _passthrough_dec
    mock_app.put = _passthrough_dec
    mock_app.delete = _passthrough_dec
    mock_app.middleware = _passthrough_dec
    mock_fastapi.FastAPI = MagicMock(return_value=mock_app)
    mock_fastapi.HTTPException = Exception
    sys.modules["fastapi"] = mock_fastapi

if "fastapi.middleware.cors" not in sys.modules:
    sys.modules["fastapi.middleware.cors"] = MagicMock()

def _installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# Mock only dependencies that are NOT installed: a MagicMock left in sys.modules over a real package leaks
# into every other test module of the session (it broke the real-database RAG test).
for mod in [
    "litellm",
    "asyncpg",
    "redis",
    "redis.asyncio",
    "sse_starlette",
    "sse_starlette.sse",
]:
    if mod not in sys.modules and not _installed(mod):
        sys.modules[mod] = MagicMock()

import pandas as pd
import pytest

os.environ.setdefault("INTERNAL_JWT_SECRET", "test-secret-key-for-pytest-only-12345")

from src.agents.db_agent.validator import validate_sql
from src.agents.data_agent.agent import DataAnalystAgent, safe_read_csv
from src.agents.rag_agent.agent import RAGAgent
from src.config import settings
from src.gateway.main import TitleRequest, TitleResponse, generate_chat_title
from src.orchestrator.core import Orchestrator
from src.orchestrator.prompt_templates import build_planner_prompt
from src.shared.postgres_client import PostgresClient
from src.shared.redis_client import RedisClient


# ---------------------------------------------------------------------------
# Test Suite 1: Title Generation & Fallback
# ---------------------------------------------------------------------------

class TestTitleGeneration:
    """Test suite for POST /api/chat/title."""

    def test_empty_query_returns_default(self) -> None:
        """Empty query should return 'Cuộc trò chuyện mới'."""
        async def _run():
            req = TitleRequest(query="   ")
            return await generate_chat_title(req)

        resp = asyncio.run(_run())
        assert resp.title == "Cuộc trò chuyện mới"

    def test_llm_timeout_falls_back_to_exact_query(self) -> None:
        """On timeout, should return original query intact without truncation or ellipses."""
        original_query = "Phân tích doanh thu các chi nhánh quý 3 năm 2026 chi tiết"
        req = TitleRequest(query=original_query)

        # Mock an LLM that hangs forever to trigger timeout
        mock_llm = MagicMock()
        async def slow_chat(*args, **kwargs):
            await asyncio.sleep(5.0)
            return MagicMock()

        mock_llm.chat_completion = slow_chat

        with patch("src.gateway.main.llm_client", mock_llm):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                resp = asyncio.run(generate_chat_title(req))
                assert resp.title == original_query
                assert "..." not in resp.title

    def test_llm_exception_falls_back_to_exact_query(self) -> None:
        """On LLM error, should return original query intact without truncation or ellipses."""
        original_query = "Tìm kiếm thông tin thời tiết Quy Nhơn hôm nay"
        req = TitleRequest(query=original_query)

        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(side_effect=RuntimeError("OpenRouter 503"))

        with patch("src.gateway.main.llm_client", mock_llm):
            resp = asyncio.run(generate_chat_title(req))
            assert resp.title == original_query
            assert "..." not in resp.title

    def test_clean_quotes_and_ellipses(self) -> None:
        """Smart title output should strip quotes and any ellipses returned by LLM."""
        req = TitleRequest(query="Doanh thu quý 3 năm 2026")

        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = '"Doanh thu chi nhánh Q3 2026..."'
        mock_resp.choices = [mock_choice]

        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(return_value=mock_resp)

        with patch("src.gateway.main.llm_client", mock_llm):
            resp = asyncio.run(generate_chat_title(req))
            assert resp.title == "Doanh thu chi nhánh Q3 2026"
            assert '"' not in resp.title
            assert "..." not in resp.title


# ---------------------------------------------------------------------------
# Test Suite 2: Data Agent & Planner Intent Routing (No Over-triggering)
# ---------------------------------------------------------------------------

class TestIntentRoutingAndDataAgent:
    """Test suite for preventing dashboard over-triggering."""

    def test_planner_prompt_contains_requires_dashboard_rules(self) -> None:
        """Planner prompt must clearly guide when requires_dashboard is true vs false."""
        prompt = build_planner_prompt(
            agent_descriptions=[{"name": "data_agent", "description": "data"}],
            query="File này có bao nhiêu dòng?",
        )
        assert "requires_dashboard" in prompt
        assert "TUYỆT ĐỐI KHÔNG sinh dashboard" in prompt

    def test_data_agent_detects_non_dashboard_query(self) -> None:
        """Text queries without chart request should be classified as non-dashboard."""
        text_queries = [
            "File này có bao nhiêu dòng?",
            "Ý nghĩa của các cột dữ liệu là gì?",
            "Tóm tắt thông tin dataset dạng văn bản",
            "Không cần biểu đồ, hãy thống kê số lượng bản ghi",
            "Liệt kê 5 sản phẩm đầu tiên",
        ]
        for q in text_queries:
            assert DataAnalystAgent._is_dashboard_request(q) is False

    def test_data_agent_detects_dashboard_query(self) -> None:
        """Queries explicitly asking for charts/dashboards should be classified as dashboard."""
        dash_queries = [
            "Vẽ biểu đồ phân bổ doanh thu theo vùng",
            "Tạo dashboard báo cáo doanh số",
            "Dựng biểu đồ cột và tỷ trọng sản phẩm",
            "Trực quan hóa số liệu kinh doanh",
        ]
        for q in dash_queries:
            assert DataAnalystAgent._is_dashboard_request(q) is True

    def test_process_csv_text_summary_contains_no_dashboard_spec(self) -> None:
        """When query is text-only, DataAnalystAgent must return text_summary and NO dashboard_spec."""
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="Tập dữ liệu gồm 10 dòng và 2 cột."))]
        mock_llm.chat_completion = AsyncMock(return_value=mock_resp)

        agent = DataAnalystAgent(llm_client=mock_llm)
        csv_sample = "product,sales\nA,100\nB,200\nC,300\n"

        async def _run():
            return await agent.process_csv_request(
                query="File này có bao nhiêu dòng?",
                csv_content=csv_sample,
                filename="test.csv",
                session_id="test-session",
            )

        result_raw = asyncio.run(_run())
        data = json.loads(result_raw)
        assert data.get("type") == "text_summary"
        assert "dashboard_spec" not in data

    def test_safe_read_csv_max_rows_guard(self) -> None:
        """safe_read_csv should slice rows exceeding max_rows to protect memory."""
        lines = ["id,val"] + [f"{i},{i*10}" for i in range(100)]
        csv_data = "\n".join(lines)

        df = safe_read_csv(csv_data, max_rows=50)
        assert len(df) == 50


# ---------------------------------------------------------------------------
# Test Suite 3: RAG Agent Graceful Fallback
# ---------------------------------------------------------------------------

class TestRAGAgentFallback:
    """Test suite for RAG Agent fallback when TEI Reranker is unavailable."""

    def test_reranker_exception_falls_back_to_candidates(self) -> None:
        """When rerank_documents throws an error, RAGAgent should fall back to candidates."""
        mock_ks = MagicMock()
        mock_candidates = [
            {"filename": "doc1.pdf", "section_title": "NDA", "category": "legal", "content": "Content of doc1", "vector_score": 0.8},
            {"filename": "doc2.pdf", "section_title": "SOW", "category": "project", "content": "Content of doc2", "vector_score": 0.7},
        ]
        mock_ks.search = AsyncMock(return_value=mock_candidates)

        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="Câu trả lời từ context fallback [1]"), finish_reason="stop")]
        mock_llm.chat_completion = AsyncMock(return_value=mock_resp)

        rag_agent = RAGAgent(knowledge_store=mock_ks, llm_client=mock_llm)

        async def _run():
            # Mock rerank_documents to raise ConnectionError
            with patch("src.agents.rag_agent.agent.rerank_documents", side_effect=ConnectionError("TEI container down")):
                return await rag_agent.process_request(query="Điều khoản NDA là gì?", session_id="test-session")

        res_str = asyncio.run(_run())
        data = json.loads(res_str)
        assert "answer" in data
        assert len(data.get("sources", [])) > 0
        assert data["sources"][0]["file"] == "doc1.pdf"


# ---------------------------------------------------------------------------
# Test Suite 4: SQL Guardrails with sqlglot
# ---------------------------------------------------------------------------

class TestSQLGuardrails:
    """Test suite for Database Agent SQL security enforcement."""

    def test_select_queries_allowed(self) -> None:
        """SELECT queries should be permitted and have LIMIT auto-injected."""
        valid, sql, err = validate_sql("SELECT id, filename FROM rag_chunks WHERE category = 'nda'")
        assert valid is True
        assert "LIMIT" in sql.upper()

    def test_mutation_queries_rejected(self) -> None:
        """INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER must be rejected."""
        dangerous_queries = [
            "DROP TABLE rag_chunks",
            "DELETE FROM rag_chunks WHERE id = 1",
            "UPDATE rag_chunks SET content = 'hacked'",
            "INSERT INTO rag_chunks (content) VALUES ('bad')",
            "TRUNCATE TABLE rag_chunks",
            "ALTER TABLE rag_chunks ADD COLUMN leak text",
        ]
        for query in dangerous_queries:
            valid, _, err = validate_sql(query)
            assert valid is False
            assert "Security reject" in err


# ---------------------------------------------------------------------------
# Test Suite 5: Infrastructure & Connection Pool Configurations
# ---------------------------------------------------------------------------

class TestInfrastructureConfig:
    """Test suite for Postgres pool and Redis TTL settings."""

    def test_postgres_client_pool_parameters(self) -> None:
        """PostgresClient connect signature must default to min 5, max 20, max_inactive 300s."""
        client = PostgresClient(dsn="postgresql://user:pass@localhost:5432/db")
        import inspect
        sig = inspect.signature(client.connect)
        assert sig.parameters["min_size"].default == 5
        assert sig.parameters["max_size"].default == 20
        assert sig.parameters["max_inactive_connection_lifetime"].default == 300.0

    def test_redis_client_ttl_parameters(self) -> None:
        """RedisClient set_value and append_to_history should default to 86400s (24 hours)."""
        client = RedisClient(url="redis://localhost:6379/0")
        import inspect
        sig_set = inspect.signature(client.set_value)
        sig_append = inspect.signature(client.append_to_history)
        assert sig_set.parameters["ttl"].default == 86400
        assert sig_append.parameters["ttl"].default == 86400
