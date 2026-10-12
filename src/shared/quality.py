"""Online answer grading: a small share of real answers (``QUALITY_SAMPLE_RATE``) is graded 1 to 5 by a model in the background and kept in
``answer_reviews``, so the Quality page can show how answers fare WITHOUT waiting for users to press a thumb (most never do).

Care taken: it never delays or breaks a reply (a background task, every failure only logged); personal data is masked and the texts are cut
before they are stored; rows older than ``QUALITY_RETENTION_DAYS`` are deleted; and nothing is graded unless the database is configured.
The grader sees the question and the answer only, so it judges what a user would judge: is the answer on topic, specific and consistent with
itself. "Is every number in the sources" is the Verifier's job, not this one's.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any, Optional

from src.config import settings
from src.shared.auth import current_principal
from src.shared.logger import get_logger
from src.shared.memory_manager import redact_pii
from src.shared.security import unwrap_user_input

logger: logging.Logger = get_logger(__name__)

MAX_QUERY_CHARS = 1000
MAX_ANSWER_CHARS = 3000
_PURGE_ODDS = 0.02  # about one grading in fifty also deletes the expired rows: no scheduler needed

_pg: Any = None
_background: set[asyncio.Task[Any]] = set()  # a task nobody references can be garbage-collected mid-run

PROMPT = (
    "You grade an AI assistant's answer to a user's question, the way a careful colleague would.\n"
    "Score 1-5: 5 = fully answers the question, specific, consistent, nothing invented; 4 = good with a small gap; 3 = partly answers or vague; "
    "2 = mostly misses the point, contradicts itself or dodges; 1 = wrong, empty, off topic or harmful.\n"
    "A polite refusal that says what is missing is a fair 3, not a 1. Do not reward length.\n"
    'Reply with ONLY JSON: {"score": <1-5>, "reason": "<one sentence, same language as the question, max 200 characters>"}\n\n'
    "QUESTION:\n%s\n\nANSWER:\n%s"
)


def configure(pg_client: Any) -> None:
    """Called once by the gateway at start-up; until then (unit tests, scripts) nothing is graded."""
    global _pg
    _pg = pg_client


def answer_text(raw: str) -> str:
    """The words a user read: the ``answer`` / ``explanation`` of a JSON reply, else the text itself."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if isinstance(parsed, dict):
        for key in ("answer", "explanation", "response", "content"):
            if isinstance(parsed.get(key), str) and parsed[key].strip():
                return parsed[key]
    return raw


def parse_grade(raw: str) -> Optional[tuple[int, str]]:
    """``(score, reason)`` from the model's reply, or ``None`` when it did not follow the format."""
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        score = int(data["score"])
    except (ValueError, KeyError, TypeError):
        return None
    if not 1 <= score <= 5:
        return None
    return score, str(data.get("reason", ""))[:200]


async def review(llm_client: Any, model: str, who: Any, agent: str, query: str, answer: str, verified: bool, retries: int, session_id: str) -> bool:
    """Grade one answer and store the grade; ``False`` when it could not (logged, never raised)."""
    try:
        question = redact_pii(unwrap_user_input(query)[0])[:MAX_QUERY_CHARS]
        text = redact_pii(answer_text(answer))[:MAX_ANSWER_CHARS]
        if not question.strip() or not text.strip() or _pg is None:
            return False
        response = await llm_client.chat_completion(
            messages=[{"role": "user", "content": PROMPT % (question, text)}], model=model, temperature=0.0, max_tokens=150,
            metadata={"node": "quality_review"}, session_id=session_id,
        )
        grade = parse_grade(response.choices[0].message.content or "")
        if grade is None:
            logger.info("Quality review skipped: the grader's reply was not the expected JSON")
            return False
        await _pg.execute(
            "INSERT INTO answer_reviews (tenant_id, user_id, agent, query, answer, score, reason, verified, retries, model) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
            getattr(who, "tenant_id", ""), getattr(who, "user_id", ""), agent[:40], question, text, grade[0], grade[1], verified, retries, model[:80],
        )
        if random.random() < _PURGE_ODDS:
            await _pg.execute("DELETE FROM answer_reviews WHERE at < now() - make_interval(days => $1)", settings.QUALITY_RETENTION_DAYS)
        return True
    except Exception as exc:  # noqa: BLE001 - grading is a measurement, never part of the reply
        logger.warning("Quality review failed: %s", exc or type(exc).__name__)
        return False


def maybe_review(llm_client: Any, model: str, agent: str, query: str, answer: str, verified: bool, retries: int, session_id: str) -> Optional["asyncio.Task[Any]"]:
    """Grade this answer in the background with probability ``QUALITY_SAMPLE_RATE``; returns the task (None when it was not sampled)."""
    rate = settings.QUALITY_SAMPLE_RATE
    if _pg is None or llm_client is None or rate <= 0 or random.random() >= rate:
        return None
    who = current_principal()  # resolved now, in the request's context
    task = asyncio.get_running_loop().create_task(review(llm_client, model, who, agent, query, answer, verified, retries, session_id))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task
