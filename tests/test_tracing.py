"""Langfuse tracing: keys are proven against the server, failures never break the app, one client serves every request."""
import types
from unittest.mock import MagicMock

import litellm
import pytest

from src.shared import tracing
from src.shared.llm_client import LLMClient


def _settings(public="pk-lf-x", secret="sk-lf-x", enabled=True):
    return types.SimpleNamespace(
        LANGFUSE_ENABLED=enabled, LANGFUSE_PUBLIC_KEY=public, LANGFUSE_SECRET_KEY=secret, LANGFUSE_HOST="http://langfuse.test",
        OPENROUTER_API_KEY="k", OPENROUTER_BASE_URL="http://x", OPENROUTER_MODEL="m",
    )


@pytest.fixture(autouse=True)
def _restore_litellm_callbacks():
    before = (list(litellm.success_callback), list(litellm.failure_callback))
    tracing._current_trace.set(None)
    yield
    litellm.success_callback, litellm.failure_callback = before
    tracing._current_trace.set(None)


def _fake_langfuse(monkeypatch, auth_check):
    client = MagicMock()
    client.auth_check.side_effect = auth_check
    monkeypatch.setattr("langfuse.Langfuse", MagicMock(return_value=client))
    return client


def test_empty_keys_turn_tracing_off_without_calling_the_server(monkeypatch):
    client = _fake_langfuse(monkeypatch, [True])
    assert tracing.connect(_settings(public="", secret="")) is None
    client.auth_check.assert_not_called()
    assert litellm.success_callback == []


def test_keys_the_server_rejects_turn_tracing_off(monkeypatch):
    client = _fake_langfuse(monkeypatch, Exception("401 Invalid credentials"))
    assert tracing.connect(_settings(), attempts=2, delay=0) is None
    assert client.auth_check.call_count == 2
    client.shutdown.assert_called_once()
    assert litellm.success_callback == []


def test_a_server_that_comes_up_during_the_retries_is_accepted(monkeypatch):
    client = _fake_langfuse(monkeypatch, [ConnectionError("starting"), True])
    assert tracing.connect(_settings(), attempts=3, delay=0) is client
    assert litellm.success_callback == ["langfuse"] and litellm.failure_callback == ["langfuse"]


def test_the_langchain_handler_builds_with_langchain_1x_and_names_the_trace():
    from langfuse import Langfuse

    client = Langfuse(public_key="pk", secret_key="sk", host="http://127.0.0.1:9", enabled=False)
    handler = tracing.langchain_handler(client, "sess", "alice", "pev_loop_auto", ["pev_loop"], {"request_id": "r1"})
    assert type(handler).__name__ == "LangchainCallbackHandler"


def test_a_handler_failure_only_skips_tracing_for_that_request():
    client = MagicMock()
    client.trace.side_effect = RuntimeError("boom")
    assert tracing.langchain_handler(client, "s", None, "n", None, None) is None


def test_llm_client_leaves_tracing_off_when_the_server_rejects_the_keys(monkeypatch):
    monkeypatch.setattr(tracing, "connect", lambda settings: None)
    client = LLMClient(settings=_settings())
    assert client.langfuse_enabled is False
    assert client.get_langfuse_callback(session_id="s") is None


def test_llm_client_hands_each_request_a_handler_from_the_shared_client(monkeypatch):
    shared = MagicMock()
    monkeypatch.setattr(tracing, "connect", lambda settings: shared)
    seen = []
    monkeypatch.setattr(tracing, "langchain_handler", lambda *a: seen.append(a) or object())
    client = LLMClient(settings=_settings())
    assert client.langfuse_enabled is True
    client.get_langfuse_callback(session_id="s1", trace_name="a")
    client.get_langfuse_callback(session_id="s2", trace_name="b")
    assert [a[0] for a in seen] == [shared, shared]
    client.shutdown()
    shared.shutdown.assert_called_once()


def test_llm_calls_join_the_trace_that_the_request_opened():
    client = MagicMock()
    client.trace.return_value.id = "trace-1"
    assert tracing.with_trace({"a": 1}) == {"a": 1}  # no request trace open: the call keeps its own
    tracing.langchain_handler(client, "s", "u", "n", None, None)
    assert tracing.with_trace({"a": 1}) == {"a": 1, "existing_trace_id": "trace-1"}
