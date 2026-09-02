"""RAG Pipeline — Main entry point.

Orchestrates the full pipeline:
  1. Load & analyse documents from ``dataset/``.
  2. Chunk documents by section with merge / split logic.
  3. Embed chunks and deduplicate (cosine similarity > 0.90).
  4. Build FAISS index and HyDE retriever.
  5. Run a demo query.
  6. Generate ``walkthrough.md`` with statistics.

Usage:
    cd rag_pipeline
    python main.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap: ensure package is importable
# ---------------------------------------------------------------------------

# Add the rag_pipeline directory to sys.path so `src.*` imports work
_SCRIPT_DIR: Path = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

load_dotenv(dotenv_path=_SCRIPT_DIR / ".env")

from src.chunker import DocumentChunk, chunk_documents  # noqa: E402
from src.document_loader import SectionedDocument, load_and_analyze_documents  # noqa: E402
from src.embedder import embed_and_deduplicate  # noqa: E402
from src.retriever import HyDERetriever, RetrievalResult  # noqa: E402

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger: logging.Logger = logging.getLogger("rag_pipeline")

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL: str | None = os.getenv("OPENAI_BASE_URL")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
LLM_MODEL: str = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
DATASET_DIR: str = os.getenv("DATASET_DIR", "../dataset")
FAISS_INDEX_PATH: str = os.getenv("FAISS_INDEX_PATH", "output/faiss_index.bin")

# Demo query for testing
DEMO_QUERY: str = (
    "What are the confidentiality obligations in a typical NDA?"
)


# ---------------------------------------------------------------------------
# Walkthrough generator
# ---------------------------------------------------------------------------


def _generate_walkthrough(
    output_path: str,
    stats: dict[str, Any],
) -> None:
    """Generate a walkthrough.md summarising the pipeline run.

    Args:
        output_path: Where to write the markdown file.
        stats: Dictionary of pipeline statistics.
    """
    md_lines: list[str] = [
        "# 📊 RAG Pipeline — Walkthrough Report",
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
            "## 2. Section Analysis",
            "",
            "The document loader analysed each file to detect the best "
            "section-heading pattern from the following priority list:",
            "",
            "| Priority | Pattern | Example |",
            "|----------|---------|---------|",
            "| 1 | `ARTICLE X` | `ARTICLE I`, `ARTICLE 3` |",
            "| 2 | `SECTION N` | `Section 1.01`, `SECTION 2` |",
            "| 3 | `N. Title` | `1. Definitions`, `2. Term` |",
            "| 4 | `N.N Subsection` | `1.1 Overview`, `2.3.1` |",
            "| 5 | `ALL CAPS HEADING` | `RECITALS`, `DEFINITIONS` |",
            "",
            "**Pattern distribution across documents:**",
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
            f"- **Total chunks created:** {stats['total_chunks_before_dedup']}",
            f"- **Chunk size range:** 600–6000 characters",
            f"- **Small sections (< 600 chars):** merged with neighbours",
            f"- **Large sections (> 6000 chars):** split with ~12% overlap",
            f"- **Contextual prefix:** "
            "`[Source: filename | Category: cat | Section: title]`",
            "",
            "## 4. Embedding & Deduplication",
            "",
            f"- **Embedding model:** `{stats['embedding_model']}`",
            f"- **Chunks before dedup:** {stats['total_chunks_before_dedup']}",
            f"- **Chunks after dedup:** {stats['total_chunks_after_dedup']}",
            f"- **Chunks removed:** {stats['chunks_removed']} "
            f"(cosine similarity > {stats['dedup_threshold']})",
            "",
            "## 5. HyDE Configuration",
            "",
            "**HyDE (Hypothetical Document Embeddings)** is enabled for "
            "retrieval:",
            "",
            f"- **LLM model for hypothesis generation:** `{stats['llm_model']}`",
            "- **Flow:**",
            "  1. User submits a query.",
            "  2. The LLM generates a hypothetical document passage that "
            "would answer the query.",
            "  3. The hypothetical passage is embedded using "
            f"`{stats['embedding_model']}`.",
            "  4. FAISS searches for the nearest real chunks to the "
            "hypothetical embedding.",
            "  5. Top-K chunks are returned with similarity scores.",
            "",
            f"- **FAISS index type:** `IndexFlatIP` "
            "(Inner Product on L2-normalised vectors = cosine similarity)",
            f"- **Index saved to:** `{stats.get('faiss_index_path', 'N/A')}`",
            "",
        ]
    )

    # Demo query results
    demo_results: list[dict[str, Any]] = stats.get("demo_results", [])
    if demo_results:
        md_lines.extend(
            [
                "## 6. Demo Query",
                "",
                f"**Query:** *{stats.get('demo_query', '')}*",
                "",
                "| Rank | Score | Source | Section |",
                "|------|-------|--------|---------|",
            ]
        )
        for r in demo_results:
            md_lines.append(
                f"| {r['rank']} | {r['score']:.4f} | "
                f"`{r['filename']}` | {r['section'][:50]} |"
            )
        md_lines.append("")

    # Write file
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    logger.info("Walkthrough written to %s", output_path)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def main() -> None:
    """Execute the full RAG pipeline."""
    start_time: float = time.time()

    # Validate API key
    if not OPENAI_API_KEY or OPENAI_API_KEY.startswith("sk-or-v1-xxxx"):
        logger.error(
            "OPENAI_API_KEY is not set or still has placeholder value. "
            "Please set it in the .env file."
        )
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("RAG Pipeline — Starting")
    logger.info("=" * 60)

    # Resolve dataset path
    dataset_path: str = str(
        (Path(_SCRIPT_DIR) / DATASET_DIR).resolve()
    )
    logger.info("Dataset directory: %s", dataset_path)

    # ---- Step 1: Load & Analyse Documents ----
    logger.info("--- Step 1: Loading & Analysing Documents ---")
    documents: list[SectionedDocument] = load_and_analyze_documents(dataset_path)

    if not documents:
        logger.error("No documents loaded. Check the dataset directory.")
        sys.exit(1)

    # Gather category and pattern stats
    category_counts: dict[str, int] = {}
    pattern_counts: dict[str, int] = {}
    for doc in documents:
        category_counts[doc.category] = category_counts.get(doc.category, 0) + 1
        pattern_counts[doc.detected_pattern] = (
            pattern_counts.get(doc.detected_pattern, 0) + 1
        )

    logger.info(
        "Loaded %d documents. Categories: %s",
        len(documents),
        dict(category_counts),
    )
    logger.info("Pattern distribution: %s", dict(pattern_counts))

    # ---- Step 2: Chunk Documents ----
    logger.info("--- Step 2: Chunking Documents ---")
    chunks: list[DocumentChunk] = chunk_documents(documents)
    total_chunks_before_dedup: int = len(chunks)
    logger.info("Total chunks before deduplication: %d", total_chunks_before_dedup)

    # ---- Step 3: Embed & Deduplicate ----
    logger.info("--- Step 3: Embedding & Deduplicating ---")
    import numpy as np

    unique_chunks: list[DocumentChunk]
    unique_embeddings: np.ndarray
    removed_count: int

    unique_chunks, unique_embeddings, removed_count = embed_and_deduplicate(
        chunks=chunks,
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        model=EMBEDDING_MODEL,
        threshold=0.90,
    )
    total_chunks_after_dedup: int = len(unique_chunks)

    # ---- Step 4: Build Retriever ----
    logger.info("--- Step 4: Building HyDE Retriever ---")
    retriever: HyDERetriever = HyDERetriever.from_chunks(
        chunks=unique_chunks,
        embeddings=unique_embeddings,
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        embedding_model=EMBEDDING_MODEL,
        llm_model=LLM_MODEL,
    )

    # Save FAISS index
    faiss_path: str = str(Path(_SCRIPT_DIR) / FAISS_INDEX_PATH)
    retriever.save_index(faiss_path)

    # ---- Step 5: Demo Query ----
    logger.info("--- Step 5: Demo Query ---")
    logger.info("Query: %s", DEMO_QUERY)
    results: list[RetrievalResult] = retriever.query(DEMO_QUERY, top_k=5)

    demo_results: list[dict[str, Any]] = []
    for r in results:
        logger.info(
            "  [Rank %d | Score %.4f] %s — %s",
            r.rank,
            r.score,
            r.chunk.metadata.get("filename", "?"),
            r.chunk.metadata.get("section_title", "?")[:60],
        )
        demo_results.append(
            {
                "rank": r.rank,
                "score": r.score,
                "filename": r.chunk.metadata.get("filename", "?"),
                "section": r.chunk.metadata.get("section_title", "?"),
            }
        )

    # ---- Step 6: Generate Walkthrough ----
    duration: float = time.time() - start_time
    stats: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "duration_seconds": duration,
        "dataset_dir": dataset_path,
        "total_files": len(documents),
        "category_counts": category_counts,
        "pattern_counts": pattern_counts,
        "total_chunks_before_dedup": total_chunks_before_dedup,
        "total_chunks_after_dedup": total_chunks_after_dedup,
        "chunks_removed": removed_count,
        "dedup_threshold": 0.90,
        "embedding_model": EMBEDDING_MODEL,
        "llm_model": LLM_MODEL,
        "faiss_index_path": faiss_path,
        "demo_query": DEMO_QUERY,
        "demo_results": demo_results,
    }

    walkthrough_path: str = str(Path(_SCRIPT_DIR) / "walkthrough.md")
    _generate_walkthrough(walkthrough_path, stats)

    logger.info("=" * 60)
    logger.info("Pipeline complete in %.1f seconds", duration)
    logger.info("  Documents: %d", len(documents))
    logger.info("  Chunks: %d → %d (-%d deduped)", total_chunks_before_dedup, total_chunks_after_dedup, removed_count)
    logger.info("  FAISS index: %s", faiss_path)
    logger.info("  Walkthrough: %s", walkthrough_path)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
