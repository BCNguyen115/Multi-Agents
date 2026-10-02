"""Mint a test bearer token for AUTH_MODE=jwt (HS256, signed with AUTH_JWT_SECRET from .env).

    python -m scripts.make_token --user alice --tenant acme --department legal --roles approver --hours 8

Use it as:  curl -H "Authorization: Bearer <token>" http://localhost:8000/api/chat ...
Real deployments get tokens from their identity provider (set AUTH_JWKS_URL instead); this is for development and tests.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import jwt  # noqa: E402

from src.config import settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--user", required=True, help="becomes the `sub` claim")
    parser.add_argument("--tenant", default=settings.RLS_TENANT_ID)
    parser.add_argument("--department", default=settings.RLS_DEPARTMENT_ID)
    parser.add_argument("--roles", default="", help="comma separated, e.g. approver,admin")
    parser.add_argument("--hours", type=float, default=8.0)
    args = parser.parse_args()

    if not settings.AUTH_JWT_SECRET:
        sys.exit("AUTH_JWT_SECRET is empty: set it in .env (at least 32 random characters)")
    claims = {
        "sub": args.user,
        "exp": int(time.time() + args.hours * 3600),
        settings.AUTH_TENANT_CLAIM: args.tenant,
        settings.AUTH_DEPARTMENT_CLAIM: args.department,
        settings.AUTH_ROLES_CLAIM: [r for r in args.roles.split(",") if r],
    }
    if settings.AUTH_JWT_AUDIENCE:
        claims["aud"] = settings.AUTH_JWT_AUDIENCE
    if settings.AUTH_JWT_ISSUER:
        claims["iss"] = settings.AUTH_JWT_ISSUER
    print(jwt.encode(claims, settings.AUTH_JWT_SECRET, algorithm="HS256"))


if __name__ == "__main__":
    main()
