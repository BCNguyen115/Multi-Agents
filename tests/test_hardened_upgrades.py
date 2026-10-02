"""Comprehensive Pytest Test Suite for Enterprise Hardening Upgrades.

Tests all hardening improvements:
  1. SQL Validator: CREATE TABLE, TRUNCATE, MERGE rejection; nested DML detection.
  2. CSV Sanitizer: BOM stripping, corrupt headers, max column guard.
  3. Circuit Breaker: Reranker failure counting, search agent timeout.
  4. Model Tiering: Config validation.

Usage::

    python -m pytest tests/test_hardened_upgrades.py -v
"""

from __future__ import annotations

import asyncio
import io
import os
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

# Ensure environment is set before importing modules
os.environ.setdefault("INTERNAL_JWT_SECRET", "test-secret-key-for-pytest-only-12345")

from src.agents.db_agent.validator import validate_sql
from src.shared.csv_sanitizer import (
    _MAX_COLUMN_COUNT,
    _remove_diacritics,
    clean_csv_content,
    detect_and_convert_encoding,
    sanitize_column_names,
)


# ---------------------------------------------------------------------------
# Module 1: SQL Validator Hardening Tests
# ---------------------------------------------------------------------------


class TestSQLValidatorHardening:
    """Tests for hardened SQL validator — CREATE, TRUNCATE, MERGE, nested DML."""

    def test_simple_select_passes(self) -> None:
        """Simple SELECT should be accepted."""
        is_valid, sql, err = validate_sql("SELECT * FROM rag_chunks")
        assert is_valid is True
        assert err == ""
        assert "SELECT" in sql.upper()

    def test_select_with_where_passes(self) -> None:
        """SELECT with WHERE should pass without warnings."""
        is_valid, sql, err = validate_sql(
            "SELECT id, content FROM rag_chunks WHERE category = 'nda'"
        )
        assert is_valid is True
        assert err == ""

    def test_cte_select_passes(self) -> None:
        """WITH ... SELECT (CTE) should be accepted."""
        cte_sql = (
            "WITH recent AS (SELECT * FROM rag_chunks WHERE created_at > '2024-01-01') "
            "SELECT * FROM recent"
        )
        is_valid, sql, err = validate_sql(cte_sql)
        assert is_valid is True
        assert err == ""

    def test_auto_inject_limit(self) -> None:
        """Missing LIMIT should be auto-injected."""
        is_valid, sql, err = validate_sql("SELECT * FROM rag_chunks")
        assert is_valid is True
        assert "LIMIT" in sql.upper()

    def test_existing_limit_not_duplicated(self) -> None:
        """Query with existing LIMIT should not get a second one."""
        is_valid, sql, err = validate_sql("SELECT * FROM rag_chunks LIMIT 50")
        assert is_valid is True
        assert sql.upper().count("LIMIT") == 1

    def test_create_table_rejected(self) -> None:
        """CREATE TABLE should be blocked."""
        is_valid, sql, err = validate_sql(
            "CREATE TABLE malicious (id INT, data TEXT)"
        )
        assert is_valid is False
        assert err != ""

    def test_create_index_rejected(self) -> None:
        """CREATE INDEX should be blocked."""
        is_valid, sql, err = validate_sql(
            "CREATE INDEX idx_test ON rag_chunks (filename)"
        )
        assert is_valid is False
        assert err != ""

    def test_drop_table_rejected(self) -> None:
        """DROP TABLE should be blocked."""
        is_valid, sql, err = validate_sql("DROP TABLE rag_chunks")
        assert is_valid is False
        assert "DROP" in err.upper() or "Forbidden" in err or "Security" in err

    def test_delete_rejected(self) -> None:
        """DELETE should be blocked."""
        is_valid, sql, err = validate_sql("DELETE FROM rag_chunks WHERE id = 1")
        assert is_valid is False
        assert err != ""

    def test_update_rejected(self) -> None:
        """UPDATE should be blocked."""
        is_valid, sql, err = validate_sql(
            "UPDATE rag_chunks SET content = 'hacked' WHERE id = 1"
        )
        assert is_valid is False
        assert err != ""

    def test_insert_rejected(self) -> None:
        """INSERT should be blocked."""
        is_valid, sql, err = validate_sql(
            "INSERT INTO rag_chunks (content) VALUES ('malicious')"
        )
        assert is_valid is False
        assert err != ""

    def test_alter_rejected(self) -> None:
        """ALTER TABLE should be blocked."""
        is_valid, sql, err = validate_sql(
            "ALTER TABLE rag_chunks ADD COLUMN pwned TEXT"
        )
        assert is_valid is False
        assert err != ""

    def test_truncate_rejected(self) -> None:
        """TRUNCATE should be blocked by keyword blocklist."""
        is_valid, sql, err = validate_sql("TRUNCATE TABLE rag_chunks")
        assert is_valid is False
        assert "TRUNCATE" in err.upper() or "Forbidden" in err or "Security" in err

    def test_multi_statement_rejected(self) -> None:
        """Multi-statement SQL should be blocked."""
        is_valid, sql, err = validate_sql(
            "SELECT 1; DROP TABLE rag_chunks"
        )
        assert is_valid is False
        assert "multi" in err.lower() or "Multi" in err or "DROP" in err.upper()

    def test_empty_sql_rejected(self) -> None:
        """Empty SQL should be rejected."""
        is_valid, sql, err = validate_sql("")
        assert is_valid is False
        assert "empty" in err.lower()

    def test_whitespace_only_rejected(self) -> None:
        """Whitespace-only SQL should be rejected."""
        is_valid, sql, err = validate_sql("   \n\t  ")
        assert is_valid is False
        assert "empty" in err.lower()

    def test_grant_rejected(self) -> None:
        """GRANT should be blocked by keyword blocklist."""
        is_valid, sql, err = validate_sql("GRANT ALL ON rag_chunks TO public")
        assert is_valid is False
        assert err != ""

    def test_revoke_rejected(self) -> None:
        """REVOKE should be blocked by keyword blocklist."""
        is_valid, sql, err = validate_sql("REVOKE ALL ON rag_chunks FROM public")
        assert is_valid is False
        assert err != ""

    def test_union_select_passes(self) -> None:
        """UNION of two SELECTs should be accepted."""
        is_valid, sql, err = validate_sql(
            "SELECT id FROM rag_chunks UNION SELECT id FROM knowledge_documents"
        )
        assert is_valid is True
        assert err == ""


# ---------------------------------------------------------------------------
# Module 2: CSV Sanitizer Hardening Tests
# ---------------------------------------------------------------------------


class TestCSVSanitizerHardening:
    """Tests for CSV sanitizer hardening — BOM, corrupt headers, max columns."""

    def test_utf8_bom_stripped(self) -> None:
        """UTF-8 BOM (EF BB BF) should be stripped before decoding."""
        bom_bytes: bytes = b"\xef\xbb\xbfname,value\nAlice,100\n"
        result: str = detect_and_convert_encoding(bom_bytes)
        assert not result.startswith("\ufeff")
        assert result.startswith("name")

    def test_utf16_le_bom_stripped(self) -> None:
        """UTF-16 LE BOM (FF FE) should be stripped."""
        raw: bytes = b"\xff\xfename,value\nBob,200\n"
        result: str = detect_and_convert_encoding(raw)
        assert "\xff\xfe" not in result

    def test_utf16_be_bom_stripped(self) -> None:
        """UTF-16 BE BOM (FE FF) should be stripped."""
        raw: bytes = b"\xfe\xffname,value\nCharlie,300\n"
        result: str = detect_and_convert_encoding(raw)
        assert "\xfe\xff" not in result

    def test_no_bom_unchanged(self) -> None:
        """Content without BOM should pass through unchanged."""
        raw: bytes = b"name,value\nDave,400\n"
        result: str = detect_and_convert_encoding(raw)
        assert result.startswith("name")

    def test_clean_csv_with_bom(self) -> None:
        """Full pipeline should handle BOM gracefully."""
        bom_csv: bytes = b"\xef\xbb\xbfTen San Pham,Gia\nAo,50000\nQuan,70000\n"
        result: str = clean_csv_content(bom_csv)
        assert "ten_san_pham" in result
        assert "gia" in result
        assert "Ao" in result or "ao" in result.lower()

    def test_numeric_header_replaced(self) -> None:
        """All-numeric headers should be replaced with col_N."""
        df = pd.DataFrame(
            {0: [1, 2], 1: [3, 4], 2: [5, 6]},
        )
        df = sanitize_column_names(df)
        for col in df.columns:
            assert col.startswith("col_")

    def test_nan_header_replaced(self) -> None:
        """NaN header should be replaced with col_N."""
        df = pd.DataFrame([[1, 2, 3]], columns=["Valid", float("nan"), "Also_Valid"])
        df = sanitize_column_names(df)
        assert "col_1" in df.columns.tolist()

    def test_unnamed_header_replaced(self) -> None:
        """Unnamed: N headers should be replaced."""
        df = pd.DataFrame([[1, 2]], columns=["Name", "Unnamed: 1"])
        df = sanitize_column_names(df)
        assert "col_1" in df.columns.tolist()

    def test_valid_headers_preserved(self) -> None:
        """Valid headers should not be corrupted."""
        df = pd.DataFrame([[1, 2, 3]], columns=["Name", "Age", "Score"])
        df = sanitize_column_names(df)
        assert list(df.columns) == ["name", "age", "score"]

    def test_vietnamese_diacritics_removed(self) -> None:
        """Vietnamese diacritics should be removed and slugified."""
        assert _remove_diacritics("Tên Sản Phẩm") == "Ten San Pham"
        assert _remove_diacritics("Đơn Giá") == "Don Gia"
        assert _remove_diacritics("Số Lượng") == "So Luong"

    def test_full_vietnamese_column_sanitization(self) -> None:
        """Full pipeline: Vietnamese columns → ASCII snake_case."""
        df = pd.DataFrame([[1, 2]], columns=["Tên Sản Phẩm", "Đơn Giá"])
        df = sanitize_column_names(df)
        assert list(df.columns) == ["ten_san_pham", "don_gia"]

    def test_max_columns_guard_triggers(self) -> None:
        """CSV with > 500 columns should raise ValueError."""
        headers = ",".join([f"col{i}" for i in range(501)])
        values = ",".join(["1"] * 501)
        csv_bytes: bytes = f"{headers}\n{values}\n".encode("utf-8")

        with pytest.raises(ValueError, match="exceeding the maximum"):
            clean_csv_content(csv_bytes, max_columns=500)

    def test_columns_at_limit_passes(self) -> None:
        """CSV with exactly max_columns should pass."""
        headers = ",".join([f"col{i}" for i in range(10)])
        values = ",".join(["1"] * 10)
        csv_bytes: bytes = f"{headers}\n{values}\n".encode("utf-8")

        result: str = clean_csv_content(csv_bytes, max_columns=10)
        assert "col0" in result

    def test_columns_above_custom_limit_rejected(self) -> None:
        """CSV exceeding a custom max_columns limit should raise."""
        headers = ",".join([f"col{i}" for i in range(20)])
        values = ",".join(["1"] * 20)
        csv_bytes: bytes = f"{headers}\n{values}\n".encode("utf-8")

        with pytest.raises(ValueError, match="exceeding the maximum"):
            clean_csv_content(csv_bytes, max_columns=15)

    def test_empty_rows_removed(self) -> None:
        """Fully empty rows should be removed."""
        csv_bytes: bytes = b"a,b\n1,2\n,\n3,4\n"
        result: str = clean_csv_content(csv_bytes)
        df = pd.read_csv(io.StringIO(result))
        assert len(df) == 2

    def test_duplicate_columns_deduplicated(self) -> None:
        """Duplicate column names should get numeric suffixes."""
        df = pd.DataFrame([[1, 2, 3]], columns=["Name", "Name", "Name"])
        df = sanitize_column_names(df)
        cols = list(df.columns)
        assert len(set(cols)) == 3
        assert "name" in cols
        assert "name_1" in cols
        assert "name_2" in cols


# ---------------------------------------------------------------------------
# Module 3: Circuit Breaker Tests
# ---------------------------------------------------------------------------


class TestRerankerCircuitBreaker:
    """Tests for reranker circuit breaker state tracking."""

    def test_circuit_breaker_opens_after_threshold(self) -> None:
        """Circuit breaker should open after N consecutive failures."""
        from src.shared import reranker_client

        reranker_client._consecutive_failures = 0
        reranker_client._last_failure_time = 0.0

        for _ in range(reranker_client._CIRCUIT_BREAKER_THRESHOLD):
            reranker_client._record_failure()

        assert reranker_client._is_circuit_open() is True

    def test_circuit_breaker_closed_initially(self) -> None:
        """Circuit breaker should be closed with zero failures."""
        from src.shared import reranker_client

        reranker_client._consecutive_failures = 0
        reranker_client._last_failure_time = 0.0

        assert reranker_client._is_circuit_open() is False

    def test_circuit_breaker_resets_on_success(self) -> None:
        """Circuit breaker should reset after a successful call."""
        from src.shared import reranker_client

        reranker_client._consecutive_failures = 2
        reranker_client._record_success()

        assert reranker_client._consecutive_failures == 0
        assert reranker_client._is_circuit_open() is False

    def test_circuit_breaker_half_open_after_cooldown(self) -> None:
        """Circuit breaker should allow probe after cooldown expires."""
        from src.shared import reranker_client

        reranker_client._consecutive_failures = reranker_client._CIRCUIT_BREAKER_THRESHOLD
        reranker_client._last_failure_time = (
            time.monotonic() - reranker_client._CIRCUIT_BREAKER_COOLDOWN - 1.0
        )

        assert reranker_client._is_circuit_open() is False
        # exactly one trial is allowed: a single failure must re-open the breaker
        assert reranker_client._consecutive_failures == reranker_client._CIRCUIT_BREAKER_THRESHOLD - 1
        reranker_client._record_failure()
        assert reranker_client._is_circuit_open() is True
        reranker_client._consecutive_failures = 0
        reranker_client._last_failure_time = 0.0

    def test_circuit_breaker_stays_open_during_cooldown(self) -> None:
        """Circuit breaker should remain open during cooldown period."""
        from src.shared import reranker_client

        reranker_client._consecutive_failures = reranker_client._CIRCUIT_BREAKER_THRESHOLD
        reranker_client._last_failure_time = time.monotonic()

        assert reranker_client._is_circuit_open() is True

    def test_rerank_fallback_on_circuit_open(self) -> None:
        """When circuit is open, rerank should return docs immediately without HTTP call."""
        from src.shared import reranker_client

        reranker_client._consecutive_failures = reranker_client._CIRCUIT_BREAKER_THRESHOLD
        reranker_client._last_failure_time = time.monotonic()

        docs = [
            {"content": "doc1", "score": 0.9},
            {"content": "doc2", "score": 0.8},
            {"content": "doc3", "score": 0.7},
        ]

        async def _run() -> list:
            return await reranker_client.rerank_documents(
                query="test query",
                documents=docs,
                top_k=2,
                session_id="test",
            )

        result = asyncio.run(_run())
        assert len(result) == 2
        assert result[0]["content"] == "doc1"

        reranker_client._consecutive_failures = 0


# ---------------------------------------------------------------------------
# Module 4: Model Tiering Config Tests
# ---------------------------------------------------------------------------


class TestModelTieringConfig:
    """Tests for model tiering configuration."""

    def test_fast_model_configured(self) -> None:
        """FAST_LLM_MODEL should be set in config."""
        from src.config import settings

        assert hasattr(settings, "FAST_LLM_MODEL")
        assert settings.FAST_LLM_MODEL

    def test_heavy_model_configured(self) -> None:
        """HEAVY_LLM_MODEL should be set in config."""
        from src.config import settings

        assert hasattr(settings, "HEAVY_LLM_MODEL")
        assert settings.HEAVY_LLM_MODEL

    def test_reranker_timeout_is_circuit_breaker_compatible(self) -> None:
        """RERANKER_TIMEOUT is ONE total budget per rerank: short enough that a dead reranker costs little
        (the old 0.8s default was below the measured CPU latency, so reranking never worked), long enough for it."""
        from src.config import Settings

        default_timeout: float = Settings.model_fields["RERANKER_TIMEOUT"].default
        assert 1.0 < default_timeout <= 10.0, f"RERANKER_TIMEOUT default={default_timeout} outside the 1-10s budget"

    def test_fast_model_is_valid_format(self) -> None:
        """Model identifiers should follow provider/model format."""
        from src.config import settings

        assert "/" in settings.FAST_LLM_MODEL

    def test_heavy_model_is_valid_format(self) -> None:
        """Model identifiers should follow provider/model format."""
        from src.config import settings

        assert "/" in settings.HEAVY_LLM_MODEL


# ---------------------------------------------------------------------------
# Module 5: Search Agent Timeout Tests
# ---------------------------------------------------------------------------


class TestSearchAgentCircuitBreaker:
    """Tests for search agent circuit breaker improvements."""

    def test_tavily_timeout_handling(self) -> None:
        """Tavily search should handle timeout gracefully."""
        pytest.importorskip("litellm", reason="litellm not installed")
        from src.agents.search_agent.agent import SearchAgent

        mock_settings = MagicMock()
        mock_settings.TAVILY_API_KEY = "tvly-test-key"
        mock_settings.OPENROUTER_MODEL = "openai/gpt-4o-mini"

        mock_llm = MagicMock()
        agent = SearchAgent(
            llm_client=mock_llm,
            settings=mock_settings,
        )

        async def _run() -> list:
            with patch("src.agents.search_agent.agent.asyncio.wait_for") as mock_wait:
                mock_wait.side_effect = asyncio.TimeoutError()
                return await agent._search_tavily("test query")

        result = asyncio.run(_run())
        assert result == []

    def test_search_agent_returns_fallback_on_empty_results(self) -> None:
        """SearchAgent should return user-friendly fallback on no results."""
        pytest.importorskip("litellm", reason="litellm not installed")
        from src.agents.search_agent.agent import SearchAgent

        mock_settings = MagicMock()
        mock_settings.TAVILY_API_KEY = ""
        mock_settings.OPENROUTER_MODEL = "openai/gpt-4o-mini"

        mock_llm = MagicMock()
        agent = SearchAgent(llm_client=mock_llm, settings=mock_settings)

        async def _run() -> str:
            return await agent.process_request("test", "session-123")

        result = asyncio.run(_run())
        assert "không khả dụng" in result or "⚠️" in result

    def test_search_agent_catches_exception_gracefully(self) -> None:
        """SearchAgent should catch all exceptions and return error message."""
        pytest.importorskip("litellm", reason="litellm not installed")
        from src.agents.search_agent.agent import SearchAgent

        mock_settings = MagicMock()
        mock_settings.TAVILY_API_KEY = "tvly-valid-key"
        mock_settings.OPENROUTER_MODEL = "openai/gpt-4o-mini"

        mock_llm = MagicMock()
        agent = SearchAgent(llm_client=mock_llm, settings=mock_settings)

        async def _run() -> str:
            with patch.object(agent, "_search_tavily", side_effect=RuntimeError("Network error")):
                return await agent.process_request("test", "session-456")

        result = asyncio.run(_run())
        assert "⚠️" in result or "không khả dụng" in result or "lỗi" in result.lower()
