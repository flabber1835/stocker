#!/usr/bin/env python3
"""Hold and prove the host GO lock across validation, promotion, and handoff."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "artifacts" / "sentinel" / "go-validation" / "go-validation.lock"
LOCK_FD_ENV = "SENTINEL_GO_LOCK_FD"
LOCK_HELD_ENV = "SENTINEL_GO_LOCK_HELD"
RUN_TOKEN_ENV = "SENTINEL_GO_RUN_TOKEN"
RUN_PASS_SCHEMA = "sentinel.go-requested-target-pass/1"
RUN_PASS_PATH = (
    ROOT / "artifacts" / "sentinel" / "go-validation" /
    "current-run-requested-target-pass.json"
)


def lifecycle_lock_is_held(env=None) -> bool:
    """Prove this process inherited the open description holding the GO flock.

    The shell marker alone is not authority: an unsupported direct Python call
    could set an environment variable.  The supported lock parent passes its
    actually locked descriptor into the child.  We verify that descriptor names
    the exact lock inode, then open the lock path independently and require the
    second non-blocking exclusive flock to conflict.  If it succeeds, no other
    open description currently owns the lifecycle lock and mutation must refuse.
    """
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


def current_run_token(env=None) -> str | None:
    values = os.environ if env is None else env
    value = str(values.get(RUN_TOKEN_ENV) or "")
    if len(value) != 64:
        return None
    try:
        int(value, 16)
    except ValueError:
        return None
    return value


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
            env[LOCK_HELD_ENV] = "1"
            env[LOCK_FD_ENV] = str(handle.fileno())
            # One opaque capability identifies this exact serialized lifecycle.
            # Only its hash is persisted after a successful requested-target GO;
            # a later lock invocation receives a different token and therefore
            # cannot reuse an old target result to promote a runtime.
            env[RUN_TOKEN_ENV] = secrets.token_hex(32)
            # Pass the locked open-file description into the child. If this
            # small parent is SIGKILLed while the real validation survives, the
            # child still holds the kernel flock and a second GO cannot start.
            completed = subprocess.run(
                [str(item) for item in command], cwd=str(ROOT), env=env,
                pass_fds=(handle.fileno(),), check=False)
            return int(completed.returncode)
    except OSError as exc:
        print(
            "REFUSED: Sentinel GO validation lock is unavailable: %s" % type(exc).__name__,
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
