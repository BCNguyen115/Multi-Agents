"""A deterministic second look at a finished patch, before a person sees it and again before anything is pushed.

The ideas come from how an autonomous-agent action monitor is described in the Claude Code prompt collection: judge the CONTENT that is
written and committed (not only the command that ships it), treat a removed safeguard as seriously as an added hazard, decode before
judging, and take plain statements of intent in comments at face value. Here they become a short list of rules over the unified diff.

Two severities. ``high`` makes the work not ready for review and makes the publisher refuse it. ``medium`` is shown to the reviewer. A rule
that fires is a reason to look, not a verdict on the author: the reviewer decides, and the sandbox's own protections do not depend on this.
"""

from __future__ import annotations

import re
from typing import Any, Optional

CODE_SUFFIXES = (".py", ".js", ".mjs", ".ts", ".tsx", ".sh")
SAFE_HOSTS = ("localhost", "127.0.0.1", "example.com", "example.org", "example.test", "github.com", "docs.python.org", "pypi.org")

# (rule, regex over ONE added line of non-test code, severity)
ADDED_RULES: tuple[tuple[str, "re.Pattern[str]", str], ...] = (
    ("shell-true", re.compile(r"shell\s*=\s*True"), "high"),
    ("os-command", re.compile(r"\bos\.(system|popen)\s*\("), "high"),
    ("dynamic-exec", re.compile(r"(?<![\w.])(eval|exec)\s*\(|\bnew\s+Function\s*\("), "high"),
    ("unsafe-deserialization", re.compile(r"\b(pickle|marshal|cPickle)\.loads?\s*\(|\byaml\.load\s*\((?![^)]*Loader)"), "high"),
    ("tls-verification-off", re.compile(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED"), "high"),
    ("hook-or-signing-bypass", re.compile(r"--no-verify|--no-gpg-sign|gpgsign\s*=\s*false"), "high"),
    ("remote-script", re.compile(r"(curl|wget)[^\n|]*\|\s*(ba)?sh\b"), "high"),
    ("world-writable", re.compile(r"chmod\s+(-R\s+)?0?777"), "high"),
    ("stated-intent", re.compile(r"#.*\b(bypass|disable|ignore|skip)\b.{0,20}\b(auth|authentication|authorization|security|verification|the guard|the check)\b", re.I), "high"),
)
ENCODED = re.compile(r"b64decode|base64\s+-d|fromhex|\\x[0-9a-f]{2}\\x[0-9a-f]{2}", re.I)
EXECUTES = re.compile(r"\b(exec|eval|subprocess|os\.system|Popen)\b")
URL = re.compile(r"https?://([A-Za-z0-9.-]+)")
# what a removed line says about a safeguard
GUARDS = re.compile(
    r"Depends\(\s*(authenticate|require_admin)|require_admin|audit\.record|can_approve|status_code\s*=\s*40[13]|compare_digest|"
    r"is_protected|check_patch|find_secrets|validate_\w+|_may_write|safe_join|enforce\(|escape\(|sanitize|parameteri[sz]ed",
)
WEAKENED_TEST = re.compile(r"@pytest\.mark\.(skip|xfail)|\bpytest\.(skip|xfail)\(|\b(it|test|describe)\.(skip|only)\(|\bxit\(|\bxdescribe\(")
ASSERTION = re.compile(r"\bassert\b|\bexpect\(")


def _is_test(path: str) -> bool:
    low = path.lower()
    return low.startswith("tests/") or "/tests/" in low or "/test_" in f"/{low}" or low.endswith((".test.ts", ".test.tsx", ".spec.ts"))


def _finding(severity: str, rule: str, path: str, line: Optional[int], text: str) -> dict[str, Any]:
    return {"severity": severity, "rule": rule, "file": path, "line": line, "text": text.strip()[:160]}


def parse(patch: str) -> list[dict[str, Any]]:
    """Per file: ``path``, ``added`` [(new line number, text)], ``removed`` [text], ``deleted`` (the whole file was removed)."""
    files: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    new_line = 0
    for raw in patch.splitlines():
        if raw.startswith("diff --git "):
            parts = raw.split()
            path = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else (parts[-1] if parts else "")
            current = {"path": path, "added": [], "removed": [], "deleted": False}
            files.append(current)
        elif current is None:
            continue
        elif raw.startswith("deleted file mode"):
            current["deleted"] = True
        elif raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            new_line = int(match.group(1)) if match else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            current["added"].append((new_line, raw[1:]))
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            current["removed"].append(raw[1:])
        elif raw.startswith(" "):
            new_line += 1
    return files


def review_patch(patch: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for entry in parse(patch):
        path, added, removed = entry["path"], entry["added"], entry["removed"]
        if _is_test(path):
            if entry["deleted"]:
                findings.append(_finding("medium", "test-file-deleted", path, None, "the whole test file is removed"))
            for number, text in added:
                if WEAKENED_TEST.search(text):
                    findings.append(_finding("medium", "test-weakened", path, number, text))
            lost = sum(1 for text in removed if ASSERTION.search(text))
            kept = sum(1 for _, text in added if ASSERTION.search(text))
            if lost > kept + 2:
                findings.append(_finding("medium", "assertions-removed", path, None, f"{lost} assertion line(s) removed, {kept} added"))
            continue
        if not path.lower().endswith(CODE_SUFFIXES):
            continue
        for number, text in added:
            for rule, pattern, severity in ADDED_RULES:
                if pattern.search(text):
                    findings.append(_finding(severity, rule, path, number, text))
            if ENCODED.search(text) and EXECUTES.search(text):
                findings.append(_finding("high", "encoded-execution", path, number, text))
            for host in URL.findall(text):
                if not host.lower().endswith(SAFE_HOSTS):
                    findings.append(_finding("medium", "new-outbound-host", path, number, text))
                    break
        # a safeguard that disappears: judged by the net count, so moving a check to another function is not a finding
        lost_guards = [text for text in removed if GUARDS.search(text)]
        kept_guards = [text for _, text in added if GUARDS.search(text)]
        if len(lost_guards) > len(kept_guards):
            findings.append(_finding("high", "safeguard-removed", path, None, lost_guards[0]))
    return findings


def blocking(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in findings if f["severity"] == "high"]
