"""Chat history that does not forget: the Redis history keeps the last 5 turns, what falls off is folded into a short
running summary (``history_summary:<session>``) by one fast-model call in the background. The RAG planner reads it
together with the recent turns, so a follow-up to something said 8 turns ago can still be understood."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.config import settings
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

MAX_TURNS: int = 5
SUMMARY_CHARS: int = 800
_SYSTEM_PROMPT: str = (
    "You keep the running summary of a chat between a user and an assistant. Merge the old summary with the new "
    f"messages into ONE summary of at most {SUMMARY_CHARS} characters, in the language of the conversation. Keep "
    "names, document names, numbers and what the user is trying to find out; drop greetings and filler. "
    "Output only the summary."
)
_background: set[asyncio.Task[None]] = set()  # a task nobody references can be garbage-collected mid-run


async def persist_turn(redis_client: Any, llm_client: Any, session_id: str, query: str, answer: str) -> None:
    """Store one finished turn; summarise whatever the 5-turn cap pushed out (never delays or breaks the reply)."""
    dropped: list[dict[str, str]] = []
    for role, content in (("user", query), ("assistant", answer)):
        trimmed = await redis_client.append_to_history(session_id=session_id, role=role, content=content, max_turns=MAX_TURNS)
        if isinstance(trimmed, list):
            dropped += trimmed
    if dropped and llm_client is not None:
        task = asyncio.create_task(_fold(redis_client, llm_client, session_id, dropped))
        _background.add(task)
        task.add_done_callback(_background.discard)


async def _fold(redis_client: Any, llm_client: Any, session_id: str, dropped: list[dict[str, str]]) -> None:
    try:
        previous: str = await redis_client.get_history_summary(session_id)
        transcript: str = "\n".join(f"{m.get('role', 'user')}: {str(m.get('content', ''))[:500]}" for m in dropped)
        response: Any = await asyncio.wait_for(
            llm_client.chat_completion(
                model=settings.FAST_LLM_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"Old summary:\n{previous or '(none)'}\n\nNew messages:\n{transcript}"},
                ],
                temperature=0.0,
                max_tokens=300,
                metadata={"purpose": "history_summary"},
                session_id=session_id,
            ),
            timeout=20,
        )
        summary: str = (response.choices[0].message.content or "").strip()[:SUMMARY_CHARS]
        if summary:
            await redis_client.set_history_summary(session_id, summary)
    except Exception as exc:  # noqa: BLE001 - a summary is a convenience
        logger.warning("History summary skipped: %s", exc or type(exc).__name__, extra={"session_id": session_id})
