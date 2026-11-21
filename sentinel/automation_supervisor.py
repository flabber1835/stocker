"""Hard supervisor for the unattended automation worker.

The Python automation callback is deliberately treated as disposable execution
state. Durable lease/cycle/journal state lives in PostgreSQL. If a callback runs
past its fingerprinted deadline, or this worker stops making progress, this
supervisor terminates the entire worker process. A fresh worker then converges
through the existing lease and recovery protocol.
"""
from __future__ import annotations

import math
import errno
import json
import multiprocessing
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import NamedTuple

from sentinel.automation_runtime import config_from_env
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store
from sentinel import supervisor_io

HOLDER_FILE = Path("/tmp/sentinel-automation-holder-id")
SNAPSHOT_SECONDS = 1.0
_SNAPSHOT_PACKET = 2048
_SNAPSHOT_STAGES = ('ADMISSION', 'CONNECT', 'QUERY', 'ROLLBACK', 'RESULT')
_DIAGNOSTIC_INCARNATION = uuid.uuid4().hex


def _diagnostic(stage, outcome, *, child, started, completed, worker_started,
                error=None, snapshot=None, lease_seconds=None, dependency_step=None, immediate=True):
    context = {'incarnation': _DIAGNOSTIC_INCARNATION, 'supervisor_pid': os.getpid(),
               'started': started, 'completed': completed, 'decision_at': completed,
               'worker_started': worker_started, 'elapsed_seconds': completed - started}
    child_pid = getattr(child, 'pid', None)
    if child_pid is not None:
        context['child_pid'] = child_pid
    if snapshot is not None:
        context.update(state=snapshot.state, heartbeat_age_seconds=snapshot.heartbeat_age_seconds)
    if lease_seconds is not None:
        context['lease_seconds'] = lease_seconds
    if dependency_step is not None:
        context['dependency_step'] = dependency_step
    return supervisor_io.report_event('automation', stage, outcome, error=error,
                                      context=context, immediate=True)


@dataclass
class CallbackWatch:
    state: str | None = None
    observed_at: float | None = None
    invocation: object = None


class InstanceSnapshot(NamedTuple):
    state: str | None = None
    heartbeat_age_seconds: float | None = None
    invocation: datetime | None = None
    callback_age_seconds: float | None = None
    callback_remaining_seconds: float | None = None


def _session_process_groups(session_id: int) -> set[int]:
    groups: set[int] = set()
    proc = Path("/proc")
    if not proc.is_dir():
        return {session_id}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(encoding="utf-8")
            fields = raw[raw.rfind(")") + 2:].split()
            process_group, process_session = int(fields[2]), int(fields[3])
        except (OSError, ValueError, IndexError):
            continue
        if process_session == session_id:
            groups.add(process_group)
    return groups or {session_id}


def _terminate(child: subprocess.Popen, *, grace_seconds: float = 0.0) -> None:
    """Immediately kill every process group in the worker's dedicated session."""
    del grace_seconds
    for process_group in _session_process_groups(child.pid):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if child.poll() is None:
        child.wait(timeout=1)


def _callback_deadline_expired(
        watch: CallbackWatch, *, state: str | None, now_monotonic: float,
        deadline_seconds: float,
        state_age_seconds: float | None = None,
        invocation=None) -> bool:
    if not state or not state.endswith("_CALLBACK"):
        watch.state = None
        watch.observed_at = None
        watch.invocation = None
        return False
    if (watch.state != state or watch.observed_at is None
            or invocation is not None and watch.invocation != invocation):
        watch.state = state
        watch.invocation = invocation
        watch.observed_at = now_monotonic - max(0.0, state_age_seconds or 0.0)
        return now_monotonic - watch.observed_at > deadline_seconds
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
                      startup_grace_elapsed: bool,
                      state: str | None = None) -> bool:
    if state and state.endswith("_CALLBACK"):
        return False
    if not startup_grace_elapsed:
        return False
    if heartbeat_age_seconds is None:
        return True
    return heartbeat_age_seconds > lease_seconds


def _snapshot(database_url: str, holder_id: str):
    started = time.monotonic()
    snapshot = supervisor_io.run(
        _read_snapshot, database_url, holder_id, timeout=SNAPSHOT_SECONDS)
    # A suspended parent may resume after the child has already completed.
    # Successful IPC alone does not make that old observation current.
    if not 0 <= time.monotonic() - started <= SNAPSHOT_SECONDS:
        raise TimeoutError('automation dependency observation is no longer current')
    return snapshot


def _read_snapshot(database_url: str, holder_id: str):
    conn = feed_store.connect(database_url, connect_timeout=1, statement_timeout_ms=750)
    try:
        conn.read_only = True
        return _query_snapshot(conn, holder_id)
    finally:
        conn.close()


def _query_snapshot(conn, holder_id, stage=None):
    if stage is not None:
        stage.value = 2
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state,heartbeat_at,clock_timestamp(),"
            " callback_started_at,callback_deadline_at "
            "FROM sentinel_automation_service_instances "
            "WHERE instance_id=%s", (holder_id,))
        row = cur.fetchone()
    if stage is not None:
        stage.value = 3
    conn.rollback()
    if row is None:
        return InstanceSnapshot()
    state, heartbeat_at, database_now, callback_start, callback_end = row
    age = ((database_now - heartbeat_at).total_seconds() if heartbeat_at is not None else None)
    callback = state.endswith('_CALLBACK')
    return InstanceSnapshot(
        state, age, callback_start if callback else heartbeat_at,
        (database_now - callback_start).total_seconds() if callback_start is not None else None,
        (callback_end - database_now).total_seconds() if callback_end is not None else None)


def _serve_snapshots(channel, peer, parent_pid, database_url, stage):
    peer.close()
    supervisor_io._parent_death(parent_pid)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    conn = None
    with channel:
        try:
            while request := channel.recv(_SNAPSHOT_PACKET):
                if conn is None:
                    stage.value = 1
                    conn = feed_store.connect(database_url, connect_timeout=1, statement_timeout_ms=750)
                    conn.read_only = True
                result = _query_snapshot(conn, request.decode('utf-8'), stage)
                stage.value = 4
                channel.send(json.dumps(['ok', list(result)], default=datetime.isoformat,
                                        allow_nan=False).encode('ascii'))
        except Exception as exc:  # noqa: BLE001
            channel.send(json.dumps(['error', supervisor_io.error_diagnostic(exc)]).encode('ascii'))
        finally:
            if conn is not None:
                conn.close()


class SnapshotReader:
    """Own one disposable backend for fresh watchdog reads across worker ticks."""

    def __init__(self, database_url):
        self.database_url = database_url
        self.context = multiprocessing.get_context('fork')
        self.stage = self.context.RawValue('i', 0)
        self.process = None
        self.channel = None

    def _start(self):
        parent, child = socket.socketpair(type=socket.SOCK_SEQPACKET)
        try:
            process = self.context.Process(target=_serve_snapshots, name='sentinel-watchdog-reader',
                args=(child, parent, os.getpid(), self.database_url, self.stage))
            process.start()
        except BaseException:
            parent.close()
            raise
        finally:
            child.close()
        self.channel, self.process = parent, process

    def close(self):
        if self.channel is not None:
            self.channel.close()
            self.channel = None
        if self.process is not None:
            if self.process.is_alive():
                self.process.kill()
            self.process.join(timeout=.05)
            if self.process.is_alive():
                return False
            self.process.close()
            self.process = None
        return True

    def read(self, database_url, holder_id):
        if database_url != self.database_url:
            raise RuntimeError('watchdog reader database binding changed')
        started = time.monotonic()
        deadline = started + SNAPSHOT_SECONDS
        self.stage.value = 0
        try:
            if self.channel is None or not self.process.is_alive():
                if not self.close():
                    raise TimeoutError('prior watchdog reader is not reaped')
                self._start()
            raw = holder_id.encode('utf-8')
            if not raw or len(raw) >= _SNAPSHOT_PACKET:
                raise ValueError('watchdog holder identity exceeds packet bound')
            self.channel.settimeout(self._remaining(deadline))
            if self.channel.send(raw) != len(raw):
                raise RuntimeError('watchdog observation request was incomplete')
            self.channel.settimeout(self._remaining(deadline))
            response = self.channel.recv(_SNAPSHOT_PACKET)
            if not response or len(response) >= _SNAPSHOT_PACKET:
                raise RuntimeError('watchdog observation response unavailable')
            status, value = json.loads(response)
            if status != 'ok':
                raise supervisor_io.DependencyError(value)
            if value[2] is not None:
                value[2] = datetime.fromisoformat(value[2])
            if not 0 <= time.monotonic() - started <= SNAPSHOT_SECONDS:
                raise TimeoutError('automation dependency observation is no longer current')
            return InstanceSnapshot(*value)
        except Exception:
            self.close()
            raise

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('watchdog observation exceeded its wall-clock budget')
        return remaining


def _holder_id() -> str:
    host = socket.gethostname().strip() or "host"
    return f"sentinel-{host}-{uuid.uuid4()}"


def _spawn(
        holder_id: str, *, command: tuple[str, ...] | None = None
        ) -> subprocess.Popen:
    env = os.environ.copy()
    env["SENTINEL_AUTOMATION_HOLDER_ID"] = holder_id
    supervisor_io.run(_write_holder, holder_id)
    return subprocess.Popen(
        list(command or (
            sys.executable, "-m", "sentinel.automation_worker")),
        stdin=subprocess.DEVNULL, env=env, start_new_session=True)


def _write_holder(holder_id):
    HOLDER_FILE.write_text(holder_id, encoding="utf-8")


def _remove_holder():
    HOLDER_FILE.unlink(missing_ok=True)


def main(*, serve_health=False) -> int:
    sentinel_config = SentinelConfig.from_env()
    if not sentinel_config.database_url:
        supervisor_io.report("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 2
    automation_config = config_from_env()
    poll_seconds = float(os.environ.get(
        "SENTINEL_AUTOMATION_SUPERVISOR_POLL_SECONDS", "2"))
    startup_grace_seconds = float(os.environ.get(
        "SENTINEL_AUTOMATION_SUPERVISOR_STARTUP_GRACE_SECONDS", "20"))
    if (not math.isfinite(poll_seconds) or not math.isfinite(startup_grace_seconds)
            or poll_seconds <= 0 or startup_grace_seconds < 0):
        supervisor_io.report("REFUSED: invalid automation supervisor timing", file=sys.stderr)
        return 2

    reader = None
    if serve_health:
        from sentinel.automation_health_probe import WarmHealthReader

        reader = WarmHealthReader(
            sentinel_config.database_url, automation_config.lease_seconds,
            max_pulse_age=poll_seconds + 2*SNAPSHOT_SECONDS + 1)
    snapshots = SnapshotReader(sentinel_config.database_url) if serve_health else None
    try:
        return _watch(sentinel_config, automation_config, poll_seconds, startup_grace_seconds,
                      reader, snapshots)
    finally:
        if snapshots is not None:
            snapshots.close()
        if reader is not None:
            reader.close()


def _watch(sentinel_config, automation_config, poll_seconds, startup_grace_seconds, reader, snapshots=None):
    stopping = False
    child: subprocess.Popen | None = None
    observe = _snapshot if snapshots is None else snapshots.read

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
        if child is not None:
            _terminate(child)

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop)

    while not stopping:
        holder_id = _holder_id()
        if snapshots is not None:
            snapshots.close()
        try:
            child = _spawn(holder_id)
        except (TimeoutError, OSError) as exc:
            if not isinstance(exc, TimeoutError) and exc.errno not in {errno.EAGAIN, errno.ENOMEM}:
                raise
            supervisor_io.report(
                'automation supervisor launch deferred: ' + type(exc).__name__,
                file=sys.stderr)
            time.sleep(min(1.0, poll_seconds))
            continue
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
            if reader is not None:
                try:
                    reader.tick()
                except OSError as exc:
                    supervisor_io.report(
                        'automation health reader unavailable: '+type(exc).__name__)
            now_mono = time.monotonic()
            observation_started = now_mono
            observation_stage = 'SNAPSHOT'
            try:
                snapshot = observe(
                    sentinel_config.database_url, holder_id)
                now_mono = time.monotonic()
                if _instance_stalled(
                        heartbeat_age_seconds=snapshot.heartbeat_age_seconds,
                        lease_seconds=automation_config.lease_seconds,
                        startup_grace_elapsed=(
                            now_mono - started >= startup_grace_seconds),
                        state=snapshot.state):
                    observation_stage = 'CONFIRMATION'
                    observation_started = now_mono
                    if snapshots is not None and not snapshots.close():
                        raise TimeoutError('prior watchdog reader is not reaped for confirmation')
                    snapshot = observe(sentinel_config.database_url, holder_id)
                    now_mono = time.monotonic()
                # A failed confirmation remains one unobservable interval;
                # the successful first probe cannot reset its hard deadline.
                database_unreadable_since = None
            except Exception as exc:  # noqa: BLE001
                now_mono = time.monotonic()
                _diagnostic(observation_stage, 'FAILED', child=child,
                            started=observation_started, completed=now_mono,
                            worker_started=started, error=exc,
                            dependency_step=_SNAPSHOT_STAGES[snapshots.stage.value]
                            if snapshots is not None else None)
                if database_unreadable_since is None:
                    database_unreadable_since = now_mono
                supervisor_io.report(f"automation supervisor health read failed: {exc}",
                      file=sys.stderr)
                if _callback_deadline_expired_during_database_loss(
                        watch, now_monotonic=now_mono,
                        database_unreadable_since=database_unreadable_since,
                        deadline_seconds=(
                            automation_config.callback_deadline_seconds)):
                    _diagnostic('DATABASE_DEADLINE', 'TERMINATING', child=child,
                                started=observation_started, completed=now_mono,
                                worker_started=started, immediate=True)
                    supervisor_io.report(
                        f"automation supervisor terminating worker {holder_id}: "
                        "database authority was unobservable for the hard "
                        f"{automation_config.callback_deadline_seconds}s "
                        "callback deadline",
                        file=sys.stderr)
                    _terminate(child)
                    break
                time.sleep(poll_seconds)
                continue

            state = snapshot.state
            heartbeat_age = snapshot.heartbeat_age_seconds
            invalid_callback = bool(state and state.endswith("_CALLBACK") and (
                snapshot.callback_age_seconds is None
                or snapshot.callback_age_seconds < 0
                or snapshot.callback_remaining_seconds is None
                or snapshot.callback_remaining_seconds <= 0))
            if invalid_callback or _callback_deadline_expired(
                    watch, state=state, now_monotonic=now_mono,
                    deadline_seconds=automation_config.callback_deadline_seconds,
                    state_age_seconds=snapshot.callback_age_seconds,
                    invocation=snapshot.invocation):
                _diagnostic('CALLBACK_DEADLINE', 'TERMINATING', child=child,
                            started=observation_started, completed=now_mono,
                            worker_started=started, snapshot=snapshot, immediate=True)
                supervisor_io.report(
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
                        now_mono - started >= startup_grace_seconds),
                    state=state):
                age_detail = ("missing" if heartbeat_age is None
                              else f"{heartbeat_age:.3f}s")
                _diagnostic('IDLE_STALL', 'TERMINATING', child=child,
                            started=observation_started, completed=now_mono,
                            worker_started=started, snapshot=snapshot,
                            lease_seconds=automation_config.lease_seconds, immediate=True)
                _terminate(child)
                supervisor_io.report(
                    f"automation supervisor terminating stalled worker "
                    f"{holder_id}: heartbeat age {age_detail}; lease "
                    f"{automation_config.lease_seconds}s",
                    file=sys.stderr)
                break
            time.sleep(poll_seconds)

        if stopping:
            break
        # The old session was reaped. A failed next launch must not leave a
        # stale PID available to the stop handler after that PID is reused.
        child = None
        time.sleep(min(1.0, poll_seconds))

    if child is not None:
        _terminate(child)
    try:
        supervisor_io.run(_remove_holder)
    except Exception:
        pass
    return 0

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(serve_health=True))
