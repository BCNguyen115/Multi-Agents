"""/ready tells an orchestrator whether this instance can serve; /health only says the process is alive."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from src.gateway import main


def ready(monkeypatch, *, postgres_ok=True, redis_ok=True, reranker_ok=True, orchestrator=True):
    pg = MagicMock()
    pg.fetch = AsyncMock() if postgres_ok else AsyncMock(side_effect=ConnectionError("db down"))
    redis = MagicMock()
    redis.client = MagicMock(ping=AsyncMock() if redis_ok else AsyncMock(side_effect=ConnectionError("redis down")))

    class Http:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def get(self, url):
            assert url.endswith("/health") and "/rerank" not in url
            if not reranker_ok:
                raise ConnectionError("no reranker")
            return MagicMock(raise_for_status=lambda: None)

    monkeypatch.setattr(main, "pg_client", pg)
    monkeypatch.setattr(main, "redis_client", redis)
    monkeypatch.setattr(main, "orchestrator", MagicMock() if orchestrator else None)
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Http)
    response = asyncio.run(main.readiness())
    return response.status_code, json.loads(response.body)


def test_everything_up_is_ready(monkeypatch):
    code, body = ready(monkeypatch)
    assert code == 200 and body["status"] == "ready" and set(body["checks"].values()) == {"ok"}


def test_a_missing_reranker_is_degraded_but_still_serves(monkeypatch):
    code, body = ready(monkeypatch, reranker_ok=False)
    assert code == 200 and body["status"] == "degraded" and body["checks"]["reranker"].startswith("ConnectionError")


def test_postgres_or_redis_down_is_unavailable(monkeypatch):
    for kw in ({"postgres_ok": False}, {"redis_ok": False}):
        code, body = ready(monkeypatch, **kw)
        assert code == 503 and body["status"] == "unavailable"


def test_not_ready_until_the_orchestrator_is_built(monkeypatch):
    code, body = ready(monkeypatch, orchestrator=False)
    assert code == 503 and body["orchestrator"] is False


def test_a_hanging_dependency_cannot_hang_the_probe(monkeypatch):
    monkeypatch.setattr(main, "_READY_TIMEOUT_SECONDS", 0.05)

    async def slow():
        await asyncio.sleep(1)

    assert asyncio.run(main._probe(slow)).startswith("TimeoutError")
