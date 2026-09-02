"""Application configuration module.

Loads all environment variables using pydantic-settings.
Provides a centralized, type-safe configuration object for the entire
Multi-Agent MVP application.

Usage:
    from src.config import settings
    api_key = settings.OPENROUTER_API_KEY
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from environment variables and .env file.

    Attributes:
        OPENROUTER_API_KEY: API key for OpenRouter LLM service.
        OPENROUTER_BASE_URL: Base URL for the OpenRouter API endpoint.
        OPENROUTER_MODEL: The LLM model identifier to use (default: gpt-4o-mini).
        POSTGRES_URL: Connection string for PostgreSQL with pgvector.
        REDIS_URL: Connection string for Redis cache/state store.
        LOG_LEVEL: Logging verbosity level (default: INFO).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- OpenRouter LLM ---
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "openai/gpt-4o-mini"

    # --- Model Tiering (Latency Optimization) ---
    FAST_LLM_MODEL: str = "openai/gpt-4o-mini"     # Low-latency: Planner, Verifier
    HEAVY_LLM_MODEL: str = "openai/gpt-4o-mini"    # High-quality: Data Storyteller, RAG Synthesis

    # --- PostgreSQL + Pgvector ---
    POSTGRES_URL: str = "postgresql://user:password@localhost:5432/multi_agent_db"

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_AUTH: str = ""

    # --- Langfuse Observability ---
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "http://localhost:3000"

    # --- Tavily Search API ---
    TAVILY_API_KEY: str = ""

    # --- TEI Reranker Service ---
    RERANKER_ENDPOINT: str = "http://tei-reranker:80/rerank"
    RERANK_TOP_K: int = 5
    HYBRID_CANDIDATES_K: int = 10
    MAX_RERANK_TEXT_LENGTH: int = 500
    RERANKER_TIMEOUT: float = 30.0

    # --- Internal Security (Inter-service JWT) ---
    INTERNAL_JWT_SECRET: str = ""

    # --- HuggingFace Hub ---
    HF_TOKEN: Optional[str] = None

    # --- Application ---
    LOG_LEVEL: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings (singleton pattern).

    Returns:
        Settings: The application configuration object.
    """
    return Settings()


# Convenience alias — import directly as `from src.config import settings`
settings: Settings = get_settings()
