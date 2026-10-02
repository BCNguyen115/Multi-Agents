"""Orchestrator forced-agent routing must bypass LLM classification (verifier hardening lives in test_verifier.py)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.orchestrator.core import Orchestrator
from src.orchestrator.state import AgentState


class TestOrchestratorForcedRouting:
    def test_planner_respects_forced_rag_agent(self):
        async def _run():
            mock_registry = MagicMock()
            mock_settings = MagicMock()
            mock_settings.FAST_LLM_MODEL = "openai/gpt-4o-mini"
            mock_settings.OPENROUTER_MODEL = "anthropic/claude-3.5-sonnet"
            mock_settings.LOG_LEVEL = "INFO"
            mock_llm = MagicMock()
            mock_memory = MagicMock()
            mock_memory.get_relevant_memories = AsyncMock(return_value=[])

            orchestrator = Orchestrator(
                registry=mock_registry,
                settings=mock_settings,
                llm_client=mock_llm,
                memory_manager=mock_memory,
            )

            state: AgentState = {
                "query": "Tóm tắt điều khoản bảo mật hợp đồng NDA",
                "session_id": "test_session_rag",
                "target_agent": "rag_agent",
                "forced_target_agent": "rag_agent",
                "messages": [],
                "team_memory": {},
                "plan": "",
                "execution_result": "",
                "final_response": "",
                "is_verified": False,
                "verifier_feedback": "",
                "retry_count": 0,
                "max_retries": 2,
            }

            result = await orchestrator._planner_node(state)
            assert result["target_agent"] == "rag_agent"
            assert result["requires_dashboard"] is False
            assert "hợp đồng" in result["plan"].lower() or "nda" in result["plan"].lower()
            # Ensure LLM chat_completion was NOT called because classification was bypassed
            assert mock_llm.chat_completion.call_count == 0

        asyncio.run(_run())

    def test_planner_respects_forced_search_agent(self):
        async def _run():
            mock_registry = MagicMock()
            mock_settings = MagicMock()
            mock_settings.FAST_LLM_MODEL = "openai/gpt-4o-mini"
            mock_settings.OPENROUTER_MODEL = "anthropic/claude-3.5-sonnet"
            mock_settings.LOG_LEVEL = "INFO"
            mock_llm = MagicMock()
            mock_memory = MagicMock()
            mock_memory.get_relevant_memories = AsyncMock(return_value=[])

            orchestrator = Orchestrator(
                registry=mock_registry,
                settings=mock_settings,
                llm_client=mock_llm,
                memory_manager=mock_memory,
            )

            state: AgentState = {
                "query": "Tin tức thị trường công nghệ hôm nay",
                "session_id": "test_session_search",
                "forced_target_agent": "search_agent",
                "messages": [],
                "team_memory": {},
                "plan": "",
                "execution_result": "",
                "final_response": "",
                "is_verified": False,
                "verifier_feedback": "",
                "retry_count": 0,
                "max_retries": 2,
            }

            result = await orchestrator._planner_node(state)
            assert result["target_agent"] == "search_agent"
            assert result["requires_dashboard"] is False
            assert mock_llm.chat_completion.call_count == 0

        asyncio.run(_run())
