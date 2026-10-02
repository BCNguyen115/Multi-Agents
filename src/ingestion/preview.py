"""A page of a stored PDF as an image, with the cited passage highlighted.

Used by ``GET /api/knowledge/page``: the answer cites ``[n]`` -> file, page, snippet; the UI shows the page so the reader can
check the wording in context. ``pypdfium2`` renders the page and finds the snippet's words on it; the matches are shaded
with a translucent rectangle. If the snippet cannot be found (scan, a PDF whose text order differs, OCR text) the page is
returned plain: a missing highlight never hides the page.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional

MAX_SCALE = 3.0
_PROBE_WORDS = 6  # a window this long is unlikely to occur twice on a page and short enough to survive line breaks


def _windows(snippet: str) -> list[str]:
    """Phrases of the snippet to look for: the whole start first, then sliding windows of a few words."""
    words = [w for w in re.sub(r"\s+", " ", snippet).strip().split(" ") if w]
    if not words:
        return []
    phrases = [" ".join(words[:18])]
    phrases += [" ".join(words[i:i + _PROBE_WORDS]) for i in range(0, max(len(words) - _PROBE_WORDS + 1, 1), _PROBE_WORDS)]
    seen: set[str] = set()
    return [p for p in phrases if len(p) >= 12 and not (p in seen or seen.add(p))]


def _alnum(text: str) -> tuple[str, list[int]]:
    """Lower-case letters and digits of ``text`` only, and where each one sat: spacing, hyphenation and punctuation differ
    between a PDF's text layer and the chunk stored from it, the letters do not."""
    chars: list[str] = []
    where: list[int] = []
    for position, char in enumerate(text):
        if char.isalnum():
            chars.append(char.lower())
            where.append(position)
    return "".join(chars), where


def _span_boxes(textpage, snippet: str) -> list[tuple[float, float, float, float]]:
    """Character boxes of ONE continuous stretch of the page that reads like the snippet (empty when none does)."""
    wanted, _ = _alnum(snippet)
    page_text = textpage.get_text_range()
    have, where = _alnum(page_text)
    probe = 28
    if len(wanted) < probe or len(have) < probe:
        return []
    start = have.find(wanted[:probe])
    if start < 0 or have.count(wanted[:probe]) > 1:
        return []  # not on this page, or the opening words occur twice: do not guess
    stop = min(start + len(wanted), len(have)) - 1
    boxes = []
    for index in range(where[start], where[stop] + 1):
        left, bottom, right, top = textpage.get_charbox(index)
        if right > left and top > bottom:
            boxes.append((left, bottom, right, top))
    return boxes


def find_boxes(page, snippet: str) -> list[tuple[float, float, float, float]]:
    """Rectangles ``(left, bottom, right, top)`` in PDF points where the snippet is on ``page``."""
    textpage = page.get_textpage()
    boxes: list[tuple[float, float, float, float]] = []
    try:
        boxes = _span_boxes(textpage, snippet)
        if boxes:
            return boxes
        return _phrase_boxes(textpage, snippet)
    finally:
        textpage.close()


def _phrase_boxes(textpage, snippet: str) -> list[tuple[float, float, float, float]]:
    """Fallback: shade the individual phrases of the snippet that the PDF's own search can find."""
    boxes: list[tuple[float, float, float, float]] = []
    phrases = _windows(snippet)
    for position, phrase in enumerate(phrases):
        searcher = textpage.search(phrase)
        while True:
            hit = searcher.get_next()
            if hit is None:
                break
            start, count = hit
            for i in range(start, start + count):
                left, bottom, right, top = textpage.get_charbox(i)
                if right > left and top > bottom:
                    boxes.append((left, bottom, right, top))
        if boxes and position == 0:
            break  # the whole start matched: no need for the sliding windows
    return boxes


def _merge_line_boxes(boxes: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    """Character boxes -> one rectangle per text line (same baseline), so the highlight is a few bars, not hundreds of tiles."""
    lines: dict[int, list[float]] = {}
    for left, bottom, right, top in boxes:
        key = round((bottom + top) / 2 / 3)  # characters of one line differ by less than ~3 points in height centre
        merged = lines.setdefault(key, [left, bottom, right, top])
        merged[0], merged[1] = min(merged[0], left), min(merged[1], bottom)
        merged[2], merged[3] = max(merged[2], right), max(merged[3], top)
    return [(v[0], v[1], v[2], v[3]) for v in lines.values()]


def render_page(path: str | Path, page_number: int, snippet: Optional[str] = None, scale: float = 1.6) -> tuple[bytes, int, bool]:
    """PNG bytes of page ``page_number`` (1-based) of ``path``, the page count, and whether a highlight was drawn."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw

    scale = max(0.5, min(scale, MAX_SCALE))
    pdf = pdfium.PdfDocument(str(path))
    try:
        total = len(pdf)
        if not 1 <= page_number <= total:
            raise IndexError(f"page {page_number} of {total}")
        page = pdf[page_number - 1]
        image = page.render(scale=scale).to_pil().convert("RGBA")
        highlighted = False
        if snippet:
            boxes = _merge_line_boxes(find_boxes(page, snippet))
            if boxes:
                overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                height = page.get_height()
                for left, bottom, right, top in boxes:
                    # PDF origin is bottom-left; the image's is top-left
                    draw.rectangle(
                        [left * scale - 2, (height - top) * scale - 2, right * scale + 2, (height - bottom) * scale + 2],
                        fill=(255, 214, 0, 90), outline=(245, 158, 11, 200),
                    )
                image = Image.alpha_composite(image, overlay)
                highlighted = True
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), total, highlighted
    finally:
        pdf.close()
