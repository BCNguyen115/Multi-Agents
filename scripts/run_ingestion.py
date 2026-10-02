"""RAG ingestion pipeline (incremental).

    load PDF/DOCX -> detect sections -> chunk (with page numbers) -> embed -> per-document dedup -> pgvector

Only new or changed documents (by content hash) are embedded and stored; unchanged ones are skipped, so adding
one file costs one file. Each document is replaced atomically.

Usage (from the project root):
    python -m scripts.run_ingestion                 # sync: new/changed documents only
    python -m scripts.run_ingestion --prune         # also delete documents that left the dataset folder
    python -m scripts.run_ingestion --reset         # wipe rag_chunks first, then ingest everything
    docker exec agent_backend python -m scripts.run_ingestion

Exit code is 1 when any document failed to ingest.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT: Path = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

import openai  # noqa: E402

from src.config import settings  # noqa: E402
from src.ingestion.chunker import DocumentChunk, chunk_documents  # noqa: E402
from src.ingestion.context import contextualize_chunks  # noqa: E402
from src.ingestion.document_loader import SectionedDocument, load_and_analyze_documents  # noqa: E402
from src.ingestion.embedder import IngestionEmbedder  # noqa: E402
from src.shared.llm_client import LLMClient  # noqa: E402
from src.shared.migrations import upgrade_to_head  # noqa: E402
from src.shared.postgres_client import PostgresClient  # noqa: E402

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger: logging.Logger = logging.getLogger("ingestion")

DATASET_DIR: str = os.getenv("DATASET_DIR", str(_ROOT / "dataset"))


def _write_report(path: Path, stats: dict[str, Any]) -> None:
    """Short human-readable summary of the run (``dataset/walkthrough_rag.md``)."""
    lines: list[str] = [
        "# RAG ingestion report",
        "",
        f"- **Generated:** {stats['timestamp']} ({stats['duration_seconds']:.1f}s)",
        f"- **Dataset:** `{stats['dataset_dir']}`; {stats['files']} files: "
        + ", ".join(f"`{c}` {n}" for c, n in sorted(stats["category_counts"].items())),
        f"- **Section patterns:** " + ", ".join(f"`{p}` {n}" for p, n in sorted(stats["pattern_counts"].items(), key=lambda x: -x[1])),
        f"- **Documents:** {stats['docs_ingested']} ingested, {stats['docs_skipped']} unchanged (skipped), {len(stats['failed'])} failed",
        f"- **Chunks:** {stats['chunks_before_dedup']} created -> {stats['chunks_after_dedup']} after per-document dedup "
        f"(cosine > 0.95), {stats['inserted']} inserted, {stats['pruned']} pruned",
        "- **Storage:** PostgreSQL `rag_chunks`: HNSW (cosine) vector index + GIN full-text index; chunks carry page, section, category",
    ]
    if stats["failed"]:
        lines += ["", "## Failed documents", *[f"- `{k}`" for k in stats["failed"]]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run_ingestion(dataset_dir: str, reset: bool = False, prune: bool = False, llm_context: bool = False) -> int:
    """Run the pipeline; returns the process exit code."""
    started: float = time.time()
    api_key: str = settings.OPENROUTER_API_KEY
    if not api_key or api_key.startswith("sk-or-v1-xxxx"):
        logger.error("OPENROUTER_API_KEY is not set (or is the placeholder). Update it in .env.")
        return 1

    pg_client: PostgresClient = PostgresClient(dsn=settings.POSTGRES_URL)
    await pg_client.connect()
    try:
        embedder: IngestionEmbedder = IngestionEmbedder(
            pg=pg_client, openai_client=openai.AsyncOpenAI(api_key=api_key, base_url=settings.OPENROUTER_BASE_URL)
        )
        await embedder.ensure_schema()
        if settings.AUTO_MIGRATE:
            await asyncio.to_thread(upgrade_to_head)  # same as the gateway: the table must be at the newest revision before rows go in
        if reset:
            await embedder.clear_table()

        dataset_path: str = str(Path(dataset_dir).resolve())
        documents: list[SectionedDocument] = load_and_analyze_documents(dataset_path)
        if not documents:
            logger.error("No documents loaded from %s", dataset_path)
            return 1

        chunks: list[DocumentChunk] = chunk_documents(documents)
        if llm_context:  # one LLM sentence per chunk (contextual retrieval), only for documents that will actually be (re)embedded
            stored = {} if reset else await embedder.existing_documents()
            llm = LLMClient(settings=settings)
            for doc in documents:
                if stored.get(doc.metadata["doc_key"]) == doc.metadata["doc_hash"]:
                    continue
                mine = [c for c in chunks if c.metadata.get("doc_key") == doc.metadata["doc_key"]]
                logger.info("Context for %s: %d chunks", doc.metadata["doc_key"], await contextualize_chunks(llm, doc.raw_text, mine))
        stats: dict[str, Any] = await embedder.ingest(chunks, prune=prune)

        category_counts: dict[str, int] = {}
        pattern_counts: dict[str, int] = {}
        for doc in documents:
            category_counts[doc.category] = category_counts.get(doc.category, 0) + 1
            pattern_counts[doc.detected_pattern] = pattern_counts.get(doc.detected_pattern, 0) + 1
        stats.update(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), duration_seconds=time.time() - started,
            dataset_dir=dataset_path, files=len(documents), category_counts=category_counts, pattern_counts=pattern_counts,
        )
        try:
            _write_report(Path(dataset_path) / "walkthrough_rag.md", stats)
        except OSError as exc:  # e.g. a read-only or host-owned mount: the documents are already stored, only the summary is lost
            logger.warning("Could not write the ingestion report: %s", exc)

        logger.info(
            "Done in %.1fs: %d ingested, %d unchanged, %d failed; %d chunks inserted",
            stats["duration_seconds"], stats["docs_ingested"], stats["docs_skipped"], len(stats["failed"]), stats["inserted"],
        )
        return 1 if stats["failed"] else 0
    finally:
        await pg_client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dataset", default=DATASET_DIR, help="folder with <category>/<file>.pdf|docx")
    parser.add_argument("--reset", action="store_true", help="truncate rag_chunks before ingesting")
    parser.add_argument("--llm-context", action="store_true", help="add an LLM-written context sentence to every new chunk (one LLM call per chunk)")
    parser.add_argument("--prune", action="store_true", help="delete stored documents that are no longer in the dataset folder")
    args = parser.parse_args()
    sys.exit(asyncio.run(run_ingestion(args.dataset, reset=args.reset, prune=args.prune, llm_context=args.llm_context)))


if __name__ == "__main__":
    main()
