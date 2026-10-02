"""Apply database migrations by hand (the gateway also does it at start).

    python -m scripts.migrate                 # upgrade to the newest revision
    python -m scripts.migrate --status        # print the database's revision and the newest one, change nothing
    docker exec agent_backend python -m scripts.migrate

New change: ``alembic revision -m "add x"`` from the project root, edit the file in migrations/versions, then run this.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.shared.migrations import current_revision, head_revision, upgrade_to_head  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--status", action="store_true", help="show where the database is, do not change it")
    args = parser.parse_args()
    if args.status:
        print(f"database: {current_revision() or '(never migrated)'}   newest: {head_revision()}")
        return
    print(f"database is now at revision {upgrade_to_head()}")


if __name__ == "__main__":
    main()
