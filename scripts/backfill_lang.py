"""Fill ``rag_chunks.lang`` for chunks written before migration 0007 (new chunks get it when they are ingested).

    python -m scripts.backfill_lang                 # every chunk whose lang is NULL
    docker exec agent_backend python -m scripts.backfill_lang

The language ('vi' / 'en') decides in which language(s) the query planner writes its HyDE passages: a corpus that is mostly
English is searched with English passages, one with Vietnamese documents also with Vietnamese ones. Until this runs the
languages of old chunks are unknown and the search behaves as it did before (English passages only). Nothing is re-embedded.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.agents.data_agent.i18n import detect_language  # noqa: E402
from src.config import settings  # noqa: E402
from src.shared.postgres_client import PostgresClient  # noqa: E402


async def run(dsn: str) -> dict[str, int]:
    pg = PostgresClient(dsn=dsn, ensure_pgvector=False)
    await pg.connect(min_size=1, max_size=2)
    try:
        rows = await pg.fetch("SELECT id, raw_content FROM rag_chunks WHERE lang IS NULL")
        by_language: dict[str, list[int]] = {}
        for row in rows:
            by_language.setdefault(detect_language((row["raw_content"] or "")[:600]), []).append(row["id"])
        for language, ids in by_language.items():
            await pg.execute("UPDATE rag_chunks SET lang = $1 WHERE id = ANY($2::bigint[])", language, ids)
        return {language: len(ids) for language, ids in by_language.items()}
    finally:
        await pg.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", default=settings.POSTGRES_URL, help="database to update (default: POSTGRES_URL)")
    counts = asyncio.run(run(parser.parse_args().dsn))
    print(f"language filled for {sum(counts.values())} chunk(s): {counts or 'nothing to do'}")


if __name__ == "__main__":
    main()
