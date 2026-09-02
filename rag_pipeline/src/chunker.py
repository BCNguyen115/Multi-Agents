"""Section-Based Chunker for legal documents.

Takes ``SectionedDocument`` objects produced by the document loader and
creates contextually enriched chunks that respect section boundaries.

Strategy:
  1. Use the pre-identified section boundaries.
  2. Merge sections that are too small (< 600 chars) with neighbours.
  3. Split sections that are too large (> 6000 chars) using
     ``RecursiveCharacterTextSplitter`` with 10-15 % overlap.
  4. Prepend contextual metadata to each chunk.

Usage:
    from src.chunker import chunk_documents
    chunks = chunk_documents(sectioned_documents)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.document_loader import Section, SectionedDocument

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_CHUNK_SIZE: int = 600       # Minimum chunk length (chars)
MAX_CHUNK_SIZE: int = 6000      # Maximum chunk length (chars)
RECURSIVE_CHUNK_SIZE: int = 3000  # Target size when splitting oversized sections
OVERLAP_RATIO: float = 0.12      # 12 % overlap (~360 chars at 3000)
FALLBACK_CHUNK_SIZE: int = 3000   # Used when no sections were detected
FALLBACK_OVERLAP: int = 400       # Overlap for fallback splitter


# ---------------------------------------------------------------------------
# Data class for chunks
# ---------------------------------------------------------------------------


@dataclass
class DocumentChunk:
    """A single chunk of text ready for embedding.

    Attributes:
        content: The chunk text **with** contextual prefix already prepended.
        raw_content: The chunk text **without** the prefix (for dedup comparison).
        metadata: Metadata dictionary carried from the source document.
    """

    content: str
    raw_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_contextual_prefix(
    filename: str,
    category: str,
    section_title: str,
) -> str:
    """Build the contextual prefix prepended to each chunk.

    Args:
        filename: Source document filename.
        category: Document category (msa, nda, …).
        section_title: Title of the section this chunk belongs to.

    Returns:
        Formatted prefix string.
    """
    return f"[Source: {filename} | Category: {category} | Section: {section_title}]\n\n"


def _merge_small_sections(
    sections: list[Section],
    min_size: int = MIN_CHUNK_SIZE,
) -> list[Section]:
    """Merge consecutive sections whose content is shorter than *min_size*.

    Args:
        sections: Ordered list of sections.
        min_size: Minimum character count for a standalone section.

    Returns:
        New list of sections after merging.
    """
    if not sections:
        return sections

    merged: list[Section] = []
    buffer_title: str = sections[0].title
    buffer_content: str = sections[0].content
    buffer_start: int = sections[0].start_index
    buffer_end: int = sections[0].end_index

    for section in sections[1:]:
        if len(buffer_content) < min_size:
            # Merge current section into the buffer
            buffer_title = f"{buffer_title} + {section.title}"
            buffer_content = f"{buffer_content}\n\n{section.content}"
            buffer_end = section.end_index
        else:
            # Flush buffer and start new one
            merged.append(
                Section(
                    title=buffer_title,
                    content=buffer_content,
                    start_index=buffer_start,
                    end_index=buffer_end,
                )
            )
            buffer_title = section.title
            buffer_content = section.content
            buffer_start = section.start_index
            buffer_end = section.end_index

    # Flush remaining buffer
    merged.append(
        Section(
            title=buffer_title,
            content=buffer_content,
            start_index=buffer_start,
            end_index=buffer_end,
        )
    )

    # Final pass: if the last chunk is still too small, merge with previous
    if len(merged) >= 2 and len(merged[-1].content) < min_size:
        last: Section = merged.pop()
        merged[-1] = Section(
            title=f"{merged[-1].title} + {last.title}",
            content=f"{merged[-1].content}\n\n{last.content}",
            start_index=merged[-1].start_index,
            end_index=last.end_index,
        )

    return merged


def _split_oversized_section(
    section: Section,
    max_size: int = MAX_CHUNK_SIZE,
    target_size: int = RECURSIVE_CHUNK_SIZE,
    overlap_ratio: float = OVERLAP_RATIO,
) -> list[tuple[str, str]]:
    """Split a section that exceeds *max_size* using recursive text splitting.

    Args:
        section: The oversized section.
        max_size: Threshold above which splitting is triggered.
        target_size: Target chunk size for the recursive splitter.
        overlap_ratio: Fraction of overlap between sub-chunks.

    Returns:
        List of ``(sub_title, sub_content)`` tuples.
    """
    if len(section.content) <= max_size:
        return [(section.title, section.content)]

    overlap: int = int(target_size * overlap_ratio)
    splitter: RecursiveCharacterTextSplitter = RecursiveCharacterTextSplitter(
        chunk_size=target_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )
    sub_texts: list[str] = splitter.split_text(section.content)

    results: list[tuple[str, str]] = []
    for idx, sub_text in enumerate(sub_texts, start=1):
        sub_title: str = f"{section.title} (Part {idx}/{len(sub_texts)})"
        results.append((sub_title, sub_text))

    logger.debug(
        "Split section '%s' (%d chars) into %d sub-chunks",
        section.title[:50],
        len(section.content),
        len(results),
    )
    return results


# ---------------------------------------------------------------------------
# Fallback chunking (when no sections detected)
# ---------------------------------------------------------------------------


def _fallback_chunk(
    raw_text: str,
    filename: str,
    category: str,
    metadata: dict[str, Any],
) -> list[DocumentChunk]:
    """Chunk a document that has no detected section structure.

    Uses ``RecursiveCharacterTextSplitter`` with default sizes.

    Args:
        raw_text: Full document text.
        filename: Source filename.
        category: Document category.
        metadata: Base metadata dict.

    Returns:
        List of ``DocumentChunk`` objects.
    """
    splitter: RecursiveCharacterTextSplitter = RecursiveCharacterTextSplitter(
        chunk_size=FALLBACK_CHUNK_SIZE,
        chunk_overlap=FALLBACK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )
    texts: list[str] = splitter.split_text(raw_text)

    chunks: list[DocumentChunk] = []
    for idx, text in enumerate(texts):
        prefix: str = _build_contextual_prefix(filename, category, f"Part {idx + 1}")
        chunk_meta: dict[str, Any] = {
            **metadata,
            "section_title": f"Part {idx + 1}",
            "chunk_index": idx,
            "chunk_method": "fallback_recursive",
        }
        chunks.append(
            DocumentChunk(
                content=prefix + text,
                raw_content=text,
                metadata=chunk_meta,
            )
        )

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chunk_documents(
    documents: list[SectionedDocument],
) -> list[DocumentChunk]:
    """Convert a list of sectioned documents into contextually enriched chunks.

    Pipeline:
      1. Merge small sections (< 600 chars).
      2. Split oversized sections (> 6000 chars) with overlap.
      3. Prepend contextual prefix to each chunk.

    Args:
        documents: List of ``SectionedDocument`` objects from the loader.

    Returns:
        Flat list of ``DocumentChunk`` objects ready for embedding.
    """
    all_chunks: list[DocumentChunk] = []

    for doc in documents:
        # If loader couldn't detect sections, use fallback
        if len(doc.sections) <= 1 and doc.detected_pattern == "none":
            chunks: list[DocumentChunk] = _fallback_chunk(
                raw_text=doc.raw_text,
                filename=doc.filename,
                category=doc.category,
                metadata=doc.metadata,
            )
            all_chunks.extend(chunks)
            logger.info(
                "[%s] %s → %d chunks (fallback)",
                doc.category,
                doc.filename,
                len(chunks),
            )
            continue

        # Step 1: Merge small sections
        merged_sections: list[Section] = _merge_small_sections(doc.sections)

        # Step 2 & 3: Split oversized + build chunks
        chunk_index: int = 0
        for section in merged_sections:
            sub_chunks: list[tuple[str, str]] = _split_oversized_section(section)

            for sub_title, sub_content in sub_chunks:
                prefix: str = _build_contextual_prefix(
                    doc.filename, doc.category, sub_title
                )
                chunk_meta: dict[str, Any] = {
                    **doc.metadata,
                    "section_title": sub_title,
                    "chunk_index": chunk_index,
                    "chunk_method": "section_based",
                    "detected_pattern": doc.detected_pattern,
                }
                all_chunks.append(
                    DocumentChunk(
                        content=prefix + sub_content,
                        raw_content=sub_content,
                        metadata=chunk_meta,
                    )
                )
                chunk_index += 1

        logger.info(
            "[%s] %s → %d chunks (%d sections, pattern=%s)",
            doc.category,
            doc.filename,
            chunk_index,
            len(merged_sections),
            doc.detected_pattern,
        )

    # Post-processing: filter out noise chunks (very short raw content)
    min_raw_content: int = 50  # Absolute minimum for meaningful content
    filtered_chunks: list[DocumentChunk] = []
    filtered_count: int = 0
    for chunk in all_chunks:
        if len(chunk.raw_content.strip()) < min_raw_content:
            filtered_count += 1
            logger.debug(
                "Filtered tiny chunk (%d chars): %s",
                len(chunk.raw_content),
                chunk.raw_content[:80].replace("\n", " "),
            )
        else:
            filtered_chunks.append(chunk)

    if filtered_count > 0:
        logger.info(
            "Filtered out %d noise chunks (< %d chars raw content)",
            filtered_count,
            min_raw_content,
        )

    logger.info("Total chunks created: %d", len(filtered_chunks))
    return filtered_chunks
