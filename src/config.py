"""Application configuration module.

Loads all environment variables using pydantic-settings.
Provides a centralized, type-safe configuration object for the entire
Multi-Agent MVP application.

Usage:
    from src.config import settings
    api_key = settings.OPENROUTER_API_KEY
"""

from functools import lru_cache
from typing import Any, Optional

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
    OPENROUTER_MODEL: str = "openai/gpt-4o"

    # --- Model Tiering (Latency Optimization) ---
    FAST_LLM_MODEL: str = "openai/gpt-4o-mini"             # Low-latency: Planner, Title Gen, Verifier
    HEAVY_LLM_MODEL: str = "openai/gpt-4o"                 # High-quality: Data Storyteller, RAG Synthesis
    MEM0_LLM_MODEL: str = "openai/gpt-4o-mini"              # Entity & Fact Extraction for Long-term Memory

    # --- PostgreSQL + Pgvector ---
    POSTGRES_URL: str = "postgresql://user:password@localhost:5432/multi_agent_db"

    # --- Integration Agent: which hosts REST calls may reach (src/shared/mcp_client.py) ---
    # Defaults keep the demo targets working; in production list only your own APIs. Hosts ending in `.internal` are also allowed.
    INTEGRATION_ALLOWED_HOSTS: list[str] = [
        "localhost", "127.0.0.1", "[::1]", "api.enterprise.internal", "jsonplaceholder.typicode.com", "httpbin.org", "example.com",
    ]

    # --- Database Agent: read-only role (see src/shared/db_roles.py) ---
    DB_AGENT_PASSWORD: str = ""              # set (>= 16 chars) to run the db_agent's SQL as a read-only role instead of the application's account
    DB_AGENT_ROLE: str = "agent_readonly"
    DB_AGENT_TABLES: list[str] = ["knowledge_documents"]  # tables (schema public) the db_agent may SELECT from; nothing else is reachable

    # --- Agent long-term memory (mem0) ---
    MEM0_VECTOR_STORE: str = "memory"        # memory = in-process Qdrant (lost on restart; tests/dev) | pgvector = the PostgreSQL above (persistent)
    MEM0_PG_COLLECTION: str = "mem0_memories" # table name used by mem0 in PostgreSQL (mem0 adds a companion `<name>_entities` collection)

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
    LANGFUSE_HOST: str = "http://localhost:3005"  # Compose publishes langfuse-web here; inside the network it is http://langfuse-web:3000

    # --- Tavily Search API ---
    TAVILY_API_KEY: str = ""

    # --- TEI Reranker Service ---
    RERANKER_ENDPOINT: str = "http://tei-reranker:80/rerank"
    RERANK_TOP_K: int = 5
    HYBRID_CANDIDATES_K: int = 20       # fused (vector + keyword) candidates kept
    RERANK_POOL_K: int = 10             # how many of them the cross-encoder scores (cost grows with pool x text length)
    MAX_RERANK_TEXT_LENGTH: int = 1000  # eval on the real corpus (CPU TEI, 10 docs): 500 chars MRR .53 in 2.4s, 1000 chars MRR .58 in 4.2s, no rerank MRR .41
    RERANKER_TIMEOUT: float = 8.0       # TOTAL time budget for one rerank (all endpoints, DNS included); median at 1000 chars is 4.2s

    # --- RAG retrieval / answering ---
    RAG_QUERY_MODE: str = "both"        # raw | hyde | both: which query embeddings feed the vector search
    RAG_MIN_VECTOR_SCORE: float = 0.30  # best cosine similarity below this = "nothing relevant"; eval: out-of-domain questions peak at 0.29, answerable ones start at 0.36 (a leaked out-of-domain question is still refused by the LLM)
    RAG_RRF_K: int = 60                 # reciprocal-rank-fusion constant
    RAG_HISTORY_MESSAGES: int = 4       # last messages used to turn a follow-up into a standalone question
    RAG_TENANT_IDS: Optional[list[str]] = None  # ponytail: hook only, restrict chunks to these tenants (None = all) until the gateway has an identity

    # Extra endpoints probed when the primary one is unreachable (container vs. local dev)
    RERANKER_FALLBACK_ENDPOINTS: list[str] = ["http://localhost:8080/rerank"]

    # --- Data agent limits ---
    DATA_MAX_FILE_MB: int = 25          # upload size cap
    DATA_MAX_ROWS: int = 100_000        # larger tables are randomly sampled (disclosed in the dashboard)
    DATA_TABLE_ROWS: int = 5_000        # rows shipped to the browser data grid / client-side cross-filter
    # Where LLM-written analysis code runs. Empty = a child process of the API (fine for development). With a URL it runs in
    # the network-less sandbox container (docker-compose service python-sandbox) and fails closed when that is unreachable.
    SANDBOX_URL: str = ""
    SANDBOX_SECRET: str = ""            # shared HMAC secret between the API and the sandbox container (>= 16 characters)

    # --- Human-in-the-Loop / Row-Level Security ---
    # ponytail: single static tenant until the gateway carries an authenticated identity
    RLS_TENANT_ID: str = "tenant_enterprise"
    RLS_DEPARTMENT_ID: str = "dept_general"
    HITL_APPROVAL_TTL_SECONDS: int = 900

    # --- Gateway authentication (see src/shared/auth.py) ---
    AUTH_MODE: str = "off"              # off = anonymous single user (local dev) | jwt = every /api call needs a Bearer token
    AUTH_JWT_SECRET: str = ""           # HS256 shared secret (>= 32 random chars) ...
    AUTH_JWKS_URL: str = ""             # ... or an identity provider's JWKS endpoint (RS256/ES256); wins when set
    AUTH_JWT_AUDIENCE: str = ""         # verified only when set
    AUTH_JWT_ISSUER: str = ""           # verified only when set
    AUTH_TENANT_CLAIM: str = "tenant_id"
    AUTH_DEPARTMENT_CLAIM: str = "department_id"
    AUTH_ROLES_CLAIM: str = "roles"
    # Built-in login screen (jwt mode with AUTH_JWT_SECRET): users that may sign in, as JSON in .env, e.g.
    #   AUTH_USERS=[{"username":"alice","password_hash":"scrypt$...","roles":["admin"],"tenant_id":"acme","department_id":"legal"}]
    # Make the hash with `python -m scripts.make_user`. With an identity provider (AUTH_JWKS_URL) leave this empty.
    AUTH_USERS: list[dict[str, Any]] = []
    AUTH_TOKEN_TTL_MINUTES: int = 480   # lifetime of a token issued by /api/auth/login
    # Self-service sign-up (POST /api/auth/register): OFF by default, an internal system normally gets its accounts from an
    # administrator. New accounts get NO roles (no approving, no knowledge upload) and the default tenant/department below.
    AUTH_ALLOW_REGISTRATION: bool = False
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 10     # sign-in attempts per IP per minute (brute force); 0 = unlimited
    RATE_LIMIT_REGISTER_PER_MINUTE: int = 5   # sign-up attempts per IP per minute; 0 = unlimited
    RATE_LIMIT_PASSWORD_PER_MINUTE: int = 5   # password change / reset attempts per IP (reset) or user (change) per minute; 0 = unlimited
    RATE_LIMIT_CHAT_PER_MINUTE: int = 30      # chat / stream / title calls per user (or IP) per minute; 0 = unlimited
    RATE_LIMIT_ANALYZE_PER_MINUTE: int = 10   # uploads / analyses per user (or IP) per minute; 0 = unlimited
    HITL_APPROVER_ROLES: list[str] = ["approver", "admin"]  # roles allowed to approve a sensitive action (authenticated mode)

    AUTO_MIGRATE: bool = True           # apply pending Alembic revisions when the gateway starts (a failure stops the start)

    # --- Knowledge base upload from the chat (POST /api/knowledge/upload) ---
    KNOWLEDGE_UPLOAD_ROLES: list[str] = ["admin"]  # roles allowed to add/replace documents (authenticated mode; anonymous dev may)
    KNOWLEDGE_MAX_FILE_MB: int = 25
    KNOWLEDGE_MAX_CHUNKS: int = 2000    # one document may not produce more chunks than this (embedding cost)
    KNOWLEDGE_DIR: str = "dataset"      # a copy of each upload is kept in <KNOWLEDGE_DIR>/<category>/ so run_ingestion --prune/--reset keep it
    # OCR of scanned PDFs (needs the tesseract program; see src/ingestion/ocr.py)
    OCR_ENABLED: bool = True
    OCR_LANGS: str = "vie+eng"
    OCR_MAX_PAGES: int = 80
    OCR_DPI: int = 200
    # Contextual retrieval with an LLM: one short sentence per chunk saying where it sits in its document (src/ingestion/context.py)
    KB_LLM_CONTEXT: bool = False

    # --- Internal Security (Inter-service JWT) ---
    INTERNAL_JWT_SECRET: str = ""

    # --- HuggingFace Hub ---
    HF_TOKEN: Optional[str] = None

    # --- Application ---
    LOG_LEVEL: str = "INFO"
    # Browser origins allowed to call the gateway (set as JSON list in .env for other deployments)
    CORS_ALLOW_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings (singleton pattern).

    Returns:
        Settings: The application configuration object.
    """
    return Settings()


# Convenience alias — import directly as `from src.config import settings`
settings: Settings = get_settings()
