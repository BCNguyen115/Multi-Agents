"""HTTP front of the code sandbox: the coding agent's hands, run inside the ``code-sandbox`` container.

    python -m src.agents.coding_agent.executor_server          # listens on CODE_SANDBOX_PORT (default 8081)

One endpoint, ``POST /run``, with ``X-Signature`` = HMAC-SHA256 of the raw body under ``CODING_SANDBOX_SECRET`` (the same scheme as the analysis
sandbox). Bodies carry a timestamp; one older than ``MAX_AGE_SECONDS`` is refused, so a captured request cannot be replayed later.
Operations: ``init`` (unpack a repository tarball into a fresh workspace), ``call`` (one tool of ``Workspace.call``), ``close``.

Trust: the only caller is the backend's controller. The container has no network, a read-only root, no capabilities, and no secret but the
signing key; the workspace lives in a tmpfs, so nothing survives a restart. Every limit that matters is enforced in ``workspace.py``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from src.agents.coding_agent.workspace import Workspace, WorkspaceError

logger = logging.getLogger("code_sandbox")

MAX_BODY_BYTES = int(os.environ.get("CODE_SANDBOX_MAX_BODY_MB", "96")) * 1024 * 1024
MAX_AGE_SECONDS = 120
MAX_SESSIONS = int(os.environ.get("CODE_SANDBOX_MAX_SESSIONS", "6"))        # finished work stays open for review, so several can be alive at once
SESSION_TTL_SECONDS = int(os.environ.get("CODE_SANDBOX_SESSION_TTL", "1800"))  # an idle session (nobody reviewing) is deleted after this
MIN_SECRET_CHARS = 16
WORK_ROOT = Path(os.environ.get("CODE_SANDBOX_WORK", tempfile.gettempdir())) / "coding-workspaces"


def sign_request(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class Sessions:
    """Workspaces by id; at most ``MAX_SESSIONS`` alive, and one idle for ``SESSION_TTL_SECONDS`` is deleted."""

    def __init__(self, extra_protected: tuple[str, ...] = (), root: Path | None = None) -> None:
        self._items: dict[str, tuple[Workspace, float]] = {}
        self._lock = threading.Lock()
        self._extra = extra_protected
        self._root = root or WORK_ROOT

    def _sweep(self) -> None:
        now = time.monotonic()
        for key, (workspace, touched) in list(self._items.items()):
            if now - touched > SESSION_TTL_SECONDS:
                shutil.rmtree(workspace.root, ignore_errors=True)
                del self._items[key]

    def create(self, tar: bytes) -> tuple[str, int]:
        with self._lock:
            self._sweep()
            if len(self._items) >= MAX_SESSIONS:
                raise WorkspaceError("the code sandbox is busy")
            session = uuid.uuid4().hex
            root = self._root / session
            root.mkdir(parents=True)
            workspace = Workspace(root, self._extra)
            try:
                files = workspace.load_tar(tar)
            except Exception:
                shutil.rmtree(root, ignore_errors=True)
                raise
            self._items[session] = (workspace, time.monotonic())
            return session, files

    def get(self, session: str) -> Workspace:
        with self._lock:
            item = self._items.get(session)
            if item is None:
                raise WorkspaceError("unknown or expired session")
            self._items[session] = (item[0], time.monotonic())
            return item[0]

    def close(self, session: str) -> None:
        with self._lock:
            item = self._items.pop(session, None)
        if item is not None:
            shutil.rmtree(item[0].root, ignore_errors=True)


def handle(sessions: Sessions, body: bytes, now: float | None = None) -> dict[str, Any]:
    """Execute one signed request body. Refusals are ``{"error": ...}`` (the controller shows them to the model or stops)."""
    request = json.loads(body)
    age = (time.time() if now is None else now) - float(request.get("ts", 0))
    if age > MAX_AGE_SECONDS or age < -30:
        return {"error": "request expired"}
    op = request.get("op")
    try:
        if op == "init":
            session, files = sessions.create(base64.b64decode(request["tar_b64"]))
            return {"session": session, "files": files}
        if op == "call":
            return sessions.get(str(request["session"])).call(str(request["tool"]), dict(request.get("args") or {}))
        if op == "review_put":  # a reviewer's edit, not a model tool: only the controller sends it, on behalf of a person who passed the gateway's checks
            return sessions.get(str(request["session"])).review_put(str(request["path"]), str(request["content"]))
        if op == "close":
            sessions.close(str(request["session"]))
            return {"closed": True}
    except (WorkspaceError, ValueError, KeyError) as exc:
        return {"error": str(exc)}
    return {"error": f"unknown op {op!r}"}


def make_handler(secret: str, sessions: Sessions) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature of the base class
            logger.info("%s %s", self.address_string(), format % args)

        def _reply(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            if self.path == "/health":
                self._reply(200, {"status": "ok"})
            else:
                self._reply(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/run":
                return self._reply(404, {"error": "not found"})
            length = self.headers.get("Content-Length", "")
            if not length.isdigit() or int(length) > MAX_BODY_BYTES:
                return self._reply(413, {"error": "request too large"})
            body = self.rfile.read(int(length))
            if not hmac.compare_digest(self.headers.get("X-Signature", ""), sign_request(secret, body)):
                logger.warning("Rejected a request with a bad signature from %s", self.address_string())
                return self._reply(401, {"error": "bad signature"})
            try:
                self._reply(200, handle(sessions, body))
            except Exception as exc:  # noqa: BLE001 - a malformed request must not kill the server
                logger.warning("Bad request: %s", exc)
                self._reply(400, {"error": f"bad request: {exc}"})

    return Handler


def serve(secret: str, host: str = "0.0.0.0", port: int = 8081) -> ThreadingHTTPServer:  # noqa: S104 - reachable on the internal network only
    if len(secret) < MIN_SECRET_CHARS:
        raise SystemExit(f"CODING_SANDBOX_SECRET must be at least {MIN_SECRET_CHARS} characters")
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    return ThreadingHTTPServer((host, port), make_handler(secret, Sessions()))


def take_secret() -> str:
    """The signing key, kept out of the process environment: commands run by the shell can read ``/proc/<pid>/environ`` of this process, so the
    first start reads the key from the environment, puts it in a pipe and re-executes itself WITHOUT it; the new image reads it from the pipe.
    (It still lives in this process's memory; see the note in ``shell_guard``.)"""
    fd = os.environ.pop("CODING_SANDBOX_SECRET_FD", "")
    if fd:
        with os.fdopen(int(fd), "rb") as pipe:
            return pipe.read().decode()
    secret = os.environ.get("CODING_SANDBOX_SECRET", "")
    if not secret or os.name != "posix":
        return secret
    reader, writer = os.pipe()
    os.write(writer, secret.encode())
    os.close(writer)
    os.set_inheritable(reader, True)
    env = {key: value for key, value in os.environ.items() if key != "CODING_SANDBOX_SECRET"}
    env["CODING_SANDBOX_SECRET_FD"] = str(reader)
    os.execve(sys.executable, [sys.executable, "-m", "src.agents.coding_agent.executor_server"], env)
    return secret  # unreachable: execve replaces this process


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    server = serve(take_secret(), port=int(os.environ.get("CODE_SANDBOX_PORT", "8081")))
    logger.info("Code sandbox listening on %s:%s", *server.server_address[:2])
    server.serve_forever()
