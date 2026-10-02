"""OCR for scanned PDFs (pages that are pictures, with no text layer).

``pypdfium2`` renders each page to an image (a pip wheel, no poppler) and Tesseract reads it. Tesseract is a system program,
installed in the backend image (``tesseract-ocr`` + the Vietnamese and English language data); on a machine without it
``ocr_available()`` is False and a scanned PDF is refused with the same message as before. OCR is slow (about 1-2 s per page)
and approximate (accents, small print, tables), so it is capped (``OCR_MAX_PAGES``) and the caller tells the user the text was
read by OCR.
"""

from __future__ import annotations

import logging
import shutil
from typing import Optional

from src.config import settings
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)


def ocr_available() -> bool:
    """OCR switched on, the Tesseract program present and the Python wrappers importable."""
    if not settings.OCR_ENABLED or shutil.which("tesseract") is None:
        return False
    try:
        import pypdfium2  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def _languages(requested: str) -> str:
    """The requested Tesseract languages that are actually installed (``vie+eng``), else English."""
    import pytesseract

    try:
        installed = set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001 - listing failed: let Tesseract try the requested ones
        return requested
    usable = [lang for lang in requested.split("+") if lang in installed]
    return "+".join(usable) or "eng"


def ocr_pdf_pages(path: str, max_pages: Optional[int] = None, dpi: Optional[int] = None, langs: Optional[str] = None) -> list[str]:
    """Text of every page of ``path`` read by OCR (blocking: call it in a worker thread). ``[]`` when OCR is unavailable."""
    if not ocr_available():
        return []
    import pypdfium2 as pdfium
    import pytesseract

    max_pages = max_pages or settings.OCR_MAX_PAGES
    scale = (dpi or settings.OCR_DPI) / 72
    language = _languages(langs or settings.OCR_LANGS)
    pdf = pdfium.PdfDocument(path)
    try:
        total = len(pdf)
        pages: list[str] = []
        for index in range(min(total, max_pages)):
            image = pdf[index].render(scale=scale).to_pil().convert("L")
            pages.append(pytesseract.image_to_string(image, lang=language).strip())
        if total > max_pages:
            logger.warning("OCR read the first %d of %d pages (OCR_MAX_PAGES)", max_pages, total, extra={"session_id": "INGESTION"})
        return pages
    finally:
        pdf.close()
