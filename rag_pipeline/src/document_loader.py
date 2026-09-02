"""Document Loader & Section Analyzer for legal documents.

Recursively traverses the dataset directory, extracts text from PDF and DOCX
files, and analyzes document structure to identify section boundaries
(ARTICLE, SECTION, numbered headings, etc.) for downstream section-based
chunking.

Usage:
    from src.document_loader import load_and_analyze_documents
    documents = load_and_analyze_documents("../dataset")
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from pypdf import PdfReader

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """A single identified section within a document.

    Attributes:
        title: The heading / identifier of the section (e.g. "Article 1").
        content: The full text content of the section.
        start_index: Character offset where this section starts in the raw text.
        end_index: Character offset where this section ends in the raw text.
    """

    title: str
    content: str
    start_index: int
    end_index: int


@dataclass
class SectionedDocument:
    """A document that has been loaded and analyzed for section boundaries.

    Attributes:
        filename: Original filename (e.g. ``contract.pdf``).
        filepath: Absolute path to the source file.
        category: Subdirectory name (e.g. ``msa``, ``nda``).
        raw_text: The complete extracted text.
        sections: Ordered list of identified sections.
        detected_pattern: Name of the regex pattern family that matched best.
        metadata: Arbitrary key-value metadata carried through the pipeline.
    """

    filename: str
    filepath: str
    category: str
    raw_text: str
    sections: list[Section] = field(default_factory=list)
    detected_pattern: str = "none"
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Section heading patterns (ordered by specificity / priority)
# ---------------------------------------------------------------------------

# Each tuple: (compiled_regex, human-readable name, flags)
# The regex MUST capture the full heading line so we can split on it.

SECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ARTICLE I / ARTICLE 1 / ARTICLE 10
    (
        re.compile(
            r"(?m)^[ \t]*(ARTICLE\s+(?:[IVXLCDM]+|\d+)[\.:\s—–-]*.*)$",
            re.IGNORECASE,
        ),
        "ARTICLE",
    ),
    # SECTION 1.01 / Section 1 / SECTION 2
    (
        re.compile(
            r"(?m)^[ \t]*((?:SECTION|Sec\.?)\s+\d+(?:\.\d+)*[\.:\s—–-]*.*)$",
            re.IGNORECASE,
        ),
        "SECTION",
    ),
    # Numbered heading: 1. DEFINITIONS / 2. Term
    (
        re.compile(
            r"(?m)^[ \t]*(\d{1,2}\.[ \t]+[A-Z].{2,80})$",
        ),
        "NUMBERED_HEADING",
    ),
    # Decimal sub-sections: 1.1 / 2.3.1
    (
        re.compile(
            r"(?m)^[ \t]*(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?[ \t]+.{2,80})$",
        ),
        "DECIMAL_SUBSECTION",
    ),
    # ALL-CAPS headings (at least 6 chars, on their own line)
    (
        re.compile(
            r"(?m)^[ \t]*([A-Z][A-Z \t]{5,})$",
        ),
        "ALL_CAPS_HEADING",
    ),
]


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------


def _extract_pdf_text(filepath: str) -> str:
    """Extract all text from a PDF file using pypdf.

    Args:
        filepath: Absolute or relative path to the PDF.

    Returns:
        Concatenated text from all pages, or empty string on failure.
    """
    try:
        reader: PdfReader = PdfReader(filepath)
        pages: list[str] = []
        for page in reader.pages:
            page_text: str | None = page.extract_text()
            if page_text:
                pages.append(page_text)
        return "\n".join(pages)
    except Exception as exc:
        logger.warning("Failed to read PDF %s: %s", filepath, exc)
        return ""


def _extract_docx_text(filepath: str) -> str:
    """Extract all text from a DOCX file using python-docx.

    Args:
        filepath: Absolute or relative path to the DOCX.

    Returns:
        Concatenated paragraph text, or empty string on failure.
    """
    try:
        doc: DocxDocument = DocxDocument(filepath)
        paragraphs: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as exc:
        logger.warning("Failed to read DOCX %s: %s", filepath, exc)
        return ""


# ---------------------------------------------------------------------------
# Section analysis
# ---------------------------------------------------------------------------


def _detect_best_pattern(text: str) -> tuple[re.Pattern[str], str]:
    """Determine which section-heading pattern best fits the document.

    Strategy: try each pattern in priority order and pick the one with the
    most matches (minimum 2 to avoid false positives).  If none meets the
    threshold, fall back to ALL_CAPS_HEADING or return ``None``.

    Args:
        text: The full document text.

    Returns:
        A tuple of ``(compiled_pattern, pattern_name)``.  If nothing matched,
        returns the ALL_CAPS_HEADING pattern as a fallback.
    """
    best_pattern: re.Pattern[str] = SECTION_PATTERNS[-1][0]
    best_name: str = SECTION_PATTERNS[-1][1]
    best_count: int = 0

    for pattern, name in SECTION_PATTERNS:
        matches: list[str] = pattern.findall(text)
        if len(matches) >= 2 and len(matches) > best_count:
            best_count = len(matches)
            best_pattern = pattern
            best_name = name

    if best_count >= 2:
        logger.debug(
            "Best pattern: %s (%d matches)", best_name, best_count
        )
    else:
        logger.debug("No strong pattern found, using ALL_CAPS_HEADING fallback")

    return best_pattern, best_name


def _split_into_sections(
    text: str,
    pattern: re.Pattern[str],
    pattern_name: str,
) -> list[Section]:
    """Split document text into sections using the detected heading pattern.

    Args:
        text: Full document text.
        pattern: The compiled regex for section headings.
        pattern_name: Human-readable name for logging.

    Returns:
        Ordered list of ``Section`` objects. If no splits are found, returns
        the entire text as a single section.
    """
    # Find all heading positions
    matches: list[re.Match[str]] = list(pattern.finditer(text))

    if not matches:
        return [
            Section(
                title="Full Document",
                content=text.strip(),
                start_index=0,
                end_index=len(text),
            )
        ]

    sections: list[Section] = []

    # If there is text before the first heading, capture it as a preamble
    if matches[0].start() > 0:
        preamble_text: str = text[: matches[0].start()].strip()
        if preamble_text:
            sections.append(
                Section(
                    title="Preamble",
                    content=preamble_text,
                    start_index=0,
                    end_index=matches[0].start(),
                )
            )

    # Split on each heading
    for i, match in enumerate(matches):
        heading: str = match.group(1).strip()
        start: int = match.start()
        end: int = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text: str = text[start:end].strip()

        sections.append(
            Section(
                title=heading,
                content=section_text,
                start_index=start,
                end_index=end,
            )
        )

    logger.debug(
        "Split into %d sections using pattern '%s'",
        len(sections),
        pattern_name,
    )
    return sections


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_and_analyze_documents(
    dataset_dir: str,
    supported_extensions: tuple[str, ...] = (".pdf", ".docx"),
) -> list[SectionedDocument]:
    """Load all documents from a dataset directory and analyze their structure.

    Recursively walks ``dataset_dir``, extracts text from each supported file,
    detects the best section-heading pattern, and splits the text into
    ordered sections.

    Args:
        dataset_dir: Root directory containing categorised document folders.
        supported_extensions: File extensions to process (default: pdf, docx).

    Returns:
        List of ``SectionedDocument`` objects ready for chunking.

    Raises:
        FileNotFoundError: If ``dataset_dir`` does not exist.
    """
    dataset_path: Path = Path(dataset_dir).resolve()
    if not dataset_path.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_path}")

    documents: list[SectionedDocument] = []
    skipped: int = 0

    for root, _dirs, files in os.walk(dataset_path):
        for filename in sorted(files):
            ext: str = os.path.splitext(filename)[1].lower()
            if ext not in supported_extensions:
                skipped += 1
                continue

            filepath: str = os.path.join(root, filename)
            # Determine category from the immediate parent folder name
            category: str = Path(root).name
            if category == dataset_path.name:
                category = "root"

            logger.info("Loading: [%s] %s", category, filename)

            # Extract text
            if ext == ".pdf":
                raw_text: str = _extract_pdf_text(filepath)
            elif ext == ".docx":
                raw_text = _extract_docx_text(filepath)
            else:
                continue

            if not raw_text.strip():
                logger.warning("Empty text extracted from %s — skipping", filename)
                skipped += 1
                continue

            # Analyze section structure
            pattern, pattern_name = _detect_best_pattern(raw_text)
            sections: list[Section] = _split_into_sections(
                raw_text, pattern, pattern_name
            )

            doc = SectionedDocument(
                filename=filename,
                filepath=filepath,
                category=category,
                raw_text=raw_text,
                sections=sections,
                detected_pattern=pattern_name,
                metadata={
                    "source": filepath,
                    "filename": filename,
                    "category": category,
                    "total_chars": len(raw_text),
                    "num_sections": len(sections),
                },
            )
            documents.append(doc)

    logger.info(
        "Loaded %d documents (%d skipped) from %s",
        len(documents),
        skipped,
        dataset_path,
    )
    return documents
