"""The repositories the coding agent may work on, chosen per task: a GitHub link or a git folder this server can see.

  * ``github``: an ``https://github.com/<owner>/<repo>`` link. Any coding user may add one. Cloning and the pull request use the single
    ``GITHUB_PR_TOKEN`` of this server, so a private repository works only if that token can reach it.
  * ``local``: a folder on the machine the backend runs on. A browser cannot hand the server a path, so folders are PICKED from the git
    repositories found under the roots the operator allowed (``CODING_LOCAL_ROOTS``, mounted into the container), never typed in free-form;
    only an administrator may add one, because it opens part of the server's disk to the agent. A path is re-checked against the roots every
    time it is used (symlinks resolved), so it cannot be pointed outside them later.

The built-in ``default`` repository is whatever ``CODING_REPO_URL`` says, if anything.
"""

from __future__ import annotations

import os
import re
import uuid
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from asyncpg.exceptions import UniqueViolationError

from src.agents.coding_agent.publisher import GITHUB_URL, Publisher
from src.config import settings

# The repository chosen in the chat for the request being served (set by the gateway, read by the agent).
selected_repo: ContextVar[str] = ContextVar("coding_repo", default="")

DEFAULT_ID = "default"
NAME = re.compile(r"^[\w][\w .\-]{0,59}$", re.UNICODE)
REPO_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
BRANCH = re.compile(r"^[A-Za-z0-9._/\-]{0,100}$")
_SKIP = {"node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", ".git"}
MAX_FOUND = 200


class RepoError(ValueError):
    """A refusal with a message key (``src/shared/messages.py``) the gateway turns into the caller's language."""

    def __init__(self, key: str, **values: Any) -> None:
        super().__init__(key)
        self.key, self.values = key, values


@dataclass(frozen=True)
class Repo:
    id: str
    name: str
    kind: str          # github | local
    location: str      # the GitHub URL, or the folder path
    branch: str = ""
    tenant_id: str = ""
    owner: str = ""

    def public(self) -> dict[str, Any]:
        return asdict(self)


def default_repo() -> Optional[Repo]:
    url = settings.CODING_REPO_URL
    if not url:
        return None
    kind = "github" if url.startswith("https://") else "local"
    label = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or "default"
    return Repo(DEFAULT_ID, label, kind, url, settings.CODING_REPO_BRANCH)


def roots() -> list[Path]:
    found: list[Path] = []
    for raw in settings.CODING_LOCAL_ROOTS:
        path = Path(raw)
        if path.is_dir():
            found.append(path.resolve())
    return found


def _is_git(path: Path) -> bool:
    return (path / ".git").exists() or (path / "HEAD").is_file()  # a working tree, or a bare repository


def allowed_folder(raw: str) -> Path:
    """The resolved folder if it is a git repository inside an allowed root (symlinks resolved), else ``RepoError``."""
    if not raw or "\x00" in raw:
        raise RepoError("coding.repo_bad_folder")
    try:
        path = Path(os.path.realpath(raw))
    except (OSError, ValueError) as exc:
        raise RepoError("coding.repo_bad_folder") from exc
    if not any(path == root or root in path.parents for root in roots()):
        raise RepoError("coding.repo_folder_not_allowed")
    if not path.is_dir() or not _is_git(path):
        raise RepoError("coding.repo_not_git")
    return path


def _head_branch(path: Path) -> str:
    try:
        head = (path / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return head.removeprefix("ref: refs/heads/") if head.startswith("ref: refs/heads/") else ""


def discover(max_depth: int = 2) -> list[dict[str, str]]:
    """Git repositories under the allowed roots (a root that is one, and folders up to ``max_depth`` below), for the picker."""
    found: list[dict[str, str]] = []
    for root in roots():
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack and len(found) < MAX_FOUND:
            folder, depth = stack.pop()
            if _is_git(folder):
                found.append({"path": str(folder), "name": folder.name, "branch": _head_branch(folder)})
                continue  # the repository's own sub-folders are part of it
            if depth >= max_depth:
                continue
            try:
                children = sorted(c for c in folder.iterdir() if c.is_dir() and not c.is_symlink() and c.name not in _SKIP and not c.name.startswith("."))
            except OSError:
                continue
            stack.extend((child, depth + 1) for child in reversed(children))
    return found


def _row(r: Any) -> Repo:
    return Repo(r["id"], r["name"], r["kind"], r["location"], r["branch"], r["tenant_id"], r["owner"])


async def list_repos(pg: Any, tenant_id: str) -> list[Repo]:
    rows = await pg.fetch("SELECT id, tenant_id, owner, name, kind, location, branch FROM coding_repos WHERE tenant_id = $1 ORDER BY lower(name)", tenant_id)
    repos = [_row(r) for r in rows]
    default = default_repo()
    return ([default] if default else []) + repos


async def resolve(pg: Any, tenant_id: str, repo_id: str) -> Optional[Repo]:
    if not repo_id or repo_id == DEFAULT_ID:
        return default_repo()
    if not REPO_ID.match(repo_id):
        return None
    rows = await pg.fetch("SELECT id, tenant_id, owner, name, kind, location, branch FROM coding_repos WHERE id = $1 AND tenant_id = $2", repo_id, tenant_id)
    return _row(rows[0]) if rows else None


async def add_repo(pg: Any, *, tenant_id: str, owner: str, is_admin: bool, kind: str, location: str, name: str, branch: str = "") -> Repo:
    name, branch, location = name.strip(), branch.strip(), location.strip()
    if not NAME.match(name):
        raise RepoError("coding.repo_bad_name")
    if not BRANCH.match(branch) or ".." in branch:
        raise RepoError("coding.repo_bad_branch")
    if kind == "github":
        if not GITHUB_URL.match(location):
            raise RepoError("coding.repo_bad_github")
        location = location.rstrip("/")
    elif kind == "local":
        if not is_admin:
            raise RepoError("coding.repo_need_admin")
        location = str(allowed_folder(location))
    else:
        raise RepoError("coding.repo_bad_kind")
    repo = Repo(uuid.uuid4().hex[:12], name, kind, location, branch, tenant_id, owner)
    try:
        await pg.execute("INSERT INTO coding_repos (id, tenant_id, owner, name, kind, location, branch) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                         repo.id, tenant_id, owner, name, kind, location, branch)
    except UniqueViolationError as exc:
        raise RepoError("coding.repo_name_taken", name=name) from exc
    return repo


async def remove_repo(pg: Any, *, tenant_id: str, user_id: str, is_admin: bool, repo_id: str) -> bool:
    if not REPO_ID.match(repo_id) or repo_id == DEFAULT_ID:
        return False
    rows = await pg.fetch("DELETE FROM coding_repos WHERE id = $1 AND tenant_id = $2 AND ($3 OR owner = $4) RETURNING id", repo_id, tenant_id, is_admin, user_id)
    return bool(rows)


def publisher_for(repo: Repo) -> Publisher:
    """The publisher for one repository, built when it is used. A local folder is checked against the allowed roots again here."""
    protected = tuple(settings.CODING_PROTECTED_PATHS)
    if repo.kind == "github":
        return Publisher(repo.location, settings.GITHUB_PR_TOKEN, repo.branch, settings.CODING_BRANCH_PREFIX, protected)
    folder = allowed_folder(repo.location)
    return Publisher(str(folder), "", repo.branch, settings.CODING_BRANCH_PREFIX, protected, local=True, snapshot=settings.CODING_LOCAL_SNAPSHOT)
