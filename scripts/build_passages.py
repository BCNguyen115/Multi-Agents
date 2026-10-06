"""Build the ~600 character passages (table ``rag_passages``) for chunks that have none, without re-ingesting anything.

    python -m scripts.build_passages                 # every chunk without passages
    python -m scripts.build_passages --limit 200     # try it on a few first
    docker exec agent_backend python -m scripts.build_passages

Needed once for a corpus ingested before RAG_INDEX_PASSAGES existed, then to measure small-to-big retrieval:

    python -m scripts.run_rag_eval --rerank --set RAG_PASSAGE_SEARCH=true --rerank-presets single10,passage10

It embeds every passage (about 5 per long chunk): a few cents for a corpus of two thousand chunks. Safe to repeat: chunks that
already have passages are skipped; passages disappear with their chunk (ON DELETE CASCADE).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

import openai  # noqa: E402

from src.config import settings  # noqa: E402
from src.ingestion.embedder import EMBEDDING_BATCH_SIZE, IngestionEmbedder  # noqa: E402
from src.ingestion.passages import split_passages  # noqa: E402
from src.shared.postgres_client import PostgresClient  # noqa: E402

CHUNKS_PER_ROUND = 50


async def run(dsn: str, limit: int) -> tuple[int, int]:
    pg = PostgresClient(dsn=dsn, ensure_pgvector=False)
    await pg.connect(min_size=1, max_size=2)
    embedder = IngestionEmbedder(pg, openai.AsyncOpenAI(api_key=settings.OPENROUTER_API_KEY, base_url=settings.OPENROUTER_BASE_URL))
    chunks_done = passages_done = 0
    try:
        rows = await pg.fetch(
            "SELECT c.id, c.raw_content FROM rag_chunks c "
            "WHERE NOT EXISTS (SELECT 1 FROM rag_passages p WHERE p.chunk_id = c.id) AND length(c.raw_content) >= 800 ORDER BY c.id"
            + (f" LIMIT {int(limit)}" if limit else "")
        )
        for start in range(0, len(rows), CHUNKS_PER_ROUND):
            batch = [(r["id"], pos, text) for r in rows[start:start + CHUNKS_PER_ROUND] for pos, text in enumerate(split_passages(r["raw_content"]))]
            vectors: list[list[float]] = []
            for i in range(0, len(batch), EMBEDDING_BATCH_SIZE):
                vectors.extend(await embedder._embed_batch([b[2] for b in batch[i:i + EMBEDDING_BATCH_SIZE]]))
            async with pg.transaction() as conn:
                await conn.executemany(
                    "INSERT INTO rag_passages (chunk_id, position, content, embedding) VALUES ($1, $2, $3, $4::vector)",
                    [(cid, pos, text, json.dumps(vec)) for (cid, pos, text), vec in zip(batch, vectors)],
                )
            chunks_done += len(rows[start:start + CHUNKS_PER_ROUND])
            passages_done += len(batch)
            print(f"  {chunks_done}/{len(rows)} chunks, {passages_done} passages")
    finally:
        await pg.disconnect()
    return chunks_done, passages_done


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", default=settings.POSTGRES_URL, help="database to update (default: POSTGRES_URL)")
    parser.add_argument("--limit", type=int, default=0, help="only the first N chunks without passages (0 = all)")
    args = parser.parse_args()
    chunks, passages = asyncio.run(run(args.dsn, args.limit))
    print(f"{passages} passage(s) built for {chunks} chunk(s)")


if __name__ == "__main__":
    main()
