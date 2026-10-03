"""Move a self-registered account out of the pending tenant, set its roles, or put it back.

    python -m scripts.grant_user --list                                   # every self-registered account and its scope
    python -m scripts.grant_user --username alice --tenant tenant_enterprise --department dept_legal
    python -m scripts.grant_user --username alice --tenant tenant_enterprise --department dept_legal --roles approver
    python -m scripts.grant_user --username alice --revoke                # back to the pending tenant, no roles
    docker exec agent_backend python -m scripts.grant_user --list

A new sign-up lands in REGISTRATION_TENANT_ID: it can chat, but sees no knowledge-base document and no database row.
The change reaches the account at its next sign-in (a token already issued keeps its old scope until it expires,
AUTH_TOKEN_TTL_MINUTES at most). Accounts of AUTH_USERS live in the environment, not here.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import settings  # noqa: E402
from src.shared.postgres_client import PostgresClient  # noqa: E402


async def run(args: argparse.Namespace) -> int:
    pg = PostgresClient(dsn=args.dsn, ensure_pgvector=False)
    await pg.connect(min_size=1, max_size=2)
    try:
        if args.list:
            rows = await pg.fetch("SELECT username, tenant_id, department_id, roles, created_at FROM app_users ORDER BY created_at")
            for row in rows:
                pending = "  (pending)" if row["tenant_id"] == settings.REGISTRATION_TENANT_ID else ""
                print(f"{row['username']:24} {row['tenant_id']:22} {row['department_id']:18} roles={list(row['roles'] or [])}{pending}")
            print(f"{len(rows)} account(s)")
            return 0
        if not args.username:
            print("--username is required (or use --list)", file=sys.stderr)
            return 2
        if args.revoke:
            tenant, department, roles = settings.REGISTRATION_TENANT_ID, settings.REGISTRATION_DEPARTMENT_ID, []
        elif args.tenant and args.department:
            tenant, department, roles = args.tenant, args.department, [r for r in args.roles.split(",") if r]
        else:
            print("give --tenant and --department (or --revoke)", file=sys.stderr)
            return 2
        done = await pg.fetch(
            "UPDATE app_users SET tenant_id = $2, department_id = $3, roles = $4 WHERE username = $1 RETURNING username",
            args.username.lower(), tenant, department, roles,
        )
        if not done:
            print(f"no self-registered account named {args.username!r}", file=sys.stderr)
            return 1
        print(f"{args.username.lower()}: tenant={tenant} department={department} roles={roles}")
        return 0
    finally:
        await pg.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--list", action="store_true", help="show every self-registered account")
    parser.add_argument("--username")
    parser.add_argument("--tenant")
    parser.add_argument("--department")
    parser.add_argument("--roles", default="", help="comma separated, e.g. approver,admin (replaces the current roles)")
    parser.add_argument("--revoke", action="store_true", help="back to the pending tenant, no roles")
    parser.add_argument("--dsn", default=settings.POSTGRES_URL, help="database to update (default: POSTGRES_URL)")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
