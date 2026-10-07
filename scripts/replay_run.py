"""Look at, resume or replay a saved run of the orchestrator (needs CHECKPOINT_ENABLED=true; a run's id is ``pev_trace.run_id``).

    python -m scripts.replay_run list [--session S] [--limit 20]       # newest runs: id, time, question, agent, verdict
    python -m scripts.replay_run show RUN_ID                           # every saved step: what ran next and the state after it
    python -m scripts.replay_run replay RUN_ID --from CHECKPOINT_ID    # run the graph again from that step (id from `show`)
    python -m scripts.replay_run replay RUN_ID                         # continue a run that stopped halfway (nothing happens to a finished one)

A replay really executes the nodes after the step: LLM calls are paid, tools are called again (a mutating call stops at the approval gate
as usual) and it runs without a signed-in user. Replay from the planner step: answers are cut in the saved copy (CHECKPOINT_MAX_FIELD_CHARS).
In Docker: ``docker exec agent_backend python -m scripts.replay_run list``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

_SHOWN = ("target_agent", "plan", "retry_count", "is_verified", "verifier_feedback", "requires_human_approval")


def _brief(values: dict[str, Any]) -> dict[str, Any]:
    out = {key: values[key] for key in _SHOWN if values.get(key) not in (None, "", False, 0)}
    for key in ("execution_result", "final_response"):
        if values.get(key):
            out[key] = str(values[key])[:160]
    return out


async def run(args: argparse.Namespace) -> int:
    from src.gateway import main as gateway

    async with gateway.lifespan(gateway.app):
        orch = gateway.orchestrator
        if orch is None or orch.graph.checkpointer is None:
            print("Run checkpoints are off or could not start: set CHECKPOINT_ENABLED=true (see the gateway log).", file=sys.stderr)
            return 2
        if args.command == "list":
            for row in await orch.recent_runs(args.session, args.limit):
                print(json.dumps(row, ensure_ascii=False))
        elif args.command == "show":
            history = await orch.run_history(args.run_id)
            if not history:
                print(f"No saved run {args.run_id}", file=sys.stderr)
                return 1
            for step in history:
                print(json.dumps({"step": step["step"], "checkpoint_id": step["checkpoint_id"], "next": step["next"], **_brief(step["values"])}, ensure_ascii=False))
        else:
            final = await orch.replay_run(args.run_id, args.checkpoint)
            print(json.dumps(_brief(final), ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--session")
    listing.add_argument("--limit", type=int, default=20)
    sub.add_parser("show").add_argument("run_id")
    replay = sub.add_parser("replay")
    replay.add_argument("run_id")
    replay.add_argument("--from", dest="checkpoint", help="checkpoint id to replay from")
    args = parser.parse_args()
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:  # psycopg's async mode cannot use the proactor loop Windows defaults to
        sys.exit(runner.run(run(args)))


if __name__ == "__main__":
    main()
