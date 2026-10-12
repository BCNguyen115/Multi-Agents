"""Hermetic defaults for the whole suite.

No test talks to a real LLM provider, but the OpenAI/LiteLLM clients refuse to be built without a key. A developer's .env
supplies one; a CI runner has none. Environment variables win over .env, so a real key already in the environment is left
alone. An EMPTY one is not a key either: a runner with an empty variable or secret (``OPENROUTER_API_KEY: ${{ secrets.X }}``
that is not defined) exports "", which ``os.environ.setdefault`` keeps, and LLMClient then fails with "Missing credentials".
"""
import os


def _default_env(name: str, value: str) -> None:
    if not os.environ.get(name):  # unset OR empty
        os.environ[name] = value


_default_env("OPENROUTER_API_KEY", "test-key-not-used")
_default_env("OPENAI_API_KEY", "test-key-not-used")


import pytest  # noqa: E402 - after the environment defaults above, which must be set before anything imports src.config


@pytest.fixture(autouse=True)
def _keep_hermetic_api_keys():
    """LLMClient and MemoryManager write the key they are given into os.environ. A test that builds one with an empty key
    would leave "" behind, and every later test that builds a client would fail with "Missing credentials": reset before each."""
    _default_env("OPENROUTER_API_KEY", "test-key-not-used")
    _default_env("OPENAI_API_KEY", "test-key-not-used")
    yield
os.environ.setdefault("KNOWLEDGE_PARSE_ISOLATED", "false")  # a worker process per upload is exercised in tests/test_upload_safety.py
os.environ.setdefault("AUTH_SCRYPT_LOG2_N", "12")  # tests hash dozens of passwords: the production cost (2**16) is exercised in tests/test_password_hash.py
