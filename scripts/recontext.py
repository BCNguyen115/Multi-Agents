"""Add LLM-written context sentences ("contextual retrieval") to chunks that are already stored, and re-embed them.

    python -m scripts.recontext --dsn postgresql://admin:pw@127.0.0.1:55432/postgres     # a COPY of the table: to measure first
    python -m scripts.recontext --dry-run                                                # how many chunks / LLM calls, no change
    python -m scripts.recontext --only nda --limit-docs 3

For each document the model sees the start of the document and a chunk and writes one sentence (see src/ingestion/context.py);
``content`` becomes ``<prefix>[Context: ...]\\n\\n<text>`` and the embedding is recomputed (the full-text column follows by
itself). ``raw_content`` is never touched. Chunks that already carry a context are skipped unless ``--force``.
It costs one LLM call and one embedding per chunk: measure on a copy with ``scripts/run_rag_eval.py`` before running it on the real table.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
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
from src.ingestion.chunker import DocumentChunk  # noqa: E402
from src.ingestion.context import CONTEXT_MARK, EXCERPT_CHARS, apply_context, contextualize  # noqa: E402
from src.ingestion.embedder import IngestionEmbedder  # noqa: E402
from src.shared.llm_client import LLMClient  # noqa: E402
from src.shared.postgres_client import PostgresClient  # noqa: E402

KEY = "COALESCE(doc_key, category || '/' || filename)"


async def run(args: argparse.Namespace) -> int:
    pg = PostgresClient(dsn=args.dsn, ensure_pgvector=False)
    await pg.connect(min_size=1, max_size=4)
    try:
        rows = await pg.fetch(
            f"SELECT id, {KEY} AS doc, category, section_title, raw_content, content FROM rag_chunks "
            "WHERE ($1::text IS NULL OR category = $1) ORDER BY doc, chunk_index NULLS LAST, id",
            args.only,
        )
        documents: dict[str, list] = {}
        for row in rows:
            documents.setdefault(row["doc"], []).append(row)
        todo = {k: v for k, v in documents.items() if args.force or any(CONTEXT_MARK not in r["content"] for r in v)}
        if args.limit_docs:
            todo = dict(list(todo.items())[: args.limit_docs])
        chunks = sum(len(v) for v in todo.values())
        print(f"{len(rows)} chunks in {len(documents)} documents; to do: {chunks} chunks in {len(todo)} documents")
        if args.dry_run or not chunks:
            return 0

        llm = LLMClient(settings=settings)
        embedder = IngestionEmbedder(pg=pg, openai_client=openai.AsyncOpenAI(api_key=settings.OPENROUTER_API_KEY, base_url=settings.OPENROUTER_BASE_URL))
        started, done, with_context = time.time(), 0, 0
        for doc, group in todo.items():
            text = "\n".join(r["raw_content"] for r in group)[:EXCERPT_CHARS]
            contexts = await contextualize(llm, text, [(r["section_title"] or "", r["raw_content"]) for r in group], args.concurrency)
            fresh = [(r, apply_context(r["content"], r["raw_content"], c)) for r, c in zip(group, contexts) if c]
            if fresh:
                vectors = await embedder.embed_all_chunks([DocumentChunk(content=new, raw_content=r["raw_content"]) for r, new in fresh])
                async with pg.transaction() as conn:
                    await conn.executemany(
                        "UPDATE rag_chunks SET content = $2, embedding = $3::vector WHERE id = $1",
                        [(r["id"], new, json.dumps(v.tolist())) for (r, new), v in zip(fresh, vectors)],
                    )
            done += len(group)
            with_context += len(fresh)
            print(f"  {doc}: {len(fresh)}/{len(group)} chunks  [{done}/{chunks}, {time.time() - started:.0f}s]", flush=True)
        print(f"Done: {with_context} of {chunks} chunks now carry a context ({time.time() - started:.0f}s)")
        return 0
    finally:
        await pg.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", default=settings.POSTGRES_URL, help="database to update (default: POSTGRES_URL)")
    parser.add_argument("--only", help="only this category")
    parser.add_argument("--limit-docs", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=6, help="parallel LLM calls per document")
    parser.add_argument("--force", action="store_true", help="redo chunks that already have a context")
    parser.add_argument("--dry-run", action="store_true")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
