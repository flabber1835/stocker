"""Hard supervisor for the unattended automation worker.

The Python automation callback is deliberately treated as disposable execution
state. Durable lease/cycle/journal state lives in PostgreSQL. If a callback runs
past its fingerprinted deadline, or the scheduler stops making progress, this
supervisor terminates the entire worker process. That is the only reliable way
to stop synchronous Python/driver/network code that cannot be cancelled safely.
A fresh worker then converges through the existing lease and recovery protocol.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sentinel.automation.health import read_health
from sentinel.automation_runtime import config_from_env
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store


@dataclass
class CallbackWatch:
    state: str | None = None
    observed_at: float | None = None


def _terminate(child: subprocess.Popen, *, grace_seconds: float = 5.0) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=max(1.0, grace_seconds))


def _callback_deadline_expired(
        watch: CallbackWatch, *, state: str | None, now_monotonic: float,
        deadline_seconds: float) -> bool:
    if not state or not state.endswith("_CALLBACK"):
        watch.state = None
        watch.observed_at = None
        return False
    if watch.state != state or watch.observed_at is None:
        watch.state = state
        watch.observed_at = now_monotonic
        return False
    return now_monotonic - watch.observed_at > deadline_seconds


def _restart_for_health(*, enabled: bool | None, killed: bool | None,
                        operational_ready: bool, policy_state: str,
                        startup_grace_elapsed: bool) -> bool:
    if not startup_grace_elapsed or not enabled or killed:
        return False
    if operational_ready:
        return False
    return policy_state in {
        "SCHEDULER_STALLED", "SCHEDULER_OVERDUE", "WAITING_FOR_LEADER"
    }


def _snapshot(database_url: str):
    conn = feed_store.connect(database_url)
    try:
        health = read_health(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state,heartbeat_at FROM sentinel_automation_service_instances "
                "ORDER BY heartbeat_at DESC LIMIT 1")
            row = cur.fetchone()
        conn.rollback()
        return health, (row[0] if row else None)
    finally:
        conn.close()


def _spawn() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "sentinel", "automation-run"],
        stdin=subprocess.DEVNULL)


def main() -> int:
    sentinel_config = SentinelConfig.from_env()
    if not sentinel_config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 2
    automation_config = config_from_env()
    poll_seconds = float(os.environ.get(
        "SENTINEL_AUTOMATION_SUPERVISOR_POLL_SECONDS", "2"))
    startup_grace_seconds = float(os.environ.get(
        "SENTINEL_AUTOMATION_SUPERVISOR_STARTUP_GRACE_SECONDS", "20"))
    if poll_seconds <= 0 or startup_grace_seconds < 0:
        print("REFUSED: invalid automation supervisor timing", file=sys.stderr)
        return 2

    stopping = False
    child: subprocess.Popen | None = None

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
        if child is not None:
            _terminate(child)

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop)

    while not stopping:
        child = _spawn()
        started = time.monotonic()
        watch = CallbackWatch()
        while not stopping:
            code = child.poll()
            if code is not None:
                break
            now_mono = time.monotonic()
            try:
                health, state = _snapshot(sentinel_config.database_url)
            except Exception as exc:  # noqa: BLE001
                # Database loss prevents safe authority validation. The child
                # will fail closed on its own; do not kill-loop while DB is down.
                print(f"automation supervisor health read failed: {exc}",
                      file=sys.stderr)
                time.sleep(poll_seconds)
                continue

            if _callback_deadline_expired(
                    watch, state=state, now_monotonic=now_mono,
                    deadline_seconds=automation_config.callback_deadline_seconds):
                print(
                    f"automation supervisor terminating worker: {state} exceeded "
                    f"{automation_config.callback_deadline_seconds}s deadline",
                    file=sys.stderr)
                _terminate(child)
                break

            if _restart_for_health(
                    enabled=health.enabled,
                    killed=health.kill_switch_engaged,
                    operational_ready=health.operational_ready,
                    policy_state=health.policy_state,
                    startup_grace_elapsed=(
                        now_mono - started >= startup_grace_seconds)):
                print(
                    "automation supervisor terminating non-progressing worker: "
                    f"{health.policy_state}", file=sys.stderr)
                _terminate(child)
                break
            time.sleep(poll_seconds)

        if stopping:
            break
        # Durable fencing, not this delay, controls takeover. Keep restart delay
        # small so a replacement process is already alive before lease expiry.
        time.sleep(min(1.0, poll_seconds))

    if child is not None:
        _terminate(child)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
