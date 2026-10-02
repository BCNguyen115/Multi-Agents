"""Data Analyst Agent package.

``DataAnalystAgent`` is imported lazily so that light-weight submodules (profiler, ingest, insights, ...)
can be used without loading the whole agent (and its LLM client) — and without import cycles.
"""

from typing import Any

__all__: list[str] = ["DataAnalystAgent"]


def __getattr__(name: str) -> Any:
    if name == "DataAnalystAgent":
        from src.agents.data_agent.agent import DataAnalystAgent

        return DataAnalystAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
