"""HTTP front of the analysis sandbox, run inside the network-less ``python-sandbox`` container.

    python -m src.agents.data_agent.sandbox_server          # listens on SANDBOX_PORT (default 8080)

The backend (``SafePythonSandbox`` with ``remote_url`` set) POSTs ``{"code", "timeout", "memory_mb", "df_parquet_b64"}``
to ``/run`` and gets the ``SandboxResult`` fields back as JSON. Inside this container the code goes through the very same
layers as a local run (AST allow-list, restricted builtins, a killed-on-timeout child interpreter with rlimits), and the
container adds its own: no internet (an internal-only Docker network), read-only root filesystem, no capabilities, memory
and process limits. A compromised analysis can therefore reach neither the backend's secrets nor its database.

Trust: the only caller is the backend. Requests must carry ``X-Signature`` = HMAC-SHA256 of the raw body with the shared
``SANDBOX_SECRET``; the data frame travels as Parquet (never pickle, which would let anyone who can reach the port run code).
Only the Python standard library is needed to serve; pandas/numpy/scipy/matplotlib/pyarrow run the analysis.
"""

from __future__ import annotations

import base64
import hmac
import io
import json
import logging
import os
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pandas as pd

from src.agents.data_agent.sandbox import SafePythonSandbox, sign_request

logger = logging.getLogger("sandbox_server")

MAX_BODY_BYTES: int = int(os.environ.get("SANDBOX_MAX_BODY_MB", "128")) * 1024 * 1024
MAX_TIMEOUT_SECONDS: float = float(os.environ.get("SANDBOX_MAX_TIMEOUT", "30"))
MAX_MEMORY_MB: int = int(os.environ.get("SANDBOX_MAX_MEMORY_MB", "768"))
MAX_PARALLEL_RUNS: int = int(os.environ.get("SANDBOX_MAX_PARALLEL", "2"))
QUEUE_WAIT_SECONDS: float = 5.0
MIN_SECRET_CHARS: int = 16

_slots = threading.BoundedSemaphore(MAX_PARALLEL_RUNS)


def run_request(body: bytes) -> dict[str, Any]:
    """Execute one request body; the result is ``SandboxResult`` as a dict. Limits asked for are clamped to this container's."""
    request = json.loads(body)
    code = request["code"]
    encoded = request.get("df_parquet_b64")
    df = pd.read_parquet(io.BytesIO(base64.b64decode(encoded))) if encoded else None
    timeout = max(1.0, min(float(request.get("timeout", 10.0)), MAX_TIMEOUT_SECONDS))
    memory_mb = max(128, min(int(request.get("memory_mb", MAX_MEMORY_MB)), MAX_MEMORY_MB))
    return asdict(SafePythonSandbox(timeout_seconds=timeout, memory_mb=memory_mb).execute_sync(code, df))


def make_handler(secret: str) -> type[BaseHTTPRequestHandler]:
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
            if not _slots.acquire(timeout=QUEUE_WAIT_SECONDS):
                return self._reply(503, {"error": "sandbox busy"})
            try:
                self._reply(200, run_request(body))
            except Exception as exc:  # noqa: BLE001 - a malformed request must not kill the server
                logger.warning("Bad sandbox request: %s", exc)
                self._reply(400, {"error": f"bad request: {exc}"})
            finally:
                _slots.release()

    return Handler


def serve(secret: str, host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:  # noqa: S104 - reachable on the internal network only
    if len(secret) < MIN_SECRET_CHARS:
        raise SystemExit(f"SANDBOX_SECRET must be at least {MIN_SECRET_CHARS} characters")
    return ThreadingHTTPServer((host, port), make_handler(secret))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    server = serve(os.environ.get("SANDBOX_SECRET", ""), port=int(os.environ.get("SANDBOX_PORT", "8080")))
    logger.info("Analysis sandbox listening on %s:%s", *server.server_address[:2])
    server.serve_forever()
