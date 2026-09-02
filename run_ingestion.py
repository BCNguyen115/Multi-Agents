"""RAG Ingestion Pipeline — Standalone script.

Executes the full document ingestion pipeline:
  1. Connect to PostgreSQL (shared infrastructure).
  2. Load & analyse documents from ``/app/dataset`` (or ``dataset/``).
  3. Chunk documents by section with merge/split logic.
  4. Embed chunks via ``text-embedding-3-small``.
  5. Deduplicate (cosine similarity > 0.90).
  6. Store unique chunks in pgvector (``rag_chunks`` table).
  7. Generate ``walkthrough_rag.md`` report.

Usage (local):
    python run_ingestion.py

Usage (Docker):
    docker exec agent_backend python run_ingestion.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: ensure src package is importable
# ---------------------------------------------------------------------------

_SCRIPT_DIR: Path = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Load .env for local development (ignored if envs are already set)
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_SCRIPT_DIR / ".env")
except ImportError:
    pass

import openai  # noqa: E402

from src.config import settings  # noqa: E402
from src.ingestion.chunker import DocumentChunk, chunk_documents  # noqa: E402
from src.ingestion.document_loader import (  # noqa: E402
    SectionedDocument,
    load_and_analyze_documents,
)
from src.ingestion.embedder import IngestionEmbedder  # noqa: E402
from src.shared.postgres_client import PostgresClient  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger: logging.Logger = logging.getLogger("ingestion")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Dataset path: /app/dataset in Docker, or ./dataset locally
DATASET_DIR: str = os.getenv(
    "DATASET_DIR",
    str(_SCRIPT_DIR / "dataset") if (_SCRIPT_DIR / "dataset").is_dir()
    else "/app/dataset",
)


# ---------------------------------------------------------------------------
# Walkthrough generator
# ---------------------------------------------------------------------------


def _generate_walkthrough(
    output_path: str,
    stats: dict[str, Any],
) -> None:
    """Generate a walkthrough_rag.md summarising the ingestion run.

    Args:
        output_path: Where to write the markdown file.
        stats: Dictionary of pipeline statistics.
    """
    md_lines: list[str] = [
        "# RAG Ingestion Pipeline — Walkthrough Report",
        "",
        f"**Generated:** {stats['timestamp']}",
        f"**Duration:** {stats['duration_seconds']:.1f} seconds",
        "",
        "---",
        "",
        "## 1. Document Loading",
        "",
        f"- **Dataset directory:** `{stats['dataset_dir']}`",
        f"- **Total files processed:** {stats['total_files']}",
        f"- **File breakdown:**",
    ]

    category_counts: dict[str, int] = stats.get("category_counts", {})
    for cat, count in sorted(category_counts.items()):
        md_lines.append(f"  - `{cat}`: {count} files")

    md_lines.extend(
        [
            "",
            "## 2. Section Analysis (Regex Patterns)",
            "",
            "The loader analysed each document to detect the best "
            "section-heading pattern:",
            "",
            "| Priority | Pattern | Description |",
            "|----------|---------|-------------|",
            "| 1 | `ARTICLE` | `ARTICLE I`, `ARTICLE 3` |",
            "| 2 | `SECTION` | `Section 1.01`, `SECTION 2` |",
            "| 3 | `NUMBERED_HEADING` | `1. Definitions`, `2. Term` |",
            "| 4 | `DECIMAL_SUBSECTION` | `1.1 Overview`, `2.3.1` |",
            "| 5 | `ALL_CAPS_HEADING` | `RECITALS`, `DEFINITIONS` |",
            "",
            "**Pattern distribution:**",
            "",
        ]
    )

    pattern_counts: dict[str, int] = stats.get("pattern_counts", {})
    for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
        md_lines.append(f"- `{pattern}`: {count} documents")

    md_lines.extend(
        [
            "",
            "## 3. Chunking",
            "",
            f"- **Total chunks created:** {stats['chunks_before_dedup']}",
            "- **Strategy:** Section-based chunking with merge/split",
            "- **Chunk size range:** 600-6000 characters",
            "- **Small sections (< 600 chars):** merged with neighbours",
            "- **Large sections (> 6000 chars):** split with ~12% overlap",
            "- **Contextual prefix:** `[Source: filename - Section: title]`",
            "",
            "## 4. Embedding & Deduplication",
            "",
            f"- **Embedding model:** `text-embedding-3-small`",
            f"- **Chunks before dedup:** {stats['chunks_before_dedup']}",
            f"- **Chunks after dedup:** {stats['chunks_after_dedup']}",
            f"- **Chunks removed:** {stats['chunks_removed']} "
            "(cosine similarity > 0.90)",
            "",
            "## 5. Storage",
            "",
            f"- **Database:** PostgreSQL (pgvector)",
            f"- **Table:** `rag_chunks`",
            f"- **Chunks inserted:** {stats['chunks_inserted']}",
            f"- **Index:** ivfflat (vector_cosine_ops)",
            "",
            "## 6. HyDE Configuration",
            "",
            "The RAG Agent uses **HyDE (Hypothetical Document Embeddings)**:",
            "",
            "1. User submits a query",
            "2. LLM (`gpt-4o-mini`) generates a hypothetical answer passage",
            "3. The hypothetical passage is embedded using `text-embedding-3-small`",
            "4. pgvector searches for nearest real chunks to the hypothetical embedding",
            "5. Top-5 chunks are returned with source metadata",
            "",
        ]
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    logger.info("Walkthrough written to %s", output_path)


# ---------------------------------------------------------------------------
# Database check helper
# ---------------------------------------------------------------------------


async def check_if_data_exists(pg_client: PostgresClient) -> int:
    """Check the number of existing vector chunk records in PostgreSQL.

    Queries the ``rag_chunks`` table. If the table does not exist or an error
    occurs, returns 0 so that ingestion can create the table and proceed.

    Args:
        pg_client: An active ``PostgresClient`` instance.

    Returns:
        int: Total number of rows in ``rag_chunks`` (0 if empty or table missing).
    """
    try:
        rows = await pg_client.fetch(
            "SELECT COUNT(*) AS cnt FROM rag_chunks;",
            session_id="INGESTION",
        )
        if rows:
            return int(rows[0]["cnt"])
        return 0
    except Exception as exc:
        logger.debug(
            "Table rag_chunks does not exist yet or count query failed (%s). Assuming 0 records.",
            exc,
            extra={"session_id": "INGESTION"},
        )
        return 0


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def run_ingestion() -> None:
    """Execute the full ingestion pipeline with Auto-Check."""
    start_time: float = time.time()

    logger.info("=" * 60)
    logger.info("RAG Ingestion Pipeline — Starting")
    logger.info("=" * 60)

    # --- Connect to PostgreSQL ---
    pg_client: PostgresClient = PostgresClient(dsn=settings.POSTGRES_URL)
    await pg_client.connect()

    try:
        # --- Check DB State ---
        count: int = await check_if_data_exists(pg_client)
        if count > 0:
            logger.info(
                "Vector Database đã chứa dữ liệu (%d bản ghi). Bỏ qua quá trình Ingestion để tránh trùng lặp.",
                count,
                extra={"session_id": "INGESTION"},
            )
            return

        logger.info(
            "Vector Database đang trống. Bắt đầu quá trình Ingestion từ thư mục dataset...",
            extra={"session_id": "INGESTION"},
        )

        # --- API Key Check ---
        api_key: str = settings.OPENROUTER_API_KEY
        if not api_key or api_key.startswith("sk-or-v1-xxxx"):
            logger.error(
                "OPENROUTER_API_KEY is not set or contains placeholder 'sk-or-v1-xxxx'. "
                "Please update OPENROUTER_API_KEY in multi_agent_mvp/.env with a valid API key.",
                extra={"session_id": "INGESTION"},
            )
            sys.exit(1)

        openai_client: openai.AsyncOpenAI = openai.AsyncOpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
        )

        embedder: IngestionEmbedder = IngestionEmbedder(
            pg=pg_client, openai_client=openai_client
        )
        await embedder.ensure_table()

        # --- Step 1: Load & Analyse Documents ---
        logger.info("--- Step 1: Loading & Analysing Documents ---")
        dataset_path: str = str(Path(DATASET_DIR).resolve())
        logger.info("Dataset directory: %s", dataset_path)

        documents: list[SectionedDocument] = load_and_analyze_documents(
            dataset_path
        )

        if not documents:
            logger.error("No documents loaded. Check the dataset directory.")
            return

        category_counts: dict[str, int] = {}
        pattern_counts: dict[str, int] = {}
        for doc in documents:
            category_counts[doc.category] = (
                category_counts.get(doc.category, 0) + 1
            )
            pattern_counts[doc.detected_pattern] = (
                pattern_counts.get(doc.detected_pattern, 0) + 1
            )

        logger.info(
            "Loaded %d documents. Categories: %s",
            len(documents),
            dict(category_counts),
        )

        # --- Step 2: Chunk Documents ---
        logger.info("--- Step 2: Chunking Documents ---")
        chunks: list[DocumentChunk] = chunk_documents(documents)
        logger.info("Total chunks before deduplication: %d", len(chunks))

        # --- Step 3: Embed, Deduplicate & Store ---
        logger.info("--- Step 3: Embedding, Deduplicating & Storing ---")
        embed_stats: dict[str, int] = (
            await embedder.embed_deduplicate_and_store(chunks)
        )

        # --- Step 3b: Create HNSW Index for Accelerated Vector Search ---
        logger.info("--- Step 3b: Creating HNSW Index ---")
        try:
            await pg_client.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_chunks_hnsw "
                "ON rag_chunks "
                "USING hnsw (embedding vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 64);",
                session_id="INGESTION",
            )
            logger.info("HNSW index on rag_chunks.embedding created / verified")
        except Exception as idx_exc:
            logger.warning("HNSW index creation failed (non-fatal): %s", idx_exc)

        # --- Step 4: Generate Walkthrough ---
        duration: float = time.time() - start_time
        stats: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            ),
            "duration_seconds": duration,
            "dataset_dir": dataset_path,
            "total_files": len(documents),
            "category_counts": category_counts,
            "pattern_counts": pattern_counts,
            "chunks_before_dedup": embed_stats["total_before"],
            "chunks_after_dedup": embed_stats["total_after"],
            "chunks_removed": embed_stats["removed"],
            "chunks_inserted": embed_stats["inserted"],
        }

        walkthrough_path: str = str(_SCRIPT_DIR / "walkthrough_rag.md")
        _generate_walkthrough(walkthrough_path, stats)

        # Also write copy to dataset directory (mounted volume to host)
        dataset_walkthrough_path: str = str(Path(dataset_path) / "walkthrough_rag.md")
        if dataset_walkthrough_path != walkthrough_path:
            _generate_walkthrough(dataset_walkthrough_path, stats)

        logger.info("=" * 60)
        logger.info("Ingestion complete in %.1f seconds", duration)
        logger.info("  Documents: %d", len(documents))
        logger.info(
            "  Chunks: %d -> %d (-%d deduped)",
            embed_stats["total_before"],
            embed_stats["total_after"],
            embed_stats["removed"],
        )
        logger.info(
            "  Inserted: %d into rag_chunks", embed_stats["inserted"]
        )
        logger.info("  Walkthrough: %s", walkthrough_path)
        logger.info("=" * 60)

    finally:
        await pg_client.disconnect()


def main() -> None:
    """Entry point for the ingestion script."""
    asyncio.run(run_ingestion())


if __name__ == "__main__":
    main()
