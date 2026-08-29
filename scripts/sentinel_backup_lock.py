#!/usr/bin/env python3
"""Serialize Sentinel physical base-backup creation on one host.

The lock is process-backed with ``fcntl.flock``. The locked descriptor is passed
into the child backup script, so the lock survives if this small parent process
is terminated while the real backup remains alive. A forged environment marker
is never accepted as proof of the lock.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import subprocess
import sys
from typing import Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "artifacts" / "sentinel" / "base-backup.lock"
LOCK_FD_ENV = "SENTINEL_BASE_BACKUP_LOCK_FD"
LOCK_HELD_ENV = "SENTINEL_BASE_BACKUP_LOCK_HELD"


def lock_is_held(env=None) -> bool:
    values = os.environ if env is None else env
    if str(values.get(LOCK_HELD_ENV) or "") != "1":
        return False
    try:
        fd = int(str(values.get(LOCK_FD_ENV) or ""))
        inherited = os.fstat(fd)
        target = LOCK.stat()
    except (OSError, TypeError, ValueError):
        return False
    if (inherited.st_dev, inherited.st_ino) != (target.st_dev, target.st_ino):
        return False
    try:
        with LOCK.open("a+", encoding="ascii") as probe:
            try:
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            else:
                fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
                return False
    except OSError:
        return False


def _hold(command: Sequence[str]) -> int:
    if not command:
        print("REFUSED: base-backup lock helper requires a command", file=sys.stderr)
        return 2
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LOCK.open("a+", encoding="ascii") as handle:
            os.chmod(LOCK, 0o600)
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(
                    "REFUSED: another Sentinel base backup is already running on this host",
                    file=sys.stderr,
                )
                return 2
            os.set_inheritable(handle.fileno(), True)
            env = dict(os.environ)
            env[LOCK_HELD_ENV] = "1"
            env[LOCK_FD_ENV] = str(handle.fileno())
            completed = subprocess.run(
                [str(item) for item in command], cwd=str(ROOT), env=env,
                pass_fds=(handle.fileno(),), check=False)
            return int(completed.returncode)
    except OSError as exc:
        print(
            "REFUSED: Sentinel base-backup lock is unavailable: %s"
            % type(exc).__name__,
            file=sys.stderr,
        )
        return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    if raw == ["verify"]:
        return 0 if lock_is_held() else 2
    if raw and raw[0] == "hold":
        return _hold(raw[1:])
    print(
        "REFUSED: usage: sentinel_backup_lock.py verify | hold COMMAND...",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
