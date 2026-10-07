"""Run one function in a throw-away child process, with a deadline and (where the OS allows it) memory and CPU limits.

For work on files nobody here wrote (PDF, DOCX, PPTX parsing, OCR): a parser bug, a decompression bomb or a crafted file then
costs a child process, not the API's memory, event loop or secrets. The child is a fresh interpreter (``spawn``): it shares
nothing with the API process except the arguments and the result, which must be picklable.

``resource`` limits exist on Linux (the container the API runs in); elsewhere the deadline and the isolation still apply.
"""

from __future__ import annotations

import multiprocessing
import os
from typing import Any, Callable


class IsolatedError(RuntimeError):
    """The child raised, crashed or died (for instance out of memory)."""


def _child(conn: Any, func: Callable[..., Any], args: tuple[Any, ...], memory_mb: int, cpu_seconds: int) -> None:
    try:
        try:
            import resource

            if memory_mb:
                resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024, memory_mb * 1024 * 1024))
            if cpu_seconds:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        except (ImportError, ValueError, OSError):
            pass  # not available here: the deadline still holds
        conn.send(("ok", func(*args)))
    except BaseException as exc:  # noqa: BLE001 - whatever happened, the parent hears about it
        try:
            conn.send(("error", type(exc).__name__, str(exc)[:300]))
        except Exception:  # noqa: BLE001
            os._exit(1)
    finally:
        conn.close()


def run_isolated(func: Callable[..., Any], *args: Any, timeout: float, memory_mb: int = 0) -> Any:
    """``func(*args)`` in a child process. Raises ``TimeoutError`` after ``timeout`` seconds (the child is killed) and
    ``IsolatedError`` when the child failed. ``func`` must be importable at module level."""
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child, args=(sender, func, args, memory_mb, int(timeout) + 5), daemon=True)
    process.start()
    sender.close()
    try:
        if not receiver.poll(timeout):
            raise TimeoutError(f"no answer within {timeout} s")
        try:
            message = receiver.recv()
        except EOFError:
            raise IsolatedError("the worker died without an answer (out of memory, or it crashed)") from None
    finally:
        receiver.close()
        if process.is_alive():
            process.kill()
        process.join(5)
    if message[0] == "ok":
        return message[1]
    raise IsolatedError(f"{message[1]}: {message[2]}")
