"""A read-only PostgreSQL role for the Database Agent.

The application connects as the database owner (it creates tables, ingests documents, runs Langfuse's schema in the same
database...). The Database Agent runs SQL that an LLM wrote, so it must not use that account: the SQL validator and the
Row-Level-Security rewrite are application-level defences that a bug or a new syntax can slip past. This module makes the
database itself enforce the boundary:

  * ``NOSUPERUSER NOCREATEDB NOCREATEROLE``, and every transaction read-only (``default_transaction_read_only``);
  * ``SELECT`` on an explicit allow-list of tables (``DB_AGENT_TABLES``) and nothing else: no other table, no other schema
    (Langfuse's 40+ tables stay out of reach), no DDL, no writes;
  * a statement timeout, so a runaway query cannot hold a connection.

``ensure_readonly_role`` is idempotent and runs at gateway start when ``DB_AGENT_PASSWORD`` is set.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
STATEMENT_TIMEOUT = "15s"
IDLE_IN_TRANSACTION_TIMEOUT = "30s"


def _identifier(value: str, what: str) -> str:
    if not _IDENTIFIER.match(value):
        raise ValueError(f"Invalid {what} {value!r}: use lowercase letters, digits and underscores only")
    return f'"{value}"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def readonly_dsn(admin_dsn: str, role: str, password: str) -> str:
    """``admin_dsn`` with the credentials replaced by the read-only role's."""
    parts = urlsplit(admin_dsn)
    host = parts.hostname or "localhost"
    netloc = f"{quote(role, safe='')}:{quote(password, safe='')}@{host}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


async def ensure_readonly_role(pg: Any, role: str, password: str, tables: list[str], schema: str = "public") -> list[str]:
    """Create/refresh ``role`` (run with the admin pool ``pg``); returns the tables it can read (missing ones are skipped)."""
    if len(password) < 16:
        raise ValueError("DB_AGENT_PASSWORD must be at least 16 characters")
    quoted_role, quoted_schema = _identifier(role, "role name"), _identifier(schema, "schema")
    database = (await pg.fetch("SELECT current_database() AS name"))[0]["name"]
    quoted_database = '"' + database.replace('"', '""') + '"'

    exists = await pg.fetch("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
    verb = "ALTER" if exists else "CREATE"
    await pg.execute(f"{verb} ROLE {quoted_role} LOGIN PASSWORD {_literal(password)} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION")
    await pg.execute(f"ALTER ROLE {quoted_role} SET default_transaction_read_only = on")
    await pg.execute(f"ALTER ROLE {quoted_role} SET statement_timeout = '{STATEMENT_TIMEOUT}'")
    await pg.execute(f"ALTER ROLE {quoted_role} SET idle_in_transaction_session_timeout = '{IDLE_IN_TRANSACTION_TIMEOUT}'")
    await pg.execute(f"GRANT CONNECT ON DATABASE {quoted_database} TO {quoted_role}")
    await pg.execute(f"GRANT USAGE ON SCHEMA {quoted_schema} TO {quoted_role}")
    await pg.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {quoted_schema} FROM {quoted_role}")  # start from nothing, every time

    granted: list[str] = []
    for table in tables:
        quoted_table = _identifier(table, "table name")
        if await pg.fetch("SELECT 1 FROM pg_tables WHERE schemaname = $1 AND tablename = $2", schema, table):
            await pg.execute(f"GRANT SELECT ON TABLE {quoted_schema}.{quoted_table} TO {quoted_role}")
            await _apply_tenant_policy(pg, quoted_role, quoted_schema, quoted_table, schema, table)
            granted.append(table)
        else:
            logger.warning("db_agent role: table %s.%s does not exist yet, not granted", schema, table, extra={"session_id": "SYSTEM"})
    logger.info("Read-only role %s ready: SELECT on %s", role, granted or "nothing", extra={"session_id": "SYSTEM"})
    return granted


# What the policies read: set per transaction by ``PostgresClient.fetch_scoped`` (``set_config(name, value, true)``).
SCOPE_SETTINGS: dict[str, str] = {"tenant_id": "app.tenant_id", "department_id": "app.department_id"}
POLICY_NAME = "tenant_scope"


async def _apply_tenant_policy(pg: Any, quoted_role: str, quoted_schema: str, quoted_table: str, schema: str, table: str) -> None:
    """Row-Level Security in PostgreSQL itself, for a table that carries ``tenant_id`` and/or ``department_id``.

    The rewrite in ``rls_transformer`` adds the same predicates to the SQL text; this policy makes the database refuse
    the other rows even if that rewrite is bypassed. With no ``app.*`` setting in the transaction ``current_setting(.., true)``
    is NULL, the predicate is never true and the role sees no rows (fail closed). The owner (the application's own account)
    is not subject to the policy, so ingestion and maintenance are unaffected.
    """
    columns = {
        r["column_name"]
        for r in await pg.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = $1 AND table_name = $2 AND column_name = ANY($3::text[])",
            schema, table, list(SCOPE_SETTINGS),
        )
    }
    if not columns:
        logger.warning(
            "db_agent role: %s.%s has no tenant_id/department_id column, so the database cannot separate its rows by tenant "
            "(the Database Agent's own tenant filter cannot be applied to it either)", schema, table, extra={"session_id": "SYSTEM"},
        )
        return
    predicate = " AND ".join(f"{column}::text = current_setting('{SCOPE_SETTINGS[column]}', true)" for column in SCOPE_SETTINGS if column in columns)
    await pg.execute(f"ALTER TABLE {quoted_schema}.{quoted_table} ENABLE ROW LEVEL SECURITY")
    await pg.execute(f'DROP POLICY IF EXISTS "{POLICY_NAME}" ON {quoted_schema}.{quoted_table}')
    await pg.execute(f'CREATE POLICY "{POLICY_NAME}" ON {quoted_schema}.{quoted_table} FOR SELECT TO {quoted_role} USING ({predicate})')
    logger.info("Row-Level Security policy on %s.%s: %s", schema, table, sorted(columns), extra={"session_id": "SYSTEM"})
