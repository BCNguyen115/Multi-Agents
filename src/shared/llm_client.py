"""Unified LLM Client — centralised gateway for all LLM interactions.

Wraps **LiteLLM** (model routing) and **Langfuse** (observability) into
a single async interface that every Agent and the Orchestrator uses.

Key features:
  - Automatic model routing via LiteLLM prefix conventions
    (``openai/gpt-4o-mini``, ``openrouter/...``, etc.).
  - Optional Langfuse tracing controlled by the ``LANGFUSE_ENABLED``
    feature flag.  When disabled, all calls still work through LiteLLM
    without any tracing overhead.
  - Singleton-friendly: create once in ``lifespan()``, inject everywhere.

Usage:
    from src.shared.llm_client import LLMClient

    client = LLMClient(settings=settings)
    resp = await client.chat_completion(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
    )
    # resp.choices[0].message.content → "Hi there!"

    emb = await client.embedding(
        model="text-embedding-3-small",
        input_text="Some document text",
    )
    # emb → [0.012, -0.034, ...]
"""

import logging
import uuid
from typing import Any, Optional

import litellm
import openai
from litellm import acompletion, aembedding

from src.config import Settings
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Suppress verbose litellm & langfuse logs
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("LiteLLM Proxy").setLevel(logging.WARNING)
logging.getLogger("LiteLLM Router").setLevel(logging.WARNING)
logging.getLogger("langfuse").setLevel(logging.CRITICAL)


class LLMClient:
    """Centralised async client for all LLM chat and embedding calls.

    Wraps LiteLLM for model routing and optionally attaches a Langfuse
    callback handler for observability (token usage, latency, cost).

    Attributes:
        api_key: The OpenRouter / OpenAI API key.
        api_base: The base URL for the LLM provider.
        default_model: Fallback model when none is specified.
        langfuse_enabled: Whether Langfuse tracing is active.
        _langfuse_handler: The Langfuse callback handler (if enabled).
        raw_openai_client: Native AsyncOpenAI client for robust embeddings.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise the LLM client.

        Configures LiteLLM with the OpenRouter credentials and optionally
        sets up Langfuse tracing.

        Args:
            settings: Application settings containing API keys and config.
        """
        import os

        self.settings: Settings = settings
        self.api_key: str = settings.OPENROUTER_API_KEY
        self.api_base: str = settings.OPENROUTER_BASE_URL
        self.default_model: str = settings.OPENROUTER_MODEL
        self.langfuse_enabled: bool = settings.LANGFUSE_ENABLED
        self._langfuse_handler: Any = None

        from src.shared.telemetry import disable_telemetry
        disable_telemetry()

        # Force environment variables & litellm configuration for OpenRouter routing
        os.environ["OPENROUTER_API_KEY"] = self.api_key
        os.environ["OPENAI_API_KEY"] = self.api_key
        os.environ["OPENAI_BASE_URL"] = self.api_base
        litellm.api_key = self.api_key
        litellm.api_base = self.api_base
        litellm.drop_params = True  # Drop unsupported params gracefully

        # Native OpenAI-compatible client for OpenRouter fallback
        self.raw_openai_client: openai.AsyncOpenAI = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
        )

        # --- Langfuse setup (if enabled) ---
        if self.langfuse_enabled:
            try:
                import os
                import sys
                import httpx
                import langfuse

                # Health check probe with retry and detailed HTTP logging
                candidate_hosts = [
                    settings.LANGFUSE_HOST.rstrip("/"),
                    "http://langfuse-web:3000",
                    "http://localhost:3005",
                    "http://127.0.0.1:3005",
                ]
                seen_hosts: set[str] = set()
                unique_hosts: list[str] = []
                for h in candidate_hosts:
                    if h not in seen_hosts:
                        seen_hosts.add(h)
                        unique_hosts.append(h)

                working_host: str | None = None
                last_error_reason: str = "Unknown error"

                with httpx.Client(timeout=5.0) as http_client:
                    for cand in unique_hosts:
                        for attempt in range(1, 3):  # Retry up to 2 times
                            try:
                                res = http_client.get(f"{cand}/api/public/health")
                                if res.status_code in [200, 401, 403]:  # Server is up
                                    working_host = cand
                                    break
                                else:
                                    last_error_reason = f"HTTP status {res.status_code}"
                            except httpx.ConnectError as conn_err:
                                last_error_reason = f"ConnectionRefused ({conn_err})"
                            except httpx.TimeoutException:
                                last_error_reason = "Timeout (5.0s exceeded)"
                            except Exception as http_err:
                                last_error_reason = f"Network error ({http_err})"

                        if working_host:
                            break

                is_reachable: bool = working_host is not None
                if working_host and working_host != settings.LANGFUSE_HOST.rstrip("/"):
                    logger.info(
                        "Langfuse host auto-resolved from '%s' to '%s'",
                        settings.LANGFUSE_HOST,
                        working_host,
                        extra={"session_id": "SYSTEM"},
                    )
                    settings.LANGFUSE_HOST = working_host

                # Check key validity
                has_keys: bool = bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)
                is_dummy_key: bool = (
                    "pk-lf-345be264" in settings.LANGFUSE_PUBLIC_KEY
                    or "sk-lf-f005" in settings.LANGFUSE_SECRET_KEY
                    or "change-me" in settings.LANGFUSE_PUBLIC_KEY.lower()
                )

                if not is_reachable:
                    logger.warning(
                        "Langfuse host '%s' is unreachable (%s). Tracing disabled gracefully.",
                        settings.LANGFUSE_HOST,
                        last_error_reason,
                        extra={"session_id": "SYSTEM"},
                    )
                    self.langfuse_enabled = False
                    litellm.success_callback = []
                    litellm.failure_callback = []
                elif is_dummy_key or not has_keys:
                    logger.warning(
                        "Langfuse host '%s' is reachable, but keys are default dummy placeholders. "
                        "Tracing disabled. To enable, generate real API keys in Langfuse UI (http://localhost:3005 -> Project Settings -> API Keys) and set in .env.",
                        settings.LANGFUSE_HOST,
                        extra={"session_id": "SYSTEM"},
                    )
                    self.langfuse_enabled = False
                    litellm.success_callback = []
                    litellm.failure_callback = []
                else:
                    # Patch for litellm compatibility with newer langfuse versions
                    if not hasattr(langfuse, "version"):
                        import types
                        langfuse.version = types.ModuleType("version")
                        langfuse.version.__version__ = getattr(langfuse, "__version__", "unknown")
                        sys.modules["langfuse.version"] = langfuse.version
                    
                    # Patch Langfuse.__init__ to ignore 'sdk_integration' from litellm
                    from langfuse import Langfuse
                    if not hasattr(Langfuse, "_patched_for_litellm"):
                        _original_langfuse_init = Langfuse.__init__
                        def _patched_langfuse_init(self, *args, **kwargs):
                            kwargs.pop("sdk_integration", None)
                            _original_langfuse_init(self, *args, **kwargs)
                        Langfuse.__init__ = _patched_langfuse_init
                        Langfuse._patched_for_litellm = True

                    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
                    os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
                    os.environ["LANGFUSE_HOST"] = settings.LANGFUSE_HOST

                    litellm.success_callback = ["langfuse"]
                    litellm.failure_callback = ["langfuse"]

                    logger.info(
                        "Langfuse tracing ENABLED and verified (host=%s)",
                        settings.LANGFUSE_HOST,
                        extra={"session_id": "SYSTEM"},
                    )
            except Exception as exc:
                logger.warning(
                    "Langfuse initialisation failed — tracing disabled: %s",
                    exc,
                    extra={"session_id": "SYSTEM"},
                )
                self.langfuse_enabled = False
                litellm.success_callback = []
                litellm.failure_callback = []
        else:
            litellm.success_callback = []
            litellm.failure_callback = []
            logger.info(
                "Langfuse tracing DISABLED (LANGFUSE_ENABLED=false)",
                extra={"session_id": "SYSTEM"},
            )

        logger.info(
            "LLMClient initialised (default_model=%s, langfuse=%s)",
            self.default_model,
            self.langfuse_enabled,
            extra={"session_id": "SYSTEM"},
        )

    # ------------------------------------------------------------------
    # Chat Completion
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        metadata: dict[str, Any] | None = None,
        session_id: str = "N/A",
    ) -> Any:
        """Send a chat completion request via LiteLLM.

        Args:
            messages: List of message dicts (role/content).
            model: LLM model identifier. Falls back to ``default_model``.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.
            metadata: Optional metadata dict passed to Langfuse trace.
            session_id: Correlation ID for logging.

        Returns:
            The LiteLLM completion response (OpenAI-compatible format).

        Raises:
            Exception: Propagates any LiteLLM / provider errors.
        """
        resolved_model: str = model or self.default_model
        if not resolved_model.startswith("openai/") and not resolved_model.startswith("openrouter/"):
            resolved_model = f"openai/{resolved_model}"
        request_trace_id = str(uuid.uuid4())
        call_metadata: dict[str, Any] = {
            "trace_id": request_trace_id,
            "session_id": session_id,
            "request_id": request_trace_id,
            "trace_user_id": session_id,
            "trace_name": (metadata.get("trace_name") if metadata else None) or f"llm_chat_{session_id[:8]}",
            **(metadata or {}),
        }

        logger.debug(
            "LLM chat_completion (model=%s, msgs=%d, temp=%.1f)",
            resolved_model,
            len(messages),
            temperature,
            extra={"session_id": session_id},
        )

        try:
            response: Any = await acompletion(
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=self.api_key,
                api_base=self.api_base,
                metadata=call_metadata,
            )

            # Extract usage for logging
            total_tokens: Any = getattr(
                getattr(response, "usage", None), "total_tokens", "N/A"
            )
            logger.info(
                "LLM chat_completion OK (model=%s, tokens=%s)",
                resolved_model,
                total_tokens,
                extra={"session_id": session_id},
            )
            return response

        except Exception as exc:
            logger.warning(
                "LLM chat_completion failed with Langfuse callbacks enabled (%s) — disabling Langfuse and retrying…",
                exc,
                extra={"session_id": session_id},
            )
            if self.langfuse_enabled:
                self.langfuse_enabled = False
                litellm.success_callback = []
                litellm.failure_callback = []
                try:
                    retry_resp: Any = await acompletion(
                        model=resolved_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        api_key=self.api_key,
                        api_base=self.api_base,
                    )
                    return retry_resp
                except Exception as retry_exc:
                    logger.error(
                        "LLM chat_completion retry FAILED (model=%s): %s",
                        resolved_model,
                        retry_exc,
                        extra={"session_id": session_id},
                    )
                    raise retry_exc
            raise exc

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    async def embedding(
        self,
        input_text: str | None = None,
        text: str | None = None,
        model: str = "text-embedding-3-small",
        metadata: dict[str, Any] | None = None,
        session_id: str = "N/A",
        **kwargs: Any,
    ) -> list[float]:
        """Generate vector embedding for a single text string.

        Args:
            input_text: Input text string to embed.
            text: Alternative keyword argument for input_text.
            model: Embedding model identifier (default: text-embedding-3-small).
            metadata: Optional metadata dictionary for tracing.
            session_id: Correlation ID for logging.
            **kwargs: Extra parameters for backward/forward compatibility.

        Returns:
            list[float]: Embedding vector of floats.
        """
        raw_text: str = (input_text if input_text is not None else text) or ""
        if not raw_text or not raw_text.strip():
            logger.warning("Empty input text provided for embedding", extra={"session_id": session_id})
            return []

        clean_model: str = model.replace("openai/", "").replace("openrouter/", "")
        resolved_model: str = f"openai/{clean_model}"

        logger.debug(
            "Generating embedding (model=%s, len=%d chars)",
            clean_model,
            len(raw_text),
            extra={"session_id": session_id},
        )

        request_trace_id = str(uuid.uuid4())
        call_metadata: dict[str, Any] = {
            "trace_id": request_trace_id,
            "session_id": session_id,
            "request_id": request_trace_id,
            "trace_user_id": session_id,
            "trace_name": "embedding",
            **(metadata or {}),
        }

        try:
            native_resp: Any = await self.raw_openai_client.embeddings.create(
                model=clean_model,
                input=raw_text,
            )
            emb_vector = native_resp.data[0].embedding
            logger.debug(
                "Native AsyncOpenAI embedding OK (dim=%d)",
                len(emb_vector),
                extra={"session_id": session_id},
            )
            return emb_vector
        except Exception as first_exc:
            logger.warning(
                "Native AsyncOpenAI embedding failed (%s), trying LiteLLM aembedding fallback...",
                first_exc,
                extra={"session_id": session_id},
            )
            try:
                response: Any = await aembedding(
                    model=resolved_model,
                    input=[raw_text],
                    api_key=self.api_key,
                    api_base=self.api_base,
                    metadata=call_metadata,
                )
                emb_vector = response.data[0]["embedding"]
                logger.info(
                    "LiteLLM aembedding fallback OK (dim=%d)",
                    len(emb_vector),
                    extra={"session_id": session_id},
                )
                return emb_vector
            except Exception as second_exc:
                logger.error(
                    "LLM embedding FAILED completely: %s",
                    second_exc,
                    extra={"session_id": session_id},
                )
                raise

    async def aembedding(self, *args: Any, **kwargs: Any) -> list[float]:
        """Async alias for embedding."""
        return await self.embedding(*args, **kwargs)

    # ------------------------------------------------------------------
    # Langfuse Handler & Async Flush
    # ------------------------------------------------------------------

    def get_langfuse_callback(
        self,
        session_id: str = "N/A",
        user_id: str | None = None,
        trace_name: str = "orchestrator_pev_loop",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Instantiate and return a brand-new Langfuse CallbackHandler for each request."""
        if not self.langfuse_enabled:
            return None

        try:
            CallbackHandler = None
            try:
                from langfuse.callback import CallbackHandler
            except ImportError:
                try:
                    from langfuse.langchain import CallbackHandler
                except ImportError:
                    try:
                        from langfuse.langchain import LangfuseHandler as CallbackHandler
                    except ImportError:
                        try:
                            from langfuse import CallbackHandler
                        except ImportError:
                            CallbackHandler = None

            if CallbackHandler is None:
                logger.debug("Langfuse CallbackHandler is not available (langfuse[langchain] extra missing)")
                return None

            # Each request receives a completely unique request_id and trace configuration
            request_trace_id = str(uuid.uuid4())
            merged_metadata = {
                "request_id": request_trace_id,
                **(metadata or {}),
            }

            handler = CallbackHandler(
                public_key=self.settings.LANGFUSE_PUBLIC_KEY,
                secret_key=self.settings.LANGFUSE_SECRET_KEY,
                host=self.settings.LANGFUSE_HOST,
                session_id=session_id,  # Groups traces by conversation session
                user_id=user_id or session_id,
                trace_name=trace_name,
                tags=tags or ["pev_loop"],
                metadata=merged_metadata,
            )
            return handler
        except Exception as exc:
            logger.debug("Langfuse CallbackHandler creation skipped: %s", exc)
            return None

    def get_langfuse_handler(
        self,
        session_id: str = "N/A",
        trace_name: str = "agent-trace",
        user_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Backward-compatible alias for get_langfuse_callback."""
        return self.get_langfuse_callback(
            session_id=session_id,
            user_id=user_id,
            trace_name=trace_name,
            tags=tags,
            metadata=metadata,
        )

    def flush(self) -> None:
        """Synchronously flush pending Langfuse and LiteLLM trace buffers."""
        if self.langfuse_enabled:
            try:
                import litellm
                if hasattr(litellm, "flush") and callable(litellm.flush):
                    litellm.flush()
            except Exception as exc:
                logger.debug("litellm.flush exception: %s", exc)

            try:
                from langfuse import Langfuse
                lf = Langfuse(
                    public_key=self.settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=self.settings.LANGFUSE_SECRET_KEY,
                    host=self.settings.LANGFUSE_HOST,
                )
                lf.flush()
            except Exception as exc:
                logger.debug("Langfuse client flush exception: %s", exc)

    async def flush_async(self) -> None:
        """Asynchronously flush pending Langfuse trace buffers."""
        if self.langfuse_enabled:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.flush)
            except Exception as exc:
                logger.debug("flush_async exception: %s", exc)

    async def aflush(self) -> None:
        """Async alias for flush_async."""
        await self.flush_async()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Flush any pending Langfuse traces and clean up resources.

        Should be called during application shutdown.
        """
        if self.langfuse_enabled:
            try:
                self.flush()
                logger.info(
                    "Langfuse traces flushed successfully",
                    extra={"session_id": "SYSTEM"},
                )
            except Exception as exc:
                logger.warning(
                    "Langfuse flush failed: %s",
                    exc,
                    extra={"session_id": "SYSTEM"},
                )

        try:
            litellm.cache = None  # Clear any cached responses
        except Exception:
            pass

        logger.info(
            "LLMClient shutdown complete",
            extra={"session_id": "SYSTEM"},
        )
