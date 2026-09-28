"""Structured logging module with session_id correlation.

Provides a centralized logging setup that injects ``session_id`` into every
log record, enabling end-to-end request tracing across Gateway → Orchestrator
→ Registry → Agent.

Usage:
    from src.shared.logger import get_logger

    logger = get_logger(__name__)
    logger.info("Processing request", extra={"session_id": "abc-123"})
"""

import json
import logging
import os
import sys
from typing import Optional


class SessionFilter(logging.Filter):
    """Logging filter that guarantees ``session_id`` and ``trace_id`` on every record.

    If the log call does not supply ``session_id`` or ``trace_id`` via *extra*,
    the filter injects default placeholders so formatters never break.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach default session_id and trace_id if missing."""
        if not hasattr(record, "session_id"):
            record.session_id = "N/A"  # type: ignore[attr-defined]
        if not hasattr(record, "trace_id"):
            record.trace_id = getattr(record, "session_id", "N/A")  # type: ignore[attr-defined]
        return True


class JsonFormatter(logging.Formatter):
    """Single-line JSON log formatter for structured observability with Langfuse."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "session_id": getattr(record, "session_id", "N/A"),
            "trace_id": getattr(record, "trace_id", getattr(record, "session_id", "N/A")),
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


_LOG_FORMAT: str = (
    "%(asctime)s | %(levelname)-8s | %(name)s | "
    "session_id=%(session_id)s | trace_id=%(trace_id)s | %(message)s"
)

_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

# Track whether the root handler has been configured to avoid duplicates.
_root_configured: bool = False


def setup_root_logger(level: str = "INFO") -> None:
    """Configure the root logger with structured format and session/trace filter.

    This function is idempotent — calling it multiple times will not add
    duplicate handlers.

    Args:
        level: Logging level string (e.g. ``"DEBUG"``, ``"INFO"``).
    """
    global _root_configured  # noqa: PLW0603
    if _root_configured:
        return

    root_logger: logging.Logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    handler: logging.StreamHandler = logging.StreamHandler(stream=sys.stdout)  # type: ignore[type-arg]

    use_json = os.environ.get("LOG_FORMAT", "").lower() == "json"
    if use_json:
        handler.setFormatter(JsonFormatter(datefmt=_DATE_FORMAT))
    else:
        handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT))

    handler.addFilter(SessionFilter())

    root_logger.addHandler(handler)
    _root_configured = True


def get_logger(name: Optional[str] = None, level: str = "INFO") -> logging.Logger:
    """Return a named logger pre-configured with the session-aware format.

    On the first call, this also sets up the root logger via
    :func:`setup_root_logger`.

    Args:
        name: Logger name — typically ``__name__`` of the calling module.
        level: Logging level string (default ``"INFO"``).

    Returns:
        logging.Logger: A configured logger instance.
    """
    setup_root_logger(level=level)
    logger: logging.Logger = logging.getLogger(name)
    return logger
