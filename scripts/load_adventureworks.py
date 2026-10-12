"""Load the AdventureWorks sample company (``dataset/archive``, one xlsx per table) into PostgreSQL schema ``aw``.

    python -m scripts.load_adventureworks [--dsn DSN] [--archive DIR] [--only sales_order_header ...] [--reset]

The rules (names, what is left out, the repairs of the files) live in ``src/ingestion/aw_catalog.py``. The run prints, per table, the
rows in the workbook and the rows in the database, and exits with an error if any differ. It is safe to run again: a table that exists is
replaced, ``--reset`` drops the whole schema first. ``--dsn`` defaults to ``POSTGRES_URL``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import asyncpg
import openpyxl

from src.config import settings
from src.ingestion import aw_catalog as catalog

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARCHIVE = ROOT / "dataset" / "archive"


def read_sheet(path: Path) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Column names and rows of the first sheet of a workbook."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = workbook.worksheets[0].iter_rows(values_only=True)
        header = [str(h) for h in next(rows)]
        return header, [r for r in rows if any(cell is not None for cell in r)]
    finally:
        workbook.close()


def prepare(header: list[str], rows: list[tuple[Any, ...]]) -> tuple[list[tuple[str, str]], list[tuple[Any, ...]]]:
    """Kept columns with their PostgreSQL types, and the cleaned, typed rows."""
    keep: list[tuple[int, str]] = []
    for index, source in enumerate(header):
        name = catalog.column_name(source)
        if name not in catalog.DROPPED_COLUMNS:
            keep.append((index, name))
    cleaned = [tuple(catalog.repair_value(name, row[i] if i < len(row) else None) for i, name in keep) for row in rows]
    columns = [(name, catalog.infer_type(name, (row[pos] for row in cleaned))) for pos, (_, name) in enumerate(keep)]
    typed = [tuple(catalog.coerce(columns[pos][1], value) for pos, value in enumerate(row)) for row in cleaned]
    return columns, typed


async def load_table(conn: asyncpg.Connection, path: Path) -> tuple[str, int, int]:
    table = catalog.table_name(path.stem)
    header, rows = read_sheet(path)
    columns, typed = prepare(header, rows)
    q = catalog.quote_ident
    async with conn.transaction():
        await conn.execute(f"DROP TABLE IF EXISTS {catalog.SCHEMA}.{q(table)} CASCADE")
        await conn.execute(catalog.create_table_sql(table, columns))
        await conn.copy_records_to_table(table, records=typed, columns=[c for c, _ in columns], schema_name=catalog.SCHEMA)
        doc = catalog.table_doc(table)
        if doc:
            await conn.execute(f"COMMENT ON TABLE {catalog.SCHEMA}.{q(table)} IS '{doc.replace(chr(39), chr(39) * 2)}'")
    for statement in catalog.index_sql(table, [c for c, _ in columns], len(typed)):
        await conn.execute(statement)
    stored = await conn.fetchval(f"SELECT count(*) FROM {catalog.SCHEMA}.{q(table)}")
    return table, len(rows), int(stored)


def workbooks(archive: Path, only: set[str]) -> list[Path]:
    found = []
    for path in sorted(archive.glob("*.xlsx")):
        table = catalog.table_name(path.stem)
        if table in catalog.EXCLUDED_TABLES or (only and table not in only):
            continue
        found.append(path)
    return found


async def run(dsn: str, archive: Path, only: set[str], reset: bool) -> int:
    paths = workbooks(archive, only)
    if not paths:
        print(f"no workbook to load in {archive}", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn)
    try:
        if reset:
            await conn.execute(f"DROP SCHEMA IF EXISTS {catalog.SCHEMA} CASCADE")
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {catalog.SCHEMA}")
        mismatches = 0
        for path in paths:
            started = time.time()
            table, expected, stored = await load_table(conn, path)
            flag = "" if expected == stored else "  <-- MISMATCH"
            mismatches += expected != stored
            print(f"{table:<34}{expected:>9} xlsx {stored:>9} db {time.time() - started:6.1f}s{flag}", flush=True)
        await conn.execute("ANALYZE")
    finally:
        await conn.close()
    print(f"{len(paths)} tables loaded into schema {catalog.SCHEMA}" + (f", {mismatches} with a different row count" if mismatches else ""))
    return 1 if mismatches else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", default=settings.POSTGRES_URL)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--only", nargs="*", default=[], help="table names (snake_case) to load")
    parser.add_argument("--reset", action="store_true", help="drop schema aw first")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.dsn, args.archive, set(args.only), args.reset)))


if __name__ == "__main__":
    main()
