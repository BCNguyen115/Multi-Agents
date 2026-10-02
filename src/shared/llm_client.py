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
from src.shared import tracing
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Suppress verbose litellm & langfuse logs
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("LiteLLM Proxy").setLevel(logging.WARNING)
logging.getLogger("LiteLLM Router").setLevel(logging.WARNING)
logging.getLogger("langfuse").setLevel(logging.CRITICAL)

DEFAULT_FALLBACK_MODEL: str = "openrouter/openai/gpt-4o-mini"
DEFAULT_OPENROUTER_HEADERS: dict[str, str] = {
    "HTTP-Referer": "https://github.com/enterprise-multi-agent",
    "X-Title": "Multi-Agent Enterprise System",
}


def normalize_model_name(model_name: str | None) -> str:
    """Đảm bảo mọi model định tuyến qua OpenRouter đều có tiền tố openrouter/"""
    if not model_name or not str(model_name).strip():
        return "openrouter/openai/gpt-4o-mini"
    clean_name = str(model_name).strip()
    if clean_name.startswith("openrouter/"):
        return clean_name
    # Nếu model là anthropic/..., openai/..., meta-llama/... thì thêm openrouter/
    return f"openrouter/{clean_name}"


class LLMClient:
    """Centralised async client for all LLM chat and embedding calls.

    Wraps LiteLLM for model routing and optionally attaches a Langfuse
    callback handler for observability (token usage, latency, cost).

    Attributes:
        api_key: The OpenRouter / OpenAI API key.
        api_base: The base URL for the LLM provider.
        default_model: Fallback model when none is specified.
        langfuse_enabled: Whether Langfuse tracing is active.
        _langfuse: The shared Langfuse client (None while tracing is off).
        raw_openai_client: Native AsyncOpenAI client for robust embeddings.
        unavailable_models: Circuit Breaker registry of models returning 404.
    """

    _global_unavailable_models: set[str] = set()

    def __init__(self, settings: Optional[Settings] = None) -> None:
        """Initialise the LLM client.

        Configures LiteLLM with the OpenRouter credentials and optionally
        sets up Langfuse tracing.

        Args:
            settings: Application settings containing API keys and config.
                If None, uses application singleton from src.config.
        """
        import os

        if settings is None:
            from src.config import settings as default_settings
            settings = default_settings

        self.settings: Settings = settings
        self.api_key: str = settings.OPENROUTER_API_KEY
        self.api_base: str = settings.OPENROUTER_BASE_URL
        self.default_model: str = settings.OPENROUTER_MODEL
        self.langfuse_enabled: bool = settings.LANGFUSE_ENABLED
        self.unavailable_models: set[str] = LLMClient._global_unavailable_models

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

        # --- Langfuse: ONE shared client, keys proven against the server (src/shared/tracing.py) ---
        self._langfuse: Any = tracing.connect(settings) if self.langfuse_enabled else None
        self.langfuse_enabled = self._langfuse is not None
        if not self.langfuse_enabled:
            litellm.success_callback = []
            litellm.failure_callback = []

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
        **kwargs: Any,
    ) -> Any:
        """Send a chat completion request via LiteLLM with OpenRouter prefix normalization and smart fallback.

        Args:
            messages: List of message dicts (role/content).
            model: LLM model identifier. Falls back to ``default_model``.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.
            metadata: Optional metadata dict passed to Langfuse trace.
            session_id: Correlation ID for logging.
            **kwargs: Extra parameters passed to litellm.acompletion.

        Returns:
            The LiteLLM completion response (OpenAI-compatible format).

        Raises:
            Exception: Propagates any LiteLLM / provider errors after retries and fallback fail.
        """
        requested_model: str = model or self.default_model
        resolved_model: str = normalize_model_name(requested_model)
        fallback_model: str = DEFAULT_FALLBACK_MODEL

        # Circuit Breaker: Zero-latency instant bypass if model has been blacklisted
        if (
            resolved_model in self.unavailable_models
            or requested_model in self.unavailable_models
        ) and resolved_model != fallback_model:
            logger.debug(
                "[LLMClient] Instant bypass for blacklisted model '%s' -> '%s' (0ms latency)",
                resolved_model,
                fallback_model,
                extra={"session_id": session_id},
            )
            resolved_model = fallback_model

        request_trace_id = str(uuid.uuid4())
        call_metadata: dict[str, Any] = {
            "trace_id": request_trace_id,
            "session_id": session_id,
            "request_id": request_trace_id,
            "trace_user_id": session_id,
            "trace_name": (metadata.get("trace_name") if metadata else None) or f"llm_chat_{session_id[:8]}",
            **(metadata or {}),
        }
        call_metadata = tracing.with_trace(call_metadata)

        # OpenRouter required headers
        extra_headers: dict[str, str] = dict(DEFAULT_OPENROUTER_HEADERS)
        if "extra_headers" in kwargs:
            extra_headers.update(kwargs.pop("extra_headers"))

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
                extra_headers=extra_headers,
                **kwargs,
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
            err_msg: str = str(exc)
            not_found_type = getattr(litellm, "NotFoundError", None)
            is_not_found_cls = isinstance(not_found_type, type) and issubclass(not_found_type, BaseException)
            is_404_or_no_endpoints: bool = (
                (is_not_found_cls and isinstance(exc, not_found_type))
                or "404" in err_msg
                or "No endpoints found" in err_msg
                or "not found" in err_msg.lower()
            )

            fallback_model: str = DEFAULT_FALLBACK_MODEL

            # Fast 404 / No endpoints found bypass: Blacklist model and fallback
            if is_404_or_no_endpoints and resolved_model != fallback_model:
                if resolved_model not in self.unavailable_models:
                    self.unavailable_models.add(resolved_model)
                    if requested_model:
                        self.unavailable_models.add(requested_model)
                    logger.warning(
                        "[LLMClient] Blacklisting unavailable model '%s' for this session.",
                        resolved_model,
                        extra={"session_id": session_id},
                    )
                logger.warning(
                    "[LLMClient] Model %s unavailable on OpenRouter (404). Auto-fallbacking to %s...",
                    resolved_model,
                    fallback_model,
                    extra={"session_id": session_id},
                )
                try:
                    fallback_resp: Any = await acompletion(
                        model=fallback_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        api_key=self.api_key,
                        api_base=self.api_base,
                        extra_headers=extra_headers,
                        **kwargs,
                    )
                    logger.info(
                        "LLM chat_completion auto-fallback to '%s' SUCCEEDED",
                        fallback_model,
                        extra={"session_id": session_id},
                    )
                    return fallback_resp
                except Exception as fb_exc:
                    logger.error(
                        "LLM chat_completion fallback also FAILED (model=%s): %s",
                        fallback_model,
                        fb_exc,
                        extra={"session_id": session_id},
                    )
                    raise fb_exc

            logger.warning(
                "LLM chat_completion failed on model '%s' (%s) — attempting recovery/fallback…",
                resolved_model,
                exc,
                extra={"session_id": session_id},
            )
            last_exc = exc

            # Smart Fallback Mechanism:
            # If the primary model encounters network issues, timeout, rate limit, or other errors,
            # automatically fallback to openrouter/openai/gpt-4o-mini to maintain PEV execution
            if resolved_model != fallback_model:
                logger.warning(
                    "Primary LLM '%s' failed. Automatically falling back to '%s' to maintain PEV workflow...",
                    resolved_model,
                    fallback_model,
                    extra={"session_id": session_id},
                )
                try:
                    fallback_resp: Any = await acompletion(
                        model=fallback_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        api_key=self.api_key,
                        api_base=self.api_base,
                        extra_headers=extra_headers,
                        **kwargs,
                    )
                    logger.info(
                        "LLM chat_completion fallback to '%s' SUCCEEDED",
                        fallback_model,
                        extra={"session_id": session_id},
                    )
                    return fallback_resp
                except Exception as fb_exc:
                    logger.error(
                        "LLM chat_completion fallback also FAILED (model=%s): %s",
                        fallback_model,
                        fb_exc,
                        extra={"session_id": session_id},
                    )
                    raise fb_exc

            raise last_exc

    async def acompletion(self, *args: Any, **kwargs: Any) -> Any:
        """Async alias for chat_completion conforming to LiteLLM / client protocol."""
        return await self.chat_completion(*args, **kwargs)

    def completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        metadata: dict[str, Any] | None = None,
        session_id: str = "N/A",
        **kwargs: Any,
    ) -> Any:
        """Synchronous chat completion with OpenRouter prefix normalization and fallback."""
        requested_model: str = model or self.default_model
        resolved_model: str = normalize_model_name(requested_model)
        fallback_model: str = DEFAULT_FALLBACK_MODEL

        # Circuit Breaker: Zero-latency instant bypass if model has been blacklisted
        if (
            resolved_model in self.unavailable_models
            or requested_model in self.unavailable_models
        ) and resolved_model != fallback_model:
            logger.debug(
                "[LLMClient] Instant bypass for blacklisted model '%s' -> '%s' (0ms latency)",
                resolved_model,
                fallback_model,
                extra={"session_id": session_id},
            )
            resolved_model = fallback_model

        extra_headers: dict[str, str] = dict(DEFAULT_OPENROUTER_HEADERS)
        if "extra_headers" in kwargs:
            extra_headers.update(kwargs.pop("extra_headers"))

        try:
            return litellm.completion(
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=self.api_key,
                api_base=self.api_base,
                extra_headers=extra_headers,
                **kwargs,
            )
        except Exception as exc:
            err_msg: str = str(exc)
            not_found_type = getattr(litellm, "NotFoundError", None)
            is_not_found_cls = isinstance(not_found_type, type) and issubclass(not_found_type, BaseException)
            is_404_or_no_endpoints: bool = (
                (is_not_found_cls and isinstance(exc, not_found_type))
                or "404" in err_msg
                or "No endpoints found" in err_msg
                or "not found" in err_msg.lower()
            )
            fallback_model: str = DEFAULT_FALLBACK_MODEL
            if resolved_model != fallback_model:
                if is_404_or_no_endpoints:
                    if resolved_model not in self.unavailable_models:
                        self.unavailable_models.add(resolved_model)
                        if requested_model:
                            self.unavailable_models.add(requested_model)
                        logger.warning(
                            "[LLMClient] Blacklisting unavailable model '%s' for this session.",
                            resolved_model,
                            extra={"session_id": session_id},
                        )
                    logger.warning(
                        "[LLMClient] Model %s unavailable on OpenRouter (404). Auto-fallbacking to %s...",
                        resolved_model,
                        fallback_model,
                        extra={"session_id": session_id},
                    )
                else:
                    logger.warning(
                        "Sync LLM completion failed on '%s' (%s). Falling back to '%s'...",
                        resolved_model,
                        exc,
                        fallback_model,
                        extra={"session_id": session_id},
                    )
                return litellm.completion(
                    model=fallback_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_key=self.api_key,
                    api_base=self.api_base,
                    extra_headers=extra_headers,
                    **kwargs,
                )
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
        call_metadata = tracing.with_trace(call_metadata)

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
        """A callback that records one request as its own Langfuse trace (None while tracing is off)."""
        if not self.langfuse_enabled:
            return None
        return tracing.langchain_handler(
            self._langfuse, session_id, user_id, trace_name, tags,
            {"request_id": str(uuid.uuid4()), **(metadata or {})},
        )

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
        """Send the buffered Langfuse events now (LiteLLM's logger and the shared client)."""
        if not self.langfuse_enabled:
            return
        try:
            if callable(getattr(litellm, "flush", None)):
                litellm.flush()
        except Exception as exc:
            logger.debug("litellm.flush exception: %s", exc)
        try:
            self._langfuse.flush()
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
                self._langfuse.shutdown()
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
