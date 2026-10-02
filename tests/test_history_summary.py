"""The 5-turn history cap folds what it drops into a running summary that the RAG planner can read."""
import asyncio
from types import SimpleNamespace

from src.shared import history_summary
from src.shared.redis_client import RedisClient


class FakeRedis:
    """Just the list/string commands the history helpers use."""

    def __init__(self):
        self.lists, self.strings = {}, {}

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    async def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        n = len(items)
        start = max(start + n, 0) if start < 0 else start
        end = end + n if end < 0 else end
        return items[start:end + 1] if end >= 0 else []

    async def ltrim(self, key, start, end):
        self.lists[key] = await self.lrange(key, start, end)

    async def expire(self, key, ttl):
        pass

    async def get(self, key):
        return self.strings.get(key)

    async def set(self, key, value, ex=None):
        self.strings[key] = value


def make_client():
    client = RedisClient.__new__(RedisClient)
    client.client = FakeRedis()
    return client


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Summary: asked about the NDA term."))])


async def settle():
    await asyncio.gather(*history_summary._background)


def test_history_is_capped_at_five_turns_and_the_dropped_ones_are_summarised():
    async def go():
        redis, llm = make_client(), FakeLLM()
        for i in range(5):
            await history_summary.persist_turn(redis, llm, "s", f"question {i}", f"answer {i}")
        await settle()
        assert llm.calls == [] and await redis.get_history_summary("s") == ""  # nothing fell off yet

        await history_summary.persist_turn(redis, llm, "s", "question 5", "answer 5")
        await settle()
        history = await redis.get_history("s")
        assert len(history) == 10 and history[0]["content"] == "question 1"
        assert len(llm.calls) == 1 and "question 0" in llm.calls[0]["messages"][1]["content"]
        assert await redis.get_history_summary("s") == "Summary: asked about the NDA term."

    asyncio.run(go())


def test_a_failing_summary_never_breaks_the_turn():
    class BrokenLLM:
        async def chat_completion(self, **kwargs):
            raise RuntimeError("llm down")

    async def go():
        redis = make_client()
        for i in range(6):
            await history_summary.persist_turn(redis, BrokenLLM(), "s", f"q{i}", f"a{i}")
        await settle()
        assert len(await redis.get_history("s")) == 10 and await redis.get_history_summary("s") == ""

    asyncio.run(go())
