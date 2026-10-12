"""The coding agent's hands: a git workspace and the few operations a model may ask for. Runs INSIDE the code-sandbox container (no network,
read-only root, no secrets); the checks here are the ones that count, because the model's own instructions are not trusted.

A workspace starts from a tarball of the repository (``git archive`` made by the controller), is committed as ``base`` and every change is
read back as ``git diff base``. Nothing here talks to a remote.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import shutil
import signal
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any

from src.agents.coding_agent.policy import check_argv, is_protected, is_unreadable, safe_join
from src.agents.coding_agent.shell_guard import Blocked, check_shell

logger = logging.getLogger("code_sandbox.shell")
SHELL_FLAG = "CODE_SANDBOX_ALLOW_SHELL"  # set to 1 on the sandbox container: the shell exists only where the operator switched it on
DEFAULT_SHELL_SECONDS = 120.0
MAX_SHELL_SECONDS = 600.0
SHELL_HEAD = 1000

MAX_TAR_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024
MAX_READ_BYTES = 200 * 1024
MAX_LIST = 500
MAX_HITS = 100
MAX_CHANGED_FILES = 25
MAX_PATCH_BYTES = 500 * 1024
MAX_PAIR_BYTES = 256 * 1024     # one side of one file in the diff editor
MAX_PAIRS_TOTAL = 2 * 1024 * 1024
OUTPUT_TAIL = 6000
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".next"}


def _key(path: str) -> str:
    normal = path.replace("\\", "/")
    while normal.startswith("./"):
        normal = normal[2:]
    return normal.strip("/").casefold()


def _limits(seconds: float):
    """Resource limits for the child (Linux): CPU time, one file's size, open files, processes, no core dumps. Memory is the container's."""
    def apply() -> None:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (int(seconds) + 5, int(seconds) + 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
    return apply


def _kill(proc: "subprocess.Popen[bytes]") -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)  # the whole group, including anything the command started
        else:  # off Linux (development machines): the whole tree, or a child would keep the output pipe open
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=15)
    except (ProcessLookupError, PermissionError, OSError):
        pass


class WorkspaceError(Exception):
    """A refusal the model can read and react to (never a crash)."""


def _git(root: Path, *args: str, check: bool = True) -> str:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
    done = subprocess.run(
        ["git", "-c", "user.name=coding-agent", "-c", "user.email=coding-agent@localhost", "-c", "core.hooksPath=" + os.devnull, *args],
        cwd=root, capture_output=True, text=True, timeout=60, env=env, shell=False,
    )
    if check and done.returncode != 0:
        raise WorkspaceError(f"git {args[0]} failed: {done.stderr.strip()[:300]}")
    return done.stdout


def _git_bytes(root: Path, *args: str) -> bytes:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
    for harmless in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):
        if harmless in os.environ:
            env[harmless] = os.environ[harmless]
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=60, env=env, shell=False)
    if done.returncode != 0:
        raise WorkspaceError(f"git {args[0]} failed: {done.stderr.decode('utf-8', errors='replace').strip()[:300]}")
    return done.stdout  # bytes, so Windows line endings survive for the diff editor


def _git_succeeds(root: Path, *args: str) -> bool:
    try:
        _git(root, *args)
        return True
    except WorkspaceError:
        return False


class Workspace:
    def __init__(self, root: Path, extra_protected: tuple[str, ...] = ()) -> None:
        self.root = root
        self.extra = extra_protected
        self._base_sha = ""
        self._seen: set[str] = set()  # files the model has read (or written) in this session: an existing file is never changed blind

    # ------------------------------------------------------------------ start
    def load_tar(self, data: bytes) -> int:
        """Unpack a repository tarball (links, absolute and parent paths are refused) and commit it as ``base``. Returns the file count."""
        if len(data) > MAX_TAR_BYTES:
            raise WorkspaceError("repository archive too large")
        count = 0
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for member in archive:
                if not (member.isfile() or member.isdir()):
                    continue  # symlinks, devices, hard links: not needed and a classic escape route
                target = safe_join(self.root, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if member.size > MAX_TAR_BYTES:
                    raise WorkspaceError("a file in the archive is too large")
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = archive.extractfile(member)
                if extracted is not None:
                    target.write_bytes(extracted.read())
                    count += 1
        _git(self.root, "init", "-q")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "--no-gpg-sign", "-m", "base")
        _git(self.root, "tag", "base")
        self._base_sha = _git(self.root, "rev-parse", "base").strip()
        return count

    # ------------------------------------------------------------------ reading
    def list_files(self, path: str = ".") -> dict[str, Any]:
        base = self.root.resolve() if path in ("", ".") else safe_join(self.root, path)
        if not base.is_dir():
            raise WorkspaceError(f"not a directory: {path}")
        files: list[str] = []
        for current, dirs, names in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
            for name in sorted(names):
                rel = (Path(current) / name).relative_to(self.root.resolve()).as_posix()
                if not is_unreadable(rel):
                    files.append(rel)
            if len(files) > MAX_LIST:
                break
        return {"files": files[:MAX_LIST], "truncated": len(files) > MAX_LIST}

    def read_file(self, path: str) -> dict[str, Any]:
        if is_unreadable(path):
            raise WorkspaceError("that file is not readable by the coding agent")
        target = safe_join(self.root, path)
        if not target.is_file():
            raise WorkspaceError(f"no such file: {path}")
        raw = target.read_bytes()
        text = raw[:MAX_READ_BYTES].decode("utf-8", errors="replace")
        if len(raw) <= MAX_READ_BYTES:
            self._seen.add(_key(path))  # a truncated read is not enough to overwrite or edit the file
        return {"path": path, "content": text, "truncated": len(raw) > MAX_READ_BYTES}

    def search(self, pattern: str, path: str = ".") -> dict[str, Any]:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise WorkspaceError(f"bad regular expression: {exc}") from exc
        hits: list[dict[str, Any]] = []
        for rel in self.list_files(path)["files"]:
            try:
                lines = safe_join(self.root, rel).read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(lines, 1):
                if regex.search(line):
                    hits.append({"path": rel, "line": number, "text": line[:200]})
                    if len(hits) >= 100:
                        return {"hits": hits, "truncated": True}
        return {"hits": hits, "truncated": False}

    # ------------------------------------------------------------------ writing
    def _may_write(self, path: str) -> Path:
        if is_protected(path, self.extra):
            raise WorkspaceError(f"{path} is protected: a person changes it, not the coding agent")
        return safe_join(self.root, path)

    def _changed(self) -> list[str]:
        _git(self.root, "add", "-A")
        return [line for line in _git(self.root, "diff", "--cached", "--name-only", "base").splitlines() if line]

    def _require_read(self, path: str, target: Path) -> None:
        if target.exists() and _key(path) not in self._seen:
            raise WorkspaceError(f"read {path} completely before changing it (an existing file is never overwritten or edited blind)")

    def edit_file(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict[str, Any]:
        """Exact string replacement in a file already read: the smallest change that does the job, and the diff stays reviewable."""
        target = self._may_write(path)
        if not target.is_file():
            raise WorkspaceError(f"no such file: {path} (use write_file to create a new one)")
        self._require_read(path, target)
        if not old_string:
            raise WorkspaceError("old_string must not be empty")
        if old_string == new_string:
            raise WorkspaceError("old_string and new_string are identical")
        content = target.read_text(encoding="utf-8")
        found = content.count(old_string)
        if found == 0:
            raise WorkspaceError("old_string was not found; it must match the file exactly, including indentation")
        if found > 1 and not replace_all:
            raise WorkspaceError(f"old_string matches {found} places; add the few lines around it that make it unique, or set replace_all")
        result = self.write_file(path, content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1))
        return {**result, "replaced": found if replace_all else 1}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        target = self._may_write(path)
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise WorkspaceError(f"file too large (limit {MAX_FILE_BYTES} bytes)")
        if target.is_dir():
            raise WorkspaceError(f"{path} is a directory")
        self._require_read(path, target)
        existed = target.exists()
        previous = target.read_bytes() if existed else None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        changed = self._changed()
        if len(changed) > MAX_CHANGED_FILES:
            if previous is None:
                target.unlink()
            else:
                target.write_bytes(previous)
            self._changed()
            raise WorkspaceError(f"too many changed files (limit {MAX_CHANGED_FILES}); the change is too large for one pull request")
        self._seen.add(_key(path))  # the model knows what it just wrote
        return {"path": path, "created": not existed, "changed_files": len(changed)}

    def delete_file(self, path: str) -> dict[str, Any]:
        target = self._may_write(path)
        if not target.is_file():
            raise WorkspaceError(f"no such file: {path}")
        target.unlink()
        return {"path": path, "deleted": True, "changed_files": len(self._changed())}

    def diff(self) -> dict[str, Any]:
        files = self._changed()
        patch = _git(self.root, "diff", "--cached", "--no-color", "base")
        return {"patch": patch[:MAX_PATCH_BYTES], "truncated": len(patch) > MAX_PATCH_BYTES, "files": files}

    def file_pairs(self) -> dict[str, Any]:
        """What each changed file looked like before and after, for the diff editor. Binary and oversized files come without content;
        the total is capped (``truncated``)."""
        files: list[dict[str, Any]] = []
        total = 0
        truncated = False
        self._changed()
        for line in _git(self.root, "diff", "--cached", "--name-status", "--no-renames", "base").splitlines():
            status_code, _, path = line.partition("\t")
            if not path:
                continue
            entry: dict[str, Any] = {"path": path, "status": {"A": "added", "D": "deleted"}.get(status_code[:1], "modified"), "before": "", "after": ""}
            before = b"" if entry["status"] == "added" else _git_bytes(self.root, "show", f"base:{path}")
            target = self.root / path
            after = target.read_bytes() if entry["status"] != "deleted" and target.is_file() else b""
            if b"\0" in before[:4096] or b"\0" in after[:4096]:
                entry["binary"] = True
            elif len(before) > MAX_PAIR_BYTES or len(after) > MAX_PAIR_BYTES or total + len(before) + len(after) > MAX_PAIRS_TOTAL:
                entry["too_large"] = True
                truncated = True
            else:
                entry["before"], entry["after"] = before.decode("utf-8", errors="replace"), after.decode("utf-8", errors="replace")
                total += len(before) + len(after)
            entry["protected"] = is_protected(path, self.extra)
            files.append(entry)
        return {"files": files, "truncated": truncated}

    def review_put(self, path: str, content: str) -> dict[str, Any]:
        """A reviewer's edit of a file that is already part of the change (not one of the model's tools: it has its own operation in the
        server). Protected files, files outside the change, oversized content and paths that leave the workspace are refused."""
        if is_protected(path, self.extra):
            raise WorkspaceError(f"{path} is protected: a person changes it outside the coding agent")
        target = safe_join(self.root, path)
        if _key(path) not in {_key(p) for p in self._changed()}:
            raise WorkspaceError(f"{path} is not part of this change; only files the agent changed can be edited here")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise WorkspaceError(f"file too large (limit {MAX_FILE_BYTES} bytes)")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
        self._seen.add(_key(path))
        return {"path": path, "changed_files": len(self._changed())}

    # ------------------------------------------------------------------ checks
    def run_check(self, name: str, paths: list[str] | None = None, keyword: str = "", timeout: float = 240.0) -> dict[str, Any]:
        try:
            argv = check_argv(name, paths or [], keyword, self.root)
        except ValueError as exc:
            raise WorkspaceError(str(exc)) from exc
        env = {  # nothing from the container's environment but what Python needs: no secret could be read by the code under test
            "PATH": os.environ.get("PATH", ""), "HOME": str(self.root), "PYTHONPATH": str(self.root), "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        }
        for harmless in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):  # Windows needs these to start sockets; nothing secret
            if harmless in os.environ:
                env[harmless] = os.environ[harmless]
        try:
            done = subprocess.run(argv, cwd=self.root, capture_output=True, text=True, timeout=max(5.0, min(timeout, 600.0)), env=env, shell=False)
        except subprocess.TimeoutExpired:
            return {"check": name, "ok": False, "exit_code": None, "output": "timed out"}
        output = (done.stdout + done.stderr)[-OUTPUT_TAIL:]
        return {"check": name, "ok": done.returncode == 0, "exit_code": done.returncode, "output": output}

    # ------------------------------------------------------------------ the shell
    def _fingerprint(self) -> str:
        self._changed()
        return hashlib.sha256(_git(self.root, "diff", "--cached", "--no-color", "base").encode("utf-8", errors="replace")).hexdigest()

    def _enforce(self) -> list[str]:
        """After a shell command: put the `base` tag back if it moved, and restore any protected file the command changed (or remove one it
        created). Returns the paths restored."""
        if _git(self.root, "rev-parse", "base", check=False).strip() != self._base_sha:
            _git(self.root, "tag", "-f", "base", self._base_sha)
        restored: list[str] = []
        for path in self._changed():
            if not is_protected(path, self.extra):
                continue
            if _git_succeeds(self.root, "cat-file", "-e", f"base:{path}"):  # it existed in the original: put it back; otherwise the command created it
                _git(self.root, "checkout", "base", "--", path)
            else:
                (self.root / path).unlink(missing_ok=True)
            restored.append(path)
        if restored:
            self._changed()
        return restored

    def run_shell(self, command: str, timeout: float = DEFAULT_SHELL_SECONDS) -> dict[str, Any]:
        """One shell command in the workspace. Every command is logged. The container is the boundary; this adds a filter with reasons
        (`shell_guard`), a minimal environment, resource limits, a time limit that kills the whole process group, a capped output, and a
        check afterwards that protected files and the `base` tag are as they were."""
        if os.environ.get(SHELL_FLAG, "").strip().lower() not in {"1", "true", "yes"}:
            raise WorkspaceError("the shell is switched off in this sandbox (CODING_ALLOW_SHELL); use the file tools and run_check")
        started = time.monotonic()
        try:
            check_shell(command, self.root.resolve().as_posix())
        except Blocked as exc:
            logger.warning("shell BLOCKED: %s -- %s", command[:300].replace("\n", " ; "), exc)
            return {"command": command[:500], "blocked": True, "error": str(exc)}
        shell = shutil.which("bash") or shutil.which("sh")
        if shell is None:
            raise WorkspaceError("no shell is installed in this sandbox")
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": str(self.root), "PYTHONPATH": str(self.root),
            "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "LANG": "C.UTF-8", "TERM": "dumb",
        }
        for harmless in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):
            if harmless in os.environ:
                env[harmless] = os.environ[harmless]
        limit = max(1.0, min(float(timeout), MAX_SHELL_SECONDS))
        before = self._fingerprint()
        proc = subprocess.Popen(
            [shell, "-c", command], cwd=self.root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix", preexec_fn=_limits(limit) if os.name == "posix" else None,
        )
        timed_out = False
        try:
            raw, _ = proc.communicate(timeout=limit)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(proc)
            raw, _ = proc.communicate()
        _kill(proc)  # whatever the command left behind in its process group
        text = raw.decode("utf-8", errors="replace")
        output = text if len(text) <= OUTPUT_TAIL else text[:SHELL_HEAD] + "\n...[output cut]...\n" + text[-(OUTPUT_TAIL - SHELL_HEAD):]
        restored = self._enforce()
        modified = self._fingerprint() != before or bool(restored)
        seconds = round(time.monotonic() - started, 2)
        logger.info("shell exit=%s %.1fs modified=%s restored=%s timed_out=%s: %s", proc.returncode, seconds, modified, restored, timed_out, command[:300].replace("\n", " ; "))
        result: dict[str, Any] = {"command": command[:500], "exit_code": proc.returncode, "ok": proc.returncode == 0 and not timed_out, "seconds": seconds,
                                  "timed_out": timed_out, "output": output, "modified": modified, "changed_files": len(self._changed())}
        if restored:
            result["restored"] = restored
            result["warning"] = "protected files were changed by the command and have been restored: " + ", ".join(restored)
        if result["changed_files"] > MAX_CHANGED_FILES:
            result["warning"] = (result.get("warning", "") + f" {result['changed_files']} files differ from the original (limit {MAX_CHANGED_FILES} for one pull request): "
                                 "remove generated files or add them to .gitignore").strip()
        return result

    # ------------------------------------------------------------------ dispatch
    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """One model-requested operation. A refusal comes back as ``{"error": ...}`` for the model to read."""
        try:
            if tool == "list_files":
                return self.list_files(str(args.get("path", ".")))
            if tool == "read_file":
                return self.read_file(str(args.get("path", "")))
            if tool == "search":
                return self.search(str(args.get("pattern", "")), str(args.get("path", ".")))
            if tool == "write_file":
                return self.write_file(str(args.get("path", "")), str(args.get("content", "")))
            if tool == "edit_file":
                return self.edit_file(str(args.get("path", "")), str(args.get("old_string", "")), str(args.get("new_string", "")), bool(args.get("replace_all", False)))
            if tool == "delete_file":
                return self.delete_file(str(args.get("path", "")))
            if tool == "git_diff":
                return self.diff()
            if tool == "git_files":
                return self.file_pairs()
            if tool == "run_shell":
                return self.run_shell(str(args.get("command", "")), float(args.get("timeout", DEFAULT_SHELL_SECONDS) or DEFAULT_SHELL_SECONDS))
            if tool == "run_check":
                return self.run_check(str(args.get("check", "")), [str(p) for p in args.get("paths", [])][:20], str(args.get("keyword", "")))
            return {"error": f"unknown tool {tool!r}"}
        except (WorkspaceError, ValueError) as exc:
            return {"error": str(exc)}
