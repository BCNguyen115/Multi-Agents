"""RAG evaluation on the real document store (needs Postgres with ingested chunks + OPENROUTER_API_KEY).

What it measures (nothing here is a keyword check on the question):
  * retrieval: hit@1/5/10/20 and MRR of the chunk a question was written from, per query mode (raw | hyde | both)
    and, with --rerank, after the cross-encoder at several text lengths (with latency);
  * refusal: how well the best vector similarity separates answerable from out-of-domain questions, and the
    error rates of each candidate RAG_MIN_VECTOR_SCORE threshold;
  * answers (--answers K): citation rate, numbers unsupported by the sources, correct refusals, and an LLM judge
    that sees the retrieved sources.

Questions are generated once from random chunks (--build N) and saved to dataset/rag_eval.json so later runs
compare configurations on the same set. Ground truth = same file + section title as the source chunk.

    python -m scripts.run_rag_eval --build 60                 # create the question set
    python -m scripts.run_rag_eval --rerank --answers 20      # evaluate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

from src.agents.rag_agent.agent import RAGAgent  # noqa: E402
from src.agents.rag_agent.knowledge import KnowledgeStore  # noqa: E402
from src.agents.rag_agent.planner import QueryPlan, QueryPlanner  # noqa: E402
from src.config import settings  # noqa: E402
from src.shared.llm_client import LLMClient  # noqa: E402
from src.shared.postgres_client import PostgresClient  # noqa: E402
from src.shared import reranker_client  # noqa: E402
from src.shared.reranker_client import rerank_documents  # noqa: E402
from src.shared.security import wrap_user_input  # noqa: E402

QUESTIONS_PATH = _ROOT / "dataset" / "rag_eval.json"
MANUAL_PATH = _ROOT / "dataset" / "rag_eval_manual.json"
REPORT_DIR = _ROOT / "reports"
KS = (1, 5, 10, 20)
THRESHOLDS = (0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50)

# Out-of-domain or unanswerable from contracts: the agent must say "not found"
UNANSWERABLE = [
    "What is the capital of France?", "Who won the 2018 football World Cup?", "How do I cook pho at home?",
    "Explain how photosynthesis works.", "What is the weather in Hanoi tomorrow?", "Write a Python function to reverse a string.",
    "Thủ đô của Nhật Bản là gì?", "Cách nấu phở bò ngon là gì?", "Giá vàng hôm nay là bao nhiêu?",
    "Ai là tổng thống Mỹ năm 2010?", "Công thức tính diện tích hình tròn là gì?", "Bitcoin là gì và hoạt động thế nào?",
]

_QUESTION_PROMPT = (
    "Write ONE question, in {language}, that a user could ask and that is answered by the passage below. "
    "Do not copy long phrases from the passage and do not mention 'the passage' or the file name. "
    'Reply with JSON only: {{"question": "..."}}\n\nPASSAGE:\n{passage}'
)
_JUDGE_PROMPT = (
    "You check a RAG answer against its sources. Sources:\n{sources}\n\nAnswer:\n{answer}\n\n"
    'Reply with JSON only: {{"supported": <0..1 share of the answer\'s factual claims that the sources support>}}'
)


async def _chat_json(llm: LLMClient, prompt: str, max_tokens: int = 200) -> dict[str, Any]:
    response = await llm.chat_completion(model=settings.FAST_LLM_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.0, max_tokens=max_tokens)
    text = response.choices[0].message.content or "{}"
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


async def build_questions(pg: PostgresClient, llm: LLMClient, n: int) -> dict[str, Any]:
    rows = await pg.fetch(
        "SELECT filename, category, section_title, content FROM rag_chunks WHERE length(content) BETWEEN 600 AND 3500 ORDER BY random() LIMIT $1", n
    )
    answerable: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        language = "Vietnamese" if i % 2 else "English"
        try:
            question = (await _chat_json(llm, _QUESTION_PROMPT.format(language=language, passage=row["content"][:3000])))["question"]
        except Exception as exc:  # noqa: BLE001
            print(f"  skipped a chunk: {exc}")
            continue
        answerable.append({"id": len(answerable) + 1, "question": question, "lang": language[:2].lower(), "filename": row["filename"], "section_title": row["section_title"]})
    data = {"answerable": answerable, "unanswerable": [{"question": q} for q in UNANSWERABLE]}
    QUESTIONS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(answerable)} answerable + {len(UNANSWERABLE)} unanswerable questions -> {QUESTIONS_PATH}")
    return data


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _is_answer(doc: dict[str, Any], item: dict[str, Any]) -> bool:
    """Generated questions: the chunk they were written from (same file + section). Hand-written ones: any chunk of the
    named file that contains the answer phrase (robust to the same clause appearing in several chunks)."""
    if "phrase" in item:
        return doc["filename"].startswith(item["file"]) and _norm(item["phrase"]) in _norm(doc.get("content", ""))
    return doc["filename"] == item["filename"] and doc["section_title"] == item["section_title"]


def _rank(results: list[dict[str, Any]], item: dict[str, Any]) -> int | None:
    for position, doc in enumerate(results, start=1):
        if _is_answer(doc, item):
            return position
    return None


def _transcript(item: dict[str, Any]) -> str:
    return "\n".join(f"{m['role']}: {m['content']}" for m in item.get("history", []))


def _retrieval_metrics(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks)
    metrics = {f"hit@{k}": sum(1 for r in ranks if r and r <= k) / n for k in KS}
    metrics["mrr"] = sum(1 / r for r in ranks if r) / n
    return {k: round(v, 3) for k, v in metrics.items()}


def _metrics_by_language(data: dict[str, Any], ranks: list[int | None]) -> dict[str, Any]:
    """Overall metrics plus the same metrics for the Vietnamese and English questions separately."""
    out: dict[str, Any] = _retrieval_metrics(ranks)
    groups = {"vi": lambda i: i.get("lang") == "vi", "en": lambda i: i.get("lang") == "en", "followup": lambda i: bool(i.get("history"))}
    for name, member in groups.items():
        subset = [r for r, item in zip(ranks, data["answerable"]) if member(item)]
        if subset:
            out[name] = _retrieval_metrics(subset)
    return out


# (label, RAG_QUERY_MODE, does the search use the planner's standalone question + HyDE passage)
MODES = [("raw", "raw", False), ("both", "both", False), ("plan", "both", True)]
RERANK_INPUT = "plan"  # candidate lists the rerank presets are applied to

# name -> settings overrides (MAX_RERANK_TEXT_LENGTH stays at 1000 chars)
RERANK_PRESETS: dict[str, dict[str, int]] = {
    "single10": {"RERANK_POOL_K": 10},
    "single20": {"RERANK_POOL_K": 20},
}


RERANK_THRESHOLDS = (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5)


async def _rerank_refusal_gate(best_answerable: list[float], data: dict[str, Any], plans: dict[str, QueryPlan], candidate_lists: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """Would "best reranker score below T = nothing relevant" separate answerable from out-of-domain questions better than cosine?"""
    best_unanswerable: list[float] = []
    for item, candidates in zip(data["unanswerable"], candidate_lists):
        top = await rerank_documents(query=plans[item["question"]].standalone, documents=candidates, top_k=10)
        best_unanswerable.append(top[0].get("rerank_score", 0.0) if top else 0.0)
    return {
        "answerable_min/median": [round(min(best_answerable), 4), round(statistics.median(best_answerable), 4)],
        "unanswerable_median/max": [round(statistics.median(best_unanswerable), 4), round(max(best_unanswerable), 4)],
        "thresholds": {
            f"{t:g}": {
                "answerable_rejected": round(sum(1 for x in best_answerable if x < t) / len(best_answerable), 3),
                "unanswerable_accepted": round(sum(1 for x in best_unanswerable if x >= t) / len(best_unanswerable), 3),
            }
            for t in RERANK_THRESHOLDS
        },
    }


async def evaluate_retrieval(store: KnowledgeStore, planner: QueryPlanner, data: dict[str, Any], rerank_presets: list[str]) -> dict[str, Any]:
    report: dict[str, Any] = {"modes": {}, "rerank": {}, "threshold": {}, "planner": {}}
    plans: dict[str, QueryPlan] = {}
    latencies: list[float] = []
    for item in data["answerable"] + data["unanswerable"]:
        started = time.time()
        plans[item["question"]] = await planner.plan(item["question"], _transcript(item), "eval")
        latencies.append(time.time() - started)
    report["planner"] = {"median_s": round(statistics.median(latencies), 2), "failed": sum(1 for p in plans.values() if not p.passage)}
    print(f"  planner: {report['planner']}")

    best_scores: dict[str, dict[str, list[float]]] = {}
    fused_cache: dict[str, list[list[dict[str, Any]]]] = {}
    unanswerable_cache: dict[str, list[list[dict[str, Any]]]] = {}
    for label, mode, planned in MODES:
        settings.RAG_QUERY_MODE = mode
        ranks: list[int | None] = []
        fused_lists: list[list[dict[str, Any]]] = []
        for item in data["answerable"]:
            q = item["question"]
            results = await store.search(plans[q].standalone if planned else q, top_k=20, plan=plans[q] if planned else None)
            fused_lists.append(results)
            ranks.append(_rank(results, item))
        report["modes"][label] = _metrics_by_language(data, ranks)
        fused_cache[label] = fused_lists
        best = {"answerable": [max((d["vector_score"] for d in r), default=0.0) for r in fused_lists], "unanswerable": []}
        unanswerable_cache[label] = []
        for item in data["unanswerable"]:
            q = item["question"]
            results = await store.search(plans[q].standalone if planned else q, top_k=20, plan=plans[q] if planned else None)
            unanswerable_cache[label].append(results)
            best["unanswerable"].append(max((d["vector_score"] for d in results), default=0.0))
        best_scores[label] = best
        print(f"  {label:>9}: {report['modes'][label]}")

    for mode, best in best_scores.items():
        report["threshold"][mode] = {
            f"{t:.2f}": {
                "answerable_rejected": round(sum(1 for s in best["answerable"] if s < t) / len(best["answerable"]), 3),
                "unanswerable_accepted": round(sum(1 for s in best["unanswerable"] if s >= t) / len(best["unanswerable"]), 3),
            }
            for t in THRESHOLDS
        }
        report["threshold"][mode]["_scores"] = {
            "answerable_min/median": [round(min(best["answerable"]), 3), round(statistics.median(best["answerable"]), 3)],
            "unanswerable_median/max": [round(statistics.median(best["unanswerable"]), 3), round(max(best["unanswerable"]), 3)],
        }

    if rerank_presets:
        lists = fused_cache[RERANK_INPUT]
        saved = {k: getattr(settings, k) for k in ("RERANK_POOL_K", "RERANKER_TIMEOUT")}
        settings.RERANKER_TIMEOUT = 120.0  # measure the real latency of every preset; a timeout would trip the circuit breaker and skip the rest
        for name in rerank_presets:
            for key, value in RERANK_PRESETS[name].items():
                setattr(settings, key, value)
            reranker_client._consecutive_failures = 0
            ranks, latencies, best_rerank = [], [], []
            for item, candidates in zip(data["answerable"], lists):
                plan = plans[item["question"]]
                query = plan.standalone
                started = time.time()
                top = await rerank_documents(query=query, documents=candidates, top_k=settings.RERANK_TOP_K)
                latencies.append(time.time() - started)
                top5 = top[: settings.RERANK_TOP_K]
                best_rerank.append(top[0].get("rerank_score", 0.0) if top else 0.0)
                ranks.append(_rank(top5, item))
            report["rerank"][name] = {
                **_metrics_by_language(data, ranks),
                "median_s": round(statistics.median(latencies), 2),
                "used_reranker": any("rerank_score" in d for d in top),
            }
            if report["rerank"][name]["used_reranker"] and name == rerank_presets[0]:
                report["rerank"][name]["refusal_gate"] = await _rerank_refusal_gate(best_rerank, data, plans, unanswerable_cache[RERANK_INPUT])
            if not report["rerank"][name]["used_reranker"]:
                print(f"  WARNING: preset {name} did not reach the reranker; its numbers are the fused order, not a rerank")
            print(f"  rerank {name}: {report['rerank'][name]}")
        for key, value in saved.items():
            setattr(settings, key, value)
        report["rerank"]["no_rerank_fused_order"] = _metrics_by_language(data, [_rank(candidates[: settings.RERANK_TOP_K], item) for item, candidates in zip(data["answerable"], lists)])
    return report


async def evaluate_answers(store: KnowledgeStore, llm: LLMClient, data: dict[str, Any], k: int) -> dict[str, Any]:
    agent = RAGAgent(store, llm, model=settings.OPENROUTER_MODEL)
    sample = random.Random(0).sample(data["answerable"], min(k, len(data["answerable"])))
    stats = {"answered": 0, "not_found": 0, "cited": 0, "no_unsupported_numbers": 0, "judge_supported": []}
    for item in sample:
        out = json.loads(await agent.process_request(wrap_user_input(item["question"])[0], "eval"))
        v = out["verification"]
        if v["status"] == "not_found":
            stats["not_found"] += 1
            continue
        stats["answered"] += 1
        stats["cited"] += int(v.get("grounded", False))
        stats["no_unsupported_numbers"] += int(not v.get("unsupported_numbers"))
        sources = "\n".join(f"[{s['cite']}] {s['snippet']}" for s in out["sources"])
        try:
            stats["judge_supported"].append(float((await _chat_json(llm, _JUDGE_PROMPT.format(sources=sources or "(none)", answer=out["answer"]), 60))["supported"]))
        except Exception:  # noqa: BLE001
            pass
    refused = 0
    for item in data["unanswerable"]:
        out = json.loads(await agent.process_request(wrap_user_input(item["question"])[0], "eval"))
        refused += int(out["verification"]["status"] == "not_found")
    a = max(stats["answered"], 1)
    return {
        "questions": len(sample), "answered": stats["answered"], "not_found_on_answerable": stats["not_found"],
        "cited_rate": round(stats["cited"] / a, 3), "numbers_supported_rate": round(stats["no_unsupported_numbers"] / a, 3),
        "judge_supported_mean": round(statistics.mean(stats["judge_supported"]), 3) if stats["judge_supported"] else None,
        "correct_refusals_on_unanswerable": f"{refused}/{len(data['unanswerable'])}",
    }


def _row(name: str, m: dict[str, Any], overall: tuple[str, ...], extra: tuple[Any, ...] = ()) -> str:
    """One markdown table row: overall metrics, then MRR and hit@5 per question group (``-`` when a group is absent)."""
    groups = [m.get(group, {}).get(key, "-") for key in ("mrr", "hit@5") for group in ("vi", "en", "followup")]
    return "| " + " | ".join(str(v) for v in (name, *(m[k] for k in overall), *groups, *extra)) + " |"


_GROUP_COLUMNS = "MRR vi | MRR en | MRR follow-up | hit@5 vi | hit@5 en | hit@5 follow-up"


def write_report(report: dict[str, Any], report_name: str = "rag_eval") -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / f"{report_name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# RAG evaluation", "", f"Questions: {report['n_answerable']} answerable, {report['n_unanswerable']} unanswerable. Settings: "
             f"`RAG_MIN_VECTOR_SCORE={settings.RAG_MIN_VECTOR_SCORE}`, pool `{settings.HYBRID_CANDIDATES_K}`, rerank pool `{settings.RERANK_POOL_K}`.", "",
             f"Query planner (one LLM call): {report['retrieval']['planner']}", "",
             "## Retrieval by query mode (`plan` = the planner's standalone question + its HyDE passage)", "",
             f"| mode | hit@1 | hit@5 | hit@10 | hit@20 | MRR | {_GROUP_COLUMNS} |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for mode, m in report["retrieval"]["modes"].items():
        lines.append(_row(mode, m, ("hit@1", "hit@5", "hit@10", "hit@20", "mrr")))
    if report["retrieval"]["rerank"]:
        lines += ["", f"## Reranking of `{RERANK_INPUT}` candidates (top 5 after the cross-encoder, 1000 chars; presets in RERANK_PRESETS)", "",
                  f"| preset | hit@1 | hit@5 | MRR | {_GROUP_COLUMNS} | median s | reranker used |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, m in report["retrieval"]["rerank"].items():
            lines.append(_row(name, m, ("hit@1", "hit@5", "mrr"), (m.get("median_s", "-"), m.get("used_reranker", "-"))))
    for name, m in report["retrieval"]["rerank"].items():
        gate = m.get("refusal_gate") if isinstance(m, dict) else None
        if gate:
            lines += ["", f"### Refusal gate on the reranker score (`{name}`): best score of answerable vs out-of-domain questions", "",
                      f"answerable min/median {gate['answerable_min/median']}, out-of-domain median/max {gate['unanswerable_median/max']}", "",
                      "| min rerank score | answerable rejected | unanswerable accepted |", "|---|---|---|"]
            lines += [f"| {t} | {v['answerable_rejected']} | {v['unanswerable_accepted']} |" for t, v in gate["thresholds"].items()]
    lines += ["", "## Relevance threshold on the cosine score (answerable rejected / out-of-domain accepted)", ""]
    for mode, table in report["retrieval"]["threshold"].items():
        lines.append(f"`{mode}`: {table['_scores']}")
        lines.append("")
        lines += ["| threshold | answerable rejected | unanswerable accepted |", "|---|---|---|"]
        lines += [f"| {t} | {v['answerable_rejected']} | {v['unanswerable_accepted']} |" for t, v in table.items() if t != "_scores"]
        lines.append("")
    if report.get("answers"):
        lines += ["## Answers", "", "```json", json.dumps(report["answers"], ensure_ascii=False, indent=2), "```"]
    (REPORT_DIR / f"{report_name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report -> {REPORT_DIR / (report_name + '.md')}")


async def main_async(args: argparse.Namespace) -> None:
    pg = PostgresClient(dsn=settings.POSTGRES_URL)
    await pg.connect(min_size=1, max_size=6)
    llm = LLMClient(settings=settings)
    try:
        data = await build_questions(pg, llm, args.build) if args.build else json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
        if args.build and not args.evaluate:
            return
        if args.manual or args.only_manual:
            manual = [{"id": 1000 + i, "lang": "vi", **item} for i, item in enumerate(json.loads(MANUAL_PATH.read_text(encoding="utf-8")), start=1)]
            data = {"answerable": manual if args.only_manual else data["answerable"] + manual, "unanswerable": data["unanswerable"]}
        store = KnowledgeStore(pg, llm)
        await store.ensure_schema()
        print(f"Evaluating {len(data['answerable'])} answerable + {len(data['unanswerable'])} unanswerable questions")
        presets = args.rerank_presets.split(",") if args.rerank else []
        retrieval = await evaluate_retrieval(store, QueryPlanner(llm), data, presets)
        answers = await evaluate_answers(store, llm, data, args.answers) if args.answers else None
        write_report({"n_answerable": len(data["answerable"]), "n_unanswerable": len(data["unanswerable"]), "retrieval": retrieval, "answers": answers},
                     "rag_eval_manual" if args.only_manual else "rag_eval")
        if args.min_hit5 or args.min_mrr or args.baseline or args.save_baseline:
            check_gate(retrieval, args)
    finally:
        await llm.flush_async()
        await pg.disconnect()


def check_gate(retrieval: dict[str, Any], args: argparse.Namespace) -> None:
    """CI gate: exit 1 when hit@5 or MRR of ``--gate-on`` (a query mode or a rerank preset) is below the minimum."""
    metrics = retrieval["rerank"].get(args.gate_on) or retrieval["modes"].get(args.gate_on)
    if metrics is None:
        sys.exit(f"--gate-on {args.gate_on!r}: not a measured mode or rerank preset")
    floors = {"hit@5": args.min_hit5, "mrr": args.min_mrr}
    label = {"hit@5": "hit@5", "mrr": "MRR"}
    baseline_path = Path(args.baseline) if args.baseline else None
    if baseline_path is not None and baseline_path.exists():  # regression gate: no more than --max-drop below the last accepted run
        accepted = json.loads(baseline_path.read_text(encoding="utf-8"))
        floors = {key: max(floors[key], round(accepted[key] - args.max_drop, 4)) for key in floors}
    elif baseline_path is not None:
        print(f"No baseline at {baseline_path}: only the absolute minimums apply (create one with --save-baseline)")
    failures = [f"{label[key]} {metrics[key]} < {minimum}" for key, minimum in floors.items() if metrics[key] < minimum]
    print(f"Quality gate on {args.gate_on}: {'FAIL - ' + '; '.join(failures) if failures else 'PASS'}")
    if args.save_baseline and not failures:
        Path(args.save_baseline).write_text(json.dumps({key: metrics[key] for key in floors}, indent=2) + "\n", encoding="utf-8")
        print(f"Baseline saved to {args.save_baseline}")
    if failures:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--build", type=int, default=0, help="generate N questions from random chunks (then evaluate unless --no-eval)")
    parser.add_argument("--no-eval", dest="evaluate", action="store_false", help="only build the question set")
    parser.add_argument("--manual", action="store_true", help=f"add the hand-written questions in {MANUAL_PATH.name} (answer = a chunk of the named file that contains a phrase; some are follow-ups with chat history)")
    parser.add_argument("--only-manual", action="store_true", help="evaluate only the hand-written questions (report: reports/rag_eval_manual.md)")
    parser.add_argument("--gate-on", default="plan", help="mode or rerank preset checked by --min-hit5 / --min-mrr")
    parser.add_argument("--min-hit5", type=float, default=0.0, help="CI gate: exit 1 if hit@5 of --gate-on is lower")
    parser.add_argument("--min-mrr", type=float, default=0.0, help="CI gate: exit 1 if MRR of --gate-on is lower")
    parser.add_argument("--baseline", default="", help="JSON of the last accepted hit@5/MRR: exit 1 if --gate-on drops more than --max-drop below it")
    parser.add_argument("--max-drop", type=float, default=0.03, help="largest accepted fall against --baseline (absolute, default 0.03)")
    parser.add_argument("--save-baseline", default="", help="write this run's hit@5/MRR of --gate-on to PATH when the gate passes")
    parser.add_argument("--rerank", action="store_true", help="also measure the TEI cross-encoder (see --rerank-presets)")
    parser.add_argument("--rerank-presets", default=",".join(RERANK_PRESETS), help=f"comma list of: {', '.join(RERANK_PRESETS)}")
    parser.add_argument("--answers", type=int, default=0, help="also generate and judge answers for K questions")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
