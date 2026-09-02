"""FastAPI Gateway — the HTTP entry point for the Multi-Agent system.

Provides the ``POST /api/chat`` endpoint that:
  1. Accepts ``{ "query": "...", "session_id": "..." }``.
  2. Loads conversation history from Redis (max 5 turns).
  3. Delegates to the Orchestrator.
  4. Stores the new exchange in Redis.
  5. Returns the agent's response.

Lifecycle events (``startup`` / ``shutdown``) handle connecting and
disconnecting all shared resources (PostgreSQL, Redis).

Usage:
    uvicorn src.gateway.main:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import logging
import os
import uuid
import warnings
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

from src.shared.telemetry import disable_telemetry
disable_telemetry()

# Suppress harmless Qdrant local payload index & HF Hub warnings
warnings.filterwarnings(
    "ignore",
    message=".*Payload indexes have no effect in the local Qdrant.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=".*sending unauthenticated requests to the HF Hub.*",
)
warnings.filterwarnings(
    "ignore",
    message=".*unauthenticated requests to the HF Hub.*",
)

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.agents.data_agent.agent import DataAnalystAgent
from src.agents.db_agent.agent import DatabaseAgent
from src.agents.integration_agent.agent import IntegrationAgent
from src.agents.rag_agent.agent import RAGAgent
from src.agents.rag_agent.knowledge import KnowledgeStore
from src.agents.search_agent.agent import SearchAgent
from src.config import settings
from src.orchestrator.core import Orchestrator
from src.registry.manager import AgentRegistry
from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger
from src.shared.mcp_client import MCPClient
from src.shared.memory_manager import MemoryManager
from src.shared.postgres_client import PostgresClient
from src.shared.redis_client import RedisClient
from src.shared.csv_sanitizer import clean_csv_content
from src.shared.security import inspect_prompt_safety

logger: logging.Logger = get_logger(__name__, level=settings.LOG_LEVEL)

# ---------------------------------------------------------------------------
# Shared resource singletons (initialised on startup)
# ---------------------------------------------------------------------------
pg_client: PostgresClient = PostgresClient(dsn=settings.POSTGRES_URL)
redis_client: RedisClient = RedisClient(url=settings.REDIS_URL)

# These will be assigned during the ``lifespan`` startup phase.
orchestrator: Orchestrator | None = None
llm_client: LLMClient | None = None


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SourceItem(BaseModel):
    """Citation source item schema.

    Attributes:
        file: Source document filename.
        section: Section title.
        category: Document category (e.g. nda, msa, sow).
    """

    file: str
    section: str
    category: str | None = None


class ChatRequest(BaseModel):
    """Payload schema for ``POST /api/chat``.

    Attributes:
        query: The user's natural-language question.
        session_id: A unique session identifier for conversation tracking.
    """

    query: str = Field(..., min_length=1, description="User query text")
    session_id: str = Field(
        ..., min_length=1, description="Session correlation ID"
    )
    agent_mode: str | None = Field(
        default=None, description="Optional forced agent mode (e.g. search_agent)"
    )


class ChatResponse(BaseModel):
    """Response schema for ``POST /api/chat``.

    Attributes:
        session_id: Echo of the request session ID.
        response: The agent's textual response.
        sources: List of document citations used to generate the answer.
        pev_trace: LangGraph PEV trace metadata.
    """

    session_id: str
    response: str
    sources: list[SourceItem] = Field(default_factory=list)
    pev_trace: dict[str, Any] | None = None


class AnalyzeResponse(BaseModel):
    """Response schema for ``POST /api/analyze``.

    Attributes:
        session_id: Echo of the request session ID.
        explanation: Natural-language explanation of the analysis.
        generated_code: Executable Python code (legacy/fallback).
        dashboard_spec: Standardized JSON Spec for dynamic dashboard rendering.
        pev_trace: LangGraph PEV trace metadata.
    """

    session_id: str
    explanation: str
    generated_code: str = ""
    dashboard_spec: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    pev_trace: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Application lifespan (startup / shutdown)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle: connect resources on startup,
    disconnect on shutdown.

    Args:
        app: The FastAPI application instance.

    Yields:
        None
    """
    global orchestrator, llm_client  # noqa: PLW0603

    # ---- STARTUP ----
    if getattr(settings, "HF_TOKEN", None):
        os.environ["HF_TOKEN"] = settings.HF_TOKEN

    logger.info("Starting up — connecting to databases…", extra={"session_id": "SYSTEM"})

    try:
        await pg_client.connect()
    except Exception as exc:
        logger.error(
            "PostgreSQL connection failed during startup: %s", exc,
            extra={"session_id": "SYSTEM"},
        )
        raise

    try:
        await redis_client.connect()
    except Exception as exc:
        logger.error(
            "Redis connection failed during startup: %s", exc,
            extra={"session_id": "SYSTEM"},
        )
        await pg_client.disconnect()
        raise

    # Build unified LLM Client (LiteLLM + Langfuse)
    llm_client = LLMClient(settings=settings)

    # Build MCP Client (Layer 3 Tools)
    mcp_client: MCPClient = MCPClient(pg_client=pg_client)

    # Build Long-term Memory Manager (Layer 2 Memory) & Pre-load Models
    memory_manager: MemoryManager = MemoryManager(settings=settings)
    try:
        await memory_manager.warmup()
    except Exception as exc:
        logger.warning("MemoryManager warmup notice (non-fatal): %s", exc, extra={"session_id": "SYSTEM"})

    # Build KnowledgeStore & RAGAgent
    knowledge_store: KnowledgeStore = KnowledgeStore(
        pg=pg_client, llm_client=llm_client
    )
    await knowledge_store.ensure_table()

    rag_agent: RAGAgent = RAGAgent(
        knowledge_store=knowledge_store,
        llm_client=llm_client,
        model=settings.OPENROUTER_MODEL,
    )

    # Build DataAnalystAgent (with Tool Delegation via MCP & Redis Session State)
    data_agent: DataAnalystAgent = DataAnalystAgent(
        llm_client=llm_client,
        model=settings.OPENROUTER_MODEL,
        mcp_client=mcp_client,
        redis_client=redis_client,
    )

    # Build DatabaseAgent
    db_agent: DatabaseAgent = DatabaseAgent(
        mcp_client=mcp_client,
        llm_client=llm_client,
        model=settings.OPENROUTER_MODEL,
    )

    # Build IntegrationAgent
    integration_agent: IntegrationAgent = IntegrationAgent(
        mcp_client=mcp_client,
        llm_client=llm_client,
        model=settings.OPENROUTER_MODEL,
    )

    # Build SearchAgent (Tavily + Crawl4AI)
    search_agent: SearchAgent = SearchAgent(
        llm_client=llm_client,
        settings=settings,
        model=settings.OPENROUTER_MODEL,
    )

    # Build Registry & register agents
    registry: AgentRegistry = AgentRegistry()
    registry.register(rag_agent)
    registry.register(data_agent)
    registry.register(db_agent)
    registry.register(integration_agent)
    registry.register(search_agent)

    # Build Orchestrator with LangGraph, MemoryManager & LLMClient
    orchestrator = Orchestrator(
        registry=registry,
        settings=settings,
        llm_client=llm_client,
        memory_manager=memory_manager,
    )

    logger.info("Startup complete — system ready (4-Layer Framework active)", extra={"session_id": "SYSTEM"})

    yield  # ← Application runs here

    # ---- SHUTDOWN ----
    logger.info("Shutting down — disconnecting resources…", extra={"session_id": "SYSTEM"})
    await mcp_client.close()
    llm_client.shutdown()
    await pg_client.disconnect()
    await redis_client.disconnect()
    logger.info("Shutdown complete", extra={"session_id": "SYSTEM"})


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app: FastAPI = FastAPI(
    title="Multi-Agent Enterprise MVP",
    description="Gateway API for the Multi-Agent orchestration system.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post(
    "/api/chat/stream",
    summary="Send a chat message with real-time SSE PEV Loop event streaming",
)
async def chat_stream(request: ChatRequest) -> EventSourceResponse:
    """Stream PEV Loop events (plan, executing, verifying, final_response) via SSE."""
    session_id: str = request.session_id
    query: str = request.query

    # Dedicated Gateway Guardrail — Prompt Injection Scan
    is_safe, violation_label = inspect_prompt_safety(query)
    if not is_safe:
        logger.warning(
            "Security Violation Blocked in /api/chat/stream: %s",
            violation_label,
            extra={"session_id": session_id},
        )
        raise HTTPException(
            status_code=400,
            detail=f"Cảnh báo bảo mật: Phát hiện dấu hiệu Prompt Injection ({violation_label}). Yêu cầu bị từ chối.",
        )

    logger.info(
        "Incoming /api/chat/stream request (query len=%d)",
        len(query),
        extra={"session_id": session_id},
    )

    if orchestrator is None:
        logger.error("Orchestrator not initialised", extra={"session_id": session_id})
        raise HTTPException(
            status_code=503,
            detail="Service is starting up. Please try again shortly.",
        )

    async def safe_stream_wrapper():
        try:
            async for event in orchestrator.handle_stream_request(
                query=query,
                session_id=session_id,
                agent_mode=request.agent_mode,
            ):
                yield event
        except Exception as exc:
            logger.error(
                "SSE Stream Error caught: %s",
                exc,
                extra={"session_id": session_id},
            )
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "type": "error",
                        "message": f"Xảy ra lỗi trong quá trình xử lý suy luận: {str(exc)}",
                    },
                    ensure_ascii=False,
                ),
            }
        finally:
            target_llm_client = llm_client or (orchestrator.llm_client if orchestrator and hasattr(orchestrator, "llm_client") else None)
            if target_llm_client:
                await target_llm_client.flush_async()

    return EventSourceResponse(safe_stream_wrapper())


@app.post(
    "/api/chat",
    response_model=ChatResponse,
    summary="Send a chat message to the Multi-Agent system",
)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle an incoming chat request.

    Flow:
      1. Retrieve the last N turns of conversation history from Redis.
      2. Forward the query (with context) to the Orchestrator.
      3. Append both the user query and assistant response to Redis history.
      4. Return the response.

    Args:
        request: The incoming ``ChatRequest`` payload.

    Returns:
        ChatResponse: The agent's response wrapped in the standard schema.

    Raises:
        HTTPException: 503 if the Orchestrator is unavailable.
    """
    session_id: str = request.session_id
    query: str = request.query

    # Dedicated Gateway Guardrail — Prompt Injection Scan
    is_safe, violation_label = inspect_prompt_safety(query)
    if not is_safe:
        logger.warning(
            "Security Violation Blocked in /api/chat: %s",
            violation_label,
            extra={"session_id": session_id},
        )
        raise HTTPException(
            status_code=400,
            detail=f"Cảnh báo bảo mật: Phát hiện dấu hiệu Prompt Injection ({violation_label}). Yêu cầu bị từ chối.",
        )

    request_id: str = str(uuid.uuid4())
    logger.info(
        "Incoming /api/chat request (request_id=%s, query len=%d)",
        request_id,
        len(query),
        extra={"session_id": session_id},
    )

    if orchestrator is None:
        logger.error(
            "Orchestrator not initialised",
            extra={"session_id": session_id},
        )
        raise HTTPException(
            status_code=503,
            detail="Service is starting up. Please try again shortly.",
        )

    try:
        # --- 1. Load conversation history from Redis ---
        try:
            history: list[dict[str, str]] = await redis_client.get_history(
                session_id=session_id
            )
            logger.debug(
                "Loaded %d history messages",
                len(history),
                extra={"session_id": session_id},
            )
        except Exception as exc:
            logger.warning(
                "Could not load history from Redis (continuing without): %s",
                exc,
                extra={"session_id": session_id},
            )
            history = []

        # --- 2. Delegate to Orchestrator ---
        try:
            raw_response: str = await orchestrator.handle_request(
                query=query,
                session_id=session_id,
                agent_mode=request.agent_mode,
            )
        except Exception as exc:
            logger.error(
                "Orchestrator raised an unexpected error: %s",
                exc,
                extra={"session_id": session_id},
            )
            raw_response = "Đã xảy ra lỗi nội bộ. Vui lòng thử lại sau."

        # Parse response (JSON from RAGAgent or plain text fallback)
        final_answer: str = raw_response
        sources_list: list[dict[str, Any]] = []
        pev_trace: dict[str, Any] | None = None

        try:
            parsed: dict[str, Any] = json.loads(raw_response)
            if isinstance(parsed, dict):
                if "answer" in parsed:
                    final_answer = parsed["answer"]
                    sources_list = parsed.get("sources", [])
                elif "explanation" in parsed:
                    final_answer = parsed["explanation"]
                else:
                    final_answer = parsed.get("response", raw_response)
                pev_trace = parsed.get("pev_trace")
        except (json.JSONDecodeError, TypeError):
            pass

        # --- 3. Save to conversation history (max 5 turns) ---
        try:
            await redis_client.append_to_history(
                session_id=session_id,
                role="user",
                content=query,
                max_turns=5,
            )
            await redis_client.append_to_history(
                session_id=session_id,
                role="assistant",
                content=final_answer,
                max_turns=5,
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist history to Redis (non-critical): %s",
                exc,
                extra={"session_id": session_id},
            )

        logger.info(
            "Returning response (len=%d, sources=%d)",
            len(final_answer),
            len(sources_list),
            extra={"session_id": session_id},
        )

        return ChatResponse(
            session_id=session_id,
            response=final_answer,
            sources=[SourceItem(**src) for src in sources_list],
            pev_trace=pev_trace,
        )
    finally:
        target_llm_client = llm_client or (orchestrator.llm_client if orchestrator and hasattr(orchestrator, "llm_client") else None)
        if target_llm_client:
            await target_llm_client.flush_async()


@app.post(
    "/api/analyze",
    response_model=AnalyzeResponse,
    summary="Analyze uploaded CSV data and generate executive dashboard spec",
)
async def analyze_csv(
    file: Optional[UploadFile] = File(None, description="Optional CSV file to upload and analyze"),
    query: str = Form("Hãy phân tích toàn bộ dữ liệu file này", description="Analysis prompt"),
    session_id: str = Form(default_factory=lambda: str(uuid.uuid4()), description="Session correlation ID"),
) -> AnalyzeResponse:
    """Upload a CSV file or analyze previously uploaded CSV in current session."""
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="Service is starting up. Please try again shortly.",
        )

    # Dedicated Gateway Guardrail — Prompt Injection Scan
    is_safe, violation_label = inspect_prompt_safety(query)
    if not is_safe:
        logger.warning(
            "Security Violation Blocked in /api/analyze: %s",
            violation_label,
            extra={"session_id": session_id},
        )
        raise HTTPException(
            status_code=400,
            detail=f"Cảnh báo bảo mật: Phát hiện dấu hiệu Prompt Injection ({violation_label}). Yêu cầu bị từ chối.",
        )

    request_id: str = str(uuid.uuid4())
    logger.info(
        "Incoming /api/analyze request (request_id=%s, has_file=%s, query_len=%d)",
        request_id,
        file is not None,
        len(query),
        extra={"session_id": session_id},
    )

    try:
        csv_content: Optional[str] = None
        filename: str = "uploaded.csv"

        # --- 1. Read CSV content if file provided ---
        if file is not None:
            raw_bytes: bytes = await file.read()
            filename = file.filename or "uploaded.csv"

            # Sanitize CSV: auto-detect encoding, clean headers, remove empty rows
            try:
                csv_content = clean_csv_content(raw_bytes)
            except Exception as sanitize_exc:
                logger.warning(
                    "CSV sanitization failed, falling back to raw decode: %s",
                    sanitize_exc,
                    extra={"session_id": session_id},
                )
                try:
                    csv_content = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    csv_content = raw_bytes.decode("latin-1", errors="replace")

            # Cache file in Redis for session context retention
            if redis_client is not None and csv_content:
                await redis_client.set_active_file(
                    session_id=session_id,
                    filename=filename,
                    csv_content=csv_content,
                )
        else:
            # Attempt recovery from Redis
            if redis_client is not None:
                active = await redis_client.get_active_file(session_id=session_id)
                if active:
                    csv_content = active.get("csv_content")
                    filename = active.get("filename", "active_session.csv")
                    logger.info(
                        "Recovered CSV file '%s' from Redis session state",
                        filename,
                        extra={"session_id": session_id},
                    )

        # --- 2. Delegate to Orchestrator with CSV ---
        raw_response: str = await orchestrator.handle_request(
            query=query,
            session_id=session_id,
            csv_content=csv_content,
            csv_filename=filename if csv_content else None,
        )

        # --- 3. Parse agent response safely ---
        explanation: str = ""
        generated_code: str = ""
        dashboard_spec: dict[str, Any] | None = None
        metadata: dict[str, Any] | None = None
        pev_trace: dict[str, Any] | None = None

        try:
            parsed: dict[str, Any] = json.loads(raw_response)
            if isinstance(parsed, dict):
                dashboard_spec = parsed.get("dashboard_spec")
                metadata = parsed.get("metadata")
                pev_trace = parsed.get("pev_trace")
                generated_code = parsed.get("generated_code", "")

                # Safely extract text explanation (do NOT default to full raw_response JSON string)
                explanation = (
                    parsed.get("explanation")
                    or parsed.get("summaryText")
                    or parsed.get("content")
                    or ""
                )
                if not explanation and dashboard_spec:
                    explanation = dashboard_spec.get("summaryText", "Đã phân tích xong dữ liệu.")
            else:
                explanation = str(raw_response)
        except (json.JSONDecodeError, TypeError):
            explanation = raw_response

        if not explanation:
            explanation = "Đã phân tích xong dữ liệu." if dashboard_spec else raw_response[:1000]

        # Truncate explanation if excessively long (max 15,000 chars)
        if len(explanation) > 15000:
            explanation = (
                explanation[:15000]
                + "\n\n[...Nội dung giải thích quá dài đã được tự động cắt ngắn để đảm bảo hiệu năng...]"
            )

        logger.info(
            "Returning analyze response (explanation_len=%d, has_spec=%s, has_trace=%s)",
            len(explanation),
            dashboard_spec is not None,
            pev_trace is not None,
            extra={"session_id": session_id},
        )

        return AnalyzeResponse(
            session_id=session_id,
            explanation=explanation,
            generated_code=generated_code,
            dashboard_spec=dashboard_spec,
            metadata=metadata,
            pev_trace=pev_trace,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("CSV Analysis Failed", extra={"session_id": session_id})
        raise HTTPException(
            status_code=400,
            detail=f"Phân tích dữ liệu CSV thất bại (lỗi format hoặc không hợp lệ): {str(e)}",
        )
    finally:
        target_llm_client = llm_client or (orchestrator.llm_client if orchestrator and hasattr(orchestrator, "llm_client") else None)
        if target_llm_client:
            await target_llm_client.flush_async()


@app.get("/health", summary="Health check")
async def health_check() -> dict[str, str]:
    """Simple health-check endpoint.

    Returns:
        dict[str, str]: ``{"status": "ok"}``.
    """
    return {"status": "ok"}

