"""Quote-grounded answers (``RAG_QUOTE_MODE``): every cited source comes with a verbatim quote that is CHECKED.

The sources are usually English and the answer Vietnamese, so a Vietnamese sentence cannot be matched against its source word by
word. What can be checked deterministically is the quote: the model appends

    <evidence>
    [1] "the term of this Agreement is two (2) years"
    [3] "payable within thirty (30) days of receipt"
    </evidence>

and each quote must occur in the source it names (ignoring case, whitespace and quote marks). A citation whose quote is not found
is reported (``unquoted_citations``); the user sees the quotes that passed next to the source and can read the evidence themselves.

Pure functions, no I/O.
"""

from __future__ import annotations

import re

QUOTE_RULE: str = (
    "7. Sau câu trả lời, thêm đúng một khối bằng chứng, mỗi nguồn đã trích dẫn ít nhất một dòng:\n"
    "<evidence>\n"
    '[n] "một đoạn NGUYÊN VĂN ngắn (tối đa 25 từ) lấy từ Nguồn n, giữ nguyên ngôn ngữ của nguồn, không dịch, không sửa"\n'
    "</evidence>\n"
)

_OPEN = "<evidence>"
_BLOCK = re.compile(r"<evidence>(.*?)(?:</evidence>|\Z)", re.IGNORECASE | re.DOTALL)
_LINE = re.compile(r"^\s*\[(\d+)\]\s*[\"“”«»'‘’]?(.+?)[\"“”«»'‘’]?\s*$")
_MIN_PIECE = 12  # a quote shorter than this proves nothing (it occurs in any text)


def split_evidence(raw: str) -> tuple[str, list[tuple[int, str]]]:
    """``(answer without the evidence block, [(source number, quote), ...])``. A block cut off by the length limit still counts."""
    quotes: list[tuple[int, str]] = []
    for block in _BLOCK.findall(raw):
        for line in block.splitlines():
            match = _LINE.match(line)
            if match and match.group(2).strip():
                quotes.append((int(match.group(1)), match.group(2).strip()))
    return _BLOCK.sub("", raw).strip(), quotes


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\"“”«»'‘’`]", "", text)).strip().casefold()


def quote_in_source(quote: str, source: str) -> bool:
    """Is ``quote`` (cut with ``...`` / ``…`` into pieces) found in ``source``? Every piece of 12+ characters must be."""
    haystack = _normal(source)
    pieces = [_normal(p) for p in re.split(r"\.{3}|…", quote)]
    long_pieces = [p for p in pieces if len(p) >= _MIN_PIECE]
    return bool(long_pieces) and all(p in haystack for p in long_pieces)


def check_quotes(quotes: list[tuple[int, str]], source_texts: list[str]) -> dict[int, list[str]]:
    """Per source number: the quotes that really occur in that source (a number outside the sources is ignored)."""
    valid: dict[int, list[str]] = {}
    for number, quote in quotes:
        if 1 <= number <= len(source_texts) and quote_in_source(quote, source_texts[number - 1]):
            valid.setdefault(number, []).append(quote)
    return valid


class VisibleText:
    """Feeds streamed pieces and returns only the part that is NOT the evidence block (nor the start of one).

    The block is for the checker, not for the reader: nothing from ``<evidence>`` on may reach the preview, and a piece that
    ends in ``<evid`` is held back until the next one shows whether it is the marker.
    """

    def __init__(self) -> None:
        self._text = ""
        self._sent = 0

    def feed(self, piece: str) -> str:
        self._text += piece
        cut = self._text.lower().find(_OPEN)
        if cut >= 0:
            limit = cut
        else:
            limit = len(self._text)
            for size in range(min(len(_OPEN) - 1, len(self._text)), 0, -1):  # a suffix that could still become the marker
                if _OPEN.startswith(self._text[-size:].lower()):
                    limit = len(self._text) - size
                    break
        out = self._text[self._sent:limit] if limit > self._sent else ""
        self._sent = max(self._sent, limit)
        return out

    def flush(self) -> str:
        """What is left at the end of the stream: a held-back suffix that never became the marker."""
        if self._text.lower().find(_OPEN) >= 0:
            return ""
        out = self._text[self._sent:]
        self._sent = len(self._text)
        return out
