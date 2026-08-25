"""Bounded supervisor for the broker-free shadow publisher.

Each shadow advance executes in a disposable child process. A wedged ingest,
replay, filesystem or database call therefore cannot stall the publisher
forever. Transient publication lag is retried; integrity refusals latch the
service unhealthy instead of being restart-looped back to a false green state.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from sentinel.shadow_service import ShadowServiceConfig, service_health
from sentinel.shadow_worker import EXIT_REFUSED, EXIT_RETRY, EXIT_WAITING

HEARTBEAT_FILE = Path("/tmp/sentinel-shadow-supervisor-heartbeat")
LATCH_FILE = Path("/tmp/sentinel-shadow-supervisor-critical.json")


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


def _latch(reason: str, *, failures: int | None = None) -> None:
    payload = {
        "schema": "sentinel.shadow-supervisor-critical/1",
        "reason": str(reason),
        "failures": failures,
        "latched_at_unix": time.time(),
    }
    LATCH_FILE.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    print(
        "CRITICAL: shadow supervisor latched unhealthy: " + str(reason),
        file=sys.stderr, flush=True)


def _latched_wait(stopping) -> int:
    while not stopping():
        _touch()
        time.sleep(1.0)
    return 0


def _health(max_age_seconds: float, *, config=None) -> int:
    """Require both supervisor liveness and verified shadow-frontier health."""
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
    if LATCH_FILE.exists():
        try:
            detail = LATCH_FILE.read_text(encoding="utf-8")
        except OSError as exc:
            detail = f"unreadable critical latch: {exc}"
        print(f"REFUSED: shadow supervisor critical latch: {detail}",
              file=sys.stderr)
        return 1
    try:
        resolved = config if config is not None else ShadowServiceConfig.from_env()
        service_health(resolved)
    except Exception as exc:  # fail closed: health must prove frontier health
        print(
            "REFUSED: shadow frontier health failed: "
            f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


def run() -> int:
    config = ShadowServiceConfig.from_env()
    deadline_seconds = float(os.environ.get(
        "SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS", "900"))
    if deadline_seconds < 30 or deadline_seconds > 7200:
        print("REFUSED: SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS must be in [30,7200]",
              file=sys.stderr)
        return EXIT_REFUSED
    failure_threshold = int(os.environ.get(
        "SENTINEL_SHADOW_FAILURE_THRESHOLD", "3"))
    if failure_threshold < 1 or failure_threshold > 100:
        print("REFUSED: SENTINEL_SHADOW_FAILURE_THRESHOLD must be in [1,100]",
              file=sys.stderr)
        return EXIT_REFUSED

    stopping = False
    active: subprocess.Popen | None = None
    consecutive_failures = 0

    def stop(_signum=None, _frame=None):
        nonlocal stopping
        stopping = True
        if active is not None:
            _terminate(active)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        LATCH_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    _touch()
    while not stopping:
        active = subprocess.Popen(
            [sys.executable, "-m", "sentinel.shadow_worker"],
            stdin=subprocess.DEVNULL)
        started = time.monotonic()
        timed_out = False
        while not stopping and active.poll() is None:
            _touch()
            if time.monotonic() - started > deadline_seconds:
                print(
                    "shadow supervisor terminating overdue advance after "
                    f"{deadline_seconds:.0f}s", file=sys.stderr, flush=True)
                _terminate(active)
                timed_out = True
                break
            time.sleep(1.0)
        if stopping:
            break
        code = 124 if timed_out else int(active.poll() or 0)
        active = None
        _touch()
        if code == EXIT_REFUSED:
            _latch("shadow worker reported terminal integrity refusal")
            return _latched_wait(lambda: stopping)
        if code not in {0, EXIT_WAITING, EXIT_RETRY, 124}:
            _latch(f"shadow worker exited unexpectedly with {code}")
            return _latched_wait(lambda: stopping)

        if code in {EXIT_RETRY, 124}:
            consecutive_failures += 1
            if consecutive_failures >= failure_threshold:
                _latch(
                    "shadow publisher exceeded bounded retry/timeout threshold",
                    failures=consecutive_failures)
                return _latched_wait(lambda: stopping)
        else:
            # A successful advance or an intentional causal wait demonstrates
            # that the worker is responsive; only failed attempts count toward
            # the bounded failure threshold.
            consecutive_failures = 0

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
        return _health(max(10.0, min(30.0, poll)))
    return run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
