"""Prometheus: routes are counted by template, /metrics is guarded in production, LLM calls feed the cost counters."""
import asyncio

import httpx
import pytest
from fastapi import FastAPI

from src.config import settings
from src.gateway import main
from src.shared import metrics, usage


def metrics_app():
    """The gateway's own middleware and /metrics route on a small app (main.app's full stack depends on what other test modules stubbed)."""
    app = FastAPI()
    app.middleware("http")(main.observe_requests)
    app.get("/metrics")(main.prometheus_metrics)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def scrape(headers=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=metrics_app()), base_url="http://test") as client:
            return await client.get("/metrics", headers=headers or {})

    return asyncio.run(go())


def test_a_request_is_counted_under_its_route_template_not_its_url(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=metrics_app()), base_url="http://test") as client:
            await client.get("/health")
            await client.get("/api/does-not-exist/12345")

    asyncio.run(go())
    body = scrape().text
    assert 'agent_http_requests_total{method="GET",route="/health",status="200"}' in body
    assert 'route="unmatched"' in body and "12345" not in body  # no id ever becomes a label
    assert 'route="/metrics"' not in body  # scraping does not count itself


def test_metrics_are_off_in_production_without_a_token_and_need_it_with_one(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")
    assert scrape().status_code == 404
    monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-token")
    assert scrape().status_code == 401
    assert scrape({"Authorization": "Bearer wrong"}).status_code == 401
    assert scrape({"Authorization": "Bearer s3cret-token"}).status_code == 200


def test_an_llm_call_moves_the_call_token_and_cost_counters():
    prompt_before = metrics.LLM_TOKENS.labels("prompt")._value.get()
    completion_before = metrics.LLM_TOKENS.labels("completion")._value.get()
    cost_before = metrics.LLM_COST._value.get()
    metrics.record_llm({"model": "m-test", "prompt_tokens": 7, "completion_tokens": 3, "cost_usd": 0.25})
    assert metrics.LLM_CALLS.labels("m-test")._value.get() >= 1
    assert metrics.LLM_TOKENS.labels("prompt")._value.get() - prompt_before == 7
    assert metrics.LLM_TOKENS.labels("completion")._value.get() - completion_before == 3
    assert metrics.LLM_COST._value.get() - cost_before == pytest.approx(0.25)


def test_the_usage_callback_feeds_prometheus_even_without_a_database(monkeypatch):
    monkeypatch.setattr(usage, "_pg", None)
    cost_before = metrics.LLM_COST._value.get()

    class U:
        prompt_tokens, completion_tokens = 1, 1

    class R:
        usage = U()

    asyncio.run(usage.UsageLogger().async_log_success_event({"model": "m2", "response_cost": 0.5}, R(), None, None))
    assert metrics.LLM_COST._value.get() - cost_before == pytest.approx(0.5)
