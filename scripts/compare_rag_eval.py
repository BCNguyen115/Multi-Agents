"""Compare two RAG evaluation runs on the SAME questions with a paired bootstrap.

    python -m scripts.run_rag_eval --rerank                               # the baseline: writes reports/rag_eval.json
    cp reports/rag_eval.json reports/rag_eval_before.json
    python -m scripts.run_rag_eval --rerank --set RAG_FTS_SOURCE=passage  # the experiment
    python -m scripts.compare_rag_eval reports/rag_eval_before.json reports/rag_eval.json --on plan
    python -m scripts.compare_rag_eval A.json B.json --on single10 --against single10   # a rerank preset of each run

Each run stores the rank of the right chunk for every question. With 75 questions the interval of a metric is about +-0.06, so
a gain of 0.03 proves nothing; the paired difference (the same question in both runs) is far less noisy, and this prints whether
its 95% interval excludes zero. Keep a change only when it does.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any


def _scores(ranks: list[int | None]) -> dict[str, list[float]]:
    return {"hit@5": [1.0 if r and r <= 5 else 0.0 for r in ranks], "mrr": [1 / r if r else 0.0 for r in ranks]}


def paired_difference(before: list[int | None], after: list[int | None], rounds: int = 2000, seed: int = 0) -> dict[str, Any]:
    """Per metric: both means, their difference (after - before), its 95% bootstrap interval and a plain verdict."""
    if len(before) != len(after) or not before:
        raise ValueError(f"the runs must answer the same questions ({len(before)} vs {len(after)} ranks)")
    a, b, rng, n = _scores(before), _scores(after), random.Random(seed), len(before)
    out: dict[str, Any] = {}
    for metric in ("hit@5", "mrr"):
        diffs = [y - x for x, y in zip(a[metric], b[metric])]
        means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(rounds))
        low, high = means[int(0.025 * rounds)], means[int(0.975 * rounds) - 1]
        out[metric] = {
            "before": round(sum(a[metric]) / n, 3), "after": round(sum(b[metric]) / n, 3), "difference": round(sum(diffs) / n, 3),
            "ci95": [round(low, 3), round(high, 3)],
            "verdict": "better" if low > 0 else "worse" if high < 0 else "no clear difference",
        }
    return out


def _ranks(report: dict[str, Any], name: str) -> list[int | None]:
    retrieval = report["retrieval"]
    metrics = retrieval["modes"].get(name) or retrieval["rerank"].get(name)
    if metrics is None or "ranks" not in metrics:
        sys.exit(f"{name!r}: not a mode or rerank preset with stored ranks (re-run scripts.run_rag_eval with this version)")
    return metrics["ranks"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--on", default="plan", help="mode or rerank preset of BOTH runs (default: plan)")
    parser.add_argument("--against", default="", help="the preset of the second run when it has another name")
    args = parser.parse_args()
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    result = paired_difference(_ranks(before, args.on), _ranks(after, args.against or args.on))
    print(f"{args.before} -> {args.after} on {args.on!r} ({len(_ranks(before, args.on))} questions); settings changed: {after.get('overrides') or 'none'}")
    for metric, row in result.items():
        print(f"  {metric:>6}: {row['before']} -> {row['after']}  (difference {row['difference']:+}, 95% {row['ci95']})  => {row['verdict']}")


if __name__ == "__main__":
    main()
