"""Make an ``AUTH_USERS`` entry for the built-in login screen (AUTH_MODE=jwt).

    python -m scripts.make_user --username alice --roles admin --tenant acme --department legal

Prompts for the password (nothing is echoed or stored) and prints one JSON object. Put the objects of all users in a JSON
list in .env:

    AUTH_USERS=[{"username":"alice","password_hash":"scrypt$...","roles":["admin"],"tenant_id":"acme","department_id":"legal"}]

Roles: ``admin`` may approve sensitive actions and update the knowledge base; ``approver`` may approve (see
HITL_APPROVER_ROLES / KNOWLEDGE_UPLOAD_ROLES).
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import settings  # noqa: E402
from src.shared.auth import hash_password  # noqa: E402

MIN_PASSWORD_CHARS = 10


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--username", required=True)
    parser.add_argument("--roles", default="", help="comma separated, e.g. approver,admin")
    parser.add_argument("--tenant", default=settings.RLS_TENANT_ID)
    parser.add_argument("--department", default=settings.RLS_DEPARTMENT_ID)
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    if len(password) < MIN_PASSWORD_CHARS:
        sys.exit(f"The password needs at least {MIN_PASSWORD_CHARS} characters.")
    if password != getpass.getpass("Repeat: "):
        sys.exit("The passwords differ.")
    print(json.dumps({
        "username": args.username,
        "password_hash": hash_password(password),
        "roles": [r for r in args.roles.split(",") if r],
        "tenant_id": args.tenant,
        "department_id": args.department,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
