"""Contextual retrieval: one short sentence per chunk saying where it sits in its document.

A chunk like "The term is 24 months." says nothing about WHICH agreement, parties or clause; the embedding and the keyword
index then cannot tell it from the same sentence in ten other contracts. An LLM reads the start of the document and the
chunk and writes that missing context (``[Context: ...]``), which is stored in the chunk's ``content`` (what is embedded,
full-text indexed and shown to the answering model) while ``raw_content`` stays the original text.

It costs one small LLM call per chunk, so it is optional (``KB_LLM_CONTEXT``, ``run_ingestion --llm-context``,
``scripts/recontext.py``); whether it pays off is measured with ``scripts/run_rag_eval.py``, see docs/RAG_REVIEW_AND_FIXES.md.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from src.config import settings
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

CONTEXT_MARK = "[Context:"
CONTEXT_PATTERN = re.compile(r"\[Context:[^\]]*\]\s*")
EXCERPT_CHARS = 2500
MAX_CONTEXT_CHARS = 300

_SYSTEM = (
    "You write one line of search-index context for a passage taken from a document. Given the document's beginning, the "
    "section title and the passage, write ONE sentence (at most 40 words), in the language of the passage, that says which "
    "document this is (type, parties, subject) and what the passage covers, so that the passage can be found on its own. "
    "Do not repeat the passage, do not add facts that are not in the text, no preamble. Output only the sentence."
)


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip().strip('"').replace("[", "(").replace("]", ")")
    return text[:MAX_CONTEXT_CHARS].rstrip()


async def generate_context(llm: Any, excerpt: str, section: str, passage: str, session_id: str = "INGESTION") -> str:
    """The context sentence for ``passage``; ``""`` when the model fails (the chunk is then stored without one)."""
    prompt = (
        f"<document_beginning>\n{excerpt[:EXCERPT_CHARS]}\n</document_beginning>\n\n"
        f"<section>{section}</section>\n\n<passage>\n{passage[:1500]}\n</passage>"
    )
    try:
        response = await llm.chat_completion(
            model=settings.FAST_LLM_MODEL,
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=120,
            metadata={"purpose": "kb_chunk_context"},
            session_id=session_id,
        )
        return _clean(response.choices[0].message.content or "")
    except Exception as exc:  # noqa: BLE001 - a missing context only makes that chunk a little harder to find
        logger.warning("Context generation failed: %s", exc, extra={"session_id": session_id})
        return ""


def apply_context(content: str, raw_content: str, context: str) -> str:
    """``content`` (``<prefix><raw>``) with ``[Context: ...]`` between the prefix and the text; unchanged without a context."""
    if not context:
        return content
    base = CONTEXT_PATTERN.sub("", content, count=1) if CONTEXT_MARK in content else content
    cut = len(base) - len(raw_content) if base.endswith(raw_content) else 0
    return f"{base[:cut]}{CONTEXT_MARK} {context}]\n\n{base[cut:]}"


async def contextualize(
    llm: Any,
    document_text: str,
    items: list[tuple[str, str]],
    concurrency: int = 6,
    session_id: str = "INGESTION",
) -> list[str]:
    """Context sentences for ``items`` = ``(section_title, raw_content)`` of ONE document, in the same order."""
    semaphore = asyncio.Semaphore(max(1, concurrency))
    excerpt = document_text[:EXCERPT_CHARS]

    async def one(section: str, raw: str) -> str:
        async with semaphore:
            return await generate_context(llm, excerpt, section, raw, session_id)

    return list(await asyncio.gather(*(one(section, raw) for section, raw in items)))


async def contextualize_chunks(llm: Any, document_text: str, chunks: list, concurrency: int = 6, session_id: str = "INGESTION") -> int:
    """Add a context sentence to every ``DocumentChunk`` of one document (in place). Returns how many got one."""
    contexts = await contextualize(llm, document_text, [(c.metadata.get("section_title", ""), c.raw_content) for c in chunks], concurrency, session_id)
    added = 0
    for chunk, context in zip(chunks, contexts):
        if context:
            chunk.content = apply_context(chunk.content, chunk.raw_content, context)
            added += 1
    return added
