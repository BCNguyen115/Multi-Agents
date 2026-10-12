"""Checks on the API call the Integration Agent is about to make, BEFORE it makes it.

What this agent says about the result is not the risk (it prints the response it got), the request is: an LLM turns a sentence into
a URL and a method, and may invent either. Two things are enforced here, in code:

1. the URL is one the user wrote or one of ``KNOWN_ENDPOINTS`` (never an address the model made up);
2. a method that changes data (``MUTATING_METHODS``) is never run by ``process_request``: it only runs after a human approved the
   exact request (``Orchestrator.handle_approval_decision``). The gate asks the agent to parse the request once and ``process_request``
   parses it again; two LLM samples of the same sentence can differ, so the second one must not be trusted to still be a GET.

Pure: no I/O, no settings.
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlparse

# The endpoints the agent's prompt offers by default (keep in sync with _INTEGRATION_SYSTEM_PROMPT; tests/test_integration_verification.py checks it)
KNOWN_ENDPOINTS: tuple[str, ...] = ("http://localhost:8000/health",)
MUTATING_METHODS: tuple[str, ...] = ("POST", "PUT", "PATCH", "DELETE")


def _key(url: str) -> str:
    """Host + path of a URL without scheme, ``www.`` or trailing slash."""
    parts = urlparse(url.strip())
    return f"{parts.netloc.lower().removeprefix('www.')}{parts.path.rstrip('/')}"


def check_call(query: str, url: str, method: str, known: Iterable[str] = KNOWN_ENDPOINTS) -> list[str]:
    """Problems with the call (empty = fine): ``url_not_in_request`` and/or ``mutation_needs_approval``."""
    problems: list[str] = []
    wanted = _key(url)
    written = re.sub(r"https?://(www\.)?", "", query.lower())
    if wanted not in {_key(endpoint) for endpoint in known} and wanted not in written:
        problems.append("url_not_in_request")
    if method.upper() in MUTATING_METHODS:
        problems.append("mutation_needs_approval")
    return problems
