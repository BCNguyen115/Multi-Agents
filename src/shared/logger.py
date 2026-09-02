"""Structured logging module with session_id correlation.

Provides a centralized logging setup that injects ``session_id`` into every
log record, enabling end-to-end request tracing across Gateway → Orchestrator
→ Registry → Agent.

Usage:
    from src.shared.logger import get_logger

    logger = get_logger(__name__)
    logger.info("Processing request", extra={"session_id": "abc-123"})
"""

import logging
import sys
from typing import Optional


class SessionFilter(logging.Filter):
    """Logging filter that guarantees a ``session_id`` field on every record.

    If the log call does not supply ``session_id`` via *extra*, the filter
    injects a default placeholder so formatters never break.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach default session_id if missing.

        Args:
            record: The log record to process.

        Returns:
            bool: Always ``True`` — this filter never drops records.
        """
        if not hasattr(record, "session_id"):
            record.session_id = "N/A"  # type: ignore[attr-defined]
        return True


_LOG_FORMAT: str = (
    "%(asctime)s | %(levelname)-8s | %(name)s | "
    "session_id=%(session_id)s | %(message)s"
)

_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

# Track whether the root handler has been configured to avoid duplicates.
_root_configured: bool = False


def setup_root_logger(level: str = "INFO") -> None:
    """Configure the root logger with structured format and session filter.

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

    handler: logging.StreamHandler = logging.StreamHandler(stream=sys.stdout)  # type: ignore[type-arg]
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
