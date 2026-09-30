import asyncio
from src.shared.memory_manager import MemoryManager


async def test_async():
    mm = MemoryManager()
    res = await mm.add_memory(user_id="async_user_999", text="User prefers dark mode and bar charts")
    print("Async add res:", res)
    mems = await mm.get_relevant_memories(user_id="async_user_999", query="What charts does user prefer?")
    print("Async get relevant mems:", mems)


if __name__ == "__main__":
    asyncio.run(test_async())
