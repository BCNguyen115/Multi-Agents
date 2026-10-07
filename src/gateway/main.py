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

import asyncio
import json
import logging
import os
import uuid
import warnings
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Literal, Optional

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

import openai
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, Path
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.agents.data_agent.agent import DataAnalystAgent
from src.agents.data_agent.i18n import tr
from src.agents.db_agent.agent import DatabaseAgent
from src.agents.integration_agent.agent import IntegrationAgent
from src.agents.rag_agent.agent import RAGAgent
from src.agents.rag_agent.knowledge import KnowledgeStore
from src.agents.search_agent.agent import SearchAgent
from src.config import settings
from src.gateway.conversations import router as conversations_router
from src.gateway.feedback import router as feedback_router
from src.gateway.knowledge import describe_upload, router as knowledge_router
from src.gateway.schemas import (  # noqa: F401  (re-exported: tests and callers use them as main.<Name>)
    AnalyzeResponse,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ChatRequest,
    ChatResponse,
    FilterRequest,
    KnowledgeUploadResponse,
    LoginRequest,
    ChangePasswordRequest,
    LoginResponse,
    RegisterRequest,
    ResetPasswordRequest,
    SourceItem,
    TitleRequest,
    TitleResponse,
)
from src.ingestion.embedder import IngestionEmbedder
from src.ingestion.upload import UploadError, ingest_upload
from src.orchestrator.core import Orchestrator
from src.registry.manager import AgentRegistry
from src.shared.auth import (
    Principal,
    authenticate,
    authenticate_user,
    hash_password,
    hash_recovery_key,
    issue_login_token,
    login_enabled,
    new_recovery_key,
    registration_enabled,
    validate_auth_config,
    verify_recovery_key,
    verify_user_row,
)
from src.shared.user_store import create_user, get_user, set_password
from src.shared.db_roles import ensure_readonly_role, readonly_dsn
from src.shared.llm_client import LLMClient
from src.shared.logger import get_logger
from src.shared.mcp_client import MCPClient
from src.shared.memory_manager import MemoryManager
from src.shared.migrations import upgrade_to_head
from src.shared.postgres_client import PostgresClient
from src.shared.history_summary import persist_turn
from src.shared import audit
from src.shared.auth import needs_rehash, revoke_token, revoke_user_sessions
from src.shared.rate_limit import check_failures, clear_failures, enforce as enforce_rate_limit, record_failure
from src.shared.redis_client import RedisClient
from src.shared.csv_sanitizer import DatasetReadError, clean_csv_content
from src.shared.messages import msg, pick_lang, reset_lang, set_lang
from src.shared.security import (
    generate_canary_token,
    inspect_prompt_safety,
    inspect_response_for_canary_leak,
    unwrap_user_input,
    wrap_user_input,
)

logger: logging.Logger = get_logger(__name__, level=settings.LOG_LEVEL)

# ---------------------------------------------------------------------------
# Shared resource singletons (initialised on startup)
# ---------------------------------------------------------------------------
pg_client: PostgresClient = PostgresClient(dsn=settings.POSTGRES_URL)
redis_client: RedisClient = RedisClient(url=settings.REDIS_URL)

# These will be assigned during the ``lifespan`` startup phase.
orchestrator: Orchestrator | None = None
llm_client: LLMClient | None = None
knowledge_store: KnowledgeStore | None = None        # retrieval side of the knowledge base
knowledge_embedder: IngestionEmbedder | None = None  # write side: chat uploads


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
    global orchestrator, llm_client, knowledge_store, knowledge_embedder  # noqa: PLW0603

    # ---- STARTUP ----
    if getattr(settings, "HF_TOKEN", None):
        os.environ["HF_TOKEN"] = settings.HF_TOKEN

    validate_auth_config()  # raises on an unsafe configuration: better to fail at start than to serve unprotected

    logger.info("Starting up — connecting to databases…", extra={"session_id": "SYSTEM"})

    try:
        await pg_client.connect()
        audit.configure(pg_client)
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
    db_mcp_client: MCPClient = mcp_client  # what the Database Agent runs its (LLM-written) SQL through
    if settings.DB_AGENT_PASSWORD:
        # Fail closed: if the read-only role was asked for and cannot be set up, do not quietly fall back to the admin account.
        await ensure_readonly_role(pg_client, settings.DB_AGENT_ROLE, settings.DB_AGENT_PASSWORD, settings.DB_AGENT_TABLES)
        db_pg_client = PostgresClient(dsn=readonly_dsn(settings.POSTGRES_URL, settings.DB_AGENT_ROLE, settings.DB_AGENT_PASSWORD), ensure_pgvector=False)
        await db_pg_client.connect(min_size=1, max_size=5)
        db_mcp_client = MCPClient(pg_client=db_pg_client, scoped=True)  # PostgreSQL's own RLS policies see the caller's tenant/department
    else:
        logger.warning("DB_AGENT_PASSWORD is not set: the Database Agent runs SQL with the application's own database account", extra={"session_id": "SYSTEM"})

    # Build Long-term Memory Manager (Layer 2 Memory) & Pre-load Models
    memory_manager: MemoryManager = MemoryManager(settings=settings)
    try:
        await memory_manager.warmup()
    except Exception as exc:
        logger.warning("MemoryManager warmup notice (non-fatal): %s", exc, extra={"session_id": "SYSTEM"})

    # Build KnowledgeStore & RAGAgent
    knowledge_store = KnowledgeStore(
        pg=pg_client, llm_client=llm_client
    )
    app.state.knowledge_store = knowledge_store
    knowledge_embedder = IngestionEmbedder(  # same model and code path as scripts/run_ingestion.py
        pg=pg_client, openai_client=openai.AsyncOpenAI(api_key=settings.OPENROUTER_API_KEY, base_url=settings.OPENROUTER_BASE_URL)
    )
    try:
        await knowledge_store.ensure_schema()
    except Exception as exc:  # RAG then answers with an error message; the other agents keep working
        logger.error("rag_chunks schema check failed: %s", exc, extra={"session_id": "SYSTEM"})
    if settings.AUTO_MIGRATE:
        # versioned changes after the baseline; replicas starting together are serialised by an advisory lock. A failed
        # migration stops the start: serving on a half-migrated schema would corrupt data later, not now.
        revision = await asyncio.to_thread(upgrade_to_head)
        logger.info("Database schema at revision %s", revision, extra={"session_id": "SYSTEM"})

    rag_agent: RAGAgent = RAGAgent(
        knowledge_store=knowledge_store,
        llm_client=llm_client,
        model=settings.OPENROUTER_MODEL,
        redis_client=redis_client,  # conversation history: follow-up questions are rewritten as standalone ones
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
        mcp_client=db_mcp_client,
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
        redis_client=redis_client,  # pending HITL approvals survive a restart and work across replicas
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
    **({"docs_url": None, "redoc_url": None, "openapi_url": None} if settings.APP_ENV == "production" and not settings.EXPOSE_API_DOCS else {}),
)

app.state.pg_client = pg_client  # the conversations router reads it from here
app.state.redis_client = redis_client  # `authenticate` asks it for revoked tokens
app.include_router(conversations_router)
app.include_router(knowledge_router)
app.include_router(feedback_router)


async def limit_chat(request: Request, principal: Principal = Depends(authenticate)) -> None:
    await enforce_rate_limit(redis_client, principal, request, "chat", settings.RATE_LIMIT_CHAT_PER_MINUTE)
    await enforce_rate_limit(redis_client, principal, request, "chat-day", settings.RATE_LIMIT_CHAT_PER_DAY, window=86400)


async def limit_analyze(request: Request, principal: Principal = Depends(authenticate)) -> None:
    await enforce_rate_limit(redis_client, principal, request, "analyze", settings.RATE_LIMIT_ANALYZE_PER_MINUTE)


@app.middleware("http")
async def reject_oversized_uploads(request: Request, call_next):
    """Answer 413 from the Content-Length header alone, before a huge multipart body is parsed and spooled."""
    limit_mb: int | None = {"/api/analyze": settings.DATA_MAX_FILE_MB, "/api/knowledge/upload": settings.KNOWLEDGE_MAX_FILE_MB}.get(request.url.path)
    if limit_mb is not None:
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit_mb * 1024 * 1024 * 1.1 + 65536:  # + multipart overhead
            return JSONResponse(status_code=413, content={"detail": msg("file.too_big", mb=limit_mb)})
    return await call_next(request)


@app.middleware("http")
async def ui_language(request: Request, call_next):
    """Messages the gateway writes follow the interface language the browser sends (``X-UI-Lang``, else Accept-Language)."""
    token = set_lang(pick_lang(request.headers.get("x-ui-lang") or request.headers.get("accept-language")))
    try:
        return await call_next(request)
    finally:
        reset_lang(token)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post(
    "/api/chat/stream",
    dependencies=[Depends(limit_chat)],
    summary="Send a chat message with real-time SSE PEV Loop event streaming",
)
async def chat_stream(request: ChatRequest, raw_request: Request, principal: Principal = Depends(authenticate)) -> EventSourceResponse:
    """Stream PEV Loop events (plan, executing, verifying, final_response) via SSE."""
    session_id: str = principal.session(request.session_id)
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
            detail=msg("security.injection", label=violation_label),
        )

    # Dynamic Nonce Delimiter Packaging
    wrapped_query, nonce = wrap_user_input(query)

    logger.info(
        "Incoming /api/chat/stream request (query len=%d, nonce=%s)",
        len(query),
        nonce,
        extra={"session_id": session_id},
    )

    if orchestrator is None:
        logger.error("Orchestrator not initialised", extra={"session_id": session_id})
        raise HTTPException(
            status_code=503,
            detail=msg("service.starting"),
        )

    async def remember_turn(event: dict[str, Any]) -> None:
        """Persist the finished turn (like /api/chat does) so follow-up questions have their context."""
        if event.get("event") != "final_response":
            return
        try:
            answer: str = json.loads(event["data"]).get("response", "")
            try:
                parsed = json.loads(answer)
                answer = parsed.get("answer") or parsed.get("explanation") or answer if isinstance(parsed, dict) else answer
            except (json.JSONDecodeError, TypeError):
                pass
            await persist_turn(redis_client, llm_client, session_id, query, answer)
        except Exception as exc:  # noqa: BLE001 - history is non-critical
            logger.warning("Could not persist the streamed turn: %s", exc, extra={"session_id": session_id})

    async def safe_stream_wrapper():
        try:
            async for event in orchestrator.handle_stream_request(
                query=wrapped_query,
                session_id=session_id,
                agent_mode=request.agent_mode,
                target_agent=request.target_agent,
            ):
                if await raw_request.is_disconnected():
                    logger.info(
                        "Client disconnected from SSE stream, aborting pipeline execution: session_id=%s",
                        session_id,
                        extra={"session_id": session_id},
                    )
                    break

                # Canary / Prompt Leakage Defense
                event_data = event.get("data", "")
                if event_data:
                    has_leak, canary_id = inspect_response_for_canary_leak(event_data)
                    if has_leak:
                        logger.critical(
                            "PROMPT_LEAKAGE_DETECTED in SSE stream: Canary token '%s' intercepted!",
                            canary_id,
                            extra={"session_id": session_id},
                        )
                        yield {
                            "event": "final_response",
                            "data": json.dumps({
                                "response": "Cảnh báo bảo mật: Phát hiện nguy cơ rò rỉ token bảo mật hệ thống (Canary Leak). Phản hồi bị chặn theo giao thức Zero-Trust.",
                                "target_agent": "security_guardrail",
                                "is_verified": False,
                            }, ensure_ascii=False),
                        }
                        return

                yield event
                await remember_turn(event)
                await asyncio.sleep(0.01)  # Bắt buộc: nhường quyền cho event loop flush TCP socket
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
            await asyncio.sleep(0.01)
        finally:
            target_llm_client = llm_client or (orchestrator.llm_client if orchestrator and hasattr(orchestrator, "llm_client") else None)
            if target_llm_client:
                await target_llm_client.flush_async()

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream",
        "X-Accel-Buffering": "no",  # Tắt buffer trên Nginx / Cloudflare / Proxy
    }

    return EventSourceResponse(
        safe_stream_wrapper(),
        ping=15,
        headers=headers,
    )


@app.post(
    "/api/chat/title",
    dependencies=[Depends(limit_chat)],
    response_model=TitleResponse,
    summary="Generate a concise smart conversation title from the initial user query",
)
async def generate_chat_title(request: TitleRequest, principal: Principal = Depends(authenticate)) -> TitleResponse:
    """Generate a concise 3-6 word title summarizing the user's intent using FAST_LLM_MODEL."""
    raw_query: str = request.query.strip()
    session_id: str = request.session_id or "TITLE_GEN"

    if not raw_query:
        return TitleResponse(title="Cuộc trò chuyện mới")

    fallback_title: str = raw_query[:60].strip() if len(raw_query) > 60 else raw_query

    target_llm = llm_client or (
        orchestrator.llm_client
        if orchestrator and hasattr(orchestrator, "llm_client")
        else None
    )

    if not target_llm:
        logger.warning(
            "LLM client not ready for title generation; using fallback",
            extra={"session_id": session_id},
        )
        return TitleResponse(title=fallback_title)

    system_prompt = (
        "Bạn là trợ lý đặt tên hội thoại. Hãy tạo 1 tiêu đề súc tích (từ 3 đến 6 từ) "
        "bằng đúng ngôn ngữ của câu hỏi, tóm tắt ý định chính của người dùng. "
        "Tuyệt đối KHÔNG chứa dấu ngoặc kép, KHÔNG chứa dấu ba chấm (...), KHÔNG giải thích dài dòng."
    )

    try:
        resp = await asyncio.wait_for(
            target_llm.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": raw_query},
                ],
                model=settings.FAST_LLM_MODEL,
                temperature=0.2,
                max_tokens=60,
                session_id=session_id,
            ),
            timeout=2.5,
        )

        title_text = ""
        if resp and hasattr(resp, "choices") and len(resp.choices) > 0:
            title_text = resp.choices[0].message.content or ""

        # Clean any quotes or trailing ellipses
        title_text = title_text.strip().strip('"\'`').replace("...", "").strip()
        if not title_text:
            title_text = fallback_title

        logger.info(
            "Generated smart title: '%s' for query: '%s'",
            title_text,
            raw_query[:50],
            extra={"session_id": session_id},
        )
        return TitleResponse(title=title_text)
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning(
            "Smart title via LLM unavailable (%s: %s); using the raw query as the title",
            type(exc).__name__,
            exc or "no answer within 2.5s",
            extra={"session_id": session_id},
        )
        return TitleResponse(title=fallback_title)


@app.post(
    "/api/chat",
    dependencies=[Depends(limit_chat)],
    response_model=ChatResponse,
    summary="Send a chat message to the Multi-Agent system",
)

async def chat(request: ChatRequest, principal: Principal = Depends(authenticate)) -> ChatResponse:
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
    session_id: str = principal.session(request.session_id)
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
            detail=msg("security.injection", label=violation_label),
        )

    # Dynamic Nonce Delimiter Packaging
    wrapped_query, nonce = wrap_user_input(query)

    request_id: str = str(uuid.uuid4())
    logger.info(
        "Incoming /api/chat request (request_id=%s, query len=%d, nonce=%s)",
        request_id,
        len(query),
        nonce,
        extra={"session_id": session_id},
    )

    if orchestrator is None:
        logger.error(
            "Orchestrator not initialised",
            extra={"session_id": session_id},
        )
        raise HTTPException(
            status_code=503,
            detail=msg("service.starting"),
        )

    try:
        # --- 1. Delegate to Orchestrator (agents that need the chat history, e.g. RAG, read it from Redis themselves) ---
        try:
            raw_response: str = await orchestrator.handle_request(
                query=wrapped_query,
                session_id=session_id,
                agent_mode=request.agent_mode,
                target_agent=request.target_agent,
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

        # Canary / Prompt Leakage Defense
        has_leak, canary_id = inspect_response_for_canary_leak(final_answer)
        if has_leak:
            logger.critical(
                "PROMPT_LEAKAGE_DETECTED in /api/chat: Canary token '%s' intercepted!",
                canary_id,
                extra={"session_id": session_id},
            )
            final_answer = (
                "Cảnh báo bảo mật khẩn cấp: Phát hiện nguy cơ rò rỉ token bảo mật hệ thống (Prompt Leakage). "
                "Phản hồi bị chặn theo giao thức Zero-Trust."
            )

        # --- 3. Save to conversation history (max 5 turns) ---
        try:
            await persist_turn(redis_client, llm_client, session_id, query, final_answer)
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
            session_id=request.session_id,
            response=final_answer,
            sources=[SourceItem(**src) for src in sources_list],
            pev_trace=pev_trace,
        )
    finally:
        target_llm_client = llm_client or (orchestrator.llm_client if orchestrator and hasattr(orchestrator, "llm_client") else None)
        if target_llm_client:
            await target_llm_client.flush_async()


@app.post(
    "/api/chat/approve",
    response_model=ApprovalDecisionResponse,
    summary="Human-in-the-Loop approval endpoint for sensitive database & API operations",
)
async def chat_approve(request: ApprovalDecisionRequest, principal: Principal = Depends(authenticate)) -> ApprovalDecisionResponse:
    """Process human confirmation or rejection of sensitive operations (HITL Gate)."""
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail=msg("service.starting"),
        )
    session_id: str = principal.session(request.session_id)
    if not principal.can_approve:
        logger.warning(
            "HITL decision refused: user=%s has none of the approver roles %s (action_id=%s)",
            principal.user_id, settings.HITL_APPROVER_ROLES, request.action_id, extra={"session_id": session_id},
        )
        await audit.record("hitl.refused", request.action_id, "forbidden", {"roles": sorted(principal.roles)}, principal=principal)
        raise HTTPException(status_code=403, detail=msg("forbidden.approve"))

    # Audit trail: who decided what, for which action. The decision row comes FIRST and is required: no record, no execution.
    try:
        await audit.record(f"hitl.{request.decision}", request.action_id, "decided", {"feedback": request.feedback}, principal=principal, required=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=msg("audit.unavailable")) from exc
    logger.info(
        "HITL decision: user=%s tenant=%s action_id=%s decision=%s",
        principal.user_id, principal.tenant_id, request.action_id, request.decision,
        extra={"session_id": session_id},
    )

    result = await orchestrator.handle_approval_decision(
        session_id=session_id,
        action_id=request.action_id,
        decision=request.decision,
        feedback=request.feedback,
        approver=principal,
    )
    if result.get("code") == "self_approval":
        await audit.record("hitl.refused", request.action_id, "self_approval", principal=principal)
        raise HTTPException(status_code=403, detail=result.get("message", msg("forbidden.self_approval")))

    await audit.record("hitl.result", request.action_id, str(result.get("status", "")), {"decision": request.decision}, principal=principal)
    if result.get("status") == "error":
        raise HTTPException(
            status_code=404,
            detail=result.get("message", msg("approval.unknown")),
        )

    return ApprovalDecisionResponse(
        status=result.get("status", "success"),
        action_id=request.action_id,
        decision=request.decision,
        message=result.get("message"),
        response=result.get("response"),
        data=result.get("data"),
    )


@app.get("/api/approvals", summary="Pending sensitive actions of OTHER users that this approver may decide (two-person approval)")
async def pending_approvals(principal: Principal = Depends(authenticate)) -> list[dict[str, Any]]:
    if orchestrator is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    if not principal.can_approve:
        raise HTTPException(status_code=403, detail=msg("forbidden.approve"))
    return await orchestrator.list_pending_approvals(principal)


@app.get("/api/chat/approve/{action_id}/result", summary="The outcome of an action another user approved, for the person who asked")
async def approval_result(action_id: str = Path(..., pattern=r"^act_[0-9a-f]{8}$"), principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    if orchestrator is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    outcome = await orchestrator.approval_result(action_id, principal)
    if outcome is None:
        raise HTTPException(status_code=404, detail=msg("approval.result_unknown"))
    return outcome


@app.post(
    "/api/analyze",
    dependencies=[Depends(limit_analyze)],
    response_model=AnalyzeResponse,
    summary="Analyze uploaded CSV data and generate executive dashboard spec",
)
async def analyze_csv(
    file: Optional[UploadFile] = File(None, description="Optional CSV file to upload and analyze"),
    query: str = Form("Hãy phân tích dữ liệu và dựng dashboard cho file này", description="Analysis prompt"),
    session_id: str = Form(default_factory=lambda: str(uuid.uuid4()), description="Session correlation ID"),
    principal: Principal = Depends(authenticate),
) -> AnalyzeResponse:
    """Upload a CSV file or analyze previously uploaded CSV in current session."""
    client_session_id: str = session_id
    session_id = principal.session(client_session_id)
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail=msg("service.starting"),
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
            detail=msg("security.injection", label=violation_label),
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
            filename = file.filename or "uploaded.csv"
            limit_bytes: int = settings.DATA_MAX_FILE_MB * 1024 * 1024
            buffer = bytearray()
            while chunk := await file.read(1024 * 1024):  # never hold more than the limit (+1 chunk) in memory
                buffer += chunk
                if len(buffer) > limit_bytes:
                    raise HTTPException(status_code=413, detail=msg("csv.too_big", name=filename, mb=settings.DATA_MAX_FILE_MB))
            raw_bytes: bytes = bytes(buffer)

            # Normalise any supported format (CSV/TSV/Excel/Parquet/JSON, any encoding) into UTF-8 CSV.
            # Original headers are kept: the data agent derives safe identifiers and display labels itself.
            try:
                csv_content = clean_csv_content(raw_bytes, filename=filename, sanitize_headers=False)
            except (DatasetReadError, ValueError) as read_exc:
                logger.info("Unreadable upload '%s': %s", filename, read_exc, extra={"session_id": session_id})
                reason = tr("vi", f"err.{read_exc.code}") if isinstance(read_exc, DatasetReadError) else str(read_exc)
                raise HTTPException(status_code=400, detail=msg("csv.unreadable", name=filename, reason=reason)) from read_exc
            # The data agent caches the active file for follow-up questions (session context).
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

        # Dynamic Nonce Delimiter Packaging
        wrapped_query, nonce = wrap_user_input(query)

        # --- 2. Delegate to Orchestrator with CSV ---
        raw_response: str = await orchestrator.handle_request(
            query=wrapped_query,
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
            session_id=client_session_id,
            explanation=explanation,
            generated_code=generated_code,
            dashboard_spec=dashboard_spec,
            metadata=metadata,
            pev_trace=pev_trace,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("CSV Analysis Failed: %s", e, extra={"session_id": session_id})
        raise HTTPException(
            status_code=400,
            detail=msg("csv.failed"),
        )
    finally:
        target_llm_client = llm_client or (orchestrator.llm_client if orchestrator and hasattr(orchestrator, "llm_client") else None)
        if target_llm_client:
            await target_llm_client.flush_async()


def _who(principal: Principal) -> dict[str, Any]:
    """What the UI needs to know about the caller (no secrets)."""
    return {
        "authenticated": principal.authenticated,
        "user": principal.user_id,
        "tenant_id": principal.tenant_id,
        "department_id": principal.department_id,
        "roles": sorted(principal.roles),
        "can_approve": principal.can_approve,
        "can_manage_knowledge": principal.can_manage_knowledge,
        "name": principal.display_name,
        "two_person_approval": principal.authenticated and settings.HITL_REQUIRE_OTHER_APPROVER,  # the UI then shows the approvals inbox
        "access_pending": principal.unassigned,  # a fresh self-registration: chat works, documents and data come after an administrator grants access
    }


def _session_response(user: dict[str, Any], recovery_key: Optional[str] = None) -> LoginResponse:
    """The token and the caller's identity for an account that has just proved who it is (sign-in, sign-up or reset)."""
    token, expires_in = issue_login_token(user)
    principal = Principal(
        str(user["username"]),
        str(user.get("tenant_id") or settings.RLS_TENANT_ID),
        str(user.get("department_id") or settings.RLS_DEPARTMENT_ID),
        frozenset(str(r) for r in (user.get("roles") or [])),
        authenticated=True,
        display_name=str(user.get("display_name") or ""),
    )
    return LoginResponse(access_token=token, expires_in=expires_in, user=_who(principal), recovery_key=recovery_key)


async def _registered_user(username: str, password: str) -> Optional[dict[str, Any]]:
    """A self-registered account with these credentials (always one scrypt, found or not), or ``None``."""
    try:
        row = await get_user(pg_client, username)
    except Exception as exc:  # noqa: BLE001 - a database hiccup must read as "wrong credentials", not as a 500
        logger.warning("Could not look up registered users: %s", exc)
        row = None
    return row if await asyncio.to_thread(verify_user_row, password, row) else None


@app.get("/api/auth/config", summary="What the sign-in screen may offer (no secrets, no token needed)")
async def auth_config() -> dict[str, bool]:
    return {"login_enabled": login_enabled(), "registration_enabled": registration_enabled()}


@app.post("/api/auth/register", response_model=LoginResponse, summary="Create an account and sign in (only with AUTH_ALLOW_REGISTRATION)")
async def register(body: RegisterRequest, request: Request) -> LoginResponse:
    """New accounts get no roles and the pending tenant/department: they can chat, but see no document and no database row until an
    administrator moves them (``python -m scripts.grant_user``)."""
    if not registration_enabled():
        raise HTTPException(status_code=404, detail=msg("register.disabled"))
    guest = Principal("anonymous", settings.RLS_TENANT_ID, settings.RLS_DEPARTMENT_ID)
    await enforce_rate_limit(redis_client, guest, request, "register", settings.RATE_LIMIT_REGISTER_PER_MINUTE)
    username = body.username.lower()
    if any(str(u.get("username", "")).lower() == username for u in settings.AUTH_USERS):
        raise HTTPException(status_code=409, detail=msg("register.taken"))
    password_hash = await asyncio.to_thread(hash_password, body.password)  # scrypt: off the event loop
    display_name = body.display_name.strip()
    recovery_key = new_recovery_key()  # shown once in this response; only its hash is stored
    recovery_hash = await asyncio.to_thread(hash_recovery_key, recovery_key)
    created = await create_user(pg_client, username, display_name, password_hash, recovery_hash, settings.REGISTRATION_TENANT_ID, settings.REGISTRATION_DEPARTMENT_ID)
    if not created:
        raise HTTPException(status_code=409, detail=msg("register.taken"))
    logger.info("Sign-up: user=%s", username)
    user = {"username": username, "display_name": display_name, "roles": [], "tenant_id": settings.REGISTRATION_TENANT_ID, "department_id": settings.REGISTRATION_DEPARTMENT_ID}
    return _session_response(user, recovery_key=recovery_key)


@app.post("/api/auth/reset-password", response_model=LoginResponse, summary="Forgot password: set a new one with the recovery key from sign-up")
async def reset_password(body: ResetPasswordRequest, request: Request) -> LoginResponse:
    """The recovery key is single use: a reset spends it and returns a new one (shown once). The caller is signed in afterwards."""
    if not registration_enabled():  # only self-registered accounts have a recovery key
        raise HTTPException(status_code=404, detail=msg("register.disabled"))
    guest = Principal("anonymous", settings.RLS_TENANT_ID, settings.RLS_DEPARTMENT_ID)
    await enforce_rate_limit(redis_client, guest, request, "reset", settings.RATE_LIMIT_PASSWORD_PER_MINUTE)
    await check_failures(redis_client, "reset", body.username, settings.AUTH_MAX_FAILURES)
    try:
        user = await get_user(pg_client, body.username)
    except Exception as exc:  # noqa: BLE001 - a database hiccup reads as "wrong key", never as a 500 that tells more
        logger.warning("Could not look up the account for a reset: %s", exc)
        user = None
    if not await asyncio.to_thread(verify_recovery_key, body.recovery_key, user) or user is None:
        await record_failure(redis_client, "reset", body.username)
        logger.warning("Failed password reset for %r from %s", body.username[:64], request.client.host if request.client else "unknown")
        raise HTTPException(status_code=400, detail=msg("reset.bad"))
    await clear_failures(redis_client, "reset", body.username)
    await revoke_user_sessions(redis_client, user["username"])  # whoever held the old password (or a stolen session) is signed out
    new_key = new_recovery_key()
    password_hash = await asyncio.to_thread(hash_password, body.new_password)
    recovery_hash = await asyncio.to_thread(hash_recovery_key, new_key)
    await set_password(pg_client, user["username"], password_hash, recovery_hash)
    logger.info("Password reset: user=%s", user["username"])
    return _session_response(user, recovery_key=new_key)


@app.post("/api/auth/change-password", summary="Change the signed-in user's password (self-registered accounts)")
async def change_password(body: ChangePasswordRequest, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    """Needs the current password. Accounts in ``AUTH_USERS`` live in the environment and are changed by an administrator.
    Tokens issued before the change are revoked; the answer carries a fresh one so the caller stays signed in."""
    if not principal.authenticated or not registration_enabled():
        raise HTTPException(status_code=400, detail=msg("password.managed"))
    await enforce_rate_limit(redis_client, principal, request, "password", settings.RATE_LIMIT_PASSWORD_PER_MINUTE)
    await check_failures(redis_client, "password", principal.user_id, settings.AUTH_MAX_FAILURES)
    user = await get_user(pg_client, principal.user_id)
    if user is None:  # an AUTH_USERS account
        raise HTTPException(status_code=400, detail=msg("password.managed"))
    if not await asyncio.to_thread(verify_user_row, body.current_password, user):
        await record_failure(redis_client, "password", principal.user_id)
        logger.warning("Wrong current password on a change attempt: user=%s", principal.user_id)
        raise HTTPException(status_code=400, detail=msg("password.wrong"))
    await clear_failures(redis_client, "password", principal.user_id)
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail=msg("password.same"))
    await set_password(pg_client, user["username"], await asyncio.to_thread(hash_password, body.new_password))
    await revoke_user_sessions(redis_client, user["username"])  # every OTHER open session ends; this one continues with the new token
    logger.info("Password changed: user=%s", user["username"])
    token, expires_in = issue_login_token(user)
    return {"ok": True, "access_token": token, "expires_in": expires_in}


@app.post("/api/auth/login", response_model=LoginResponse, summary="Sign in with a username and password (jwt mode, AUTH_USERS)")
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    """Check the credentials against ``AUTH_USERS`` and return a short-lived bearer token."""
    if not login_enabled():
        raise HTTPException(status_code=404, detail=msg("login.disabled"))
    # throttle per client IP; this route is reachable without a token, so it is the brute-force target
    guest = Principal("anonymous", settings.RLS_TENANT_ID, settings.RLS_DEPARTMENT_ID)
    await enforce_rate_limit(redis_client, guest, request, "login", settings.RATE_LIMIT_LOGIN_PER_MINUTE)
    await check_failures(redis_client, "login", body.username, settings.AUTH_MAX_FAILURES)  # per ACCOUNT: the IP may be shared
    user = await asyncio.to_thread(authenticate_user, body.username, body.password)  # scrypt is CPU-bound: keep it off the event loop
    stored_account = False
    if user is None and settings.AUTH_ALLOW_REGISTRATION:
        user = await _registered_user(body.username, body.password)
        stored_account = user is not None
    if user is None:
        await record_failure(redis_client, "login", body.username)  # unknown names count too: a lock-out must not reveal accounts
        logger.warning("Failed sign-in for %r from %s", body.username[:64], request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail=msg("login.bad"))
    await clear_failures(redis_client, "login", body.username)
    if stored_account and needs_rehash(str(user.get("password_hash", ""))):  # the password is in hand now: store it at today's cost
        try:
            await set_password(pg_client, user["username"], await asyncio.to_thread(hash_password, body.password))
        except Exception as exc:  # noqa: BLE001 - the sign-in itself succeeded
            logger.warning("Could not upgrade the password hash of %s: %s", user["username"], exc)
    logger.info("Sign-in: user=%s tenant=%s", user["username"], user.get("tenant_id") or settings.RLS_TENANT_ID)
    return _session_response(user)


@app.post("/api/auth/logout", summary="Sign out: the token used for this call stops working everywhere")
async def logout(principal: Principal = Depends(authenticate)) -> dict[str, bool]:
    revoked = await revoke_token(redis_client, principal)
    logger.info("Sign-out: user=%s revoked=%s", principal.user_id, revoked)
    return {"ok": True}


@app.get("/api/auth/me", summary="Who am I? (the UI uses it to decide between the chat and the login screen)")
async def whoami(principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    return _who(principal)


@app.post(
    "/api/knowledge/upload",
    dependencies=[Depends(limit_analyze)],
    response_model=KnowledgeUploadResponse,
    summary="Add or update a PDF/DOCX in the RAG knowledge base (used from the chat box)",
)
async def upload_knowledge(
    file: UploadFile = File(..., description="PDF or DOCX document"),
    session_id: str = Form(default_factory=lambda: str(uuid.uuid4()), description="Session correlation ID"),
    category: Optional[str] = Form(None, description="Document category (nda, msa, ...); inferred when omitted"),
    principal: Principal = Depends(authenticate),
) -> KnowledgeUploadResponse:
    """Chunk by section (200-600 characters), embed and store a document exactly like the folder ingestion does."""
    scoped_session: str = principal.session(session_id)
    if knowledge_embedder is None or knowledge_store is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    if not principal.can_manage_knowledge:
        logger.warning(
            "Knowledge upload refused: user=%s has none of the roles %s", principal.user_id, settings.KNOWLEDGE_UPLOAD_ROLES,
            extra={"session_id": scoped_session},
        )
        raise HTTPException(status_code=403, detail=msg("forbidden.knowledge"))

    limit_bytes: int = settings.KNOWLEDGE_MAX_FILE_MB * 1024 * 1024
    buffer = bytearray()
    while block := await file.read(1024 * 1024):  # never hold more than the limit (+1 block) in memory
        buffer += block
        if len(buffer) > limit_bytes:
            raise HTTPException(status_code=413, detail=msg("file.too_big", mb=settings.KNOWLEDGE_MAX_FILE_MB))

    try:
        result = await ingest_upload(
            knowledge_embedder, file.filename or "", bytes(buffer), category=category, dataset_dir=settings.KNOWLEDGE_DIR,
            known_categories=await knowledge_store.known_categories(scoped_session), max_chunks=settings.KNOWLEDGE_MAX_CHUNKS,
            session_id=scoped_session, llm_client=llm_client,
        )
    except UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - embedding API / database failure: nothing was half-written (one transaction)
        logger.error("Knowledge upload failed: %s", exc, extra={"session_id": scoped_session})
        raise HTTPException(status_code=502, detail=msg("upload.failed")) from exc

    knowledge_store.invalidate_categories()  # a new category must be recognisable in questions straight away
    await audit.record("kb.upload", result["doc_key"], result["status"], {"filename": result["filename"], "category": result["category"], "chunks": result.get("chunks")}, principal=principal)
    logger.info(
        "Knowledge upload by user=%s tenant=%s: %s -> %s (%s)", principal.user_id, principal.tenant_id, result["filename"], result["doc_key"], result["status"],
        extra={"session_id": scoped_session},
    )
    return KnowledgeUploadResponse(session_id=session_id, message=describe_upload(result), **{k: v for k, v in result.items() if k in KnowledgeUploadResponse.model_fields})


@app.post("/api/analyze/filter", summary="Recompute a dashboard's charts and KPIs for filtered rows")
async def filter_dashboard(request: FilterRequest, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    """Cross-filtering: charts are recomputed by the same compiler and re-verified against the filtered rows."""
    agent = orchestrator.registry.lookup("data_agent") if orchestrator is not None else None
    if agent is None or not hasattr(agent, "filter_dashboard"):
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    try:
        return await agent.filter_dashboard(principal.session(request.session_id), request.chart_specs, request.filters, request.language, request.focus)
    except LookupError:
        raise HTTPException(status_code=404, detail=msg("analyze.no_active")) from None
    except (ValueError, TypeError) as exc:  # invalid filter column / malformed chart spec
        raise HTTPException(status_code=422, detail=msg("filter.invalid", reason=exc)) from exc


@app.get("/health", summary="Health check")
async def health_check() -> dict[str, str]:
    """Simple health-check endpoint.

    Returns:
        dict[str, str]: ``{"status": "ok"}``.
    """
    return {"status": "ok"}


_READY_TIMEOUT_SECONDS: float = 2.0


async def _probe(check) -> str:
    """"ok" or a short reason; never raises and never waits longer than the readiness timeout."""
    try:
        await asyncio.wait_for(check(), timeout=_READY_TIMEOUT_SECONDS)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Readiness check failed: %s: %s", type(exc).__name__, exc)  # the detail stays in the log, not in the answer
        return type(exc).__name__


@app.get("/ready", summary="Readiness: can this instance serve requests right now?")
async def readiness() -> JSONResponse:
    """200 when PostgreSQL and Redis answer; 503 otherwise. ``/health`` only says the process is alive.

    The reranker is reported but does not fail readiness: without it retrieval falls back to the fused order
    (slower to converge on the best chunk, still correct), so the instance is *degraded*, not unavailable.
    """

    async def postgres() -> None:
        await pg_client.fetch("SELECT 1")

    async def redis() -> None:
        if redis_client.client is None:
            raise ConnectionError("not connected")
        await redis_client.client.ping()

    async def reranker() -> None:
        import httpx

        url = settings.RERANKER_ENDPOINT.rsplit("/", 1)[0] + "/health"
        async with httpx.AsyncClient(timeout=_READY_TIMEOUT_SECONDS) as http:
            (await http.get(url)).raise_for_status()

    names = ("postgres", "redis", "reranker")
    results = await asyncio.gather(*(_probe(c) for c in (postgres, redis, reranker)))
    checks = dict(zip(names, results))
    ready = checks["postgres"] == "ok" and checks["redis"] == "ok" and orchestrator is not None
    status = "ready" if ready and checks["reranker"] == "ok" else ("degraded" if ready else "unavailable")
    return JSONResponse(status_code=200 if ready else 503, content={"status": status, "orchestrator": orchestrator is not None, "checks": checks})
