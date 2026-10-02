"""Does everything that must be shared between backend replicas really live outside the process?

    python -m scripts.replica_check --base http://127.0.0.1:8100 --expect-replicas 3
    python -m scripts.replica_check --base http://127.0.0.1:8100 --token "$(python -m scripts.make_token --user check)"   # jwt mode

Run it against the load balancer of ``docker-compose.scale.yml`` (it reads the ``X-Upstream`` header nginx adds to see which
replica answered). Checks:
  1. requests are spread over several replicas;
  2. the rate limit counts across replicas (Redis): N calls get exactly ``--analyze-limit`` successes, whoever serves them;
  3. a conversation saved through one replica is read back through the others (PostgreSQL);
  4. concurrent saves of one conversation through different replicas: exactly one wins, the rest get 409.
Exit code 1 when a check fails.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

import httpx


class Report:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
        if not ok:
            self.failures += 1


def upstream(response: httpx.Response) -> str:
    return response.headers.get("x-upstream", "?")


async def spread(client: httpx.AsyncClient, report: Report, expected: int) -> None:
    seen = {upstream(await client.get("/health")) for _ in range(40)}
    report.check(f"requests are spread over {expected} replicas", len(seen) >= min(expected, 2) and "?" not in seen, f"seen {sorted(seen)}")


async def shared_rate_limit(client: httpx.AsyncClient, report: Report, limit: int) -> None:
    for attempt in range(2):  # a fixed one-minute window may roll over in the middle of the burst: then measure again
        statuses, servers = [], set()
        for _ in range(limit + 6):
            response = await client.post("/api/knowledge/upload", files={"file": ("x.txt", b"x")}, data={"session_id": "replica-check"})
            statuses.append(response.status_code)
            servers.add(upstream(response))
        allowed = [s for s in statuses if s != 429]
        if len(allowed) == limit or attempt == 1:
            break
        await asyncio.sleep(61)
    report.check(
        "the rate limit is shared (Redis), not per replica",
        len(allowed) == limit and statuses.count(429) == 6 and len(servers) >= 2,
        f"{len(allowed)} allowed of {len(statuses)} (limit {limit}), served by {len(servers)} replicas",
    )


async def shared_conversations(client: httpx.AsyncClient, report: Report) -> None:
    if (await client.get("/api/conversations")).status_code == 401:
        report.check("conversations are shared (PostgreSQL)", False, "401: pass --token when the backend runs with AUTH_MODE=jwt")
        return
    ids = [f"replica-check-{uuid.uuid4().hex[:8]}" for _ in range(6)]
    try:
        versions = {}
        for i, conversation_id in enumerate(ids):
            saved = await client.put(f"/api/conversations/{conversation_id}", json={"title": f"c{i}", "messages": [{"id": "m", "role": "user", "content": "x"}]})
            if saved.status_code != 200:
                report.check("conversations are shared (PostgreSQL)", False, f"save failed: HTTP {saved.status_code}")
                return
            versions[conversation_id] = saved.json()["updated_at"]
        servers, complete = set(), True
        for _ in range(12):
            listing = await client.get("/api/conversations")
            servers.add(upstream(listing))
            complete &= set(ids) <= {c["id"] for c in listing.json()}
        report.check("a conversation saved through one replica is visible through the others", complete and len(servers) >= 2, f"read through {len(servers)} replicas")

        target = ids[0]
        results = await asyncio.gather(
            *[client.put(f"/api/conversations/{target}", json={"title": f"w{i}", "messages": [], "base_updated_at": versions[target]}) for i in range(6)]
        )
        codes = sorted(r.status_code for r in results)
        report.check("concurrent saves through different replicas: exactly one wins", codes == [200] + [409] * 5, f"statuses {codes}")
    finally:
        for conversation_id in ids:
            await client.delete(f"/api/conversations/{conversation_id}")


async def main(args: argparse.Namespace) -> int:
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    report = Report()
    async with httpx.AsyncClient(base_url=args.base, headers=headers, timeout=60, limits=httpx.Limits(max_connections=50)) as client:
        await spread(client, report, args.expect_replicas)
        await shared_rate_limit(client, report, args.analyze_limit)
        await shared_conversations(client, report)
    print("\nAll checks passed." if not report.failures else f"\n{report.failures} check(s) failed.")
    return 1 if report.failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8100", help="the load balancer in front of the replicas")
    parser.add_argument("--expect-replicas", type=int, default=2)
    parser.add_argument("--analyze-limit", type=int, default=10, help="RATE_LIMIT_ANALYZE_PER_MINUTE of the backend")
    parser.add_argument("--token", default="", help="Bearer token when AUTH_MODE=jwt")
    sys.exit(asyncio.run(main(parser.parse_args())))
