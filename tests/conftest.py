"""Hermetic defaults for the whole suite.

No test talks to a real LLM provider, but the OpenAI/LiteLLM clients refuse to be built without a key. A developer's .env
supplies one; a CI runner has none. Environment variables win over .env, and ``setdefault`` leaves a real key alone.
"""
import os

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-used")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
