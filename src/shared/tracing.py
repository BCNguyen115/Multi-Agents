"""Langfuse tracing (V2 SDK: the one LiteLLM requires) with ONE shared client.

``connect`` proves the API keys against the server before tracing is switched on, so "enabled" in the log means traces
really arrive; every failure leaves the application running with tracing off. ``langchain_handler`` hands each request a
LangChain/LangGraph callback bound to a new trace on that shared client (the SDK would otherwise build a client, with its
own background thread, per request).
"""
import importlib
import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Any

import litellm

from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Langfuse 2.x's LangChain handler imports these old paths; langchain 1.x moved the same classes into langchain_core.
_LANGCHAIN_ALIASES = {
    "langchain.callbacks.base": "langchain_core.callbacks.base",
    "langchain.schema.agent": "langchain_core.agents",
    "langchain.schema.document": "langchain_core.documents",
}

# Trace of the request being served; LLM calls made while it is set join it instead of opening their own trace.
_current_trace: ContextVar[str | None] = ContextVar("langfuse_trace_id", default=None)


def with_trace(metadata: dict[str, Any]) -> dict[str, Any]:
    """LiteLLM call metadata, placed under the current request's trace (``existing_trace_id``) when there is one."""
    trace_id = _current_trace.get()
    return {**metadata, "existing_trace_id": trace_id} if trace_id else metadata


def alias_langchain_modules() -> None:
    for old, new in _LANGCHAIN_ALIASES.items():
        try:
            importlib.import_module(old)
        except ImportError:
            sys.modules[old] = importlib.import_module(new)


def connect(settings: Any, attempts: int = 3, delay: float = 2.0) -> Any | None:
    """Return a Langfuse client whose keys the server accepted (and route LiteLLM's callbacks to it), else None."""
    litellm.success_callback = []
    litellm.failure_callback = []
    if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        logger.warning(
            "Langfuse tracing OFF: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are empty (see .env.example).",
            extra={"session_id": "SYSTEM"},
        )
        return None
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
            timeout=5,
        )
    except Exception as exc:
        logger.warning("Langfuse tracing OFF: client could not start (%s)", exc, extra={"session_id": "SYSTEM"})
        return None

    error: Exception | None = None
    for attempt in range(attempts):
        try:
            client.auth_check()  # True, or raises (401 = keys unknown to this server, connection error = host down)
            error = None
            break
        except Exception as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(delay)
    if error is not None:
        logger.warning(
            "Langfuse tracing OFF: %s did not accept the keys (%s: %s)",
            settings.LANGFUSE_HOST, type(error).__name__, str(error).splitlines()[0][:160],
            extra={"session_id": "SYSTEM"},
        )
        client.shutdown()
        return None

    # LiteLLM's own Langfuse logger reads the credentials from the environment.
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
    os.environ["LANGFUSE_HOST"] = settings.LANGFUSE_HOST
    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]
    logger.info("Langfuse tracing ENABLED, keys accepted by %s", settings.LANGFUSE_HOST, extra={"session_id": "SYSTEM"})
    return client


def langchain_handler(
    client: Any, session_id: str, user_id: str | None, trace_name: str, tags: list[str] | None, metadata: dict[str, Any] | None
) -> Any | None:
    """A callback for ``graph.ainvoke(config={"callbacks": [...]})`` that records the run as one Langfuse trace."""
    try:
        alias_langchain_modules()
        trace = client.trace(
            name=trace_name, session_id=session_id, user_id=user_id or session_id, tags=tags or ["pev_loop"], metadata=metadata,
        )
        handler = trace.get_langchain_handler()
        _current_trace.set(trace.id)
        return handler  # update_parent=True would rename the trace to "LangGraph"
    except Exception as exc:
        logger.warning("Langfuse trace handler unavailable, this request is not traced: %s", exc, extra={"session_id": session_id})
        return None
