"""Child-process entry point of the analysis sandbox (see sandbox.py).

Reads ``{"code", "df", "timeout", "memory_mb"}`` (pickle, written by the parent process only) from stdin and
prints exactly one JSON line with the result. Runs under ``python -I`` with a scrubbed environment.
"""

import json
import os
import pickle
import sys

_ROOT = os.environ.get("SANDBOX_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, _ROOT)

from src.agents.data_agent.sandbox import run_untrusted  # noqa: E402


def main() -> None:
    payload = pickle.loads(sys.stdin.buffer.read())
    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # nothing the analysis code (or a library) prints may corrupt the result line
    result = run_untrusted(payload)
    sys.stdout = real_stdout
    sys.stdout.write(json.dumps(result, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
