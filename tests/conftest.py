"""Hermetic defaults for the whole suite.

No test talks to a real LLM provider, but the OpenAI/LiteLLM clients refuse to be built without a key. A developer's .env
supplies one; a CI runner has none. Environment variables win over .env, and ``setdefault`` leaves a real key alone.
"""
import os

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-used")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
os.environ.setdefault("KNOWLEDGE_PARSE_ISOLATED", "false")  # a worker process per upload is exercised in tests/test_upload_safety.py
os.environ.setdefault("AUTH_SCRYPT_LOG2_N", "12")  # tests hash dozens of passwords: the production cost (2**16) is exercised in tests/test_password_hash.py
