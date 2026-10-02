"""Small load test for a running backend (no extra dependencies: httpx is already a runtime dependency).

    python -m scripts.loadtest                                   # cheap routes only: /health and /ready under load
    python -m scripts.loadtest --users 40 --duration 20
    python -m scripts.loadtest --chat 6                          # + 6 concurrent chat turns (each calls the LLMs: costs money)
    python -m scripts.loadtest --chat 6 --token "$(python -m scripts.make_token --user load)"   # when AUTH_MODE=jwt

What it answers: does the API stay responsive (p95 of /health) while the expensive work runs, how long do chat turns take
when they overlap, and does the rate limiter answer 429 instead of falling over. Exit code 1 when p95 of /health while
chats run exceeds ``--max-health-p95`` seconds, so it can gate a pipeline.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time

import httpx

QUESTION = "Thủ đô của Nhật Bản là gì?"  # out of domain: the cheapest full RAG turn (planner + refusal)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summary(name: str, latencies: list[float], statuses: dict[int, int]) -> str:
    codes = ", ".join(f"{code}x{n}" for code, n in sorted(statuses.items())) or "-"
    return (f"{name:<22} n={len(latencies):<5} p50={percentile(latencies, .5) * 1000:7.0f} ms  p95={percentile(latencies, .95) * 1000:7.0f} ms  "
            f"max={max(latencies, default=float('nan')) * 1000:7.0f} ms  status: {codes}")


async def hammer(client: httpx.AsyncClient, path: str, stop_at: float, latencies: list[float], statuses: dict[int, int]) -> None:
    while time.monotonic() < stop_at:
        started = time.monotonic()
        try:
            status = (await client.get(path)).status_code
        except httpx.HTTPError:
            status = 0
        latencies.append(time.monotonic() - started)
        statuses[status] = statuses.get(status, 0) + 1


async def chat_turn(client: httpx.AsyncClient, i: int, latencies: list[float], statuses: dict[int, int]) -> None:
    started = time.monotonic()
    try:
        response = await client.post("/api/chat", json={"query": QUESTION, "session_id": f"loadtest-{i}", "agent_mode": "rag_agent"}, timeout=180)
        status = response.status_code
    except httpx.HTTPError:
        status = 0
    latencies.append(time.monotonic() - started)
    statuses[status] = statuses.get(status, 0) + 1


async def main(args: argparse.Namespace) -> int:
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    limits = httpx.Limits(max_connections=args.users + args.chat + 10)
    async with httpx.AsyncClient(base_url=args.base, headers=headers, limits=limits, timeout=30) as client:
        # ---- phase 1: cheap routes under load
        results: dict[str, tuple[list[float], dict[int, int]]] = {"/health": ([], {}), "/ready": ([], {})}
        stop_at = time.monotonic() + args.duration
        await asyncio.gather(*(hammer(client, path, stop_at, *results[path]) for path in results for _ in range(max(args.users // 2, 1))))
        print(f"== {args.users} concurrent callers for {args.duration:.0f} s")
        for path, (lat, st) in results.items():
            print(summary(path, lat, st))
        total = sum(len(lat) for lat, _ in results.values())
        print(f"throughput: {total / args.duration:.0f} requests/s")

        if not args.chat:
            return 0

        # ---- phase 2: expensive turns overlapping, while /health is polled
        health_lat: list[float] = []
        health_st: dict[int, int] = {}
        chat_lat: list[float] = []
        chat_st: dict[int, int] = {}
        poll_stop = asyncio.Event()

        async def poll() -> None:
            while not poll_stop.is_set():
                started = time.monotonic()
                try:
                    status = (await client.get("/health")).status_code
                except httpx.HTTPError:
                    status = 0
                health_lat.append(time.monotonic() - started)
                health_st[status] = health_st.get(status, 0) + 1
                await asyncio.sleep(0.1)

        poller = asyncio.create_task(poll())
        await asyncio.gather(*(chat_turn(client, i, chat_lat, chat_st) for i in range(args.chat)))
        poll_stop.set()
        await poller
        print(f"\n== {args.chat} overlapping chat turns")
        print(summary("/api/chat", chat_lat, chat_st))
        print(summary("/health meanwhile", health_lat, health_st))
        if chat_lat:
            print(f"chat turns: mean {statistics.mean(chat_lat):.1f} s")
        p95 = percentile(health_lat, 0.95)
        verdict = "OK" if p95 <= args.max_health_p95 else "FAIL"
        print(f"/health p95 while chatting {p95:.2f} s (limit {args.max_health_p95:.2f} s): {verdict}")
        return 0 if verdict == "OK" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--users", type=int, default=20, help="concurrent callers for the cheap-route phase")
    parser.add_argument("--duration", type=float, default=10.0, help="seconds of the cheap-route phase")
    parser.add_argument("--chat", type=int, default=0, help="number of concurrent chat turns (each costs LLM calls)")
    parser.add_argument("--token", default="", help="Bearer token when AUTH_MODE=jwt")
    parser.add_argument("--max-health-p95", type=float, default=1.0)
    sys.exit(asyncio.run(main(parser.parse_args())))
