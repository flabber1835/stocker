#!/usr/bin/env python3
"""Serialize Sentinel physical base-backup creation per durable target.

The lock is process-backed with ``fcntl.flock`` and keyed by the canonical
backup root, so separate Git checkouts on the same host cannot concurrently
publish into one target. The locked descriptor is passed into the child backup
script, so the lock survives if this small parent process is terminated while
the real backup remains alive. A forged environment marker is never authority.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Mapping, Optional, Sequence

from sentinel_lock_ownership import owns_exclusive_flock


ROOT = Path(__file__).resolve().parents[1]
LOCK_FD_ENV = "SENTINEL_BASE_BACKUP_LOCK_FD"
LOCK_HELD_ENV = "SENTINEL_BASE_BACKUP_LOCK_HELD"
LOCK_ROOT_ENV = "SENTINEL_BASE_BACKUP_LOCK_ROOT"
MAX_WAIT_SECONDS = 3660


def _lock_path(env: Mapping[str, str]) -> Optional[Path]:
    raw = str(env.get(LOCK_ROOT_ENV) or "")
    if not raw or not os.path.isabs(raw):
        return None
    try:
        root = Path(raw)
        if root.is_symlink() or not root.is_dir():
            return None
        canonical = root.resolve(strict=True)
    except OSError:
        return None
    if str(canonical) != raw.rstrip("/"):
        return None
    digest = hashlib.sha256(str(canonical).encode("utf-8")).hexdigest()
    # The per-uid directory is stable across checkouts and private from other
    # local users. A reboot removes no useful authority: every process holding
    # the flock dies with the boot.
    lock_dir = Path("/tmp") / ("sentinel-base-backup-locks-%d" % os.getuid())
    return lock_dir / (digest + ".lock")


def lock_is_held(env=None) -> bool:
    values = os.environ if env is None else env
    if str(values.get(LOCK_HELD_ENV) or "") != "1":
        return False
    lock = _lock_path(values)
    if lock is None:
        return False
    try:
        fd = int(str(values.get(LOCK_FD_ENV) or ""))
        inherited = os.fstat(fd)
        target = lock.stat()
    except (OSError, TypeError, ValueError):
        return False
    if (inherited.st_dev, inherited.st_ino) != (target.st_dev, target.st_ino):
        return False
    return owns_exclusive_flock(fd)


def _hold(command: Sequence[str], *, wait_seconds: int = 0) -> int:
    if not command:
        print("REFUSED: base-backup lock helper requires a command", file=sys.stderr)
        return 2
    lock = _lock_path(os.environ)
    if lock is None:
        print(
            "REFUSED: canonical Sentinel base-backup lock target is unavailable",
            file=sys.stderr,
        )
        return 2
    try:
        lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(lock.parent, 0o700)
        with lock.open("a+", encoding="ascii") as handle:
            os.chmod(lock, 0o600)
            deadline = time.monotonic() + wait_seconds
            announced = False
            while True:
                if announced and time.monotonic() >= deadline:
                    print(
                        "REFUSED: another Sentinel base backup is already running for this durable target",
                        file=sys.stderr,
                    )
                    return 2
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        print(
                            "REFUSED: another Sentinel base backup is already running for this durable target",
                            file=sys.stderr,
                        )
                        return 2
                    if not announced:
                        print("[WAIT] existing Sentinel backup target owner; bounded wait %ds" % wait_seconds,
                              file=sys.stderr, flush=True)
                        announced = True
                    time.sleep(min(1, remaining))
            if not owns_exclusive_flock(handle.fileno()):
                print("REFUSED: host cannot verify the acquired Sentinel backup lock",
                      file=sys.stderr)
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
        command = raw[1:]
        wait_seconds = 0
        if command and command[0] == "--wait-seconds":
            if (len(command) < 3 or not command[1].isascii()
                    or not command[1].isdigit() or len(command[1]) > 4
                    or not 0 <= int(command[1]) <= MAX_WAIT_SECONDS):
                print("REFUSED: backup lock wait must be an integer from 0 to 3660 seconds",
                      file=sys.stderr)
                return 2
            wait_seconds = int(command[1])
            command = command[2:]
        return _hold(command, wait_seconds=wait_seconds)
    print(
        "REFUSED: usage: sentinel_backup_lock.py verify | hold [--wait-seconds 0..3660] COMMAND...",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
