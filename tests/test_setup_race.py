"""Replicas that start together on an EMPTY database must not fight over its one-time setup (extension, base schema)."""
import asyncio
import os
import subprocess
import sys

import pytest

from src.shared.migrations import ROOT
from src.shared.postgres_client import PostgresClient

DSN = os.getenv("RAG_TEST_DSN")

# what a backend replica does at start, reduced to the database part
START = """
import asyncio, os
from src.shared.postgres_client import PostgresClient
from src.ingestion.schema import ensure_schema

async def main():
    pg = PostgresClient(dsn=os.environ["POSTGRES_URL"])
    await pg.connect(min_size=1, max_size=2)   # CREATE EXTENSION vector
    try:
        await ensure_schema(pg)                # table + indexes
    finally:
        await pg.disconnect()

asyncio.run(main())
"""


@pytest.mark.skipif(not DSN, reason="set RAG_TEST_DSN to a scratch PostgreSQL database (superuser)")
def test_four_replicas_starting_on_an_empty_database_all_succeed():
    async def wipe():
        pg = PostgresClient(dsn=DSN, ensure_pgvector=False)
        await pg.connect(min_size=1, max_size=1)
        try:
            await pg.execute("DROP TABLE IF EXISTS rag_chunks, conversations, alembic_version CASCADE")
            await pg.execute("DROP EXTENSION IF EXISTS vector CASCADE")
        finally:
            await pg.disconnect()

    asyncio.run(wipe())
    env = {**os.environ, "POSTGRES_URL": DSN, "PYTHONPATH": str(ROOT)}
    procs = [subprocess.Popen([sys.executable, "-c", START], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    outputs = [p.communicate(timeout=180) for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0, 0], [err[-400:] for _, err in outputs]
