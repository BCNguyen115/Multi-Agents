"""Small passages of a chunk, for "small-to-big" retrieval (``RAG_PASSAGE_SEARCH``).

A folder-ingested chunk is 600 to 6000 characters. Its embedding is the average of everything in it, and the cross-encoder only
reads its first ``MAX_RERANK_TEXT_LENGTH`` characters, so the sentence that answers a question can be both diluted in the vector
and invisible to the reranker. A passage is a ~600 character window of the chunk: the search finds the passage that matches, the
reranker reads that passage, and the answer is still written from the whole chunk (the "big" part).

Pure functions, no I/O.
"""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

PASSAGE_CHARS: int = 600
PASSAGE_OVERLAP: int = 100
MIN_CHUNK_FOR_PASSAGES: int = 800  # a shorter chunk is already its own passage: it is not split


def split_passages(raw_content: str, size: int = PASSAGE_CHARS, overlap: int = PASSAGE_OVERLAP) -> list[str]:
    """The passages of one chunk (``[]`` when the chunk is short enough to be searched as it is). Nothing is lost: the
    windows overlap and together cover the whole text."""
    text: str = (raw_content or "").strip()
    if len(text) < MIN_CHUNK_FOR_PASSAGES:
        return []
    splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap, separators=["\n\n", "\n", ". ", " ", ""])
    return [p.strip() for p in splitter.split_text(text) if p.strip()]
