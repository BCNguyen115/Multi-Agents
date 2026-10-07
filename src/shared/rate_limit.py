"""Per-caller rate limiting for the expensive routes (every chat turn calls several LLMs and the reranker).

Fixed one-minute windows counted in Redis, keyed by user (authenticated) or client IP (anonymous dev mode), so the
limit is shared by every backend replica. Limits are settings (``RATE_LIMIT_*_PER_MINUTE``, 0 = unlimited).
If Redis is unreachable the call is counted in this process instead (a warning is logged): the limit still holds per
replica, and nothing is refused until the caller really is over it. No Redis configured (dev) = unlimited.

Behind a reverse proxy every anonymous caller shares the proxy's IP: enable authentication so users are told apart.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from typing import Any

from fastapi import HTTPException, Request

from src.config import settings
from src.shared.auth import Principal
from src.shared.logger import get_logger
from src.shared.messages import msg

logger: logging.Logger = get_logger(__name__)

WINDOW_SECONDS: int = 60


# ponytail: per-process counter used only while Redis is down, so with N replicas the effective limit is N x limit
_local: dict[str, int] = {}


def _local_count(key: str, bucket: int) -> int:
    if len(_local) > 10_000:  # the bucket is part of the key, so old windows are dead weight: drop them all now and then
        _local.clear()
    _local[key] = _local.get(key, 0) + 1
    return _local[key]


def caller_key(principal: Principal, request: Request) -> str:
    if principal.authenticated:
        return f"user:{principal.user_id}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


async def enforce(redis_client: Any, principal: Principal, request: Request, group: str, limit: int, window: int = WINDOW_SECONDS) -> None:
    """Count this call; raise 429 (with ``Retry-After``) when the caller is over ``limit`` in the current window
    (one minute by default; a daily budget passes ``window=86400``)."""
    if limit <= 0 or redis_client is None or getattr(redis_client, "client", None) is None:
        return
    now = int(time.time())
    bucket = now // window
    key = f"ratelimit:{group}:{caller_key(principal, request)}:{bucket}"
    try:
        pipe = redis_client.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window + 5, nx=True)
        count = int((await pipe.execute())[0])
    except Exception as exc:  # noqa: BLE001 - Redis down: keep limiting with this process's own counter
        logger.warning("Rate limiter: Redis unavailable, counting in this process: %s", exc or type(exc).__name__)
        count = _local_count(key, bucket)
    if count > limit:
        retry_after = (bucket + 1) * window - now
        logger.warning("Rate limit exceeded: %s group=%s count=%d limit=%d", caller_key(principal, request), group, count, limit)
        raise HTTPException(
            status_code=429,
            detail=msg("rate.limited", limit=limit, seconds=retry_after) if window <= WINDOW_SECONDS else msg("rate.daily", limit=limit, hours=-(-retry_after // 3600)),
            headers={"Retry-After": str(max(retry_after, 1))},
        )


# ---------------------------------------------------------------------------
# Failed credentials per ACCOUNT (not per IP): behind the frontend every caller can share one IP, and an IP bucket is then
# either useless or one attacker locking everybody out. Only failures are counted; a success clears the account's counter.
# An unknown username is counted exactly like a known one, so a lock-out does not reveal which accounts exist.
# ponytail: fixed window; a targeted attacker can keep ONE account locked by failing on purpose (the usual price of this control)
# ---------------------------------------------------------------------------

_failures_local: dict[str, tuple[int, float]] = {}  # only while Redis is failing: key -> (count, expires at)


def _failure_key(scope: str, name: str) -> str:
    return f"authfail:{scope}:{hashlib.sha256(name.strip().lower().encode()).hexdigest()[:32]}"


def _window() -> int:
    return max(int(settings.AUTH_FAILURE_WINDOW_MINUTES), 1) * 60


async def check_failures(redis_client: Any, scope: str, name: str, limit: int) -> None:
    """Raise 429 when ``name`` has already failed ``limit`` times in the current window (does not count anything itself)."""
    client = getattr(redis_client, "client", None)
    if limit <= 0 or client is None:
        return
    key = _failure_key(scope, name)
    count, left = 0, 0
    try:
        raw = await client.get(key)
        if raw is not None:
            count, left = int(raw), max(int(await client.ttl(key)), 1)
    except Exception as exc:  # noqa: BLE001 - Redis down: this process's own counter
        logger.warning("Failure counter: Redis unavailable, counting in this process: %s", exc or type(exc).__name__)
        count, expires = _failures_local.get(key, (0, 0.0))
        left = max(int(expires - time.time()), 1)
        if expires <= time.time():
            _failures_local.pop(key, None)
            count = 0
    if count >= limit:
        logger.warning("Account locked for now: scope=%s failures=%d", scope, count)
        raise HTTPException(
            status_code=429,
            detail=msg("auth.locked", minutes=math.ceil(left / 60)),
            headers={"Retry-After": str(left)},
        )


async def record_failure(redis_client: Any, scope: str, name: str) -> None:
    client = getattr(redis_client, "client", None)
    if client is None:
        return
    key = _failure_key(scope, name)
    try:
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, _window(), nx=True)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failure counter: Redis unavailable, counting in this process: %s", exc or type(exc).__name__)
        count, expires = _failures_local.get(key, (0, 0.0))
        if expires <= time.time():
            count, expires = 0, time.time() + _window()
        _failures_local[key] = (count + 1, expires)


async def clear_failures(redis_client: Any, scope: str, name: str) -> None:
    client = getattr(redis_client, "client", None)
    if client is None:
        return
    key = _failure_key(scope, name)
    _failures_local.pop(key, None)
    try:
        await client.delete(key)
    except Exception as exc:  # noqa: BLE001 - the counter expires by itself
        logger.warning("Could not clear the failure counter: %s", exc or type(exc).__name__)
