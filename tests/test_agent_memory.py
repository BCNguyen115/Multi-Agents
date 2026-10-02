"""Agent long-term memory: mem0 is synchronous and slow, so it must never run on the event loop; it must store what the
user wrote (not routing logs) and a slow/failed store must never break a request."""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator import core
from src.orchestrator.core import Orchestrator
from src.registry.manager import AgentRegistry
from src.shared.memory_manager import DualList, DualResult
from src.shared.security import wrap_user_input


class SlowMemory:
    """Behaves like MemoryManager: synchronous, blocking, returns awaitable containers."""

    def __init__(self, delay: float):
        self.delay, self.added, self.searched = delay, [], []

    def add_memory(self, *, user_id, text, **kw):
        time.sleep(self.delay)
        self.added.append((user_id, text))
        return DualResult({"results": []})

    def get_relevant_memories(self, *, user_id, query, limit=3):
        time.sleep(self.delay)
        self.searched.append((user_id, query))
        return DualList(["Người dùng làm ở phòng pháp chế"])


def make(memory) -> Orchestrator:
    s = MagicMock()
    s.HITL_APPROVAL_TTL_SECONDS = 900
    return Orchestrator(registry=AgentRegistry(), settings=s, llm_client=MagicMock(), memory_manager=memory)


async def worst_loop_stall(action) -> float:
    """Longest time the event loop went without running while ``action`` ran."""
    worst, last, stop = 0.0, time.monotonic(), False

    async def ticker():
        nonlocal worst, last
        while not stop:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            worst, last = max(worst, now - last - 0.01), now

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.05)
    last = time.monotonic()
    await action()
    await asyncio.sleep(0.05)
    stop = True
    await task
    return worst


def test_a_slow_memory_write_does_not_freeze_the_event_loop():
    memory = SlowMemory(delay=0.5)
    orch = make(memory)

    async def scenario():
        async def write():
            orch._remember_in_background("s1", wrap_user_input("Tôi làm ở phòng pháp chế")[0])
            await asyncio.gather(*orch._background_tasks)

        return await worst_loop_stall(write)

    assert asyncio.run(scenario()) < 0.2 and memory.added  # the write took 0.5 s, the loop never stood still for that long


def test_the_user_text_is_stored_without_the_nonce_wrapper():
    memory = SlowMemory(delay=0)
    orch = make(memory)

    async def scenario():
        orch._remember_in_background("s1", wrap_user_input("Tôi làm ở phòng pháp chế")[0])
        await asyncio.gather(*orch._background_tasks)

    asyncio.run(scenario())
    assert memory.added == [("s1", "Tôi làm ở phòng pháp chế")]


def test_a_write_that_times_out_or_fails_never_raises(monkeypatch, caplog):
    monkeypatch.setattr(core, "_MEMORY_WRITE_TIMEOUT", 0.05)
    orch = make(SlowMemory(delay=0.3))

    async def scenario():
        orch._remember_in_background("s1", "hello")
        await asyncio.gather(*orch._background_tasks)

    asyncio.run(scenario())  # no exception: the request that triggered it has long been answered
    assert any("Failed to store memory" in r.getMessage() for r in caplog.records)


def test_memory_reads_run_in_a_thread_and_have_a_real_timeout():
    orch = make(SlowMemory(delay=0.4))

    async def read():
        got = await orch._memory_call(orch.memory_manager.get_relevant_memories, user_id="s1", query="q", timeout=2)
        assert list(got) == ["Người dùng làm ở phòng pháp chế"]

    assert asyncio.run(worst_loop_stall(read)) < 0.2

    async def too_slow():
        with pytest.raises(asyncio.TimeoutError):
            await orch._memory_call(orch.memory_manager.get_relevant_memories, user_id="s1", query="q", timeout=0.05)

    asyncio.run(too_slow())


def test_async_test_doubles_are_still_awaited():
    orch = make(MagicMock())
    fake = AsyncMock(return_value=["fact"])
    assert asyncio.run(orch._memory_call(fake, user_id="s1", query="q", timeout=1)) == ["fact"]


# ---------------------------------------------------------------- whose memory, and where it is kept
def test_memory_belongs_to_the_authenticated_user_else_to_the_session():
    from src.shared import auth

    assert auth.memory_user_id("s1") == "s1"  # nobody signed in: per session, as before
    marker = auth._current.set(auth.Principal("alice", "acme", "legal", frozenset(), authenticated=True))
    try:
        assert auth.memory_user_id("alice:s1") == "acme:alice"  # follows the user, prefixed by tenant
    finally:
        auth._current.reset(marker)


def test_the_orchestrator_reads_and_writes_memory_under_the_users_id():
    from src.shared import auth

    memory = SlowMemory(delay=0)
    orch = make(memory)

    async def scenario():
        marker = auth._current.set(auth.Principal("carol", "acme", "legal", frozenset(), authenticated=True))
        try:
            orch._remember_in_background("carol:s1", wrap_user_input("Tôi thích tóm tắt ngắn")[0])
            await asyncio.gather(*orch._background_tasks)
            await orch._memory_call(memory.get_relevant_memories, user_id=auth.memory_user_id("carol:s1"), query="q", timeout=1)
        finally:
            auth._current.reset(marker)

    asyncio.run(scenario())
    assert memory.added == [("acme:carol", "Tôi thích tóm tắt ngắn")] and memory.searched[0][0] == "acme:carol"


def test_the_memory_store_is_chosen_by_configuration():
    from types import SimpleNamespace

    from src.shared.memory_manager import vector_store_config

    pg = vector_store_config(SimpleNamespace(MEM0_VECTOR_STORE="pgvector", POSTGRES_URL="postgresql://u:p@db:5432/agentdb", MEM0_PG_COLLECTION="mem"))
    assert pg == {"provider": "pgvector", "config": {"connection_string": "postgresql://u:p@db:5432/agentdb", "collection_name": "mem", "embedding_model_dims": 1536}}
    dev = vector_store_config(SimpleNamespace(MEM0_VECTOR_STORE="memory", POSTGRES_URL="unused", MEM0_PG_COLLECTION="mem"))
    assert dev["provider"] == "qdrant"
