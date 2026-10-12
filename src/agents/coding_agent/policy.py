"""What the coding agent may touch. Pure functions, shared by the executor (which ENFORCES them: the model's own words decide nothing) and
the controller (which checks the finished patch again before anything is pushed).

Two lists:
  * ``PROTECTED``: files the agent may neither write nor delete: secrets, authentication and authorization, migrations, CI, deployment,
    dependency manifests, and the coding agent itself. A person changes those.
  * ``UNREADABLE``: files it may not even read (secrets).
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
from pathlib import Path
from typing import Iterable

PROTECTED: tuple[str, ...] = (
    ".git/**", ".env*", "**/.env*",
    "src/shared/auth.py", "src/shared/policy.py", "src/shared/security.py", "src/shared/audit.py",
    "migrations/**", ".github/**", "deploy/**",
    "docker-compose*.yml", "Dockerfile*", "requirements*.txt", "requirements.lock",
    "package.json", "package-lock.json", "frontend/package.json", "frontend/package-lock.json", "frontend/next.config.mjs",
    "scripts/make_*", "src/agents/coding_agent/**", "src/gateway/coding.py",
)
UNREADABLE: tuple[str, ...] = (".env*", "**/.env*", ".git/**", "*.pem", "*.key", "**/*.pem", "**/*.key")

# name -> argv prefix. The model chooses the name and the paths; it never supplies a program or a flag.
CHECKS: dict[str, tuple[str, ...]] = {
    "pytest": ("python", "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"),
    "ruff": ("python", "-m", "ruff", "check"),
}
_KEYWORD = re.compile(r"^[A-Za-z0-9_ ]{1,80}$")


def _norm(rel: str) -> str:
    return rel.replace("\\", "/").strip("/").casefold()


def matches(rel: str, patterns: Iterable[str]) -> bool:
    path = _norm(rel)
    name = path.rsplit("/", 1)[-1]
    for raw in patterns:
        pattern = raw.casefold()
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if path == prefix or path.startswith(prefix + "/"):
                return True
        elif pattern.startswith("**/"):
            if fnmatch.fnmatchcase(name, pattern[3:]):
                return True
        elif "/" in pattern:
            if fnmatch.fnmatchcase(path, pattern):
                return True
        elif fnmatch.fnmatchcase(name, pattern) or (path == pattern):
            return True
    return False


def is_protected(rel: str, extra: Iterable[str] = ()) -> bool:
    return matches(rel, (*PROTECTED, *extra))


def is_unreadable(rel: str) -> bool:
    return matches(rel, UNREADABLE)


def safe_join(root: Path, rel: str) -> Path:
    """``root / rel`` if it stays inside ``root`` once symlinks are resolved; ``ValueError`` otherwise."""
    if not rel or "\x00" in rel or os.path.isabs(rel) or re.match(r"^[A-Za-z]:", rel) or rel.startswith(("/", "\\")):
        raise ValueError("path must be relative")
    if ".." in rel.replace("\\", "/").split("/"):
        raise ValueError("path may not contain '..'")
    base = root.resolve()
    target = (base / rel).resolve()
    if target != base and base not in target.parents:
        raise ValueError("path leaves the workspace")
    return target


def check_argv(name: str, paths: list[str], keyword: str, root: Path) -> list[str]:
    """The full argv for an allowed check, or ``ValueError``. Paths must exist inside the workspace; ``keyword`` is plain words only."""
    if name not in CHECKS:
        raise ValueError(f"unknown check {name!r}; allowed: {', '.join(sorted(CHECKS))}")
    argv = [sys.executable, *CHECKS[name][1:]]  # the interpreter that runs the executor: the one that has the project's dependencies
    for rel in paths[:20]:
        target = safe_join(root, rel)
        if not target.exists():
            raise ValueError(f"no such path: {rel}")
        argv.append(target.relative_to(root.resolve()).as_posix())
    if keyword:
        if name != "pytest" or not _KEYWORD.match(keyword):
            raise ValueError("keyword is for pytest and may only contain letters, digits, spaces and underscores")
        argv += ["-k", keyword]
    if name == "pytest" and not paths:
        argv.append("tests")
    if name == "ruff" and not paths:
        argv.append(".")
    return argv


# Obvious credentials in a patch: a person looks at the diff, this is only the net under them.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openrouter-key", re.compile(r"sk-or-v1-[A-Za-z0-9]{16,}")), ("api-key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("aws-key", re.compile(r"AKIA[0-9A-Z]{16}")), ("github-token", re.compile(r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")), ("tavily-key", re.compile(r"tvly-[A-Za-z0-9]{20,}")),
)


def find_secrets(patch: str) -> list[str]:
    """Which kinds of credential appear on the ADDED lines of a unified diff (names only, never the value)."""
    added = "\n".join(line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
    return [name for name, pattern in _SECRET_PATTERNS if pattern.search(added)]


def files_in_patch(patch: str) -> list[str]:
    """Paths a unified diff touches (both sides of a rename)."""
    found: list[str] = []
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            for token in line.split()[2:4]:
                path = token[2:] if token[:2] in ("a/", "b/") else token
                if path not in found and path != "/dev/null":
                    found.append(path)
    return found
