#!/usr/bin/env python3
"""Hold the host GO-validation lock across validation, promotion, and handoff."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "artifacts" / "sentinel" / "go-validation" / "go-validation.lock"


def main(argv=None) -> int:
    command = list(argv if argv is not None else sys.argv[1:])
    if not command:
        print("REFUSED: GO lock helper requires a command", file=sys.stderr)
        return 2
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LOCK.open("a+", encoding="ascii") as handle:
            os.chmod(LOCK, 0o600)
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(
                    "REFUSED: another Sentinel GO validation is already running on this host",
                    file=sys.stderr,
                )
                return 2
            env = dict(os.environ)
            env["SENTINEL_GO_LOCK_HELD"] = "1"
            completed = subprocess.run(
                [str(item) for item in command], cwd=str(ROOT), env=env,
                check=False)
            return int(completed.returncode)
    except OSError as exc:
        print(
            "REFUSED: Sentinel GO validation lock is unavailable: %s" % type(exc).__name__,
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
