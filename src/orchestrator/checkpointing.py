"""Run checkpoints: every step of a PEV run saved in PostgreSQL, so a run can be inspected, resumed or replayed.

Off unless ``CHECKPOINT_ENABLED``. One run = one LangGraph thread (``thread_id`` is the request id, not the session: the state
of every request is built from scratch, a thread per session would only mix runs). Debug with ``python -m scripts.replay_run``.

What is NOT saved, on purpose: the uploaded file (``csv_content``: large, personal, and the Redis session copy has it) and
anything past ``CHECKPOINT_MAX_FIELD_CHARS`` of an answer (a dashboard spec carries thousands of table rows and would be
copied into every checkpoint). A replay from a step AFTER the executor therefore sees a cut answer; replay from the planner.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Sequence

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from src.shared.logger import get_logger
from src.shared.postgres_client import SETUP_LOCK_ID

logger: logging.Logger = get_logger(__name__)

_PURGE_EVERY_SECONDS: int = 6 * 3600
_NOT_SAVED: frozenset[str] = frozenset({"csv_content"})


def _lean(value: Any, limit: int) -> Any:
    if isinstance(value, dict):  # the whole input state is saved as ONE dict under the ``__start__`` channel: scrub inside it too
        return {key: _lean(item, limit) for key, item in value.items() if key not in _NOT_SAVED}
    if isinstance(value, str) and len(value) > limit:
        return f"{value[:limit]}\n…[{len(value) - limit} more characters not saved]"
    return value


class LeanSaver(AsyncPostgresSaver):
    """``AsyncPostgresSaver`` that leaves out the uploaded file and cuts oversized text (see the module docstring)."""

    max_chars: int = 100_000

    async def aput(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        values = {k: _lean(v, self.max_chars) for k, v in checkpoint["channel_values"].items() if k not in _NOT_SAVED}
        return await super().aput(config, {**checkpoint, "channel_values": values}, metadata, new_versions)

    async def aput_writes(self, config: Any, writes: Sequence[tuple[str, Any]], task_id: str, task_path: str = "") -> None:
        kept = [(channel, _lean(value, self.max_chars)) for channel, value in writes if channel not in _NOT_SAVED]
        if kept:
            await super().aput_writes(config, kept, task_id, task_path)


async def open_checkpointer(dsn: str, max_chars: int) -> tuple[LeanSaver, Any]:
    """Connect, create the checkpoint tables if missing and return ``(saver, pool)``; the caller closes the pool."""
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(dsn, max_size=4, open=False, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
    await pool.open(wait=True, timeout=10)
    saver = LeanSaver(pool)
    saver.max_chars = max_chars
    try:
        async with pool.connection() as conn:  # replicas starting together take turns creating the tables
            await conn.execute("SELECT pg_advisory_lock(%s)", (SETUP_LOCK_ID,))
            try:
                await saver.setup()
            finally:
                await conn.execute("SELECT pg_advisory_unlock(%s)", (SETUP_LOCK_ID,))
    except Exception:
        await pool.close()
        raise
    return saver, pool


async def purge_old_runs(saver: LeanSaver, pool: Any, days: int) -> int:
    """Delete the runs whose newest checkpoint is older than ``days``; returns how many (at most 1000 per call)."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT thread_id FROM checkpoints GROUP BY thread_id "
            "HAVING max((checkpoint->>'ts')::timestamptz) < now() - make_interval(days => %s) LIMIT 1000",
            (days,),
        )
        threads = [row["thread_id"] for row in await cursor.fetchall()]
    for thread_id in threads:
        await saver.adelete_thread(thread_id)
    return len(threads)


async def purge_forever(saver: LeanSaver, pool: Any, days: int) -> None:
    """Background loop of the gateway: retention is a promise, not a manual chore."""
    while True:
        try:
            removed = await purge_old_runs(saver, pool, days)
            if removed:
                logger.info("Deleted %d run checkpoints older than %d days", removed, days, extra={"session_id": "SYSTEM"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - try again at the next round
            logger.warning("Checkpoint purge failed: %s", exc or type(exc).__name__, extra={"session_id": "SYSTEM"})
        await asyncio.sleep(_PURGE_EVERY_SECONDS)
