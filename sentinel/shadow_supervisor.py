"""Bounded supervisor for the broker-free shadow publisher.

Each shadow advance executes in a disposable child process.  A wedged ingest,
replay, filesystem or database call therefore cannot stall the publisher
forever: the supervisor terminates the child at the configured deadline and
retries after the ordinary poll interval.  The child is broker-free by the
shadow-service environment contract.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from sentinel.shadow_service import ShadowServiceConfig

HEARTBEAT_FILE = Path("/tmp/sentinel-shadow-supervisor-heartbeat")


def _touch() -> None:
    HEARTBEAT_FILE.touch(exist_ok=True)


def _terminate(child: subprocess.Popen, *, grace_seconds: float = 5.0) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=max(1.0, grace_seconds))


def _run_once(deadline_seconds: float) -> int:
    child = subprocess.Popen(
        [sys.executable, "-m", "sentinel.shadow_service", "--once"],
        stdin=subprocess.DEVNULL)
    try:
        return child.wait(timeout=deadline_seconds)
    except subprocess.TimeoutExpired:
        print(
            "shadow supervisor terminating overdue advance after "
            f"{deadline_seconds:.0f}s", file=sys.stderr, flush=True)
        _terminate(child)
        return 124


def _health(max_age_seconds: float) -> int:
    try:
        age = time.time() - HEARTBEAT_FILE.stat().st_mtime
    except OSError as exc:
        print(f"REFUSED: shadow supervisor heartbeat absent: {exc}",
              file=sys.stderr)
        return 1
    if age < 0 or age > max_age_seconds:
        print(
            f"REFUSED: shadow supervisor heartbeat stale ({age:.3f}s)",
            file=sys.stderr)
        return 1
    return 0


def run() -> int:
    config = ShadowServiceConfig.from_env()
    deadline_seconds = float(os.environ.get(
        "SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS", "900"))
    if deadline_seconds < 30 or deadline_seconds > 7200:
        print("REFUSED: SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS must be in [30,7200]",
              file=sys.stderr)
        return 2
    stopping = False
    active: subprocess.Popen | None = None

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
        if active is not None:
            _terminate(active)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    _touch()
    while not stopping:
        # Inline implementation rather than _run_once so SIGTERM can terminate
        # the current child immediately.
        active = subprocess.Popen(
            [sys.executable, "-m", "sentinel.shadow_service", "--once"],
            stdin=subprocess.DEVNULL)
        started = time.monotonic()
        while not stopping and active.poll() is None:
            _touch()
            if time.monotonic() - started > deadline_seconds:
                print(
                    "shadow supervisor terminating overdue advance after "
                    f"{deadline_seconds:.0f}s", file=sys.stderr, flush=True)
                _terminate(active)
                break
            time.sleep(1.0)
        active = None
        _touch()
        deadline = time.monotonic() + config.poll_seconds
        while not stopping and time.monotonic() < deadline:
            _touch()
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    try:
        HEARTBEAT_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args(argv)
    if args.health:
        poll = float(os.environ.get("SENTINEL_SHADOW_POLL_SECONDS", "300"))
        deadline = float(os.environ.get(
            "SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS", "900"))
        return _health(max(10.0, min(30.0, poll), deadline))
    return run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
