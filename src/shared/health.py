"""Probes for the services the platform depends on: one place for ``GET /ready`` and the administration health page.

Each ``check_*`` raises when its service does not answer. ``probe`` turns that into ``"ok"`` or the exception's class name (the
detail stays in the log, not in the answer) and never waits longer than ``timeout``; ``probe_timed`` also says how long it took.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from src.config import settings
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS: float = 2.0


async def probe(check: Callable[[], Awaitable[None]], timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str:
    """"ok" or a short reason; never raises and never waits longer than ``timeout``."""
    try:
        await asyncio.wait_for(check(), timeout=timeout)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Health check failed: %s: %s", type(exc).__name__, exc)
        return type(exc).__name__


async def probe_timed(check: Callable[[], Awaitable[None]], timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    started = time.perf_counter()
    status = await probe(check, timeout)
    return {"status": status, "ms": round((time.perf_counter() - started) * 1000)}


async def check_postgres(pg: Any) -> None:
    await pg.fetch("SELECT 1")


async def check_redis(redis: Any) -> None:
    if redis.client is None:
        raise ConnectionError("not connected")
    await redis.client.ping()


async def _get(url: str, timeout: float) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as http:
        (await http.get(url)).raise_for_status()


async def check_reranker(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
    await _get(settings.RERANKER_ENDPOINT.rsplit("/", 1)[0] + "/health", timeout)


async def check_sandbox(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
    await _get(settings.SANDBOX_URL.rstrip("/") + "/health", timeout)
