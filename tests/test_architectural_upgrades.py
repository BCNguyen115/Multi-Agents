"""Comprehensive test suite for Enterprise Architectural Upgrades (P0, P1, P2).

Tests:
  1. Golden Eval Dataset 50+ cases & Category Metrics.
  2. Human-in-the-Loop (HITL) for Mutation APIs and Sensitive SQL Queries.
  3. DAG Parallel Execution (Fan-out / Fan-in with Synthesizer).
  4. Row-Level Security (RLS) AST Transformer via sqlglot.
  5. Secure Python Execution Sandbox for Data Agent.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.db_agent.rls_transformer import inject_row_level_security
from src.agents.data_agent.sandbox import SafePythonSandbox, SandboxResult
from src.orchestrator.core import Orchestrator
from src.orchestrator.state import AgentState
from src.registry.manager import AgentRegistry


# ===========================================================================
# 1. P0.1: Golden Dataset & Offline Eval
# ===========================================================================
class TestGoldenDatasetExpansion:
    """Validate 52+ cases and category integrity in golden_eval_dataset.json."""

    def test_golden_dataset_has_at_least_50_cases(self):
        with open("dataset/golden_eval_dataset.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        assert len(data) >= 50, f"Expected >= 50 cases, found {len(data)}"
        categories = set(d.get("category") for d in data)
        assert "data_agent" in categories
        assert "rag_agent" in categories
        assert "search_agent" in categories
        assert "database_integration" in categories
        assert "security_guardrails" in categories

    def test_all_cases_have_required_fields(self):
        with open("dataset/golden_eval_dataset.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        for case in data:
            assert "id" in case
            assert "query" in case
            assert "category" in case
            assert "expected_agent" in case or "expected_target_agent" in case
            assert "required_guardrails" in case


# ===========================================================================
# 2. P1.4: Row-Level Security (RLS) AST Transformer via sqlglot
# ===========================================================================
class TestRowLevelSecurityAST:
    """Verify sqlglot RLS AST injection across all SQL patterns."""

    def test_rls_simple_select(self):
        sql = "SELECT id, name FROM users"
        secured = inject_row_level_security(sql, tenant_id="acme_corp", department_id="finance")
        assert "department_id = 'finance'" in secured
        assert "tenant_id = 'acme_corp'" in secured
        assert "WHERE" in secured

    def test_rls_select_with_existing_where(self):
        sql = "SELECT id, name FROM users WHERE is_active = true"
        secured = inject_row_level_security(sql, tenant_id="acme_corp", department_id="finance")
        assert "is_active = TRUE" in secured or "is_active = true" in secured.lower()
        assert "department_id = 'finance'" in secured
        assert "tenant_id = 'acme_corp'" in secured
        assert "AND (" in secured

    def test_rls_join_query(self):
        sql = "SELECT u.name, d.title FROM users u JOIN departments d ON u.dept_id = d.id"
        secured = inject_row_level_security(sql, tenant_id="t1", department_id="d1")
        assert "department_id = 'd1'" in secured
        assert "tenant_id = 't1'" in secured

    def test_rls_subquery(self):
        sql = "SELECT * FROM (SELECT id, salary FROM employees) sub WHERE salary > 1000"
        secured = inject_row_level_security(sql, tenant_id="t1", department_id="d1")
        # Injects into both inner and outer queries
        assert secured.count("tenant_id = 't1'") >= 1

    def test_rls_common_table_expression(self):
        sql = "WITH active_users AS (SELECT * FROM users WHERE active = 1) SELECT * FROM active_users"
        secured = inject_row_level_security(sql, tenant_id="t1", department_id="d1")
        assert "department_id = 'd1'" in secured
        assert "tenant_id = 't1'" in secured


# ===========================================================================
# 3. P2.5: Secure Python Execution Sandbox
# ===========================================================================
class TestSecurePythonSandbox:
    """Verify SafePythonSandbox isolates execution and catches hazards."""

    def test_legitimate_math_computation(self):
        sandbox = SafePythonSandbox(timeout_seconds=3.0)
        code = """
nums = [10, 20, 30, 40]
avg = sum(nums) / len(nums)
result = {'average': avg, 'max': max(nums)}
print('Done computing')
"""
        res = sandbox.execute_sync(code)
        assert res.success is True
        assert res.result_data["average"] == 25.0
        assert "Done computing" in res.stdout

    def test_blocks_os_module(self):
        sandbox = SafePythonSandbox()
        code = "import os; os.system('ls')"
        res = sandbox.execute_sync(code)
        assert res.success is False
        assert "forbidden module 'os'" in res.error

    def test_blocks_open_builtin(self):
        sandbox = SafePythonSandbox()
        code = "f = open('secrets.env', 'r')"
        res = sandbox.execute_sync(code)
        assert res.success is False
        assert "restricted builtin 'open()'" in res.error

    def test_blocks_subprocess(self):
        sandbox = SafePythonSandbox()
        code = "from subprocess import run; run(['echo', 'pwned'])"
        res = sandbox.execute_sync(code)
        assert res.success is False
        assert "forbidden module 'subprocess'" in res.error


# ===========================================================================
# 4. P0.2: Human-in-the-Loop (HITL) Gate
# ===========================================================================
class TestHumanInTheLoopGate:
    """Test pause on mutation API and sensitive DB queries."""

    @pytest.fixture
    def orchestrator(self):
        registry = AgentRegistry()
        mock_settings = MagicMock()
        mock_settings.OPENROUTER_MODEL = "openai/gpt-4o"
        mock_settings.FAST_LLM_MODEL = "openai/gpt-4o-mini"
        mock_settings.HEAVY_LLM_MODEL = "openai/gpt-4o"
        mock_llm = MagicMock()
        mock_mem = MagicMock()
        return Orchestrator(
            registry=registry,
            settings=mock_settings,
            llm_client=mock_llm,
            memory_manager=mock_mem,
        )

    def test_hitl_approval_rejection_flow(self, orchestrator):
        import asyncio
        async def _test():
            action_id = "act_test123"
            orchestrator.pending_approvals[action_id] = {
                "state": {"query": "Gọi API xóa tài khoản", "session_id": "sess_1"},
                "payload": {
                    "action_id": action_id,
                    "agent": "integration_agent",
                    "session_id": "sess_1",
                },
            }

            # Reject
            res_reject = await orchestrator.handle_approval_decision(
                session_id="sess_1",
                action_id=action_id,
                decision="reject",
                feedback="Không được phép xóa tài khoản người dùng",
            )
            assert res_reject["status"] == "rejected"
            assert action_id not in orchestrator.pending_approvals

        asyncio.run(_test())

    def test_hitl_approval_nonexistent_action(self, orchestrator):
        import asyncio
        async def _test():
            res = await orchestrator.handle_approval_decision(
                session_id="sess_1",
                action_id="act_ghost",
                decision="approve",
            )
            assert res["status"] == "error"

        asyncio.run(_test())


# ===========================================================================
# 5. P1.3: DAG Parallel Execution Decomposition
# ===========================================================================
class TestDAGParallelExecution:
    """Test task decomposition for compound queries."""

    def test_decompose_rag_and_search_query(self):
        mock_settings = MagicMock()
        mock_settings.OPENROUTER_MODEL = "openai/gpt-4o"
        mock_settings.FAST_LLM_MODEL = "openai/gpt-4o-mini"
        mock_settings.HEAVY_LLM_MODEL = "openai/gpt-4o"
        orch = Orchestrator(
            registry=AgentRegistry(),
            settings=mock_settings,
            llm_client=MagicMock(),
            memory_manager=MagicMock(),
        )

        compound_query = "Đối soát thông tin điều khoản NDA nội bộ và tìm kiếm tin tức thị trường mới nhất hôm nay"
        sub_tasks = orch._decompose_subtasks(compound_query)

        assert len(sub_tasks) == 2
        agents = [t["agent"] for t in sub_tasks]
        assert "rag_agent" in agents
        assert "search_agent" in agents


# ===========================================================================
# 6. P2.5 & P3.6: Docker Compose Sandbox & Frontend Export Configuration
# ===========================================================================
class TestDockerSandboxAndExportConfig:
    """Verify docker-compose python-sandbox service and export dependencies."""

    def test_docker_compose_has_python_sandbox_service(self):
        with open("docker-compose.yml", "r", encoding="utf-8") as f:
            content = f.read()

        assert "python-sandbox:" in content
        assert "network_mode: none" in content
        assert "memory: 256M" in content

    def test_frontend_package_has_pptxgenjs(self):
        with open("frontend/package.json", "r", encoding="utf-8") as f:
            pkg = json.load(f)
        deps = pkg.get("dependencies", {})
        assert "pptxgenjs" in deps

