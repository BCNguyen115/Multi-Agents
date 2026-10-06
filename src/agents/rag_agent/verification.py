"""Deterministic checks on a RAG answer: which sources it cites, and whether its numbers exist in them.

The answer is usually Vietnamese and the sources usually English, so a number is read the way its own text writes it:

    "1.500.000 USD"  -> 1 500 000      (Vietnamese: dot groups thousands)      "1,500,000"  -> 1 500 000   (English)
    "1,5 triệu"      -> 1 500 000      (comma decimal, "triệu" = million)       "$1.5 million" -> 1 500 000
    "75.000"         -> 75 000         (not 75)                                 "0.125" / "3,14" -> decimals

A source that spells a number out ("thirty (30) days", "twenty-four months") supplies that value as well. Spelled-out numbers in
the ANSWER are not checked: Vietnamese ones collide with ordinary words ("hai bên" = both parties, "năm" = five and year) and
a change of unit ("two years" / "24 months") would reject honest answers.

Everything here is pure: no I/O, no settings.
"""

from __future__ import annotations

import re

_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_LIST_MARKER = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+")
_SOURCE_REF = re.compile(r"(?i)\b(?:sources?|nguồn)\s+\d+(?:\s*(?:,|and|và|&)\s*\d+)*")  # "Source 3", "Nguồn 1, 2 và 4": a source number is not a claim

_NUMBER = re.compile(r"(?<![\w.,])(\d[\d.,]*\d|\d)(?:\s?(%|phần trăm|percent)|\s?(nghìn|ngàn|triệu|tỷ|tỉ|thousand|million|billion|trillion|[KMBT])(?![A-Za-z]))?", re.IGNORECASE)
_MAGNITUDE = {"nghìn": 1e3, "ngàn": 1e3, "thousand": 1e3, "k": 1e3, "triệu": 1e6, "million": 1e6, "m": 1e6,
              "tỷ": 1e9, "tỉ": 1e9, "billion": 1e9, "b": 1e9, "trillion": 1e12, "t": 1e12}
_MONTH = re.compile(r"(?i)\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b")

_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * (i + 2) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_WORD = re.compile(r"[a-z]+")


# ---------------------------------------------------------------------------------------------------------------- citations

def citations(answer: str) -> list[int]:
    """Source numbers cited in ``answer`` (``[1]``, ``[2, 3]``), in order of first appearance."""
    found: list[int] = []
    for match in _CITATION.finditer(answer):
        for number in re.split(r"\s*,\s*", match.group(1)):
            if int(number) not in found:
                found.append(int(number))
    return found


# ---------------------------------------------------------------------------------------------------------------- numbers

def _interpret(token: str) -> list[tuple[float, int]]:
    """Values (and the number of decimals written) a digit token can mean; the first one is the most likely."""
    if token.isdigit():
        return [(float(token), 0)]
    separators = re.findall(r"[.,]", token)
    groups = re.split(r"[.,]", token)
    grouped = all(len(g) == 3 for g in groups[1:]) and 1 <= len(groups[0]) <= 3 and groups[0] != "0"
    if len(set(separators)) == 1 and grouped:
        thousands = (float("".join(groups)), 0)
        if len(separators) == 1 and separators[0] == ".":  # "12.345": thousands (Vietnamese) or three decimals (English)
            return [thousands, (float(token), 3)]
        return [thousands]
    if len(separators) == 1:  # "1,5" / "3.14" / "0.125": the separator is the decimal point
        return [(float(groups[0] + "." + groups[1]), len(groups[1]))]
    last = max(token.rfind("."), token.rfind(","))  # "1.234,56" / "1,234.56": the LAST separator is the decimal point
    integer, decimals = re.sub(r"[.,]", "", token[:last]), token[last + 1:]
    if not decimals.isdigit() or not integer.isdigit():
        return []
    return [(float(f"{integer}.{decimals}"), len(decimals))]


class Reading:
    """One number written in a text: the raw token and the values it can stand for ``(value, tolerance)``."""

    def __init__(self, raw: str, candidates: list[tuple[float, float]], percent: bool) -> None:
        self.raw, self.candidates, self.percent = raw, candidates, percent


def readings(text: str) -> list[Reading]:
    found: list[Reading] = []
    for match in _NUMBER.finditer(text):
        token, percent, scale = match.group(1), bool(match.group(2)), (match.group(3) or "").lower()
        multiplier = _MAGNITUDE.get(scale, 1.0)
        candidates = [(value * multiplier, 0.5 * 10 ** (-decimals) * multiplier * 1.001 + 1e-9) for value, decimals in _interpret(token)]
        if candidates:
            found.append(Reading(match.group(0).strip(), candidates, percent))
    return found


def english_number_words(text: str) -> list[float]:
    """Numbers a text spells out in English ("thirty", "twenty-four", "one hundred twenty", "two million")."""
    values: list[float] = []
    total = current = 0
    started = False

    def close() -> None:
        nonlocal total, current, started
        if started:
            values.append(float(total + current))
        total = current = 0
        started = False

    for word in _WORD.findall(text.lower().replace("-", " ")):
        if word in _UNITS:
            current += _UNITS[word]
            started = True
        elif word in _TENS:
            current += _TENS[word]
            started = True
        elif word == "hundred":
            current = (current or 1) * 100
            started = True
        elif word in _SCALES and started:
            total += (current or 1) * _SCALES[word]
            current = 0
        elif word != "and":
            close()
    close()
    return values


def _evidence(context: str) -> list[tuple[float, float]]:
    """Every ``(value, tolerance)`` the context supports, read both ways where the writing is ambiguous."""
    allowed: list[tuple[float, float]] = [candidate for reading in readings(context) for candidate in reading.candidates]
    allowed += [(value, 1e-9) for value in english_number_words(context)]
    if _MONTH.search(context):  # a date written as 15/03/2024 against "March 15, 2024"
        allowed += [(float(month), 1e-9) for month in range(1, 13)]
    return allowed


def _supported(reading: Reading, allowed: list[tuple[float, float]]) -> bool:
    for value, tolerance in reading.candidates:
        scaled = [value / 100] if reading.percent else []  # "5%" against a source that writes 0.05
        for known, known_tolerance in allowed:
            if any(abs(v - known) <= max(tolerance, known_tolerance, 1e-9 * max(abs(known), 1.0)) for v in (value, *scaled)):
                return True
    return False


def _claims(answer: str) -> str:
    """The answer without what is not a claim: citation markers, list numbering, "Source 3"."""
    return _SOURCE_REF.sub(" ", _LIST_MARKER.sub("", _CITATION.sub(" ", answer)))


def unsupported_numbers(answer: str, context: str) -> list[str]:
    """Numbers written in ``answer`` (as written there) that no number of ``context`` supports."""
    allowed = _evidence(context)
    return [reading.raw for reading in readings(_claims(answer)) if not _supported(reading, allowed)]


def unsupported_by_citations(answer: str, chunk_texts: list[str], per_sentence: bool = False) -> list[str]:
    """Like ``unsupported_numbers``, but a number must come from a chunk the answer CITES.

    Answer-level (default): the numbers may come from any cited chunk; with no citation at all, from any chunk (the missing
    citation is reported separately). ``per_sentence``: a sentence's numbers must come from the chunks cited in that sentence.
    """
    cited = [n for n in citations(answer) if 1 <= n <= len(chunk_texts)]
    everywhere = "\n".join(chunk_texts)
    if not cited:
        return unsupported_numbers(answer, everywhere)
    if not per_sentence:
        return unsupported_numbers(answer, "\n".join(chunk_texts[n - 1] for n in cited))
    missing: list[str] = []
    union = "\n".join(chunk_texts[n - 1] for n in cited)
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer):
        own = [n for n in citations(sentence) if 1 <= n <= len(chunk_texts)]
        missing += unsupported_numbers(sentence, "\n".join(chunk_texts[n - 1] for n in own) if own else union)
    return missing
