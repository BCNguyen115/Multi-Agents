"""Sandbox for LLM-written analysis code (text-to-analysis).

Defence in depth — each layer assumes the previous one can be bypassed:

1. **AST allow-list** (:meth:`SafePythonSandbox.validate_code`): only a small set of syntax nodes is accepted;
   imports are limited to a data-science whitelist; underscore attributes, file/network/eval style attributes
   and dangerous builtins are rejected before anything runs.
2. **Restricted runtime**: a builtins whitelist and an import hook that only serves the whitelist.
3. **Process isolation**: code runs in a separate interpreter (``sandbox_worker.py``, isolated ``-I`` mode,
   scrubbed environment, no secrets) that is *killed* on timeout — a hung ``while True`` cannot stall the server.
4. **Resource limits** (POSIX): address-space, CPU-time and file-size rlimits inside the worker.

ponytail: on Windows there are no rlimits (memory is unbounded); for untrusted production traffic run the API in
the Linux image (limits apply) or execute the worker in the network-less ``python-sandbox`` container.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import builtins as _builtins
import contextlib
import hashlib
import hmac
import importlib
import io
import json
import logging
import math
import os
import pickle
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_SANDBOX_TIMEOUT: float = 10.0
DEFAULT_MEMORY_MB: int = 2048
MAX_RESULT_ROWS: int = 200

_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox_worker.py")

FORBIDDEN_CALLS: set[str] = {
    "open", "eval", "exec", "compile", "globals", "locals", "vars", "__import__", "getattr", "setattr", "delattr",
    "input", "breakpoint", "help", "exit", "quit", "memoryview", "type", "super", "object", "classmethod", "staticmethod", "property",
}

FORBIDDEN_MODULES: set[str] = {
    "os", "sys", "subprocess", "socket", "shutil", "urllib", "requests", "http", "ftplib", "poplib", "smtplib", "telnetlib",
    "pty", "posix", "nt", "threading", "multiprocessing", "signal", "importlib", "ctypes", "pickle", "marshal", "builtins",
}

ALLOWED_IMPORTS: set[str] = {"math", "statistics", "datetime", "collections", "itertools", "re", "json", "numpy", "pandas", "scipy"}

# Attributes that reach the filesystem, the network, code evaluation or interpreter internals.
DENIED_ATTRIBUTES: set[str] = {
    "format", "format_map", "eval", "query", "system", "popen", "load", "loads", "dump", "dumps", "save", "savez", "savefig", "show",
    "loadtxt", "savetxt", "genfromtxt", "fromfile", "tofile", "memmap", "fromstring", "DataSource", "io", "core", "util", "compat",
    "testing", "api", "plotting", "lib", "ctypeslib", "f2py", "distutils", "style", "plot", "hist", "gi_frame", "gi_code", "cr_frame",
    "cr_code", "tb_frame", "f_globals", "f_locals", "f_back", "f_builtins", "func_globals", "mro",
}
_ALLOWED_TO_METHODS = {"to_numpy", "to_list", "to_dict", "to_frame", "to_datetime", "to_numeric", "to_period", "to_timestamp", "to_timedelta", "to_records"}

ALLOWED_NODES: tuple[type, ...] = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Name, ast.expr_context, ast.Delete, ast.Constant,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.Call, ast.keyword, ast.Attribute, ast.Subscript, ast.Slice, ast.Tuple,
    ast.List, ast.Dict, ast.Set, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension, ast.IfExp, ast.Lambda,
    ast.arguments, ast.arg, ast.Starred, ast.JoinedStr, ast.FormattedValue, ast.If, ast.For, ast.While, ast.Break, ast.Continue,
    ast.Pass, ast.Import, ast.ImportFrom, ast.alias, ast.Try, ast.ExceptHandler, ast.Raise, ast.Assert,
    ast.operator, ast.unaryop, ast.boolop, ast.cmpop,
)


@dataclass
class SandboxResult:
    """Structured output from sandbox code execution."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    chart_base64: Optional[str] = None
    result_data: Any = None
    execution_time: float = 0.0
    error: Optional[str] = None
    table: Optional[dict[str, Any]] = field(default=None)


class SecurityASTVisitor(ast.NodeVisitor):
    """Allow-list check of the syntax tree; collects every violation."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, ALLOWED_NODES):
            self.errors.append(f"Syntax element '{type(node).__name__}' is not allowed.")
            return
        super().generic_visit(node)

    def _check_module(self, name: str, node: ast.AST) -> None:
        root = name.split(".")[0]
        if root in FORBIDDEN_MODULES:
            self.errors.append(f"Import of forbidden module '{name}' is strictly blocked.")
        elif root not in ALLOWED_IMPORTS:
            self.errors.append(f"Import of module '{name}' is not allowed (allowed: {sorted(ALLOWED_IMPORTS)}).")
        elif isinstance(node, ast.ImportFrom) and any(a.name.startswith("_") for a in node.names):
            self.errors.append("Importing private names is not allowed.")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_module(alias.name, node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level or not node.module:
            self.errors.append("Relative imports are not allowed.")
            return
        self._check_module(node.module, node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_CALLS and not isinstance(node.ctx, ast.Store):
            self.errors.append(f"Invocation of restricted builtin '{node.id}()' is strictly blocked.")
        elif node.id.startswith("__"):
            self.errors.append(f"Access to name '{node.id}' is restricted.")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        attr = node.attr
        if attr.startswith("_"):
            self.errors.append(f"Access to private attribute '{attr}' is restricted.")
        elif attr in DENIED_ATTRIBUTES:
            self.errors.append(f"Access to attribute '{attr}' is restricted.")
        elif (attr.startswith("read_") or attr.startswith("to_")) and attr not in _ALLOWED_TO_METHODS:
            self.errors.append(f"Access to attribute '{attr}' (file/database I/O) is restricted.")
        self.generic_visit(node)


def sign_request(secret: str, body: bytes) -> str:
    """``X-Signature`` of a request to the sandbox container: HMAC-SHA256 of the raw body (``sandbox_server`` checks the same)."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class SafePythonSandbox:
    """Executes analysis code in an isolated, resource-limited child interpreter.

    With ``remote_url`` the interpreter lives in the separate network-less sandbox container (``sandbox_server.py``)
    instead of a child process of the API: the code is still checked here first, then sent with the data as Parquet.
    If that container is configured but cannot be reached the run FAILS: it never silently falls back to running next
    to the API's secrets.
    """

    def __init__(
        self,
        timeout_seconds: float = DEFAULT_SANDBOX_TIMEOUT,
        memory_mb: int = DEFAULT_MEMORY_MB,
        remote_url: str = "",
        remote_secret: str = "",
    ) -> None:
        self.timeout_seconds: float = timeout_seconds
        self.memory_mb: int = memory_mb
        self.remote_url: str = remote_url.rstrip("/")
        self.remote_secret: str = remote_secret

    def validate_code(self, code: str) -> tuple[bool, Optional[str]]:
        """Statically inspect code against the AST allow-list."""
        try:
            tree = ast.parse(code)
        except SyntaxError as syn_err:
            return False, f"Cú pháp Python không hợp lệ: {syn_err}"

        visitor = SecurityASTVisitor()
        visitor.visit(tree)
        if visitor.errors:
            return False, "; ".join(dict.fromkeys(visitor.errors))
        return True, None

    async def execute_async(self, code: str, df: Optional[pd.DataFrame] = None) -> SandboxResult:
        """Run the (blocking) child process off the event loop."""
        return await asyncio.to_thread(self.execute_sync, code, df)

    def execute_sync(self, code: str, df: Optional[pd.DataFrame] = None) -> SandboxResult:
        """Validate, then run ``code`` in a child interpreter; the child is killed on timeout."""
        start = time.time()
        is_safe, err_msg = self.validate_code(code)
        if not is_safe:
            logger.warning("Security Sandbox blocked unsafe code: %s", err_msg)
            return SandboxResult(success=False, error=f"Chính sách bảo mật từ chối thực thi mã: {err_msg}", execution_time=round(time.time() - start, 3))

        if self.remote_url:
            return self._execute_remote(code, df, start)

        payload = pickle.dumps({"code": code, "df": df, "timeout": self.timeout_seconds, "memory_mb": self.memory_mb})
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        env = {
            "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "MPLBACKEND": "Agg",
            "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "SANDBOX_ROOT": root,
        }
        if os.name == "nt":  # the interpreter needs these to start on Windows
            env.update({k: os.environ[k] for k in ("SYSTEMROOT", "PATH") if k in os.environ})
        try:
            proc = subprocess.run(
                [sys.executable, "-I", _WORKER], input=payload, capture_output=True, timeout=self.timeout_seconds + 5,
                env=env, cwd=root,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Sandbox execution timed out after %.1fs", self.timeout_seconds)
            return SandboxResult(
                success=False,
                error=f"Thời gian thực thi mã Python vượt quá giới hạn an toàn ({self.timeout_seconds}s).",
                execution_time=self.timeout_seconds,
            )

        try:
            out = json.loads(proc.stdout.decode("utf-8").strip().splitlines()[-1])
        except (IndexError, ValueError):
            if proc.returncode == -getattr(signal, "SIGXCPU", 0) or time.time() - start >= self.timeout_seconds:
                # the worker's own CPU limit (RLIMIT_CPU, POSIX) killed a runaway loop a moment before our timeout did: same thing
                logger.warning("Sandbox worker killed at the CPU limit (returncode=%s)", proc.returncode)
                return SandboxResult(
                    success=False,
                    error=f"Thời gian thực thi mã Python vượt quá giới hạn an toàn ({self.timeout_seconds}s).",
                    execution_time=round(time.time() - start, 3),
                )
            detail = proc.stderr.decode("utf-8", errors="replace")[-300:]
            return SandboxResult(success=False, error=f"Lỗi thực thi Python: sandbox worker failed ({detail})", execution_time=round(time.time() - start, 3))

        result = SandboxResult(
            success=out["success"], stdout=out.get("stdout", ""), chart_base64=out.get("chart_base64"), error=out.get("error"),
            execution_time=round(time.time() - start, 3),
        )
        data = out.get("result")
        if isinstance(data, dict) and "__table__" in data:
            result.table = data["__table__"]
            result.result_data = data["__table__"]
        else:
            result.result_data = data
        return result

    def _execute_remote(self, code: str, df: Optional[pd.DataFrame], start: float) -> SandboxResult:
        """Run already-validated ``code`` in the sandbox container (see ``sandbox_server.py`` for the protocol)."""
        import httpx  # only the API needs it: the sandbox image serves with the standard library

        def failed(message: str) -> SandboxResult:
            return SandboxResult(success=False, error=message, execution_time=round(time.time() - start, 3))

        request: dict[str, Any] = {"code": code, "timeout": self.timeout_seconds, "memory_mb": self.memory_mb}
        try:
            if df is not None:
                frame = df.copy()
                frame.columns = [str(c) for c in frame.columns]
                request["df_parquet_b64"] = base64.b64encode(frame.to_parquet()).decode("ascii")
        except Exception as exc:  # noqa: BLE001 - a frame Parquet cannot hold (mixed-type object column...)
            logger.warning("Could not serialise the data frame for the sandbox container: %s", exc)
            return failed(f"Không chuyển được dữ liệu sang sandbox: {exc}")

        body = json.dumps(request).encode()
        try:
            response = httpx.post(
                f"{self.remote_url}/run", content=body, timeout=self.timeout_seconds + 15,
                headers={"Content-Type": "application/json", "X-Signature": sign_request(self.remote_secret, body)},
            )
        except httpx.HTTPError as exc:
            logger.error("Sandbox container unreachable (%s): refusing to run the code elsewhere", type(exc).__name__)
            return failed("Sandbox phân tích không khả dụng lúc này, mã không được chạy. Hãy thử lại sau.")
        if response.status_code != 200:
            logger.error("Sandbox container answered HTTP %s", response.status_code)
            return failed("Sandbox phân tích từ chối hoặc không xử lý được yêu cầu." if response.status_code in (401, 503) else f"Lỗi sandbox (HTTP {response.status_code}).")
        out = response.json()
        return SandboxResult(
            success=bool(out.get("success")), stdout=out.get("stdout", ""), stderr=out.get("stderr", ""), chart_base64=out.get("chart_base64"),
            result_data=out.get("result_data"), execution_time=round(time.time() - start, 3), error=out.get("error"), table=out.get("table"),
        )


# ---------------------------------------------------------------------------
# Worker side (runs inside the child interpreter; see sandbox_worker.py)
# ---------------------------------------------------------------------------

_SAFE_BUILTINS = {
    name: getattr(_builtins, name)
    for name in (
        "len", "range", "enumerate", "zip", "min", "max", "sum", "abs", "round", "int", "float", "str", "bool", "list", "dict", "set",
        "tuple", "frozenset", "isinstance", "sorted", "reversed", "any", "all", "map", "filter", "divmod", "pow", "ord", "chr", "repr",
        "slice", "hasattr", "ValueError", "KeyError", "TypeError", "IndexError", "ZeroDivisionError", "Exception", "StopIteration",
    )
}


def _safe_import(name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0) -> Any:
    if level or name.split(".")[0] not in ALLOWED_IMPORTS:
        raise ImportError(f"Import of '{name}' is not allowed")
    return importlib.import_module(name) if fromlist else importlib.import_module(name.split(".")[0])


def _apply_limits(memory_mb: int, timeout: float) -> None:
    try:
        import resource
    except ImportError:  # Windows
        return
    limit = memory_mb * 1024 * 1024
    for res, value in ((resource.RLIMIT_AS, limit), (resource.RLIMIT_CPU, int(timeout) + 2), (resource.RLIMIT_FSIZE, 0)):
        try:
            resource.setrlimit(res, (value, value))
        except (ValueError, OSError):
            pass


def _jsonable(value: Any) -> Any:
    """Turn an analysis result into JSON: tables become ``{"__table__": {...}}``."""
    if isinstance(value, pd.Series):
        keep_index = value.index.name or not isinstance(value.index, pd.RangeIndex)
        value = value.rename("value").reset_index() if keep_index else value.to_frame("value")
    if isinstance(value, pd.DataFrame):
        frame = value.head(MAX_RESULT_ROWS).copy()
        frame.columns = [str(c) for c in frame.columns]
        rows = json.loads(frame.to_json(orient="values", date_format="iso", default_handler=str))
        return {"__table__": {"columns": list(frame.columns), "rows": rows, "total_rows": int(len(value))}}
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def run_untrusted(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute validated code with restricted builtins; return a JSON-safe result dict."""
    code, df = payload["code"], payload.get("df")
    ok, message = SafePythonSandbox().validate_code(code)
    if not ok:
        return {"success": False, "error": f"Chính sách bảo mật từ chối thực thi mã: {message}"}

    _apply_limits(payload.get("memory_mb", DEFAULT_MEMORY_MB), payload.get("timeout", DEFAULT_SANDBOX_TIMEOUT))
    stdout = io.StringIO()
    safe_builtins = dict(_SAFE_BUILTINS)
    safe_builtins["print"] = lambda *args, **kwargs: print(*args, file=stdout, **kwargs)
    safe_builtins["__import__"] = _safe_import
    namespace: dict[str, Any] = {"__builtins__": safe_builtins, "pd": pd, "np": np, "math": math, "df": df if df is not None else pd.DataFrame()}
    try:
        import scipy.stats as stats

        namespace["stats"] = stats
    except ImportError:
        pass

    plt = None
    if "plt" in code:
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt  # noqa: F811

            namespace["plt"] = plt
        except ImportError:
            plt = None

    try:
        with contextlib.redirect_stdout(stdout):
            exec(compile(code, "<sandbox>", "exec"), namespace)  # noqa: S102 - validated, restricted, isolated process
        chart = None
        if plt is not None and plt.get_fignums():
            buffer = io.BytesIO()
            plt.tight_layout()
            plt.savefig(buffer, format="png", dpi=100, bbox_inches="tight")
            chart = base64.b64encode(buffer.getvalue()).decode("ascii")
        result = next((namespace[k] for k in ("result", "output", "predictions") if namespace.get(k) is not None), None)
        return {"success": True, "stdout": stdout.getvalue(), "chart_base64": chart, "result": _jsonable(result)}
    except Exception as exc:  # noqa: BLE001 - report any user-code error
        return {"success": False, "stdout": stdout.getvalue(), "error": f"Lỗi thực thi Python: {exc}"}
