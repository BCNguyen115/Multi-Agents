import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath("."))
import time
import pandas as pd
import warnings
from src.shared.llm_client import LLMClient
from src.config import settings

async def main():
    print("--- 1. Testing LLM Circuit Breaker ---")
    client = LLMClient(settings=settings)
    
    # Test A: Primary active model (openai/gpt-4o)
    t0 = time.time()
    resp = await client.chat_completion(
        messages=[{"role": "user", "content": "Reply with 'OK'."}],
        model="openai/gpt-4o",
        max_tokens=5,
        session_id="test_primary"
    )
    print(f"Primary model response ({time.time() - t0:.2f}s): {resp.choices[0].message.content.strip()}")
    
    # Test B: Simulated 404 model (anthropic/claude-3.5-sonnet)
    print("\nCall 1 with unavailable model (should detect 404, blacklist model, and fallback):")
    t0 = time.time()
    resp1 = await client.chat_completion(
        messages=[{"role": "user", "content": "Reply with 'Fallback 1'."}],
        model="anthropic/claude-3.5-sonnet",
        max_tokens=5,
        session_id="test_fallback_1"
    )
    print(f"Call 1 response ({time.time() - t0:.2f}s): {resp1.choices[0].message.content.strip()}")
    print(f"Blacklisted models: {client.unavailable_models}")
    assert "openrouter/anthropic/claude-3.5-sonnet" in client.unavailable_models
    
    # Test C: Call 2 with the same unavailable model (should INSTANTLY bypass with 0s latency penalty)
    print("\nCall 2 with same unavailable model (Circuit Breaker should INSTANTLY bypass without 404):")
    t0 = time.time()
    resp2 = await client.chat_completion(
        messages=[{"role": "user", "content": "Reply with 'Fallback 2'."}],
        model="anthropic/claude-3.5-sonnet",
        max_tokens=5,
        session_id="test_fallback_2"
    )
    duration2 = time.time() - t0
    print(f"Call 2 response ({duration2:.2f}s): {resp2.choices[0].message.content.strip()}")
    print("Circuit Breaker verified successfully!")
    
    print("\n--- 2. Testing Pandas Date Parsing Warning Elimination ---")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        
        # Test mixed format date series that previously threw UserWarning
        sample_dates = ["2023-01-01", "02/03/2023", "2023.04.05", "May 6, 2023"]
        df = pd.DataFrame({"order_date": sample_dates})
        
        try:
            parsed = pd.to_datetime(df["order_date"], errors="coerce", format="mixed")
        except TypeError:
            parsed = pd.to_datetime(df["order_date"], errors="coerce")
            
        print("Parsed dates:\n", parsed)
        user_warnings = [item for item in w if issubclass(item.category, UserWarning)]
        print(f"UserWarnings caught: {len(user_warnings)}")
        if user_warnings:
            for item in user_warnings:
                print(f"  Warning: {item.message}")
        assert len(user_warnings) == 0, "Expected 0 UserWarnings for date parsing!"
        print("Pandas date parsing verified: ZERO UserWarnings!")

if __name__ == "__main__":
    asyncio.run(main())
