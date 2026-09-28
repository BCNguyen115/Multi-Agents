import asyncio
from src.shared.memory_manager import MemoryManager


def test():
    mm = MemoryManager()
    res = mm.add_memory("Tôi tên là Bùi Cao Nguyên, làm việc tại Hà Nội", user_id="test_user_123")
    print("Mem0 add result:", res)
    memories = mm.get_memories("test_user_123")
    print("Mem0 retrieved memories:", memories)


if __name__ == "__main__":
    test()
