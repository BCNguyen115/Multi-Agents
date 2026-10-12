"""Getting code to and from the sandbox, and the only place that holds the GitHub token.

``make_archive`` clones the configured repository and returns a tarball of its tracked files (what the sandbox starts from).
``publish`` applies a finished patch to a FRESH clone on a new branch, re-checks it (protected files, credentials), pushes the branch and
opens a pull request. It never merges, never pushes to the base branch, and the token never reaches argv, logs or the sandbox: git gets it
through environment configuration, and every message is scrubbed of it.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import httpx

from src.agents.coding_agent import patch_guard, policy
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

GITHUB_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_SNAPSHOT_FILE_BYTES = 1024 * 1024

CreatePR = Callable[[str, str, str, str], Awaitable[str]]  # (head branch, base branch, title, body) -> pull request URL


class PublishError(Exception):
    """A refusal or failure whose message is fit to show the reviewer."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30] or "change"


class Publisher:
    def __init__(self, repo_url: str, token: str, base_branch: str = "main", branch_prefix: str = "agent/",
                 extra_protected: tuple[str, ...] = (), allow_any_url: bool = False, create_pr: Optional[CreatePR] = None,
                 local: bool = False, snapshot: bool = True) -> None:
        """``local``: ``repo_url`` is a git repository on this machine (a mounted folder). The sandbox then starts from its working tree
        (``snapshot``: tracked and untracked files git does not ignore, so uncommitted work is included) or from HEAD, and publishing creates
        a BRANCH in that repository (its working tree and checked-out branch are never touched); there is no pull request."""
        self.repo_url, self.token, self.base, self.prefix, self.extra = repo_url, token, base_branch, branch_prefix, extra_protected
        self.local, self.snapshot = local, snapshot
        if not local and not base_branch:
            self.base = "main"  # a pull request needs a base; a local folder simply starts from whatever its HEAD is
        if local:
            if not Path(repo_url).is_dir() or not (Path(repo_url) / ".git").exists() and not (Path(repo_url) / "HEAD").exists():
                raise PublishError("CODING_REPO_URL must be a git repository folder that this process can see")
        elif not allow_any_url and not GITHUB_URL.match(repo_url):
            raise PublishError("CODING_REPO_URL must look like https://github.com/<owner>/<repo>.git, or a mounted git folder")
        self._create_pr = create_pr or self._github_pr

    @property
    def target(self) -> str:
        return "local" if self.local else "github"

    # ------------------------------------------------------------------ plumbing
    def _env(self) -> dict[str, str]:
        env = {"PATH": os.environ.get("PATH", ""), "HOME": tempfile.gettempdir(), "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
        for harmless in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):
            if harmless in os.environ:
                env[harmless] = os.environ[harmless]
        if self.token and self.repo_url.startswith("https://"):
            header = "Authorization: Basic " + base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
            env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader", "GIT_CONFIG_VALUE_0": header})
        return env

    def _scrub(self, text: str) -> str:
        if self.token:
            text = text.replace(self.token, "***").replace(base64.b64encode(f"x-access-token:{self.token}".encode()).decode(), "***")
        return text

    def _git(self, cwd: Path, *args: str, stdin: str | None = None) -> str:
        done = subprocess.run(
            ["git", "-c", "user.name=coding-agent", "-c", "user.email=coding-agent@users.noreply.github.com", "-c", "safe.directory=*", *args],  # hooks and signing are never switched off
            cwd=cwd, capture_output=True, timeout=300, env=self._env(), input=stdin.encode("utf-8") if stdin is not None else None, shell=False,
        )  # bytes both ways: text mode would rewrite CRLF in the patch and a file with Windows line endings would no longer apply
        if done.returncode != 0:
            message = (done.stderr or done.stdout).decode("utf-8", errors="replace").strip()[:300]
            raise PublishError(self._scrub(f"git {args[0]} failed: {message}"))
        return done.stdout.decode("utf-8", errors="replace")

    def _clone(self, into: Path) -> None:
        if self.local:  # a full clone of the folder's repository, from its current HEAD unless a branch is named
            branch = ["--branch", self.base] if self.base else []
            self._git(into.parent, "clone", "--quiet", "--no-hardlinks", *branch, self.repo_url, into.name)
            return
        self._git(into.parent, "clone", "--quiet", "--depth", "1", "--branch", self.base, self.repo_url, into.name)

    # ------------------------------------------------------------------ the working tree of a local folder
    def _snapshot_tar(self) -> bytes:
        """Tracked and untracked-but-not-ignored files of the local folder as a tarball (so `.env` and other ignored files stay out)."""
        root = Path(self.repo_url)
        listing = self._git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
        buffer = io.BytesIO()
        total = 0
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for rel in sorted({name for name in listing if name}):
                path = root / rel
                if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_SNAPSHOT_FILE_BYTES:
                    continue  # deleted since the last commit, a link, or a big file (datasets, images): not what a code task needs
                with path.open("rb") as handle:
                    if b"\0" in handle.read(4096):
                        continue  # binary (PDF, Office, images, archives): never sent to the sandbox or the model, whatever its size
                total += path.stat().st_size
                if total > MAX_ARCHIVE_BYTES:
                    raise PublishError("the folder is too large for the code sandbox")
                archive.add(path, arcname=rel, recursive=False)
        return buffer.getvalue()

    def _overlay_snapshot(self, repo: Path) -> None:
        """Replace the clone's files with the folder's working tree and commit the difference, so the agent's commit sits on top of exactly
        what the task started from (the branch then shows the agent's change alone: `git diff <branch>~1 <branch>`)."""
        for entry in repo.iterdir():
            if entry.name != ".git":
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
        with tarfile.open(fileobj=io.BytesIO(self._snapshot_tar()), mode="r:gz") as archive:
            for member in archive:
                target = (repo / member.name).resolve()
                if member.isfile() and repo.resolve() in target.parents:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())  # type: ignore[union-attr]
        self._git(repo, "add", "-A")
        if self._git(repo, "status", "--porcelain").strip():
            self._git(repo, "commit", "-q", "-m", "Working tree at the time of the coding task (uncommitted changes)")

    # ------------------------------------------------------------------ to the sandbox
    def _archive_sync(self) -> bytes:
        if self.local and self.snapshot:
            return self._snapshot_tar()
        work = Path(tempfile.mkdtemp(prefix="coding-clone-"))
        if self.local:  # committed files only
            try:
                self._git(Path(self.repo_url), "archive", "--format=tar.gz", "-o", str(work / "src.tar.gz"), self.base or "HEAD")
                return (work / "src.tar.gz").read_bytes()
            finally:
                shutil.rmtree(work, ignore_errors=True)
        try:
            repo = work / "repo"
            self._clone(repo)
            self._git(repo, "archive", "--format=tar.gz", "-o", str(work / "src.tar.gz"), "HEAD")
            data = (work / "src.tar.gz").read_bytes()
            if len(data) > MAX_ARCHIVE_BYTES:
                raise PublishError("the repository is too large for the code sandbox")
            return data
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def make_archive(self) -> bytes:
        return await asyncio.to_thread(self._archive_sync)

    # ------------------------------------------------------------------ from the sandbox
    def check_patch(self, patch: str) -> list[str]:
        """Files of the patch; ``PublishError`` if it touches a protected path or carries a credential."""
        files = policy.files_in_patch(patch)
        if not files:
            raise PublishError("the patch is empty")
        blocked = [f for f in files if policy.is_protected(f, self.extra)]
        if blocked:
            raise PublishError("the patch changes protected files: " + ", ".join(blocked[:5]))
        secrets = policy.find_secrets(patch)
        if secrets:
            raise PublishError("the patch contains what looks like a credential (" + ", ".join(secrets) + ")")
        risky = patch_guard.blocking(patch_guard.review_patch(patch))
        if risky:
            raise PublishError("the patch has high-risk changes: " + ", ".join(f"{f['rule']} in {f['file']}" for f in risky[:5]))
        return files

    def _publish_sync(self, patch: str, title: str, task_id: str) -> str:
        self.check_patch(patch)
        branch = f"{self.prefix}{task_id[:8]}-{_slug(title)}"
        work = Path(tempfile.mkdtemp(prefix="coding-push-"))
        try:
            repo = work / "repo"
            self._clone(repo)
            self._git(repo, "checkout", "-q", "-b", branch)
            if self.local and self.snapshot:
                self._overlay_snapshot(repo)
            try:
                self._git(repo, "apply", "--index", "--whitespace=nowarn", "-", stdin=patch if patch.endswith("\n") else patch + "\n")
            except PublishError as exc:
                if self.local and self.snapshot:
                    raise PublishError("the files changed since the task ran, so the patch no longer applies; run the task again") from exc
                raise
            self._git(repo, "commit", "-q", "-m", title[:72], "-m", "Written by the coding agent; reviewed by a person before this branch was pushed.")
            self._git(repo, "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
            return branch
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def publish(self, patch: str, title: str, body: str, task_id: str) -> dict[str, Any]:
        branch = await asyncio.to_thread(self._publish_sync, patch, title, task_id)
        if self.local:  # a branch in the local repository; there is no hosting service to open a pull request on
            logger.info("Coding agent created local branch %s", branch)
            return {"branch": branch, "pr_url": "", "local": True}
        url = await self._create_pr(branch, self.base, title[:200], body[:6000])
        logger.info("Coding agent published branch %s", branch)
        return {"branch": branch, "pr_url": url}

    async def _github_pr(self, head: str, base: str, title: str, body: str) -> str:
        match = GITHUB_URL.match(self.repo_url)
        if not match or not self.token:
            raise PublishError("opening a pull request needs a GitHub repository URL and GITHUB_PR_TOKEN")
        owner, repo = match.group(1), match.group(2)
        async with httpx.AsyncClient(timeout=30.0) as http:
            response = await http.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
                json={"title": title, "head": head, "base": base, "body": body, "draft": True},
            )
        if response.status_code >= 300:
            raise PublishError(f"GitHub refused the pull request ({response.status_code})")
        return str(response.json().get("html_url", ""))
