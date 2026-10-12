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
import re
import uuid
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



def vector_store_config(cfg: Any) -> dict[str, Any]:
    """mem0's ``vector_store`` section: PostgreSQL/pgvector (persistent) or an in-process Qdrant (lost on restart)."""
    if getattr(cfg, "MEM0_VECTOR_STORE", "memory") == "pgvector":
        return {
            "provider": "pgvector",
            "config": {
                "connection_string": cfg.POSTGRES_URL,
                "collection_name": cfg.MEM0_PG_COLLECTION,
                "embedding_model_dims": 1536,  # text-embedding-3-small
            },
        }
    config: dict[str, Any] = {"on_disk": False}
    try:
        from qdrant_client import QdrantClient

        config["client"] = QdrantClient(location=":memory:")
    except Exception:  # noqa: BLE001 - mem0 then builds its own local store
        pass
    return {"provider": "qdrant", "config": config}


_PERSONAL_CUE = re.compile(
    r"(?:\b(?:tôi|mình|em|anh|chị)\s+(?:là|tên|làm|thích|muốn|hay|luôn|thường|ở|sống|đang|cần|không thích|quen)\b"
    r"|\b(?:hãy nhớ|nhớ rằng|nhớ là|đừng quên|từ nay|từ giờ|luôn luôn|mặc định|ưu tiên|gọi tôi|xưng hô)\b"
    r"|\b(?:my name|i am|i'm|i work|i prefer|i like|i always|i usually|remember (?:that|me)|from now on|please always|call me|my role|my team)\b)",
    re.IGNORECASE,
)


def worth_remembering(text: str, mode: str = "intent") -> bool:
    """Should this message be sent to long-term memory? Every extraction is an LLM call that stores whatever it finds, so by default only a
    message that SAYS something about the person (who they are, what they prefer, "remember...") goes in, not every question.
    ``mode``: ``all`` = every message (the old behaviour), ``intent`` = the cue above, ``off`` = never."""
    if mode == "all":
        return True
    return mode == "intent" and bool(_PERSONAL_CUE.search(text or ""))


class DualResult(dict):
    """A dictionary that can also be awaited in async contexts."""

    def __await__(self):
        async def _resolve():
            return self

        return _resolve().__await__()


class DualList(list):
    """A list that can also be awaited in async contexts."""

    def __await__(self):
        async def _resolve():
            return self

        return _resolve().__await__()


class MemoryManager:
    """Manages cross-session long-term memory for users and sessions.

    Wraps ``mem0.Memory`` with asynchronous/synchronous helpers and graceful fallback.

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

            # Force environment variables for OpenRouter / OpenAI routing
            if cfg.OPENROUTER_API_KEY:
                os.environ["OPENROUTER_API_KEY"] = cfg.OPENROUTER_API_KEY
                os.environ["OPENROUTER_API_BASE"] = cfg.OPENROUTER_BASE_URL
                os.environ["OPENAI_API_KEY"] = cfg.OPENROUTER_API_KEY
                os.environ["OPENAI_BASE_URL"] = cfg.OPENROUTER_BASE_URL

            if getattr(cfg, "HF_TOKEN", None):
                os.environ["HF_TOKEN"] = cfg.HF_TOKEN

            from mem0 import Memory  # type: ignore[import-untyped]

            mem0_llm_model: str = (
                getattr(cfg, "MEM0_LLM_MODEL", None)
                or getattr(cfg, "FAST_LLM_MODEL", None)
                or "openai/gpt-4o-mini"
            )

            vector_store: dict[str, Any] = vector_store_config(cfg)

            mem0_config: dict[str, Any] = {
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": mem0_llm_model,
                        "temperature": 0.1,
                        "max_tokens": 1000,
                        "openai_base_url": cfg.OPENROUTER_BASE_URL,
                        "openrouter_base_url": cfg.OPENROUTER_BASE_URL,
                        "api_key": cfg.OPENROUTER_API_KEY,
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
                "vector_store": vector_store,
            }

            try:
                self.mem0_client = Memory.from_config(mem0_config)
            except Exception as init_exc:
                logger.warning("Memory.from_config init failed, trying Memory(): %s", init_exc)
                self.mem0_client = Memory()

            logger.info(
                "MemoryManager initialised with mem0ai library (model=%s, base_url=%s, PII redaction active)",
                mem0_llm_model,
                cfg.OPENROUTER_BASE_URL,
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
                    self.mem0_client.search("warmup_query", filters={"user_id": "warmup_system"}, top_k=1)
                    logger.info("Pre-loaded mem0 memory models successfully", extra={"session_id": "SYSTEM"})
                except Exception as e:
                    logger.debug("mem0 search warm-up skipped: %s", e)

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _do_warmup)
        except Exception as exc:
            logger.warning("MemoryManager warm-up exception (non-fatal): %s", exc)

    def add_memory(
        self,
        *args: Any,
        user_id: Optional[str] = None,
        text: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> DualResult:
        """Store a new memory item for the specified user after PII redaction.

        Supports both positional and keyword argument variations, and both sync and async:
            res = mm.add_memory("Tôi tên là Nguyên", user_id="user_123")
            await mm.add_memory(user_id="user_123", text="Tôi tên là Nguyên")

        Args:
            *args: Positional text or user_id.
            user_id: User / Session correlation identifier.
            text: Memory content or key fact.
            metadata: Optional metadata dictionary.
            **kwargs: Extra arguments.

        Returns:
            DualResult: Memory addition result dictionary (awaitable).
        """
        target_user_id: str = user_id or kwargs.get("user_id", "")
        target_text: str = text or kwargs.get("text", "")

        if args:
            if len(args) == 1:
                if target_user_id:
                    target_text = str(args[0])
                elif target_text:
                    target_user_id = str(args[0])
                else:
                    target_text = str(args[0])
            elif len(args) >= 2:
                target_user_id = str(args[0])
                target_text = str(args[1])
                if len(args) >= 3 and metadata is None:
                    metadata = args[2]

        if not target_text or not target_user_id:
            return DualResult({"results": [], "status": "skipped_empty"})

        # Apply PII Redaction Pipeline
        clean_text = redact_pii(target_text)

        logger.debug(
            "Adding memory for user '%s' (PII redacted): %s",
            target_user_id,
            clean_text[:60],
            extra={"session_id": target_user_id},
        )

        if self.mem0_client is not None:
            try:
                res = self.mem0_client.add(
                    clean_text,
                    user_id=target_user_id,
                    metadata=metadata or {},
                )
                if isinstance(res, dict):
                    return DualResult(res)
                return DualResult({"results": res})
            except Exception as exc:
                logger.warning(
                    "mem0ai add_memory non-fatal failure (%s). Storing to fallback store.",
                    exc,
                    extra={"session_id": target_user_id},
                )

        # Fallback in-memory storage
        if target_user_id not in self._fallback_store:
            self._fallback_store[target_user_id] = []

        fallback_entry = {
            "id": uuid.uuid4().hex,
            "memory": clean_text,
            "metadata": metadata or {},
        }
        self._fallback_store[target_user_id].append(fallback_entry)
        return DualResult({"results": [{"memory": clean_text, "event": "ADD_FALLBACK"}]})

    def get_memories(
        self,
        user_id: str,
        limit: int = 5,
    ) -> DualList:
        """Retrieve all stored memories for a user.

        Supports both sync and async usage:
            memories = mm.get_memories("user_123")
            memories = await mm.get_memories("user_123")

        Args:
            user_id: User / Session correlation identifier.
            limit: Maximum number of memory items to return.

        Returns:
            DualList: List of memory text strings (awaitable).
        """
        if not user_id:
            return DualList([])

        memories: list[str] = []
        if self.mem0_client is not None:
            try:
                results: Any = self.mem0_client.get_all(
                    filters={"user_id": user_id},
                    top_k=limit,
                )
                items = (
                    results.get("results", [])
                    if isinstance(results, dict)
                    else (results if isinstance(results, list) else [])
                )
                for item in items:
                    if isinstance(item, dict) and "memory" in item:
                        memories.append(str(item["memory"]))
                    elif isinstance(item, str):
                        memories.append(item)
            except Exception as exc:
                logger.warning(
                    "mem0ai get_memories non-fatal exception (%s). Using fallback store.",
                    exc,
                    extra={"session_id": user_id},
                )

        if not memories and user_id in self._fallback_store:
            user_mems = self._fallback_store.get(user_id, [])
            memories = [m["memory"] for m in user_mems[-limit:]]

        return DualList(memories)

    def list_memories(self, user_id: str, limit: int = 100) -> list[dict[str, str]]:
        """What is remembered about one user, WITH ids (``get_memories`` returns bare text): ``[{"id", "memory", "created_at"}]``."""
        if not user_id:
            return []
        rows: list[dict[str, str]] = []
        if self.mem0_client is not None:
            try:
                results: Any = self.mem0_client.get_all(filters={"user_id": user_id}, top_k=limit)
                items = results.get("results", []) if isinstance(results, dict) else (results if isinstance(results, list) else [])
                rows = [
                    {"id": str(i["id"]), "memory": str(i["memory"]), "created_at": str(i.get("created_at") or "")}
                    for i in items if isinstance(i, dict) and i.get("id") and i.get("memory")
                ]
            except Exception as exc:  # noqa: BLE001
                logger.warning("mem0ai list_memories failed (%s)", exc or type(exc).__name__, extra={"session_id": user_id})
        rows += [{"id": m["id"], "memory": m["memory"], "created_at": ""} for m in self._fallback_store.get(user_id, []) if m.get("id")]
        return rows[:limit]

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """Forget one item. It must be one of THIS user's (the id alone is never enough), so nobody can delete another person's memory."""
        if memory_id not in {m["id"] for m in self.list_memories(user_id)}:
            return False
        if user_id in self._fallback_store:
            kept = [m for m in self._fallback_store[user_id] if m.get("id") != memory_id]
            if len(kept) != len(self._fallback_store[user_id]):
                self._fallback_store[user_id] = kept
                return True
        if self.mem0_client is None:
            return False
        self.mem0_client.delete(memory_id)
        return True

    def delete_all(self, user_id: str) -> int:
        """Forget everything about one user; returns how many items were removed."""
        count = len(self.list_memories(user_id, limit=10000))
        if user_id in self._fallback_store:
            self._fallback_store.pop(user_id)
        if self.mem0_client is not None:
            self.mem0_client.delete_all(user_id=user_id)
        return count

    def get_relevant_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 3,
    ) -> DualList:
        """Retrieve relevant memories for a user given a query.

        Supports both sync and async usage:
            memories = mm.get_relevant_memories("user_123", "query")
            memories = await mm.get_relevant_memories("user_123", "query")

        Args:
            user_id: User / Session correlation identifier.
            query: Current natural-language query.
            limit: Maximum number of memory items to return.

        Returns:
            DualList: List of relevant memory text strings (awaitable).
        """
        if not user_id:
            return DualList([])

        memories: list[str] = []
        if self.mem0_client is not None:
            try:
                results: Any = self.mem0_client.search(
                    query=query,
                    filters={"user_id": user_id},
                    top_k=limit,
                )
                items = (
                    results.get("results", [])
                    if isinstance(results, dict)
                    else (results if isinstance(results, list) else [])
                )
                for item in items:
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
                return DualList(memories)
            except Exception as exc:
                logger.warning(
                    "mem0ai search non-fatal exception (%s). Using fallback store.",
                    exc,
                    extra={"session_id": user_id},
                )

        # Fallback memory retrieval
        user_mems: list[dict[str, Any]] = self._fallback_store.get(user_id, [])
        return DualList([m["memory"] for m in user_mems[-limit:]])

