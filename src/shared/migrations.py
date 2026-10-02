"""Alembic migrations, run from code.

The tables the application owns (``rag_chunks``) are versioned in ``migrations/versions``. The gateway applies pending
revisions at start (``upgrade_to_head``), ``python -m scripts.migrate`` does the same by hand, and
``alembic revision -m "..."`` / ``alembic upgrade head --sql`` work from the project root as usual.

Revision ``0001`` is the schema ``src/ingestion/schema.py`` already creates (every statement is idempotent, so an existing
database is simply recorded as being at 0001). ``schema.py`` is FROZEN at that baseline: every later change is a new
revision, never an edit there. Alembic itself needs a synchronous driver, so the URL is ``postgresql+psycopg://``.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from src.config import settings
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

ROOT: Path = Path(__file__).resolve().parents[2]


def database_url(dsn: str | None = None) -> str:
    """SQLAlchemy URL (psycopg 3 driver) for an ``asyncpg``-style ``postgresql://`` DSN; defaults to ``POSTGRES_URL``."""
    dsn = dsn or settings.POSTGRES_URL
    _, _, rest = dsn.partition("://")
    return f"postgresql+psycopg://{rest}"


def alembic_config(engine=None) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["configure_logging"] = False  # the application's own logging stays as it is
    if engine is not None:
        config.attributes["engine"] = engine
    return config


def head_revision() -> str:
    """The newest revision in ``migrations/versions`` (raises if the history has more than one head)."""
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(dsn: str | None = None) -> str | None:
    """The revision the database is at (``None`` = never migrated)."""
    engine = create_engine(database_url(dsn))
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


_in_process = threading.Lock()  # Alembic's ``context`` is a process-wide global: two threads would trample each other


def upgrade_to_head(dsn: str | None = None) -> str:
    """Apply every pending revision (blocking: call it with ``asyncio.to_thread``). Returns the revision the database is at.

    Separate processes (replicas starting together) are serialised by a PostgreSQL advisory lock taken in ``migrations/env.py``.
    """
    engine = create_engine(database_url(dsn))
    try:
        with _in_process:
            before = current_revision(dsn)
            command.upgrade(alembic_config(engine), "head")
    finally:
        engine.dispose()
    after = current_revision(dsn)
    if after != before:
        logger.info("Database migrated: %s -> %s", before, after, extra={"session_id": "SYSTEM"})
    return after or ""
