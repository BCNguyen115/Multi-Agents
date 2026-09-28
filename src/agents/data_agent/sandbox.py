"""Secure Python Execution Sandbox for Advanced Analytics, Regression & Forecasting.

Provides an isolated, resource-constrained, timeout-enforced runtime for
executing Python code generated for Data Analyst tasks that exceed standard
SQL/DuckDB capabilities (e.g., statistical modelling, ARIMA/linear regression,
outlier distribution analysis, matplotlib charting).

Enforces:
  1. AST & Token-level Security Guardrails (blocks os, sys, subprocess, sockets, filesystem IO).
  2. Strict Execution Timeout (5.0s max).
  3. Matplotlib headless figure capture to Base64 PNG.
  4. Pre-populated safe scientific environment (pandas, numpy, scipy, sklearn).
"""

from __future__ import annotations

import ast
import asyncio
import base64
import contextlib
import io
import logging
import math
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Maximum execution timeout in seconds
DEFAULT_SANDBOX_TIMEOUT: float = 5.0

# Forbidden tokens and AST nodes for security isolation
FORBIDDEN_CALLS: set[str] = {
    "open",
    "eval",
    "exec",
    "compile",
    "globals",
    "locals",
    "vars",
    "__import__",
    "getattr",
    "setattr",
    "delattr",
}

FORBIDDEN_MODULES: set[str] = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "urllib",
    "requests",
    "http",
    "ftplib",
    "poplib",
    "smtplib",
    "telnetlib",
    "pty",
    "posix",
    "nt",
    "threading",
    "multiprocessing",
    "signal",
}


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


class SecurityASTVisitor(ast.NodeVisitor):
    """Inspects Python AST to ensure code violates no security constraints."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root_module = alias.name.split(".")[0]
            if root_module in FORBIDDEN_MODULES:
                self.errors.append(f"Import of forbidden module '{alias.name}' is strictly blocked.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root_module = node.module.split(".")[0]
            if root_module in FORBIDDEN_MODULES:
                self.errors.append(f"Import from forbidden module '{node.module}' is strictly blocked.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            self.errors.append(f"Invocation of restricted builtin '{node.func.id}()' is strictly blocked.")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self.errors.append(f"Access to private dunder attribute '{node.attr}' is restricted.")
        self.generic_visit(node)


class SafePythonSandbox:
    """Enterprise Secure Execution Sandbox for Data Analytics & ML."""

    def __init__(self, timeout_seconds: float = DEFAULT_SANDBOX_TIMEOUT) -> None:
        self.timeout_seconds: float = timeout_seconds

    def validate_code(self, code: str) -> tuple[bool, Optional[str]]:
        """Statically inspect code with Python AST visitor."""
        try:
            tree = ast.parse(code)
        except SyntaxError as syn_err:
            return False, f"Cú pháp Python không hợp lệ: {syn_err}"

        visitor = SecurityASTVisitor()
        visitor.visit(tree)
        if visitor.errors:
            return False, "; ".join(visitor.errors)

        return True, None

    async def execute_async(
        self,
        code: str,
        df: Optional[pd.DataFrame] = None,
    ) -> SandboxResult:
        """Run execution safely in a separate thread with a hard timeout."""
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self.execute_sync, code, df),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("Sandbox execution timed out after %.1fs", self.timeout_seconds)
            return SandboxResult(
                success=False,
                error=f"Thời gian thực thi mã Python vượt quá giới hạn an toàn ({self.timeout_seconds}s).",
                execution_time=self.timeout_seconds,
            )

    def execute_sync(
        self,
        code: str,
        df: Optional[pd.DataFrame] = None,
    ) -> SandboxResult:
        """Synchronously execute Python code with safe globals and chart capture."""
        start_time = time.time()

        # Step 1: Static AST Validation
        is_safe, err_msg = self.validate_code(code)
        if not is_safe:
            logger.warning("Security Sandbox blocked unsafe code: %s", err_msg)
            return SandboxResult(
                success=False,
                error=f"Chính sách bảo mật từ chối thực thi mã: {err_msg}",
                execution_time=round(time.time() - start_time, 3),
            )

        # Step 2: Prepare Isolated Scientific Environment
        has_matplotlib = False
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.clf()
            plt.close("all")
            has_matplotlib = True
        except ImportError:
            plt = None

        # Build isolated namespace
        stdout_capture = io.StringIO()
        chart_base64: Optional[str] = None
        result_val: Any = None

        safe_globals: dict[str, Any] = {
            "__builtins__": {
                "print": lambda *args, **kwargs: print(*args, file=stdout_capture, **kwargs),
                "len": len,
                "range": range,
                "enumerate": enumerate,
                "zip": zip,
                "min": min,
                "max": max,
                "sum": sum,
                "abs": abs,
                "round": round,
                "int": int,
                "float": float,
                "str": str,
                "bool": bool,
                "list": list,
                "dict": dict,
                "set": set,
                "tuple": tuple,
                "isinstance": isinstance,
                "math": math,
            },
            "pd": pd,
            "np": np,
            "df": df.copy() if df is not None else pd.DataFrame(),
        }

        if has_matplotlib:
            safe_globals["plt"] = plt

        # Optionally load scipy and sklearn if available
        try:
            import scipy
            import scipy.stats as stats
            safe_globals["scipy"] = scipy
            safe_globals["stats"] = stats
        except ImportError:
            pass

        try:
            import sklearn
            safe_globals["sklearn"] = sklearn
        except ImportError:
            pass

        safe_locals: dict[str, Any] = {}

        try:
            compiled_code = compile(code, "<sandbox>", "exec")
            with contextlib.redirect_stdout(stdout_capture):
                exec(compiled_code, safe_globals, safe_locals)

            # Check if any matplotlib figures were plotted
            if has_matplotlib and plt is not None:
                fig_nums = plt.get_fignums()
                if fig_nums:
                    buf = io.BytesIO()
                    plt.tight_layout()
                    plt.savefig(buf, format="png", dpi=100, bbox_inches="tight")
                    buf.seek(0)
                    chart_base64 = base64.b64encode(buf.read()).decode("utf-8")
                    plt.close("all")

            # Extract primary result if defined in locals
            result_val = safe_locals.get("result") or safe_locals.get("output") or safe_locals.get("predictions")

            exec_time = round(time.time() - start_time, 3)
            return SandboxResult(
                success=True,
                stdout=stdout_capture.getvalue(),
                chart_base64=chart_base64,
                result_data=result_val,
                execution_time=exec_time,
            )

        except Exception as runtime_err:
            exec_time = round(time.time() - start_time, 3)
            logger.error("Sandbox runtime error: %s", runtime_err)
            return SandboxResult(
                success=False,
                stdout=stdout_capture.getvalue(),
                error=f"Lỗi thực thi Python: {runtime_err}",
                execution_time=exec_time,
            )
        finally:
            if has_matplotlib and plt is not None:
                plt.close("all")
