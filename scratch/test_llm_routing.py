import asyncio
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.shared.llm_client import LLMClient
from src.config import settings

async def test():
    client = LLMClient()
    response = await client.acompletion(
        model=settings.FAST_LLM_MODEL,
        messages=[{"role": "user", "content": "Ping"}]
    )
    print("Response success:", response)
    if hasattr(response, "choices"):
        print("Model used:", getattr(response, "model", "unknown"))
        print("Content:", response.choices[0].message.content)

if __name__ == "__main__":
    asyncio.run(test())
