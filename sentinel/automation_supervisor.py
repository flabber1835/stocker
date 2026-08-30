"""Hard supervisor for the unattended automation worker.

The Python automation callback is deliberately treated as disposable execution
state. Durable lease/cycle/journal state lives in PostgreSQL. If a callback runs
past its fingerprinted deadline, or this worker stops making progress, this
supervisor terminates the entire worker process. A fresh worker then converges
through the existing lease and recovery protocol.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from sentinel.automation_runtime import config_from_env
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store

HOLDER_FILE = Path("/tmp/sentinel-automation-holder-id")


@dataclass
class CallbackWatch:
    state: str | None = None
    observed_at: float | None = None


def _terminate(child: subprocess.Popen, *, grace_seconds: float = 5.0) -> None:
    process_group = child.pid
    if child.poll() is None:
        try:
            observed_group = os.getpgid(child.pid)
        except ProcessLookupError:
            observed_group = process_group
        if observed_group != process_group:
            raise RuntimeError(
                "automation worker is not the leader of its dedicated "
                "process group")
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            pass

    # A worker may exit while a SIGTERM-ignoring callback remains. The process
    # group is still the callback's kernel-owned lifetime boundary, including
    # when the worker died just before this function observed it.
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if child.poll() is None:
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


def _callback_deadline_expired_during_database_loss(
        watch: CallbackWatch, *, now_monotonic: float,
        database_unreadable_since: float,
        deadline_seconds: float) -> bool:
    """Preserve the hard callback bound when PostgreSQL cannot be observed.

    If a callback had already been observed, its original monotonic deadline
    continues to run. If database loss began before callback state could be
    observed, conservatively cap the unobservable worker interval itself. This
    may recycle an otherwise idle worker during a prolonged DB outage, but it
    never weakens the configured hard callback bound into an unbounded wait.
    """
    anchor = (watch.observed_at if watch.state and watch.observed_at is not None
              else database_unreadable_since)
    return now_monotonic - anchor > deadline_seconds


def _instance_stalled(*, heartbeat_age_seconds: float | None,
                      lease_seconds: float,
                      startup_grace_elapsed: bool) -> bool:
    if not startup_grace_elapsed:
        return False
    if heartbeat_age_seconds is None:
        return True
    return heartbeat_age_seconds > lease_seconds


def _snapshot(database_url: str, holder_id: str):
    conn = feed_store.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state,heartbeat_at,clock_timestamp() "
                "FROM sentinel_automation_service_instances "
                "WHERE instance_id=%s", (holder_id,))
            row = cur.fetchone()
        conn.rollback()
        if row is None:
            return None, None
        state, heartbeat_at, database_now = row
        age = ((database_now - heartbeat_at).total_seconds()
               if heartbeat_at is not None else None)
        return state, age
    finally:
        conn.close()


def _holder_id() -> str:
    host = socket.gethostname().strip() or "host"
    return f"sentinel-{host}-{uuid.uuid4()}"


def _spawn(
        holder_id: str, *, command: tuple[str, ...] | None = None
        ) -> subprocess.Popen:
    env = os.environ.copy()
    env["SENTINEL_AUTOMATION_HOLDER_ID"] = holder_id
    HOLDER_FILE.write_text(holder_id, encoding="utf-8")
    return subprocess.Popen(
        list(command or (
            sys.executable, "-m", "sentinel.automation_worker")),
        stdin=subprocess.DEVNULL, env=env, start_new_session=True)


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
        holder_id = _holder_id()
        child = _spawn(holder_id)
        started = time.monotonic()
        watch = CallbackWatch()
        database_unreadable_since: float | None = None
        while not stopping:
            code = child.poll()
            if code is not None:
                # The worker's exit never proves its callback-owned descendants
                # are gone. Reap the complete old group before replacement.
                _terminate(child)
                break
            now_mono = time.monotonic()
            try:
                state, heartbeat_age = _snapshot(
                    sentinel_config.database_url, holder_id)
                database_unreadable_since = None
            except Exception as exc:  # noqa: BLE001
                if database_unreadable_since is None:
                    database_unreadable_since = now_mono
                print(f"automation supervisor health read failed: {exc}",
                      file=sys.stderr)
                if _callback_deadline_expired_during_database_loss(
                        watch, now_monotonic=now_mono,
                        database_unreadable_since=database_unreadable_since,
                        deadline_seconds=(
                            automation_config.callback_deadline_seconds)):
                    print(
                        f"automation supervisor terminating worker {holder_id}: "
                        "database authority was unobservable for the hard "
                        f"{automation_config.callback_deadline_seconds}s "
                        "callback deadline",
                        file=sys.stderr)
                    _terminate(child)
                    break
                time.sleep(poll_seconds)
                continue

            if _callback_deadline_expired(
                    watch, state=state, now_monotonic=now_mono,
                    deadline_seconds=automation_config.callback_deadline_seconds):
                print(
                    f"automation supervisor terminating worker {holder_id}: "
                    f"{state} exceeded "
                    f"{automation_config.callback_deadline_seconds}s deadline",
                    file=sys.stderr)
                _terminate(child)
                break

            if _instance_stalled(
                    heartbeat_age_seconds=heartbeat_age,
                    lease_seconds=automation_config.lease_seconds,
                    startup_grace_elapsed=(
                        now_mono - started >= startup_grace_seconds)):
                age_detail = ("missing" if heartbeat_age is None
                              else f"{heartbeat_age:.3f}s")
                print(
                    f"automation supervisor terminating stalled worker "
                    f"{holder_id}: heartbeat age {age_detail}; lease "
                    f"{automation_config.lease_seconds}s",
                    file=sys.stderr)
                _terminate(child)
                break
            time.sleep(poll_seconds)

        if stopping:
            break
        time.sleep(min(1.0, poll_seconds))

    if child is not None:
        _terminate(child)
    try:
        HOLDER_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
