"""What goes into the answer prompt: retrieved chunks screened for injection and fenced as untrusted data.

Dataset text is data. Every source sits in an envelope ``<<<BEGIN_UNTRUSTED_EXTERNAL_SOURCE ...>>>`` and nothing inside a chunk or
its labels can forge the envelope markers (they are built from ``<<<`` and ``>>>``, which are neutralised).
"""

from __future__ import annotations

import re
from typing import Any

from src.shared.security import indirect_injection_threats

_HEADER_CHARS: int = 200


def neutralize(text: str) -> str:
    """Make ``text`` unable to forge envelope markers."""
    return text.replace("<<<", "‹‹‹").replace(">>>", "›››")


def header(value: Any) -> str:
    """A metadata value (file name, section title) as a safe single-line label."""
    return neutralize(re.sub(r"\s+", " ", str(value or "")).strip())[:_HEADER_CHARS]


def looks_like_injection(text: str) -> bool:
    """A chunk is dropped only for strong signals (instruction override, safety bypass...). The weak "persona"
    pattern fires on ordinary contract wording ("acting as agent", "operate as a joint venture": ~2% of the
    real corpus); such chunks stay, still fenced as untrusted data."""
    return any(not threat.startswith("Persona Hijack") for threat in indirect_injection_threats(text))


def build_context(chunks: list[dict[str, Any]]) -> str:
    """Numbered sources in untrusted envelopes; nothing from a chunk or its labels can close the envelope."""
    parts: list[str] = []
    for number, chunk in enumerate(chunks, start=1):
        label: str = f"[Nguồn {number}] {header(chunk.get('filename'))} | {header(chunk.get('section_title'))}"
        if chunk.get("page"):
            label += f" | trang {int(chunk['page'])}"
        parts.append(
            f'<<<BEGIN_UNTRUSTED_EXTERNAL_SOURCE id="{number}" trust_level="zero">>>\n'
            f"{label}\n{neutralize(chunk['content'])}\n<<<END_UNTRUSTED_EXTERNAL_SOURCE>>>"
        )
    return "\n\n".join(parts)
