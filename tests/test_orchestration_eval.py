"""The orchestration evals run with the suite (so on every push): the deterministic routing rules and every tool trajectory.

The numbers of the real planner model (``--live``) need an API key and are measured by hand or by the scheduled CI job.
"""
import asyncio
from types import SimpleNamespace

from scripts import run_orchestration_eval as ev

AGENTS = {"rag_agent", "data_agent", "db_agent", "integration_agent", "search_agent"}


def run(coro):
    return asyncio.run(coro)


def test_the_datasets_are_well_formed():
    cases = ev._load(ev.ROUTING_FILE, "cases")
    scenarios = ev._load(ev.TRAJECTORY_FILE, "scenarios")
    assert len({c["id"] for c in cases}) == len(cases) and len({s["id"] for s in scenarios}) == len(scenarios)
    assert {c["expected"] for c in cases} <= AGENTS | {"parallel_coordinator", "none"}
    assert {c["via"] for c in cases} == {"rules", "llm"}
    assert all(set(s["agents"]) <= AGENTS for s in scenarios)


def test_routing_decided_by_code_is_always_right_without_any_llm():
    report = run(ev.run_routing(ev._load(ev.ROUTING_FILE, "cases"), ev.ScriptedLLM(planner=None)))
    assert report["by_via"]["rules"]["accuracy"] == 1.0, report["misroutes"]


def test_every_trajectory_takes_the_expected_steps_and_calls_the_expected_tools():
    report = run(ev.run_trajectories(ev._load(ev.TRAJECTORY_FILE, "scenarios")))
    assert report["failures"] == [] and report["tool_call_accuracy"] == 1.0


def test_routing_uses_the_settings_it_is_given_so_live_asks_the_configured_planner_model():
    llm = ev.ScriptedLLM(planner="rag_agent")
    settings = SimpleNamespace(HITL_APPROVAL_TTL_SECONDS=900, FAST_LLM_MODEL="the-fast-model", OPENROUTER_MODEL="m", HEAVY_LLM_MODEL="h", RAG_REQUIRE_QUOTES=False)
    report = run(ev.run_routing([{"id": "x", "via": "llm", "query": "Điều khoản NDA", "expected": "rag_agent"}], llm, settings))
    assert report["accuracy"] == 1.0 and llm.models == ["the-fast-model"]


def test_the_trajectory_eval_catches_a_sensitive_query_that_runs_without_approval():
    # a scenario that EXPECTS the query to run although it is sensitive: the graph pauses at the approval gate, so the eval must fail it
    wrong = {
        "id": "wrong", "mode": "db_agent", "query": "Lương của nhân viên?",
        "agents": {"db_agent": {"sql": "SELECT salary FROM employees", "sensitive": True, "replies": ["x"]}},
        "expect": {"trajectory": ["plan:db_agent", "exec:db_agent", "verify:pass"], "calls": {"db_agent.process_request": 1}},
    }
    result = run(ev.run_scenario(wrong))
    assert result["passed"] is False and result["call_failures"] == 1


def test_the_gate_demands_the_rules_offline_and_the_threshold_live():
    routing = {"accuracy": 0.8, "by_via": {"rules": {"accuracy": 1.0}, "llm": {"accuracy": 0.5}}}
    assert ev.gate({"routing": routing}, live=False, min_routing=0.85) == []
    assert ev.gate({"routing": routing}, live=True, min_routing=0.85) != []
    broken = {"accuracy": 0.95, "by_via": {"rules": {"accuracy": 0.96}, "llm": {"accuracy": 1.0}}}
    assert ev.gate({"routing": broken}, live=False, min_routing=0.85) != []
    assert ev.gate({"trajectory": {"passed": 15, "total": 16}}, live=False, min_routing=0.85) != []
