"""Per-caller rate limiting for the expensive routes (every chat turn calls several LLMs and the reranker).

Fixed one-minute windows counted in Redis, keyed by user (authenticated) or client IP (anonymous dev mode), so the
limit is shared by every backend replica. Limits are settings (``RATE_LIMIT_*_PER_MINUTE``, 0 = unlimited).
If Redis is unreachable the call is counted in this process instead (a warning is logged): the limit still holds per
replica, and nothing is refused until the caller really is over it. No Redis configured (dev) = unlimited.

Behind a reverse proxy every anonymous caller shares the proxy's IP: enable authentication so users are told apart.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import HTTPException, Request

from src.shared.auth import Principal
from src.shared.logger import get_logger
from src.shared.messages import msg

logger: logging.Logger = get_logger(__name__)

WINDOW_SECONDS: int = 60


# ponytail: per-process counter used only while Redis is down, so with N replicas the effective limit is N x limit
_local: dict[str, int] = {}
_local_bucket: int = -1


def _local_count(key: str, bucket: int) -> int:
    global _local_bucket
    if bucket != _local_bucket:  # a new window: every old key is dead
        _local.clear()
        _local_bucket = bucket
    _local[key] = _local.get(key, 0) + 1
    return _local[key]


def caller_key(principal: Principal, request: Request) -> str:
    if principal.authenticated:
        return f"user:{principal.user_id}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


async def enforce(redis_client: Any, principal: Principal, request: Request, group: str, limit: int) -> None:
    """Count this call; raise 429 (with ``Retry-After``) when the caller is over ``limit`` in the current window."""
    if limit <= 0 or redis_client is None or getattr(redis_client, "client", None) is None:
        return
    now = int(time.time())
    bucket = now // WINDOW_SECONDS
    key = f"ratelimit:{group}:{caller_key(principal, request)}:{bucket}"
    try:
        pipe = redis_client.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, WINDOW_SECONDS + 5, nx=True)
        count = int((await pipe.execute())[0])
    except Exception as exc:  # noqa: BLE001 - Redis down: keep limiting with this process's own counter
        logger.warning("Rate limiter: Redis unavailable, counting in this process: %s", exc or type(exc).__name__)
        count = _local_count(key, bucket)
    if count > limit:
        retry_after = (bucket + 1) * WINDOW_SECONDS - now
        logger.warning("Rate limit exceeded: %s group=%s count=%d limit=%d", caller_key(principal, request), group, count, limit)
        raise HTTPException(
            status_code=429,
            detail=msg("rate.limited", limit=limit, seconds=retry_after),
            headers={"Retry-After": str(max(retry_after, 1))},
        )
