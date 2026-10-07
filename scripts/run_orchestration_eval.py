"""Evals of the orchestration itself, not of any one answer: does the planner pick the right agent, and does a run take the right steps?

    python -m scripts.run_orchestration_eval                 # offline: scripted LLM and agents, no key, deterministic (CI runs this on every push)
    python -m scripts.run_orchestration_eval --live          # routing with the real planner model (OPENROUTER_API_KEY), gated by --min-routing

**Routing** (``dataset/routing_eval.json``): the planner node alone, query -> agent. ``via=rules`` cases are decided by code (forced
mode, attached file, compound query, keyword fallback when the planner LLM is down) and must be 100 % offline; ``via=llm`` cases need
the real model and are only graded with ``--live``.

**Trajectory** (``dataset/trajectory_eval.json``): the whole PEV graph with scripted agents. A run passes when it took exactly the
expected steps and every tool was called the expected number of times, zero included: a mutating API call or a sensitive query that
runs before approval is the failure this exists to catch.

Writes ``reports/orchestration_eval.json`` / ``.md``; exits 1 when a gate fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from src.orchestrator.common import _initial_state
from src.orchestrator.core import Orchestrator
from src.orchestrator.prompt_templates import GRACEFUL_DECLINE_MESSAGE
from src.shared.security import wrap_user_input

ROOT = Path(__file__).resolve().parent.parent
ROUTING_FILE = ROOT / "dataset" / "routing_eval.json"
TRAJECTORY_FILE = ROOT / "dataset" / "trajectory_eval.json"
_MUTATING = ("POST", "PUT", "PATCH", "DELETE")


# ------------------------------------------------------------------------------------------------------------------ test doubles


@lru_cache(maxsize=1)
def agent_descriptions() -> list[dict[str, str]]:
    """The real ``get_metadata()`` of the five agents (what the planner prompt shows), without building their dependencies."""
    from src.agents.data_agent.agent import DataAnalystAgent
    from src.agents.db_agent.agent import DatabaseAgent
    from src.agents.integration_agent.agent import IntegrationAgent
    from src.agents.rag_agent.agent import RAGAgent
    from src.agents.search_agent.agent import SearchAgent

    return [cls.__new__(cls).get_metadata() for cls in (RAGAgent, DataAnalystAgent, DatabaseAgent, IntegrationAgent, SearchAgent)]


class ScriptedLLM:
    """Answers the orchestrator's own LLM calls from a script. ``planner=None`` makes the planner call fail (keyword fallback)."""

    def __init__(self, planner: Optional[str] = None, verifier: Optional[list[dict[str, Any]]] = None) -> None:
        self.planner = planner
        self.verifier = list(verifier or [{"is_verified": True, "feedback": ""}])
        self.models: list[str] = []  # the model each call asked for

    async def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        self.models.append(kwargs.get("model", ""))
        node = (kwargs.get("metadata") or {}).get("node")
        if node == "planner":
            if self.planner is None:
                raise RuntimeError("planner LLM unavailable")
            text = json.dumps({"plan": "scripted", "target_agent": self.planner, "requires_dashboard": False})
        elif node == "verifier":
            text = json.dumps(self.verifier.pop(0) if len(self.verifier) > 1 else self.verifier[0])
        else:
            text = "Tổng hợp."
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    def get_langfuse_callback(self, **_: Any) -> None:
        return None

    async def flush_async(self) -> None:
        return None


class ScriptedRegistry:
    def __init__(self, agents: dict[str, Any]) -> None:
        self.agents = agents

    def lookup(self, name: str) -> Any:
        return self.agents.get(name)

    def list_agents(self) -> list[dict[str, str]]:
        return agent_descriptions()

    def __len__(self) -> int:
        return len(self.agents)


def make_agent(name: str, spec: dict[str, Any]) -> SimpleNamespace:
    """A scripted agent that records every call (``calls``) and the query of each ``process_request`` (``queries``)."""
    calls: list[str] = []
    queries: list[str] = []
    replies = list(spec.get("replies", ["ok"]))

    def reply() -> str:
        value = replies.pop(0) if len(replies) > 1 else replies[0]
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    async def process_request(query: str, session_id: str) -> str:
        calls.append("process_request")
        queries.append(query)
        return reply()

    agent = SimpleNamespace(name=name, calls=calls, queries=queries, process_request=process_request)
    if name == "data_agent":
        async def process_csv_request(query: str, csv_content: str, filename: str, session_id: str) -> str:
            calls.append("process_csv_request")
            queries.append(query)
            return reply()
        agent.process_csv_request = process_csv_request
    elif name == "db_agent":
        async def generate_sql(query: str, session_id: str) -> tuple[str, str]:
            calls.append("generate_sql")
            return spec["sql"], "scripted"

        async def execute_sql_query(**_: Any) -> str:
            calls.append("execute_sql_query")
            return "{}"
        agent.generate_sql = generate_sql
        agent.is_sensitive_sql = lambda sql, query: bool(spec.get("sensitive"))
        agent.mcp_client = SimpleNamespace(execute_sql_query=execute_sql_query)
    elif name == "integration_agent":
        async def parse_request(query: str, session_id: str) -> tuple[str, str, None, str]:
            calls.append("parse_request")
            return spec["url"], spec["method"], None, "scripted"

        async def execute_rest_request(**_: Any) -> str:
            calls.append("execute_rest_request")
            return "{}"
        agent.parse_request = parse_request
        agent.is_mutation_request = lambda method: method.upper() in _MUTATING
        agent.mcp_client = SimpleNamespace(execute_rest_request=execute_rest_request)
    return agent


def build_orchestrator(agents: dict[str, Any], llm: Any, checkpointer: Any = None, settings: Any = None) -> Orchestrator:
    memory = SimpleNamespace(get_relevant_memories=lambda **_: [], add_memory=lambda **_: {})
    settings = settings or SimpleNamespace(
        HITL_APPROVAL_TTL_SECONDS=900, FAST_LLM_MODEL="fast", OPENROUTER_MODEL="model", HEAVY_LLM_MODEL="heavy", RAG_REQUIRE_QUOTES=False
    )
    return Orchestrator(registry=ScriptedRegistry(agents), settings=settings, llm_client=llm, memory_manager=memory, checkpointer=checkpointer)


# ------------------------------------------------------------------------------------------------------------------ routing


def _load(path: Path, key: str) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))[key]


async def run_routing(cases: list[dict[str, Any]], llm: Any, settings: Any = None) -> dict[str, Any]:
    """The planner node alone: the agent it picks for each query, graded against ``expected``. ``settings``: the real ones for
    ``--live`` (they name the planner model), scripted ones otherwise."""
    orch = build_orchestrator({}, llm, settings=settings)
    results = []
    for case in cases:
        state = _initial_state(
            wrap_user_input(case["query"])[0], "eval", "a,b\n1,2\n" if case.get("csv") else None, "f.csv" if case.get("csv") else None,
            case.get("mode"), None,
        )
        predicted = (await orch._planner_node(state)).get("target_agent")
        results.append({"id": case["id"], "via": case["via"], "query": case["query"], "expected": case["expected"], "predicted": predicted, "ok": predicted == case["expected"]})

    def accuracy(rows: list[dict[str, Any]]) -> Optional[float]:
        return round(sum(r["ok"] for r in rows) / len(rows), 4) if rows else None

    by_expected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_expected[row["expected"]].append(row)
    return {
        "accuracy": accuracy(results),
        "by_via": {via: {"accuracy": accuracy([r for r in results if r["via"] == via]), "n": sum(r["via"] == via for r in results)} for via in ("rules", "llm")},
        "recall_by_agent": {agent: accuracy(rows) for agent, rows in sorted(by_expected.items())},
        "misroutes": [r for r in results if not r["ok"]],
        "results": results,
    }


# ------------------------------------------------------------------------------------------------------------------ trajectory


def _step(node: str, update: dict[str, Any], target: str) -> Optional[str]:
    if node == "planner":
        return f"plan:{update.get('target_agent')}"
    if node == "executor":
        if update.get("requires_human_approval"):
            return "hitl"
        if update.get("execution_result") == GRACEFUL_DECLINE_MESSAGE:
            return "decline"
        return f"exec:{update.get('target_agent') or target}"
    if node == "verifier":
        return "verify:pass" if update.get("is_verified") else "verify:retry"
    return None


async def run_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    agents = {name: make_agent(name, spec) for name, spec in scenario["agents"].items()}
    orch = build_orchestrator(agents, ScriptedLLM(scenario.get("planner"), scenario.get("verifier_llm")))
    csv = "a,b\n1,2\n" if scenario.get("csv") else None
    state = _initial_state(wrap_user_input(scenario["query"])[0], "eval", csv, "f.csv" if csv else None, scenario.get("mode"), None)

    steps: list[str] = []
    final: dict[str, Any] = dict(state)
    target = ""
    async for update in orch.graph.astream(state, stream_mode="updates"):
        for node, out in update.items():
            final.update(out or {})
            target = (out or {}).get("target_agent") or target
            if step := _step(node, out or {}, target):
                steps.append(step)
    if not final.get("is_verified", True):
        steps.append("end:unverified")

    expect = scenario["expect"]
    actual_calls = Counter(f"{name}.{call}" for name, agent in agents.items() for call in agent.calls)
    problems: list[str] = []
    if steps != expect["trajectory"]:
        problems.append(f"steps {steps} != expected {expect['trajectory']}")
    wrong_calls = {key: (actual_calls[key], want) for key, want in expect.get("calls", {}).items() if actual_calls[key] != want}
    for key, (got, want) in wrong_calls.items():
        problems.append(f"{key} called {got}x, expected {want}x")
    for name, needle in expect.get("retry_query_contains", {}).items():
        queries = agents[name].queries
        if len(queries) < 2 or needle not in queries[-1]:
            problems.append(f"the retry query of {name} does not carry {needle!r}")
    return {"id": scenario["id"], "passed": not problems, "steps": steps, "problems": problems, "call_checks": len(expect.get("calls", {})), "call_failures": len(wrong_calls)}


async def run_trajectories(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    results = [await run_scenario(s) for s in scenarios]
    checks, failures = sum(r["call_checks"] for r in results), sum(r["call_failures"] for r in results)
    return {
        "passed": sum(r["passed"] for r in results), "total": len(results),
        "tool_call_accuracy": round((checks - failures) / checks, 4) if checks else None,
        "failures": [r for r in results if not r["passed"]], "results": results,
    }


# ------------------------------------------------------------------------------------------------------------------ report / CLI


def gate(report: dict[str, Any], live: bool, min_routing: float) -> list[str]:
    failed: list[str] = []
    routing = report.get("routing")
    if routing:
        if live and (routing["accuracy"] or 0) < min_routing:
            failed.append(f"routing accuracy {routing['accuracy']} < {min_routing}")
        if not live and routing["by_via"]["rules"]["accuracy"] != 1.0:
            failed.append(f"rules-routing accuracy {routing['by_via']['rules']['accuracy']} < 1.0")
    trajectory = report.get("trajectory")
    if trajectory and trajectory["passed"] != trajectory["total"]:
        failed.append(f"trajectory {trajectory['passed']}/{trajectory['total']} scenarios passed")
    return failed


def markdown(report: dict[str, Any]) -> str:
    lines = ["# Orchestration eval", "", f"Mode: {'live planner model' if report['live'] else 'offline (scripted LLM)'}", ""]
    if routing := report.get("routing"):
        lines += ["## Routing", "", f"- accuracy: **{routing['accuracy']}**", *(f"- via={via}: {v['accuracy']} (n={v['n']})" for via, v in routing["by_via"].items()), ""]
        lines += ["| agent | recall |", "|---|---|", *(f"| {a} | {r} |" for a, r in routing["recall_by_agent"].items()), ""]
        if routing["misroutes"]:
            lines += ["### Misrouted", "", "| id | via | expected | got | query |", "|---|---|---|---|---|", *(f"| {m['id']} | {m['via']} | {m['expected']} | {m['predicted']} | {m['query']} |" for m in routing["misroutes"]), ""]
    if trajectory := report.get("trajectory"):
        lines += ["## Trajectory", "", f"- scenarios passed: **{trajectory['passed']}/{trajectory['total']}**", f"- tool-call accuracy: {trajectory['tool_call_accuracy']}", ""]
        for failure in trajectory["failures"]:
            lines += [f"- ✗ `{failure['id']}`: " + "; ".join(failure["problems"])]
    lines += ["", "Gate: " + ("**FAILED** — " + "; ".join(report["failed"]) if report["failed"] else "passed")]
    return "\n".join(lines) + "\n"


async def main_async(args: argparse.Namespace) -> int:
    report: dict[str, Any] = {"live": args.live}
    if args.only in ("all", "routing"):
        if args.live:
            from src.config import settings
            from src.shared.llm_client import LLMClient

            report["routing"] = await run_routing(_load(ROUTING_FILE, "cases"), LLMClient(settings=settings), settings)
        else:
            report["routing"] = await run_routing(_load(ROUTING_FILE, "cases"), ScriptedLLM(planner=None))
    if args.only in ("all", "trajectory"):
        report["trajectory"] = await run_trajectories(_load(TRAJECTORY_FILE, "scenarios"))
    report["failed"] = gate(report, args.live, args.min_routing)

    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    target.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 1 if report["failed"] else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="route with the real planner model (needs OPENROUTER_API_KEY)")
    parser.add_argument("--only", choices=("all", "routing", "trajectory"), default="all")
    parser.add_argument("--min-routing", type=float, default=0.85, help="--live: lowest routing accuracy that passes")
    parser.add_argument("--report", default=str(ROOT / "reports" / "orchestration_eval"), help="path without extension")
    sys.exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
