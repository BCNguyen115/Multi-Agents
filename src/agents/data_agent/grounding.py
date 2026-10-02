"""Number grounding: every number in a story must exist in the fact table.

The check extracts each number from the text (understanding ``1,234``, ``1.20M``, ``12.5%``) and matches it
against every numeric value in the facts, within the tolerance implied by how many digits the text shows.
Labels that merely *contain* digits (``2024-03``, ``Region 5``) are removed first, because they are names,
not claims.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

_NUMBER = re.compile(r"(?<![\w.])([-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?)(\s?%|[KMBT](?![A-Za-z]))?")
_SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
_DEFAULT_LITERALS = (3, 10, 80)  # numbers that appear in the story templates themselves ("top 3", "80%", "top 10%")


def _walk(value: Any, numbers: list[float], strings: list[str]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        numbers.append(float(value))
    elif isinstance(value, str):
        strings.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk(item, numbers, strings)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk(item, numbers, strings)


def collect_evidence(facts: Iterable[Any], extra_numbers: Iterable[float] = (), extra_strings: Iterable[str] = ()) -> tuple[list[float], list[str]]:
    """All numeric values and all string values (names, periods) present in the facts."""
    numbers: list[float] = [float(n) for n in extra_numbers]
    strings: list[str] = [s for s in extra_strings if s]
    for fact in facts:
        _walk(fact.numbers, numbers, strings)
        _walk(fact.refs, numbers, strings)
        _walk(getattr(fact, "caveats", []), numbers, strings)  # e.g. the partial periods a total excluded
    return numbers, sorted(set(strings), key=len, reverse=True)


def extract_numbers(text: str) -> list[tuple[float, float, bool]]:
    """``(value, tolerance, is_percent)`` for each number in ``text``."""
    found = []
    for match in _NUMBER.finditer(text):
        raw, suffix = match.group(1), (match.group(2) or "").strip()
        multiplier = _SUFFIX.get(suffix, 1.0)
        decimals = len(raw.split(".")[1]) if "." in raw and "e" not in raw.lower() else 0
        value = float(raw.replace(",", "")) * multiplier
        found.append((value, 0.5 * 10 ** (-decimals) * multiplier * 1.001 + 1e-9, suffix == "%"))
    return found


def numbers_grounded(
    text: str,
    facts: Iterable[Any],
    extra_numbers: Iterable[float] = (),
    extra_strings: Iterable[str] = (),
    literals: Iterable[float] = _DEFAULT_LITERALS,
) -> tuple[bool, list[str]]:
    """``(ok, unmatched)``: ``unmatched`` lists numbers in ``text`` that no fact supports."""
    numbers, strings = collect_evidence(facts, extra_numbers, extra_strings)
    cleaned = text
    for name in strings:
        if any(ch.isdigit() for ch in name):
            cleaned = cleaned.replace(name, " ")
    allowed = numbers + [float(x) for x in literals]

    unmatched: list[str] = []
    for value, tolerance, is_percent in extract_numbers(cleaned):
        magnitude = abs(value)
        candidates = [abs(v) for v in allowed] + [abs(v) * 100 for v in allowed if is_percent]
        if not any(abs(magnitude - c) <= max(tolerance, 1e-9 * max(c, 1.0)) for c in candidates):
            unmatched.append(f"{value:g}{'%' if is_percent else ''}")
    return not unmatched, unmatched
