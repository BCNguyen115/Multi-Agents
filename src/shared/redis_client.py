"""Redis async client for session state and caching.

Wraps ``redis.asyncio`` to provide a thin, type-hinted async interface
for storing / retrieving conversation state.  Connection errors are
handled gracefully so the rest of the system stays operational.

Usage:
    from src.shared.redis_client import RedisClient

    rc = RedisClient(url="redis://localhost:6379/0")
    await rc.connect()
    await rc.set_value("key", "value", ttl=300)
    val = await rc.get_value("key")
    await rc.disconnect()
"""

import json
import logging
from typing import Any, List, Optional

import redis.asyncio as aioredis

from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Default Redis operation timeout in seconds.
_SOCKET_TIMEOUT: float = 5.0


class RedisClient:
    """Async Redis client for session state management.

    Attributes:
        url: Redis connection string.
        client: The underlying ``redis.asyncio.Redis`` instance.
    """

    def __init__(self, url: str) -> None:
        """Initialise the Redis client wrapper.

        Args:
            url: Redis connection URL, e.g. ``"redis://localhost:6379/0"``.
        """
        self.url: str = url
        self.client: Optional[aioredis.Redis] = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish the Redis connection.

        Raises:
            redis.ConnectionError: When the server is unreachable.
        """
        try:
            self.client = aioredis.from_url(
                self.url,
                decode_responses=True,
                socket_timeout=_SOCKET_TIMEOUT,
                socket_connect_timeout=_SOCKET_TIMEOUT,
            )
            # Verify connectivity with a PING.
            await self.client.ping()
            logger.info(
                "Redis connection established",
                extra={"session_id": "SYSTEM"},
            )
        except (aioredis.ConnectionError, OSError) as exc:
            logger.error(
                "Failed to connect to Redis: %s",
                exc,
                extra={"session_id": "SYSTEM"},
            )
            raise

    async def disconnect(self) -> None:
        """Close the Redis connection gracefully."""
        if self.client is not None:
            await self.client.aclose()
            logger.info(
                "Redis connection closed",
                extra={"session_id": "SYSTEM"},
            )
            self.client = None

    # ------------------------------------------------------------------
    # Basic key/value helpers
    # ------------------------------------------------------------------

    async def set_value(
        self,
        key: str,
        value: str,
        ttl: int = 3600,
        session_id: str = "N/A",
    ) -> None:
        """Store a string value in Redis with optional TTL.

        Args:
            key: Redis key.
            value: String value to store.
            ttl: Time-to-live in seconds (default 1 hour).
            session_id: Correlation ID for logging.
        """
        if self.client is None:
            raise RuntimeError("Redis client is not connected.")

        try:
            await self.client.set(name=key, value=value, ex=ttl)
            logger.debug(
                "Redis SET %s (ttl=%ds)",
                key,
                ttl,
                extra={"session_id": session_id},
            )
        except aioredis.RedisError as exc:
            logger.error(
                "Redis SET failed for key=%s: %s",
                key,
                exc,
                extra={"session_id": session_id},
            )
            raise

    async def get_value(
        self,
        key: str,
        session_id: str = "N/A",
    ) -> Optional[str]:
        """Retrieve a string value from Redis.

        Args:
            key: Redis key to look up.
            session_id: Correlation ID for logging.

        Returns:
            Optional[str]: The stored value, or ``None`` if the key
            does not exist or has expired.
        """
        if self.client is None:
            raise RuntimeError("Redis client is not connected.")

        try:
            value: Optional[str] = await self.client.get(name=key)
            logger.debug(
                "Redis GET %s -> %s",
                key,
                "HIT" if value is not None else "MISS",
                extra={"session_id": session_id},
            )
            return value
        except aioredis.RedisError as exc:
            logger.error(
                "Redis GET failed for key=%s: %s",
                key,
                exc,
                extra={"session_id": session_id},
            )
            raise

    # ------------------------------------------------------------------
    # Conversation history helpers (list-based, capped at N turns)
    # ------------------------------------------------------------------

    async def append_to_history(
        self,
        session_id: str,
        role: str,
        content: str,
        max_turns: int = 5,
        ttl: int = 3600,
    ) -> None:
        """Append a message to the session conversation history.

        The history is stored as a Redis list of JSON-encoded dicts.
        Each entry has the form ``{"role": "...", "content": "..."}``.
        Only the latest ``max_turns`` *pairs* (i.e. ``max_turns * 2``
        individual messages) are kept — older entries are trimmed
        automatically.

        Args:
            session_id: Session correlation ID (used as Redis key prefix).
            role: Message role (``"user"`` or ``"assistant"``).
            content: Message text.
            max_turns: Maximum number of conversation turns to retain.
            ttl: TTL in seconds for the history key.
        """
        if self.client is None:
            raise RuntimeError("Redis client is not connected.")

        key: str = f"history:{session_id}"
        entry: str = json.dumps({"role": role, "content": content})

        try:
            await self.client.rpush(key, entry)
            # Truncate: keep only the last `max_turns * 2` messages.
            await self.client.ltrim(key, -(max_turns * 2), -1)
            await self.client.expire(key, ttl)
            logger.debug(
                "Appended %s message to history (key=%s)",
                role,
                key,
                extra={"session_id": session_id},
            )
        except aioredis.RedisError as exc:
            logger.error(
                "Failed to append to history key=%s: %s",
                key,
                exc,
                extra={"session_id": session_id},
            )
            raise

    async def get_history(
        self,
        session_id: str,
    ) -> List[dict[str, str]]:
        """Retrieve the full conversation history for a session.

        Args:
            session_id: Session correlation ID.

        Returns:
            List[dict[str, str]]: Ordered list of ``{"role": …, "content": …}``
            dicts, oldest first.
        """
        if self.client is None:
            raise RuntimeError("Redis client is not connected.")

        key: str = f"history:{session_id}"

        try:
            raw_entries: List[str] = await self.client.lrange(key, 0, -1)
            history: List[dict[str, str]] = [
                json.loads(entry) for entry in raw_entries
            ]
            logger.debug(
                "Retrieved %d history messages (key=%s)",
                len(history),
                key,
                extra={"session_id": session_id},
            )
            return history
        except aioredis.RedisError as exc:
            logger.error(
                "Failed to retrieve history key=%s: %s",
                key,
                exc,
                extra={"session_id": session_id},
            )
            raise

    # ------------------------------------------------------------------
    # Active CSV file caching
    # ------------------------------------------------------------------

    async def set_active_file(
        self,
        session_id: str,
        filename: str,
        csv_content: str,
        ttl: int = 86400,
    ) -> None:
        """Store active CSV file metadata and content in Redis session state (default 24h)."""
        key = f"session:{session_id}:active_file"
        payload = json.dumps({"filename": filename, "csv_content": csv_content}, ensure_ascii=False)
        await self.set_value(key=key, value=payload, ttl=ttl, session_id=session_id)

    async def get_active_file(
        self,
        session_id: str,
    ) -> Optional[dict[str, str]]:
        """Retrieve active CSV file from Redis session state."""
        key = f"session:{session_id}:active_file"
        try:
            raw = await self.get_value(key=key, session_id=session_id)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            logger.warning("Failed to parse active file from Redis: %s", exc, extra={"session_id": session_id})
        return None
