"""PostgreSQL async client with pgvector support.

Manages an ``asyncpg`` connection pool and ensures the ``pgvector``
extension is activated on first use.  All database calls include
structured error handling with timeout protection.

Usage:
    from src.shared.postgres_client import PostgresClient

    pg = PostgresClient(dsn="postgresql://...")
    await pg.connect()
    rows = await pg.fetch("SELECT 1")
    await pg.disconnect()
"""

import logging
from typing import Any, List, Optional

try:
    import asyncpg
    from asyncpg import Pool, Record
except ImportError:
    asyncpg = None
    Pool = Any
    Record = Any

from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Default connection / query timeout in seconds.
_CONNECT_TIMEOUT: float = 10.0
_QUERY_TIMEOUT: float = 15.0


class PostgresClient:
    """Async PostgreSQL client backed by an ``asyncpg`` connection pool.

    Attributes:
        dsn: PostgreSQL connection string.
        pool: The underlying asyncpg connection pool (``None`` before connect).
    """

    def __init__(self, dsn: str) -> None:
        """Initialise the client with a connection string.

        Args:
            dsn: PostgreSQL DSN, e.g.
                 ``"postgresql://user:pass@localhost:5432/db"``.
        """
        self.dsn: str = dsn
        self.pool: Optional[Pool] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(
        self,
        min_size: int = 5,
        max_size: int = 20,
        max_inactive_connection_lifetime: float = 300.0,
    ) -> None:
        """Create the connection pool and activate the pgvector extension.

        Args:
            min_size: Minimum number of connections in the pool (default: 5).
            max_size: Maximum number of connections in the pool (default: 20).
            max_inactive_connection_lifetime: Inactive connection lifetime in seconds (default: 300s).

        Raises:
            asyncpg.PostgresError: If the connection or extension setup fails.
        """
        self._min_size = min_size
        self._max_size = max_size
        self._max_inactive = max_inactive_connection_lifetime

        try:
            self.pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=min_size,
                max_size=max_size,
                max_inactive_connection_lifetime=max_inactive_connection_lifetime,
                timeout=_CONNECT_TIMEOUT,
            )
            await self._ensure_pgvector_extension()
            logger.info(
                "PostgreSQL connection pool created (min=%d, max=%d, lifetime=%.1fs)",
                min_size,
                max_size,
                max_inactive_connection_lifetime,
                extra={"session_id": "SYSTEM"},
            )
        except asyncpg.PostgresError as exc:
            logger.error(
                "Failed to create PostgreSQL pool: %s",
                exc,
                extra={"session_id": "SYSTEM"},
            )
            raise
        except OSError as exc:
            logger.error(
                "PostgreSQL connection timeout / network error: %s",
                exc,
                extra={"session_id": "SYSTEM"},
            )
            raise

    async def _ensure_connected(self) -> None:
        """Auto-reconnect if connection pool is None or closed."""
        if self.pool is None or getattr(self.pool, "_closed", False):
            logger.warning(
                "PostgreSQL connection pool closed or uninitialised; reconnecting...",
                extra={"session_id": "SYSTEM"},
            )
            await self.connect(
                min_size=getattr(self, "_min_size", 5),
                max_size=getattr(self, "_max_size", 20),
                max_inactive_connection_lifetime=getattr(self, "_max_inactive", 300.0),
            )

    async def disconnect(self) -> None:
        """Gracefully close the connection pool."""
        if self.pool is not None:
            await self.pool.close()
            logger.info(
                "PostgreSQL connection pool closed",
                extra={"session_id": "SYSTEM"},
            )
            self.pool = None

    # ------------------------------------------------------------------
    # Extension management
    # ------------------------------------------------------------------

    async def _ensure_pgvector_extension(self) -> None:
        """Ensure the ``vector`` extension is installed in the database.

        Raises:
            asyncpg.PostgresError: If the extension cannot be activated.
        """
        if self.pool is None:
            raise RuntimeError("Connection pool is not initialised.")

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "CREATE EXTENSION IF NOT EXISTS vector;",
                    timeout=_QUERY_TIMEOUT,
                )
            logger.info(
                "pgvector extension verified / activated",
                extra={"session_id": "SYSTEM"},
            )
        except asyncpg.PostgresError as exc:
            logger.error(
                "Failed to activate pgvector extension: %s",
                exc,
                extra={"session_id": "SYSTEM"},
            )
            raise

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def fetch(
        self,
        query: str,
        *args: Any,
        session_id: str = "N/A",
        timeout: float = _QUERY_TIMEOUT,
    ) -> List[Record]:
        """Execute a SELECT-style query and return all rows.

        Args:
            query: SQL query string with ``$1`` / ``$2`` placeholders.
            *args: Positional bind parameters.
            session_id: Correlation ID for structured logging.
            timeout: Per-query timeout in seconds.

        Returns:
            List[Record]: A list of ``asyncpg.Record`` objects.
        """
        if self.pool is None:
            raise RuntimeError("Connection pool is not initialised.")

        try:
            async with self.pool.acquire() as conn:
                rows: List[Record] = await conn.fetch(
                    query, *args, timeout=timeout
                )
            logger.debug(
                "Query returned %d rows",
                len(rows),
                extra={"session_id": session_id},
            )
            return rows
        except asyncpg.PostgresError as exc:
            logger.error(
                "Query execution failed: %s | query=%s",
                exc,
                query[:120],
                extra={"session_id": session_id},
            )
            raise
        except TimeoutError as exc:
            logger.error(
                "Query timed out after %.1fs: %s",
                timeout,
                query[:120],
                extra={"session_id": session_id},
            )
            raise

    async def execute(
        self,
        query: str,
        *args: Any,
        session_id: str = "N/A",
        timeout: float = _QUERY_TIMEOUT,
    ) -> str:
        """Execute a DML/DDL statement (INSERT, UPDATE, CREATE, …).

        Args:
            query: SQL statement string.
            *args: Positional bind parameters.
            session_id: Correlation ID for structured logging.
            timeout: Per-query timeout in seconds.

        Returns:
            str: The status string returned by PostgreSQL (e.g. ``"INSERT 0 1"``).
        """
        if self.pool is None:
            raise RuntimeError("Connection pool is not initialised.")

        try:
            async with self.pool.acquire() as conn:
                result: str = await conn.execute(
                    query, *args, timeout=timeout
                )
            logger.debug(
                "Statement executed: %s",
                result,
                extra={"session_id": session_id},
            )
            return result
        except asyncpg.PostgresError as exc:
            logger.error(
                "Statement execution failed: %s | query=%s",
                exc,
                query[:120],
                extra={"session_id": session_id},
            )
            raise
        except TimeoutError as exc:
            logger.error(
                "Statement timed out after %.1fs: %s",
                timeout,
                query[:120],
                extra={"session_id": session_id},
            )
            raise
