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
from typing import Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
LOCK_FD_ENV = "SENTINEL_BASE_BACKUP_LOCK_FD"
LOCK_HELD_ENV = "SENTINEL_BASE_BACKUP_LOCK_HELD"
LOCK_ROOT_ENV = "SENTINEL_BASE_BACKUP_LOCK_ROOT"


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
    try:
        with lock.open("a+", encoding="ascii") as probe:
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
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(
                    "REFUSED: another Sentinel base backup is already running for this durable target",
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
