"""Deterministic checks on a web answer: which of the pages it was given does it link to, and do its numbers exist in them.

The search agent has no table to recompute against, but it does have evidence: the exact text of the pages the model was shown.
So an answer is trusted only when (1) it links at least one of those pages, (2) every link it writes is one of them (no
invented address) and (3) every number it states appears in those pages or in the question. Pure: no I/O, no settings.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from src.agents.rag_agent.verification import unsupported_numbers

_LINK = re.compile(r"https?://[^\s)\]>\"']+")
_TRAILING = ".,;:!?"


def _key(url: str) -> str:
    """Host + path + query of a URL, without scheme, ``www.``, fragment or trailing slash: the same page written two ways compares equal."""
    parts = urlparse(url.strip().rstrip(_TRAILING))
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}" + (f"?{parts.query}" if parts.query else "")


def _host(url: str) -> str:
    return urlparse(url.strip().rstrip(_TRAILING)).netloc.lower().removeprefix("www.")


def _printed_by(url: str, sources: list[dict[str, str]]) -> int | None:
    """Position of the page that itself prints ``url`` on its own website: a section page (``/cong-nghe.html``) lists its articles, and an
    article link taken from that list is the page's own, not an invented address. A link printed on a page but pointing to ANOTHER
    website does not count: a page cannot get an outside address into the answer by writing it in its text."""
    clean = url.rstrip(_TRAILING)
    for position, source in enumerate(sources, start=1):
        if _host(source["url"]) == _host(clean) and clean in source["text"]:
            return position
    return None


def verify_web_answer(answer: str, sources: list[dict[str, str]], question: str = "") -> dict[str, Any]:
    """``sources``: ``{"title", "url", "text"}`` in the order the model saw them (``text`` as the model saw it, i.e. after sanitising)."""
    numbered = {_key(source["url"]): position for position, source in enumerate(sources, start=1)}
    cited: list[int] = []
    unknown: list[str] = []
    for url in dict.fromkeys(_LINK.findall(answer)):
        position = numbered.get(_key(url)) or _printed_by(url, sources)
        if position is None:
            unknown.append(url.rstrip(_TRAILING))
        elif position not in cited:
            cited.append(position)
    evidence = "\n".join([question, *(f"{source['title']}\n{source['text']}" for source in sources)])
    return {
        "kind": "web",
        "status": "ok",
        "grounded": bool(cited) and not unknown,
        "cited": cited,
        "unknown_urls": unknown,
        "unsupported_numbers": unsupported_numbers(_LINK.sub(" ", answer), evidence),  # an address is not a claim: its digits are not checked
    }
