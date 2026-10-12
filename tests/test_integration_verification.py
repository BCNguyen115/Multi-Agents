"""The Integration Agent checks the call BEFORE making it: an address the user never gave is not called, and a method that changes
data never runs here (it only runs after a human approved that exact request)."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.integration_agent import agent as agent_module
from src.agents.integration_agent.agent import IntegrationAgent
from src.agents.integration_agent.verification import KNOWN_ENDPOINTS, check_call
from src.orchestrator.core import Orchestrator

HEALTH = "http://localhost:8000/health"


@pytest.mark.parametrize(
    "query, url, method, problems",
    [
        ("kiểm tra health check", HEALTH, "GET", []),  # a default endpoint needs no mention
        ("gọi https://api.example.com/v1/users", "https://api.example.com/v1/users", "GET", []),
        ("gọi API.Example.com/v1/users/", "https://api.example.com/v1/users", "GET", []),  # case, scheme and trailing slash do not matter
        ("lấy danh sách người dùng", "https://api.example.com/v1/users", "GET", ["url_not_in_request"]),  # the model made the address up
        ("tạo đơn tại https://api.example.com/orders", "https://api.example.com/orders", "POST", ["mutation_needs_approval"]),
        ("tạo đơn hàng", "https://api.example.com/orders", "delete", ["url_not_in_request", "mutation_needs_approval"]),
    ],
)
def test_check_call(query, url, method, problems):
    assert check_call(query, url, method) == problems


def test_the_prompt_offers_every_known_endpoint():
    assert all(endpoint in agent_module._INTEGRATION_SYSTEM_PROMPT for endpoint in KNOWN_ENDPOINTS)


def make(parsed):
    llm = MagicMock()
    llm.chat_completion = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(parsed)))]))
    mcp = MagicMock()
    mcp.execute_rest_request = AsyncMock(return_value=json.dumps({"status": "success", "status_code": 200, "data": {"status": "ok"}}))
    return IntegrationAgent(mcp, llm), mcp


def call(agent, query):
    return json.loads(asyncio.run(agent.process_request(query, "s1")))


def test_a_read_of_a_default_endpoint_runs_and_says_so():
    agent, mcp = make({"url": HEALTH, "method": "GET", "payload": None, "explanation": "health"})
    out = call(agent, "kiểm tra health check của gateway")
    assert mcp.execute_rest_request.await_count == 1 and out["status_code"] == 200
    assert out["verification"] == {"kind": "api", "ok": True, "executed": True, "problems": []}


def test_an_address_the_user_never_gave_is_not_called():
    agent, mcp = make({"url": "https://api.example.com/v1/users", "method": "GET", "payload": None, "explanation": "users"})
    out = call(agent, "lấy danh sách người dùng")
    mcp.execute_rest_request.assert_not_awaited()
    assert out["status"] == "error" and out["verification"] == {"kind": "api", "ok": False, "executed": False, "problems": ["url_not_in_request"]}


def test_a_mutation_is_never_run_here_even_for_an_address_the_user_wrote():
    # the gate parsed a GET, this second parse says POST: it must not execute without the approval the gate would have asked for
    agent, mcp = make({"url": "https://api.example.com/orders", "method": "POST", "payload": {"id": 1}, "explanation": "create"})
    out = call(agent, "tạo đơn tại https://api.example.com/orders")
    mcp.execute_rest_request.assert_not_awaited()
    assert out["verification"]["problems"] == ["mutation_needs_approval"] and "phê duyệt" in out["answer"]


def test_a_call_that_was_refused_is_worth_a_retry_and_one_that_was_made_is_not():
    refused = Orchestrator._api_verdict({"kind": "api", "ok": False, "executed": False, "problems": ["url_not_in_request", "mutation_needs_approval"]}, 0)
    assert refused["is_verified"] is False and refused["retry_count"] == 1
    assert "địa chỉ API" in refused["verifier_feedback"] and "phê duyệt" in refused["verifier_feedback"]
    assert Orchestrator._api_verdict({"kind": "api", "ok": True, "executed": True, "problems": []}, 0) == {"is_verified": True, "verifier_feedback": ""}
