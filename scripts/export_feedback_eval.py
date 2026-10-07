"""Turn users' thumbs on answers into evaluation questions.

    python -m scripts.export_feedback_eval                      # writes dataset/rag_eval_feedback.json and ..._review.json
    python -m scripts.export_feedback_eval --since 2026-10-01
    python -m scripts.run_rag_eval --rerank --feedback          # measure retrieval on them too

  * a thumbs-UP on an answer that cited sources becomes a question: "this question is answered by a chunk of that file that
    contains that phrase" (the same format as dataset/rag_eval_manual.json, so ``run_rag_eval`` measures it as is);
  * a thumbs-DOWN goes to the review file with its comment and what was cited: somebody reads it and either fixes the corpus,
    or writes the right answer into the manual set.

Questions are the users' own, so the set stops being "questions generated from the chunks themselves". Nothing is added without
a person's thumb; the same question and file are written once.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import settings  # noqa: E402
from src.shared.postgres_client import PostgresClient  # noqa: E402

DATASET = _ROOT / "dataset"
PHRASE_CHARS = 70


def _phrase(snippet: str) -> str:
    """The first words of a cited snippet, whitespace-normalised: a phrase the cited chunk contains."""
    return re.sub(r"\s+", " ", snippet).strip()[:PHRASE_CHARS].rstrip()


def build_items(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(questions, needs_review)`` from feedback rows (``query``, ``rating``, ``comment``, ``cited``)."""
    questions: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        query = re.sub(r"\s+", " ", row.get("query") or "").strip()
        cited = row.get("cited") or []
        if isinstance(cited, str):
            cited = json.loads(cited)
        if not query:
            continue
        if row["rating"] < 0:
            review.append({"question": query, "comment": row.get("comment") or "", "cited": cited})
            continue
        for source in cited:
            phrase = _phrase(source.get("snippet", ""))
            key = (query.lower(), source.get("file", ""))
            if source.get("file") and len(phrase) >= 20 and key not in seen:
                seen.add(key)
                questions.append({"question": query, "file": source["file"], "phrase": phrase})
    return questions, review


async def run(args: argparse.Namespace) -> None:
    pg = PostgresClient(dsn=args.dsn, ensure_pgvector=False)
    await pg.connect(min_size=1, max_size=2)
    try:
        rows = await pg.fetch("SELECT query, rating, comment, cited FROM rag_feedback WHERE at >= $1::text::timestamptz ORDER BY at", args.since)
    finally:
        await pg.disconnect()
    questions, review = build_items([dict(r) for r in rows])
    (DATASET / "rag_eval_feedback.json").write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DATASET / "rag_eval_feedback_review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rows)} feedback row(s): {len(questions)} evaluation question(s), {len(review)} to review")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--since", default="1970-01-01", help="only feedback from this date on (YYYY-MM-DD)")
    parser.add_argument("--dsn", default=settings.POSTGRES_URL, help="database to read (default: POSTGRES_URL)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
