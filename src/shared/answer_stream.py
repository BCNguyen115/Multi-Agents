"""Answer tokens on their way to the browser, while the answer is still being written.

The PEV loop verifies an answer only after the agent has produced it, so what streams out first is a PREVIEW: the final,
verified text arrives later in ``final_response`` and replaces it (the UI says so). The orchestrator's SSE generator
attaches an ``AnswerStream`` to the request's context; an agent that can stream (the RAG agent) looks it up with
``current()`` and pushes text as the model produces it. No stream attached (the JSON endpoint, tests, other callers) means
no streaming and no change in behaviour.

Events put on the queue, as ``("answer", {"event": ..., "data": <json>})``:
  * ``answer_delta``  ``{"text": "..."}``  more text to append to the preview;
  * ``answer_reset``  ``{}``               discard the preview (a retry after the Verifier rejected the answer starts over).
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional


class AnswerStream:
    """Per-request sink for answer text. At most one writer at a time (``claim``), so parallel sub-answers never interleave."""

    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue: asyncio.Queue = queue
        self._claimed: bool = False
        self._started: bool = False

    def claim(self) -> bool:
        """Become the writer; ``False`` when another agent is already writing. Pair with ``release``."""
        if self._claimed:
            return False
        self._claimed = True
        return True

    def release(self) -> None:
        self._claimed = False

    async def _put(self, event: str, payload: dict) -> None:
        await self._queue.put(("answer", {"event": event, "data": json.dumps(payload, ensure_ascii=False)}))

    async def delta(self, text: str) -> None:
        if text:
            self._started = True
            await self._put("answer_delta", {"text": text})

    async def restart(self) -> None:
        """A new attempt begins: if the previous one showed text, tell the UI to drop it."""
        if self._started:
            self._started = False
            await self._put("answer_reset", {})


_current: ContextVar[Optional[AnswerStream]] = ContextVar("answer_stream", default=None)


def current() -> Optional[AnswerStream]:
    return _current.get()


def attach(stream: AnswerStream):
    """Make ``stream`` the current one for this context (and the tasks created from it); returns a token for ``detach``."""
    return _current.set(stream)


def detach(token) -> None:
    _current.reset(token)


@contextmanager
def suspended() -> Iterator[None]:
    """No streaming inside the block: for parallel sub-answers that a later synthesis step merges into the real answer."""
    token = _current.set(None)
    try:
        yield
    finally:
        _current.reset(token)
