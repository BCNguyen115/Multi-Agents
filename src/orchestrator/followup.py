"""Follow-up questions for every agent: "and for 2024?" is rewritten into a question that stands on its own, from the session's recent chat.

The RAG agent does this inside its own planner; the other agents (search, database, integration, data) saw only the bare sentence and
answered the wrong thing. One fast-model call, only for a SHORT question in a session that already has history, and any failure leaves
the question exactly as the user typed it. The nonce wrapper around the user's text is kept, so the agents still treat it as untrusted.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from src.config import settings
from src.shared.logger import get_logger
from src.shared.security import unwrap_user_input

logger: logging.Logger = get_logger(__name__)

MAX_WORDS = 12  # longer questions are assumed to carry their own context
MAX_REWRITE_CHARS = 400
HISTORY_MESSAGES = 6
_TIMEOUT_SECONDS = 8

_PROMPT = (
    "Rewrite the user's LAST message as one standalone question, using the chat only to fill in what it leaves out "
    "(who/what/which period). Keep the user's language and meaning; add nothing new. If it already stands on its own, "
    "return it unchanged. Output only the question.\n\nCHAT:\n%s\n\nLAST MESSAGE:\n%s"
)


def looks_like_followup(raw: str) -> bool:
    return 0 < len(raw.split()) <= MAX_WORDS


async def standalone(llm_client: Any, redis_client: Any, session_id: str, query: str) -> str:
    """``query`` made self-contained, or ``query`` itself when there is nothing to add or anything goes wrong."""
    if not settings.FOLLOWUP_REWRITE or llm_client is None or redis_client is None:
        return query
    raw, nonce = unwrap_user_input(query)
    if not looks_like_followup(raw):
        return query
    try:
        history = (await redis_client.get_history(session_id=session_id))[-HISTORY_MESSAGES:]
        if not history:
            return query
        chat = "\n".join(f"{m.get('role', 'user')}: {str(m.get('content', ''))[:300]}" for m in history)
        response = await asyncio.wait_for(
            llm_client.chat_completion(
                model=settings.FAST_LLM_MODEL, messages=[{"role": "user", "content": _PROMPT % (chat, raw)}],
                temperature=0.0, max_tokens=120, metadata={"node": "rewriter"}, session_id=session_id,
            ),
            timeout=_TIMEOUT_SECONDS,
        )
        rewritten = _clean(response.choices[0].message.content or "")
    except Exception as exc:  # noqa: BLE001 - the user's own words are always a safe fallback
        logger.info("Follow-up rewrite skipped: %s", exc or type(exc).__name__)
        return query
    if not rewritten or rewritten == raw:
        return query
    return f'<user_untrusted_input nonce="{nonce}">\n{rewritten}\n</user_untrusted_input nonce="{nonce}">' if nonce else rewritten


def _clean(text: str) -> Optional[str]:
    text = text.strip().strip('"').strip()
    if not text or len(text) > MAX_REWRITE_CHARS or "user_untrusted_input" in text:
        return None  # a reply that is not a question (or tries to forge the wrapper) is not used
    return text
