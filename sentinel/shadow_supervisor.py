"""Bounded supervisor for the broker-free shadow publisher.

Each shadow advance executes in a disposable child process. A wedged ingest,
replay, filesystem or database call therefore cannot stall the publisher
forever. Transient publication lag is retried; integrity refusals latch the
service unhealthy instead of being restart-looped back to a false green state.
A hard child deadline is a process-liveness boundary, not evidence of financial
corruption: a long resumable catch-up may cross it repeatedly and is restarted
until its durable checkpoints converge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sentinel.feed import calendar
from sentinel import supervisor_io
from sentinel.shadow_recovery import ShadowServiceConfig, service_health
from sentinel.shadow_worker import (
    EXIT_AVAILABILITY, EXIT_REFUSED, EXIT_RETRY, EXIT_WAITING,
)

HEARTBEAT_FILE = Path("/tmp/sentinel-shadow-supervisor-heartbeat")
LATCH_FILE = Path(os.environ.get("SENTINEL_STATE_DIR", "/var/lib/sentinel")) / "shadow-supervisor-critical.json"


def _touch() -> None:
    supervisor_io.run(_write_heartbeat)


def _write_heartbeat() -> None:
    HEARTBEAT_FILE.touch(exist_ok=True)


def _remove_heartbeat() -> None:
    HEARTBEAT_FILE.unlink(missing_ok=True)


def _enqueue_alert(*, idempotency_key: str, event_type: str,
                   severity: str, payload: dict) -> None:
    supervisor_io.run(_write_alert, idempotency_key, event_type, severity, payload)


def _write_alert(idempotency_key, event_type, severity, payload) -> None:
    """Best-effort durable projection; reporting cannot soften local state."""
    from sentinel.automation import outbox
    from sentinel.config import SentinelConfig
    from sentinel.feed import store as feed_store

    database_url = SentinelConfig.from_env().database_url
    if not database_url:
        raise RuntimeError("database URL is absent")
    conn = feed_store.connect(database_url, connect_timeout=1, statement_timeout_ms=750)
    try:
        outbox.enqueue(
            conn, idempotency_key=idempotency_key,
            event_type=event_type, severity=severity, payload=payload,
            max_attempts=8)
    finally:
        conn.close()


def _source_recovery_alert(*, now: datetime | None = None) -> None:
    """Project one causal/provider incident and its following-open escalation."""
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        target = calendar.latest_closed_session(instant)
        following = calendar.next_session(target)
        opened, _closed = calendar.session_window(following)
        deadline = opened.astimezone(timezone.utc)
        expired = instant >= deadline
        _enqueue_alert(
            idempotency_key=(
                f"shadow-source:{target}:"
                f"{'deadline-missed' if expired else 'not-ready'}"),
            event_type=(
                "SHADOW_SOURCE_DEADLINE_MISSED" if expired
                else "SHADOW_SOURCE_RECOVERY_PENDING"),
            severity="CRITICAL" if expired else "WARN",
            payload={
                "decision_session": target,
                "state": (
                    "RECOVERY_DEADLINE_MISSED" if expired
                    else "SOURCE_RECOVERY_PENDING"),
                "recovery_deadline_at": deadline.isoformat(),
                "detail": (
                    "shadow source recovery missed the following XNYS open; "
                    "operator action is required" if expired else
                    "shadow is waiting on causal source/provider recovery; "
                    "see the dashboard for current evidence"),
            })
    except Exception as exc:                                  # noqa: BLE001
        supervisor_io.report(
            "WARNING: shadow source-recovery notification unavailable: "
            f"{type(exc).__name__}", file=sys.stderr, flush=True)


def _semantic_retry_alert(*, now: datetime | None = None) -> None:
    """Project one coalesced bounded semantic-retry incident per session."""
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        target = calendar.latest_closed_session(instant)
        _enqueue_alert(
            idempotency_key=f"shadow-semantic:{target}:retrying",
            event_type="SHADOW_SEMANTIC_RETRY_PENDING",
            severity="WARN",
            payload={
                "decision_session": target,
                "state": "BOUNDED_SEMANTIC_RETRY",
                "detail": (
                    "shadow semantic retry remains below its reviewed "
                    "threshold; see the dashboard for current evidence"),
            })
    except Exception as exc:                                  # noqa: BLE001
        supervisor_io.report(
            "WARNING: shadow semantic-retry notification unavailable: "
            f"{type(exc).__name__}", file=sys.stderr, flush=True)


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
    LATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LATCH_FILE.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True))
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(LATCH_FILE.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError:
        pass  # The original refusal remains the incident evidence.
    # The latch remains the local fail-closed authority.  This best-effort
    # projection gives the independent dispatcher one durable critical event
    # when PostgreSQL is still available; inability to report never clears or
    # softens the latch.
    try:
        incident = hashlib.sha256(
            json.dumps(
                {"reason": str(reason), "failures": failures},
                sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        _enqueue_alert(
            idempotency_key=f"shadow-supervisor-latch:{incident}",
            event_type="SHADOW_SUPERVISOR_LATCHED",
            severity="CRITICAL",
            payload={"reason": str(reason), "failures": failures})
    except Exception as exc:                                  # noqa: BLE001
        supervisor_io.report(
            "CRITICAL: shadow latch notification unavailable: "
            f"{type(exc).__name__}", file=sys.stderr, flush=True)
    supervisor_io.report(
        "CRITICAL: shadow supervisor latched unhealthy: " + str(reason),
        file=sys.stderr, flush=True)


def _latched_wait(stopping) -> int:
    while not stopping():
        _touch()
        time.sleep(1.0)
    return 0


def _health(max_age_seconds: float, *, config=None) -> int:
    """Require supervisor liveness plus a safe shadow recovery state."""
    try:
        age = time.time() - HEARTBEAT_FILE.stat().st_mtime
    except OSError as exc:
        supervisor_io.report(f"REFUSED: shadow supervisor heartbeat absent: {exc}",
              file=sys.stderr)
        return 1
    if age < 0 or age > max_age_seconds:
        supervisor_io.report(
            f"REFUSED: shadow supervisor heartbeat stale ({age:.3f}s)",
            file=sys.stderr)
        return 1
    if LATCH_FILE.exists():
        try:
            detail = LATCH_FILE.read_text(encoding="utf-8")
        except OSError as exc:
            detail = f"unreadable critical latch: {exc}"
        supervisor_io.report(f"REFUSED: shadow supervisor critical latch: {detail}",
              file=sys.stderr)
        return 1
    try:
        resolved = config if config is not None else ShadowServiceConfig.from_env()
        health = service_health(resolved)
        if health.get("service_health") == "RECONSTRUCTION_PENDING":
            supervisor_io.report("REFUSED: shadow reconstruction is pending", file=sys.stderr)
            return 1
    except Exception as exc:  # structural corruption still fails health closed
        supervisor_io.report(
            "REFUSED: shadow frontier health failed: "
            f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


def run() -> int:
    config = ShadowServiceConfig.from_env()
    deadline_seconds = float(os.environ.get(
        "SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS", "7200"))
    if not math.isfinite(deadline_seconds) or deadline_seconds < 30 or deadline_seconds > 7200:
        supervisor_io.report("REFUSED: SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS must be in [30,7200]",
              file=sys.stderr)
        return EXIT_REFUSED
    failure_threshold = int(os.environ.get(
        "SENTINEL_SHADOW_FAILURE_THRESHOLD", "3"))
    if failure_threshold < 1 or failure_threshold > 100:
        supervisor_io.report("REFUSED: SENTINEL_SHADOW_FAILURE_THRESHOLD must be in [1,100]",
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
        _touch()
        if LATCH_FILE.exists():
            return _latched_wait(lambda: stopping)
        while not stopping:
            active = subprocess.Popen(
                [sys.executable, "-m", "sentinel.shadow_worker"],
                stdin=subprocess.DEVNULL)
            started = time.monotonic()
            timed_out = False
            while not stopping and active.poll() is None:
                _touch()
                if time.monotonic() - started > deadline_seconds:
                    supervisor_io.report(
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
            if code == EXIT_REFUSED:
                _latch("shadow worker reported terminal integrity refusal")
                return _latched_wait(lambda: stopping)
            if code not in {
                    0, EXIT_WAITING, EXIT_RETRY, EXIT_AVAILABILITY, 124}:
                _latch(f"shadow worker exited unexpectedly with {code}")
                return _latched_wait(lambda: stopping)

            if code == EXIT_RETRY:
                # A typed non-availability retry represents a local semantic failure
                # and remains bounded. A hard timeout is different: the child was
                # forcibly stopped at a known process boundary and the canonical
                # ingest/catch-up paths are restart-convergent, so timeout duration
                # alone cannot permanently poison an otherwise valid deployment.
                consecutive_failures += 1
                if consecutive_failures >= failure_threshold:
                    _latch(
                        "shadow publisher exceeded bounded semantic retry threshold",
                        failures=consecutive_failures)
                    return _latched_wait(lambda: stopping)
                _semantic_retry_alert()
            elif code in {EXIT_WAITING, EXIT_AVAILABILITY}:
                _source_recovery_alert()
                consecutive_failures = 0
            else:
                # SUCCESS and a bounded hard timeout are responsive states. The
                # latter may repeat while a multi-hour/multi-day resumable catch-up
                # advances durable checkpoints. Financial health stays red until
                # convergence.
                consecutive_failures = 0

            _touch()
            deadline = time.monotonic() + config.poll_seconds
            while not stopping and time.monotonic() < deadline:
                _touch()
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    finally:
        # Dispose of the active worker before any best-effort filesystem cleanup.
        if active is not None:
            _terminate(active)
        try:
            supervisor_io.run(_remove_heartbeat)
        except Exception:
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
