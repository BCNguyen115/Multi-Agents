"""Chat upload -> knowledge base.

A PDF/DOCX attached in the chat goes through the SAME loader, contextual prefix, embedding model, per-document
dedup and atomic ``replace_document`` as the folder ingestion (``scripts/run_ingestion.py``), so its rows in
``rag_chunks`` are indistinguishable from the existing ones (same columns, ``doc_key`` = ``<category>/<filename>``,
``doc_hash``, page, ``[Source: file - Section: title]`` prefix). Only the chunk sizes differ, by request:

  * one chunk per section; a section shorter than ``MIN_SECTION`` is merged with the NEXT one (the last one, with the
    previous one when the result still fits);
  * a section longer than ``MAX_SECTION`` is split into several chunks of similar length (cut at paragraph, sentence
    or word boundaries), so no text is lost; ``split`` in the result says how many sections were split;
  * a document without detectable sections (plain prose) is cut into pieces of at most ``MAX_SECTION`` the same way.

Usage:
    result = await ingest_upload(embedder, "contract.pdf", data, category="nda", dataset_dir="dataset")
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.ingestion.chunker import MIN_RAW_CONTENT, DocumentChunk, _build_contextual_prefix, _page_of
from src.config import settings
from src.ingestion.context import contextualize_chunks
from src.ingestion.document_loader import SUPPORTED_EXTENSIONS, Section, SectionedDocument, load_document
from src.ingestion.ocr import ocr_available
from src.ingestion.embedder import IngestionEmbedder
from src.shared.isolated import IsolatedError, run_isolated
from src.shared.logger import get_logger
from src.shared.messages import msg

logger: logging.Logger = get_logger(__name__)

MIN_SECTION: int = 200
MAX_SECTION: int = 600
DEFAULT_CATEGORY: str = "general"
MAX_CHUNKS: int = 2000  # one upload must not turn into an unbounded embedding bill

# Known categories of the corpus and the words that identify them in a filename or the first page.
_CATEGORY_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("nda", re.compile(r"\bnda\b|non-?disclosure|confidentiality agreement", re.IGNORECASE)),
    ("msa", re.compile(r"\bmsa\b|master (?:services?|subscription) agreement", re.IGNORECASE)),
    ("sow", re.compile(r"\bsow\b|statement of work", re.IGNORECASE)),
    ("purchase", re.compile(r"purchase (?:order|agreement)", re.IGNORECASE)),
)
_SAFE_NAME = re.compile(r"[^\w.\- ()]+", re.UNICODE)


class UploadError(ValueError):
    """The upload cannot be turned into knowledge (bad type, no text, too big); the message is for the user."""


@dataclass
class ChunkReport:
    sections: int = 0       # sections found in the document
    chunks: int = 0         # chunks produced
    merged: int = 0         # sections folded into a neighbour because they were < MIN_SECTION
    split: int = 0          # sections longer than MAX_SECTION that became several chunks (no text is lost)
    dropped: int = 0        # chunks under MIN_RAW_CONTENT characters (noise)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def safe_filename(name: str) -> str:
    """Base name only, no path or odd characters: it becomes part of ``doc_key`` and of a path on disk."""
    base: str = _SAFE_NAME.sub("_", Path(name.replace("\\", "/")).name).strip(" .")
    if not base or Path(base).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UploadError(msg("upload.unsupported"))
    return base[-150:]


def safe_category(category: str | None) -> str | None:
    """Lower-case slug (``[a-z0-9_-]``), or ``None`` when nothing usable is left."""
    slug: str = re.sub(r"[^a-z0-9_-]+", "-", (category or "").strip().lower()).strip("-")[:40]
    return slug or None


def infer_category(filename: str, text: str, known: list[str]) -> str:
    """Category of a document nobody labelled: an existing category named in the filename or the first page, else ``general``."""
    for source in (filename, text[:3000]):
        for name in known:
            if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", source, re.IGNORECASE):
                return name
        for name, pattern in _CATEGORY_HINTS:
            if pattern.search(source):
                return name
    return DEFAULT_CATEGORY


# ---------------------------------------------------------------------------
# Chunking: 200-600 characters per section
# ---------------------------------------------------------------------------


def merge_short_sections(sections: list[Section], min_size: int = MIN_SECTION, max_size: int = MAX_SECTION) -> tuple[list[Section], int]:
    """Fold every section shorter than ``min_size`` into the next one. Returns ``(sections, folded)``.

    A short LAST section has no next one: it joins the previous section when the result still fits ``max_size``
    (nothing would be cut), otherwise it stays on its own.
    """
    merged: list[Section] = []
    folded: int = 0
    buffer: Section | None = None
    for section in sections:
        if buffer is None:
            buffer = section
        elif len(buffer.content) < min_size:
            buffer = Section(f"{buffer.title} + {section.title}", f"{buffer.content}\n\n{section.content}", buffer.start_index, section.end_index)
            folded += 1
        else:
            merged.append(buffer)
            buffer = section
    if buffer is not None:
        if merged and len(buffer.content) < min_size and len(merged[-1].content) + 2 + len(buffer.content) <= max_size:
            previous: Section = merged.pop()
            buffer = Section(f"{previous.title} + {buffer.title}", f"{previous.content}\n\n{buffer.content}", previous.start_index, buffer.end_index)
            folded += 1
        merged.append(buffer)
    return merged, folded


def split_oversized(text: str, max_size: int = MAX_SECTION) -> list[str]:
    """``text`` as pieces of at most ``max_size`` characters, of similar length, cut at paragraph/sentence/word boundaries.

    Nothing is dropped: a long section becomes several chunks instead of one chunk that loses its tail.
    """
    if len(text) <= max_size:
        return [text]
    count: int = -(-len(text) // max_size)
    size: int = min(max_size, -(-len(text) // count) + 40)  # a little slack so boundaries do not create one more tiny piece
    splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=0, separators=["\n\n", "\n", ". ", " ", ""], length_function=len)
    return splitter.split_text(text)


def _paragraph_sections(doc: SectionedDocument) -> list[Section]:
    """Pseudo-sections for prose without headings: pieces of at most ``MAX_SECTION`` characters (nothing is cut away)."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=MAX_SECTION, chunk_overlap=0, separators=["\n\n", "\n", ". ", " ", ""], length_function=len
    )
    sections: list[Section] = []
    cursor: int = 0
    for index, piece in enumerate(splitter.split_text(doc.raw_text), start=1):
        found: int = doc.raw_text.find(piece[:60], cursor)
        start: int = found if found >= 0 else cursor
        cursor = start + 1
        sections.append(Section(f"Part {index}", piece, start, start + len(piece)))
    return sections


def build_upload_chunks(doc: SectionedDocument) -> tuple[list[DocumentChunk], ChunkReport]:
    """Section-based chunks of ``doc`` with the same prefix and metadata the folder ingestion produces."""
    structured: bool = not (len(doc.sections) <= 1 and doc.detected_pattern == "none")
    sections: list[Section] = doc.sections if structured else _paragraph_sections(doc)
    report: ChunkReport = ChunkReport(sections=len(sections))
    merged, report.merged = merge_short_sections(sections)

    page_starts: list[int] = doc.metadata.get("page_starts", [])
    base_meta: dict[str, Any] = {k: v for k, v in doc.metadata.items() if k != "page_starts"}
    chunks: list[DocumentChunk] = []
    for section in merged:
        pieces: list[str] = split_oversized(section.content)
        if len(pieces) > 1:
            report.split += 1
        cursor: int = 0
        for text in pieces:
            found: int = section.content.find(text[:60], cursor)
            offset: int = found if found >= 0 else cursor
            cursor = offset + 1
            if len(text.strip()) < MIN_RAW_CONTENT:
                report.dropped += 1
                continue
            meta: dict[str, Any] = {
                **base_meta,
                "section_title": section.title,
                "chunk_index": len(chunks),
                "chunk_method": "section_upload",
                "detected_pattern": doc.detected_pattern,
                "page": _page_of(section.start_index + offset, page_starts),  # a long section can run over onto the next page
            }
            chunks.append(DocumentChunk(content=_build_contextual_prefix(doc.filename, doc.category, section.title) + text, raw_content=text, metadata=meta))
    report.chunks = len(chunks)
    return chunks, report


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


MAX_ARCHIVE_ENTRIES: int = 10_000


def check_file(filename: str, data: bytes) -> None:
    """Refuse a file whose bytes are not what its name claims, or that would blow up when opened. Cheap, in-process, safe."""
    ext: str = Path(filename).suffix.lower()
    if ext == ".pdf":
        ok = b"%PDF-" in data[:1024]
    elif ext in (".docx", ".pptx"):
        if not zipfile.is_zipfile(io.BytesIO(data)):
            ok = False
        else:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ARCHIVE_ENTRIES or sum(e.file_size for e in entries) > settings.KNOWLEDGE_MAX_UNCOMPRESSED_MB * 1024 * 1024:
                    raise UploadError(msg("upload.archive_too_big", mb=settings.KNOWLEDGE_MAX_UNCOMPRESSED_MB))
            ok = True
    else:  # .txt / .md: text has no NUL bytes
        ok = b"\x00" not in data[:8192]
    if not ok:
        raise UploadError(msg("upload.bad_content", ext=ext))


def _parse(path: str, category: str, filename: str) -> SectionedDocument | None:
    """Open the file. In a child process with a deadline and memory limit unless ``KNOWLEDGE_PARSE_ISOLATED`` is off (tests, dev)."""
    if not settings.KNOWLEDGE_PARSE_ISOLATED:
        return load_document(path, category, filename)
    try:
        return run_isolated(
            load_document, path, category, filename,
            timeout=settings.KNOWLEDGE_PARSE_TIMEOUT_SECONDS, memory_mb=settings.KNOWLEDGE_PARSE_MEMORY_MB,
        )
    except TimeoutError:
        logger.warning("Parsing %s took longer than %s s: stopped", filename, settings.KNOWLEDGE_PARSE_TIMEOUT_SECONDS, extra={"session_id": "INGESTION"})
        raise UploadError(msg("upload.parse_timeout")) from None
    except IsolatedError as exc:
        logger.warning("Parsing %s failed in its worker: %s", filename, exc, extra={"session_id": "INGESTION"})
        return None  # reads as an unreadable file


def _load(data: bytes, filename: str, category: str | None, known: list[str]) -> SectionedDocument:
    """Blocking: write the bytes to a temp file (the readers want a path) and analyse it. Runs in a worker thread."""
    with tempfile.TemporaryDirectory() as tmp:
        path: Path = Path(tmp) / filename
        path.write_bytes(data)
        doc: SectionedDocument | None = _parse(str(path), category or DEFAULT_CATEGORY, filename)
        if doc is None:
            raise UploadError(msg("upload.no_text_ocr" if ocr_available() else "upload.no_text"))
        if category is None:  # the text is only known now: settle the category, and with it the document identity
            resolved: str = infer_category(filename, doc.raw_text, known)
            doc.category = resolved
            doc.metadata.update(category=resolved, doc_key=f"{resolved}/{filename}")
        doc.filepath = doc.metadata["source"] = filename  # the temp path is meaningless once the request is over
        return doc


def _save_copy(data: bytes, dataset_dir: str, category: str, filename: str) -> bool:
    """Keep the file in ``<dataset>/<category>/`` so ``run_ingestion --prune`` / ``--reset`` still find it. Best effort."""
    try:
        target: Path = Path(dataset_dir) / category / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return True
    except OSError as exc:
        logger.warning("Could not keep a copy of %s in the dataset folder: %s", filename, exc, extra={"session_id": "INGESTION"})
        return False


async def ingest_upload(
    embedder: IngestionEmbedder,
    filename: str,
    data: bytes,
    category: str | None = None,
    dataset_dir: str | None = None,
    known_categories: list[str] | None = None,
    max_chunks: int = MAX_CHUNKS,
    session_id: str = "INGESTION",
    llm_client: Any = None,
) -> dict[str, Any]:
    """Add or update one document in the knowledge base. Raises ``UploadError`` for input problems.

    Returns ``status`` (``added`` / ``updated`` / ``unchanged``), the resolved ``category``, chunk counts and
    ``saved_to_dataset``. An embedding or database failure propagates as is (the transaction leaves the old chunks).
    """
    filename = safe_filename(filename)
    category = safe_category(category)
    check_file(filename, data)
    doc: SectionedDocument = await asyncio.to_thread(_load, data, filename, category, known_categories or [])
    chunks, report = build_upload_chunks(doc)
    if not chunks:
        raise UploadError(msg("upload.no_chunks", min=MIN_RAW_CONTENT))
    if len(chunks) > max_chunks:
        raise UploadError(msg("upload.too_many_chunks", count=len(chunks), limit=max_chunks))

    contextualized: int = 0
    if llm_client is not None and settings.KB_LLM_CONTEXT:  # one LLM sentence per chunk: where it sits in its document
        contextualized = await contextualize_chunks(llm_client, doc.raw_text, chunks, session_id=session_id)

    key: str = doc.metadata["doc_key"]
    rows = await embedder.pg.fetch(
        "SELECT count(*) AS n FROM rag_chunks WHERE doc_key = $1 OR (doc_key IS NULL AND category = $2 AND filename = $3)",
        key, doc.category, filename, session_id=session_id,
    )
    previous: int = int(rows[0]["n"]) if rows else 0
    stats: dict[str, Any] = await embedder.ingest(chunks, session_id=session_id)
    if stats["failed"]:
        raise RuntimeError(f"Không ghi được tài liệu {key} vào knowledge base.")
    unchanged: bool = stats["docs_skipped"] > 0
    saved: bool = bool(dataset_dir) and not unchanged and await asyncio.to_thread(_save_copy, data, dataset_dir, doc.category, filename)
    logger.info(
        "Knowledge upload %s: %s, %d chunks (%d merged, %d split, %d duplicates removed), replaced %d",
        key, "unchanged" if unchanged else "stored", report.chunks, report.merged, report.split, stats["removed"], previous,
        extra={"session_id": session_id},
    )
    return {
        "status": "unchanged" if unchanged else ("updated" if previous else "added"),
        "filename": filename,
        "category": doc.category,
        "doc_key": key,
        "sections": report.sections,
        "chunks": 0 if unchanged else stats["inserted"],
        "merged": report.merged,
        "split": report.split,
        "dropped": report.dropped,
        "duplicates_removed": stats["removed"],
        "replaced_chunks": 0 if unchanged else previous,
        "pages": len(doc.metadata.get("page_starts", [])) or None,
        "ocr": bool(doc.metadata.get("ocr")),
        "contextualized": contextualized,
        "saved_to_dataset": saved,
    }
