"""Unit tests for LiteLLM OpenRouter Routing Normalization, Fallback, and Planner Hardening."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.shared.llm_client import (
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_OPENROUTER_HEADERS,
    LLMClient,
    normalize_model_name,
)
from src.registry.manager import AgentRegistry
from src.orchestrator.core import Orchestrator
from src.config import Settings


class TestLLMRoutingNormalization:
    """Test automatic openrouter/ prefix injection and normalization."""

    def test_normalize_model_name_empty(self) -> None:
        assert normalize_model_name("") == DEFAULT_FALLBACK_MODEL
        assert normalize_model_name(None) == DEFAULT_FALLBACK_MODEL
        assert normalize_model_name("   ") == DEFAULT_FALLBACK_MODEL

    def test_normalize_model_name_already_prefixed(self) -> None:
        assert (
            normalize_model_name("openrouter/anthropic/claude-3.5-haiku")
            == "openrouter/anthropic/claude-3.5-haiku"
        )
        assert (
            normalize_model_name("openrouter/openai/gpt-4o-mini")
            == "openrouter/openai/gpt-4o-mini"
        )

    def test_normalize_model_name_injects_prefix(self) -> None:
        assert (
            normalize_model_name("anthropic/claude-3-haiku")
            == "openrouter/anthropic/claude-3-haiku"
        )
        assert (
            normalize_model_name("anthropic/claude-3.5-haiku")
            == "openrouter/anthropic/claude-3.5-haiku"
        )
        assert (
            normalize_model_name("openai/gpt-4o-mini")
            == "openrouter/openai/gpt-4o-mini"
        )
        assert (
            normalize_model_name("meta-llama/llama-3-70b-instruct")
            == "openrouter/meta-llama/llama-3-70b-instruct"
        )
        assert (
            normalize_model_name("gpt-4o-mini")
            == "openrouter/gpt-4o-mini"
        )


class TestLLMClientFallbackAndAliases:
    """Test fallback mechanism and aliases in LLMClient."""

    def test_llm_client_default_init(self) -> None:
        client = LLMClient()
        assert client.settings is not None
        assert client.api_key == client.settings.OPENROUTER_API_KEY
        assert client.api_base == client.settings.OPENROUTER_BASE_URL

    def test_chat_completion_normalizes_and_succeeds(self) -> None:
        async def _run() -> None:
            client = LLMClient()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "Pong"

            with patch("src.shared.llm_client.acompletion", new_callable=AsyncMock) as mock_acompletion:
                mock_acompletion.return_value = mock_response

                res = await client.chat_completion(
                    model="anthropic/claude-3.5-haiku",
                    messages=[{"role": "user", "content": "Ping"}],
                )

                assert res == mock_response
                mock_acompletion.assert_called_once()
                call_kwargs = mock_acompletion.call_args.kwargs
                assert call_kwargs["model"] == "openrouter/anthropic/claude-3.5-haiku"
                assert call_kwargs["extra_headers"]["HTTP-Referer"] == "https://github.com/enterprise-multi-agent"
                assert call_kwargs["extra_headers"]["X-Title"] == "Multi-Agent Enterprise System"

        asyncio.run(_run())

    def test_chat_completion_triggers_fallback_on_failure(self) -> None:
        async def _run() -> None:
            client = LLMClient()
            fallback_resp = MagicMock()
            fallback_resp.choices = [MagicMock()]
            fallback_resp.choices[0].message.content = "Fallback Pong"

            with patch("src.shared.llm_client.acompletion", new_callable=AsyncMock) as mock_acompletion:
                # First call (primary model) fails with 404 Anthropic/Openrouter Exception
                # Second call (fallback model) succeeds
                mock_acompletion.side_effect = [
                    RuntimeError("AnthropicException 404 Not Found"),
                    fallback_resp,
                ]

                res = await client.chat_completion(
                    model="anthropic/claude-3-haiku",
                    messages=[{"role": "user", "content": "Ping"}],
                )

                assert res == fallback_resp
                assert mock_acompletion.call_count == 2
                # First call was normalized model
                assert mock_acompletion.call_args_list[0].kwargs["model"] == "openrouter/anthropic/claude-3-haiku"
                # Second call was fallback model
                assert mock_acompletion.call_args_list[1].kwargs["model"] == DEFAULT_FALLBACK_MODEL

        asyncio.run(_run())

    def test_acompletion_alias(self) -> None:
        async def _run() -> None:
            client = LLMClient()
            mock_response = MagicMock()
            with patch.object(client, "chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.return_value = mock_response
                res = await client.acompletion(
                    model="anthropic/claude-3.5-haiku",
                    messages=[{"role": "user", "content": "Ping"}],
                )
                assert res == mock_response
                mock_chat.assert_called_once_with(
                    model="anthropic/claude-3.5-haiku",
                    messages=[{"role": "user", "content": "Ping"}],
                )

        asyncio.run(_run())


class TestPlannerHardeningAndFallbackRoutes:
    """Test Planner Node heuristic fallback routes and error resilience."""

    def test_determine_fallback_route_csv_viz(self) -> None:
        orch = Orchestrator(registry=AgentRegistry(), settings=Settings())
        agent, plan, is_viz = orch._determine_fallback_route(
            query="Vẽ biểu đồ doanh thu theo tháng", csv_content="col1,col2\n1,2"
        )
        assert agent == "data_agent"
        assert is_viz is True
        assert "Dashboard" in plan

    def test_determine_fallback_route_csv_no_viz(self) -> None:
        orch = Orchestrator(registry=AgentRegistry(), settings=Settings())
        agent, plan, is_viz = orch._determine_fallback_route(
            query="Tóm tắt dữ liệu dạng văn bản không cần biểu đồ", csv_content="col1,col2\n1,2"
        )
        assert agent == "data_agent"
        assert is_viz is False

    def test_determine_fallback_route_search(self) -> None:
        orch = Orchestrator(registry=AgentRegistry(), settings=Settings())
        agent, plan, is_viz = orch._determine_fallback_route(
            query="Tìm kiếm tin tức AI mới nhất trên Internet"
        )
        assert agent == "search_agent"
        assert is_viz is False

    def test_determine_fallback_route_sql(self) -> None:
        orch = Orchestrator(registry=AgentRegistry(), settings=Settings())
        agent, plan, is_viz = orch._determine_fallback_route(
            query="Truy vấn dữ liệu bảng người dùng từ SQL database"
        )
        assert agent == "db_agent"
        assert is_viz is False

    def test_determine_fallback_route_default_rag(self) -> None:
        orch = Orchestrator(registry=AgentRegistry(), settings=Settings())
        agent, plan, is_viz = orch._determine_fallback_route(
            query="Quy định bảo mật của công ty như thế nào?"
        )
        assert agent == "rag_agent"
        assert is_viz is False

    def test_planner_node_recovers_gracefully_on_llm_exception(self) -> None:
        async def _run() -> None:
            mock_llm = MagicMock()
            mock_llm.chat_completion = AsyncMock(side_effect=RuntimeError("LiteLLM 404 Exception"))
            orch = Orchestrator(
                registry=AgentRegistry(),
                settings=Settings(),
                llm_client=mock_llm,
            )

            state = {
                "query": "Tìm kiếm thời tiết Hà Nội hôm nay",
                "session_id": "test-session",
                "csv_content": None,
                "csv_filename": None,
                "agent_mode": None,
            }

            # Should NOT raise, but return safe fallback plan
            result = await orch._planner_node(state)
            assert result["target_agent"] == "search_agent"
            assert "Tìm kiếm" in result["plan"]
            assert result["requires_dashboard"] is False

        asyncio.run(_run())
