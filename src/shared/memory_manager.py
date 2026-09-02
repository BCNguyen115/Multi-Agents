"""Long-term Memory Manager module.

Integrates with **mem0** (``mem0ai``) for cross-session long-term memory.
Extracts user preferences, past interactions, and persistent context to
enhance personalization and planning across agent interactions.

Usage:
    from src.shared.memory_manager import MemoryManager

    mem = MemoryManager(settings=settings)
    await mem.add_memory(user_id="user_123", text="Khách hàng ưu tiên vẽ biểu đồ cột cho dữ liệu doanh thu")
    context = await mem.get_relevant_memories(user_id="user_123", query="Vẽ biểu đồ doanh thu")
"""

import logging
import warnings
from typing import Any, Optional

from src.config import Settings
from src.shared.logger import get_logger

# Suppress harmless Qdrant local payload index warning from mem0
warnings.filterwarnings(
    "ignore",
    message=".*Payload indexes have no effect in the local Qdrant.*",
    category=UserWarning,
)

logger: logging.Logger = get_logger(__name__)

import re

# ---------------------------------------------------------------------------
# PII Redaction Pipeline — Regex Patterns (Tightened for VN specifics)
# ---------------------------------------------------------------------------
# Order matters: email first (to avoid partial matches), then phone, ID, card.
#
# Design decisions:
#   - Phone: requires 0 or +84 prefix, then exactly 9 or 10 additional digits.
#   - CCCD: exactly 12 digits (new VN Citizen ID format). We intentionally do NOT
#     match 9-digit numbers — too many false positives (zip codes, order IDs, etc.).
#   - Credit card: 13-19 digits with optional separators (space/dash), bounded by
#     non-digit context. More conservative than the previous unbounded regex.
#   - Email: standard RFC-like pattern with word boundaries.

_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Email addresses
    (
        re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"),
        "[REDACTED_EMAIL]",
    ),
    # Vietnamese phone numbers: 0xxx or +84xxx (9-10 digits after prefix)
    (
        re.compile(r"(?<!\d)(?:\+84|0)\d{9,10}(?!\d)"),
        "[REDACTED_PHONE]",
    ),
    # Vietnamese Citizen ID (CCCD): exactly 12 digits
    (
        re.compile(r"(?<!\d)\d{12}(?!\d)"),
        "[REDACTED_ID]",
    ),
    # Credit/debit card numbers: 13-19 digits with optional space/dash separators
    # Requires non-digit boundaries to avoid matching inside large numbers
    (
        re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)"),
        "[REDACTED_CARD]",
    ),
]


def redact_pii(text: str) -> str:
    """Sanitise text by redacting sensitive Personally Identifiable Information.

    Targets Vietnamese-specific PII patterns:
      - Email addresses → ``[REDACTED_EMAIL]``
      - Phone numbers (0xxx / +84xxx) → ``[REDACTED_PHONE]``
      - Citizen ID / CCCD (12 digits) → ``[REDACTED_ID]``
      - Credit/debit card numbers (13-19 digits) → ``[REDACTED_CARD]``

    .. note::
        This function is designed for memory storage contexts (user facts,
        conversation summaries). It should NOT be applied to structured data
        analysis outputs (CSV columns, chart data) to avoid corrupting
        legitimate numeric content.

    Args:
        text: Raw input text.

    Returns:
        str: Text with PII patterns replaced by redaction markers.
    """
    if not text:
        return ""
    sanitised = text
    for pattern, replacement in _PII_PATTERNS:
        sanitised = pattern.sub(replacement, sanitised)
    return sanitised



class MemoryManager:
    """Manages cross-session long-term memory for users and sessions.

    Wraps ``mem0.Memory`` with asynchronous helpers and graceful fallback.

    Attributes:
        enabled: Whether long-term memory is active.
        mem0_client: Instance of ``mem0.Memory`` if available.
        _fallback_store: In-memory fallback dictionary if mem0 is unavailable.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        """Initialise the Long-term Memory Manager.

        Args:
            settings: Application settings.
        """
        self.enabled: bool = True
        self.mem0_client: Any = None
        self._fallback_store: dict[str, list[dict[str, Any]]] = {}

        try:
            import os
            from src.shared.telemetry import disable_telemetry
            disable_telemetry()

            from src.config import settings as global_settings
            cfg = settings or global_settings

            # Force environment variables for OpenAI-compatible client routing (e.g. OpenRouter)
            os.environ["OPENAI_API_KEY"] = cfg.OPENROUTER_API_KEY
            os.environ["OPENAI_BASE_URL"] = cfg.OPENROUTER_BASE_URL

            if getattr(cfg, "HF_TOKEN", None):
                os.environ["HF_TOKEN"] = cfg.HF_TOKEN

            from mem0 import Memory  # type: ignore[import-untyped]

            mem0_config: dict[str, Any] = {
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": cfg.OPENROUTER_MODEL.replace("openai/", "").replace("openrouter/", ""),
                        "api_key": cfg.OPENROUTER_API_KEY,
                        "openai_base_url": cfg.OPENROUTER_BASE_URL,
                    },
                },
                "embedder": {
                    "provider": "openai",
                    "config": {
                        "model": "text-embedding-3-small",
                        "api_key": cfg.OPENROUTER_API_KEY,
                        "openai_base_url": cfg.OPENROUTER_BASE_URL,
                    },
                },
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "on_disk": False,
                    },
                },
            }

            try:
                self.mem0_client = Memory.from_config(mem0_config)
            except Exception as init_exc:
                logger.warning("Memory.from_config init failed, trying Memory(): %s", init_exc)
                self.mem0_client = Memory()

            logger.info(
                "MemoryManager initialised with mem0ai library (OpenRouter base_url, PII redaction active)",
                extra={"session_id": "SYSTEM"},
            )
        except Exception as exc:
            logger.warning(
                "mem0ai library initialization notice (using fallback memory store): %s",
                exc,
                extra={"session_id": "SYSTEM"},
            )
            self.mem0_client = None

    async def warmup(self) -> None:
        """Pre-load heavy NLP models (spaCy, fastembed) during startup.

        Executes model initialization in a thread pool to avoid blocking
        the asyncio event loop during user chat requests.
        """
        import asyncio

        def _do_warmup() -> None:
            # 1. Warm-up spaCy if installed
            try:
                import spacy
                if spacy.util.is_package("en_core_web_sm"):
                    spacy.load("en_core_web_sm")
                    logger.info("Pre-loaded spaCy model 'en_core_web_sm'", extra={"session_id": "SYSTEM"})
            except Exception as e:
                logger.debug("spaCy pre-load skipped: %s", e)

            # 2. Warm-up mem0 models if initialized
            if self.mem0_client is not None:
                try:
                    self.mem0_client.search("warmup_query", filters={"user_id": "warmup_system"}, limit=1)
                    logger.info("Pre-loaded mem0 memory models successfully", extra={"session_id": "SYSTEM"})
                except Exception as e:
                    logger.debug("mem0 search warm-up skipped: %s", e)

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _do_warmup)
        except Exception as exc:
            logger.warning("MemoryManager warm-up exception (non-fatal): %s", exc)

    async def add_memory(
        self,
        user_id: str,
        text: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Store a new memory item for the specified user after PII redaction.

        Args:
            user_id: User / Session correlation identifier.
            text: Memory content or key fact.
            metadata: Optional metadata dictionary.
        """
        if not text or not user_id:
            return

        # Apply PII Redaction Pipeline
        clean_text = redact_pii(text)

        logger.debug(
            "Adding memory for user '%s' (PII redacted): %s",
            user_id,
            clean_text[:60],
            extra={"session_id": user_id},
        )

        if self.mem0_client is not None:
            try:
                # mem0ai v2 accepts text as positional argument or messages= text
                self.mem0_client.add(
                    clean_text,
                    user_id=user_id,
                    metadata=metadata or {},
                )
                return
            except Exception as exc:
                logger.warning(
                    "mem0ai add_memory exception: %s",
                    exc,
                    extra={"session_id": user_id},
                )

        # Fallback in-memory storage
        if user_id not in self._fallback_store:
            self._fallback_store[user_id] = []

        self._fallback_store[user_id].append(
            {
                "memory": clean_text,
                "metadata": metadata or {},
            }
        )

    async def get_relevant_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 3,
    ) -> list[str]:
        """Retrieve relevant memories for a user given a query.

        Args:
            user_id: User / Session correlation identifier.
            query: Current natural-language query.
            limit: Maximum number of memory items to return.

        Returns:
            list[str]: List of relevant memory text strings.
        """
        if not user_id:
            return []

        if self.mem0_client is not None:
            try:
                # mem0ai v2 requires user_id filtering via filters={"user_id": user_id}
                results: Any = self.mem0_client.search(
                    query=query,
                    filters={"user_id": user_id},
                    limit=limit,
                )
                memories: list[str] = []
                if isinstance(results, list):
                    for item in results:
                        if isinstance(item, dict) and "memory" in item:
                            memories.append(str(item["memory"]))
                        elif isinstance(item, str):
                            memories.append(item)
                logger.info(
                    "Retrieved %d long-term memories for user '%s'",
                    len(memories),
                    user_id,
                    extra={"session_id": user_id},
                )
                return memories
            except Exception as exc:
                logger.warning(
                    "mem0ai search exception: %s",
                    exc,
                    extra={"session_id": user_id},
                )

        # Fallback memory retrieval
        user_mems: list[dict[str, Any]] = self._fallback_store.get(user_id, [])
        return [m["memory"] for m in user_mems[-limit:]]

