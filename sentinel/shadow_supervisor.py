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
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic as diagnostic_clock

from sentinel.feed import calendar
from sentinel.feed import observation_timing
from sentinel import supervisor_io, shadow_budget, shadow_drain, shadow_worker_liveness, shadow_service_status
from sentinel.backup_guard import BUSY_PROBE_SECONDS, BUSY_RETRY_MAX_SECONDS
from sentinel import shadow_restart_recovery as restart_recovery
from sentinel.shadow_service_config import ShadowServiceConfig, ShadowServiceWaiting
from sentinel.shadow_exit_codes import (
    EXIT_AVAILABILITY, EXIT_BACKUP_PROOF_BUSY, EXIT_DEPENDENCY_UNAVAILABLE,
    EXIT_REFUSED, EXIT_RETRY, EXIT_WAITING,
)

HEARTBEAT_FILE = Path("/tmp/sentinel-shadow-supervisor-heartbeat")
LATCH_FILE = Path(os.environ.get("SENTINEL_STATE_DIR", "/var/lib/sentinel")) / "shadow-supervisor-critical.json"
_STATUS_INCARNATION = uuid.uuid4().hex


def service_health(config: ShadowServiceConfig, *, now: datetime | None = None) -> dict:
    """Keep the public fallback seam without bootstrapping financial runtime."""
    from sentinel.shadow_recovery import service_health as original
    return original(config, now=now)


def _next_acquisition_close(started_at):
    try:
        previous = observation_timing.latest_acquirable_session(started_at)
        return observation_timing.acquisition_not_before(calendar.next_session(previous))
    except (calendar.CalendarUnavailable, calendar.NonSessionDate):
        return None


RETENTION_CHILD_SECONDS = 7.0
RETENTION_REAP_SECONDS = 2.0
RETENTION_SPACING_SECONDS = 30.0
_UNCHANGED_PROOF_SECONDS = 600


@dataclass(frozen=True)
class _UnchangedSchedule:
    observation: tuple
    started: float
    started_at: datetime

    @property
    def deadline(self):
        return self.started + _UNCHANGED_PROOF_SECONDS

    def current(self):
        age = (shadow_budget.now() - self.started_at).total_seconds()
        return 0 <= age < _UNCHANGED_PROOF_SECONDS and self.started <= time.monotonic() < self.deadline


def _scheduling_subject(config):
    from sentinel import shadow_health_projection
    if _latch_exists():
        return None
    return shadow_health_projection.scheduling_subject(config,
        LATCH_FILE.with_name('shadow-health-projection.json'))


def _observe_schedule(config, stopping):
    try:
        return supervisor_io.run(_scheduling_subject, config, timeout=2, cancelled=stopping)
    except (ValueError, OSError, RuntimeError, TimeoutError):
        # Optional idle observation cannot conceal a real worker refusal.
        return None


def _earned_schedule(before, measured, *, started, started_at):
    if before is None or measured is None or before[0] != measured[0]:
        return None
    verdict = measured[1]
    if (verdict is None or verdict == before[1] or not verdict[2]
            or not started_at <= verdict[1] <= shadow_budget.now()):
        return None
    hint = _UnchangedSchedule(measured, started, started_at)
    return hint if hint.current() else None


def _idle_retention(database_url, prior_witness):
    from sentinel.feed import retention

    def work():
        if _latch_exists():
            return False, None
        proof = retention.IdleCheckpointProof(prior_witness)
        keep = retention.idle_pass(database_url, checkpoint_proof=proof)
        return keep, proof.witness if keep else None

    # Hold the same admission lock used to request and acknowledge a drain.
    # An idle acknowledgement must cover this separate bounded child as well.
    return shadow_drain.arm_or_drain(LATCH_FILE.parent, database_url,
                                     _STATUS_INCARNATION, work) or (False, None)


class _IdleRetention:
    """One owner carries its cleanup clock and byte witness across polls."""

    def __init__(self, database_url, stopping):
        self.database_url = database_url
        self.stopping = stopping
        self.ready_at = 0.0
        self.witness = None

    def __call__(self):
        try:
            keep, self.witness = supervisor_io.run(_idle_retention, self.database_url,
                self.witness, timeout=RETENTION_CHILD_SECONDS, cancelled=self.stopping)
            return keep
        except Exception as exc:
            self.witness = None
            supervisor_io.report('WARNING: rolling idle maintenance unavailable: '
                                 + type(exc).__name__)
            return False
        finally:
            self.ready_at = time.monotonic() + RETENTION_SPACING_SECONDS


def _poll_after_worker(*, deadline, close_at, stopping, heartbeat, backup_completed=None,
                       idle_work=None):
    def remaining():
        budget = deadline - time.monotonic()
        if close_at is not None:
            budget = min(budget, (close_at - shadow_budget.now()).total_seconds())
        return budget

    probe_at = time.monotonic() + BUSY_PROBE_SECONDS
    while not stopping():
        budget = remaining()
        if budget <= 0:
            return
        heartbeat()
        if stopping():
            return
        if backup_completed is not None and time.monotonic() >= probe_at:
            if backup_completed():
                return
            probe_at = time.monotonic() + BUSY_PROBE_SECONDS
            continue
        if (idle_work is not None and time.monotonic() >= idle_work.ready_at
                and remaining() > RETENTION_CHILD_SECONDS + RETENTION_REAP_SECONDS):
            if not idle_work():
                idle_work = None
            continue
        time.sleep(max(0.0, min(1.0, remaining())))


def _wait_for_next_attempt(poll, hint, config):
    if hint is None or poll['close_at'] is None:
        _poll_after_worker(**poll)
        return
    acquisition_at = poll['close_at']
    due = hint.started_at + timedelta(seconds=_UNCHANGED_PROOF_SECONDS)
    cutoff = min(acquisition_at, due, hint.observation[2])
    poll['close_at'] = cutoff
    poll['deadline'] = min(poll['deadline'], hint.deadline)
    checked_at, checked_tick = shadow_budget.now(), time.monotonic()
    limit = hint.deadline
    interval = config.poll_seconds
    reserved = False
    while True:
        _poll_after_worker(**poll)
        observed_at, observed_tick = shadow_budget.now(), time.monotonic()
        if poll['stopping']() or observed_at < checked_at or observed_tick < checked_tick:
            return
        if observed_at >= cutoff or observed_tick >= limit:
            if reserved or cutoff != due:
                return
            cutoff = _opening_refresh_cutoff(hint, due, acquisition_at, observed_at, observed_tick)
            if cutoff is None:
                return
            limit = hint.started + (cutoff - hint.started_at).total_seconds()
            if observed_at >= cutoff or observed_tick >= limit:
                return
            # A full proof has expired. Only an independently reobserved
            # unchanged publication can postpone its optional maintenance.
            reserved = True
            interval = min(interval, 30)
            poll.update(close_at=cutoff, idle_work=None)
        refreshed = _observe_schedule(config, poll['stopping'])
        checked_at, checked_tick = shadow_budget.now(), time.monotonic()
        if (refreshed != hint.observation or not observed_at <= checked_at < cutoff
                or not observed_tick <= checked_tick < limit):
            return
        poll['deadline'] = min(checked_tick + interval, limit)


def _opening_refresh_cutoff(hint, due, acquisition_at, observed_at, observed_tick):
    health_until = hint.observation[2]
    if due.date() != health_until.date():
        return None
    try:
        opened, closed = calendar.session_window(due.date())
    except (calendar.CalendarUnavailable, calendar.NonSessionDate):
        return None
    cutoff = min(opened + timedelta(minutes=10), closed, health_until, acquisition_at)
    elapsed_at = hint.started_at + timedelta(seconds=observed_tick - hint.started)
    if opened <= min(due, observed_at, elapsed_at) and max(due, observed_at, elapsed_at) < cutoff:
        return cutoff
    return None


def _diagnostic(stage, outcome, *, error=None, started=None, attempt=None,
                child_pid=None, supervisor_pid=None):
    context = {'incarnation': _STATUS_INCARNATION,
               'supervisor_pid': supervisor_pid if supervisor_pid is not None else os.getpid()}
    if started is not None:
        completed = diagnostic_clock()
        context.update(started=started, completed=completed,
                       elapsed_seconds=completed-started)
    if attempt is not None:
        context['attempt'] = attempt
    if child_pid is not None:
        context['child_pid'] = child_pid
    return supervisor_io.report_event('shadow', stage, outcome, error=error,
                                      context=context, immediate=True)


def _touch() -> None:
    supervisor_io.run(_write_heartbeat)


class _Heartbeat:
    """A bounded liveness projection cannot acknowledge a financial outcome."""

    def __init__(self):
        self.unavailable = False

    def __call__(self):
        try:
            _touch()
        except (OSError, RuntimeError, TimeoutError) as exc:
            if not self.unavailable:
                _diagnostic('HEARTBEAT', 'FAILED', error=exc)
                supervisor_io.report(
                    'WARNING: shadow heartbeat unavailable; worker deadline '
                    'remains enforced: ' + type(exc).__name__, file=sys.stderr)
            self.unavailable = True
        else:
            if self.unavailable:
                _diagnostic('HEARTBEAT', 'RECOVERED')
                supervisor_io.report('shadow heartbeat observation recovered',
                                     file=sys.stderr)
            self.unavailable = False

def _write_heartbeat():
    HEARTBEAT_FILE.touch(exist_ok=True)
    shadow_service_status.publish(LATCH_FILE, _STATUS_INCARNATION)
    shadow_drain.acknowledge_idle(LATCH_FILE.parent,
        os.environ.get('SENTINEL_DATABASE_URL',''),_STATUS_INCARNATION)


def _latch_exists():
    for marker in (LATCH_FILE, _pending_file()):
        try:
            marker.lstat()
        except FileNotFoundError:
            continue
        return True
    return False


def _pending_file():
    return LATCH_FILE.with_name('shadow-supervisor-pending.json')


def _arm_worker(supervisor_pid=None):
    # A positive, durable acknowledgement is required before launching work.
    # Never reuse an existing marker from an unacknowledged prior attempt.
    def arm():
        attempt = uuid.uuid4().hex
        _write_marker(_pending_file(), restart_recovery.make_pending(
            attempt, supervisor_pid if supervisor_pid is not None else os.getpid()))
        _diagnostic('ARM', 'ACCEPTED', attempt=attempt, supervisor_pid=supervisor_pid)
        return attempt
    return shadow_drain.arm_or_drain(LATCH_FILE.parent,
        os.environ.get('SENTINEL_DATABASE_URL',''),_STATUS_INCARNATION,arm)


def _retry_arm_worker(supervisor_pid):
    # The publisher owner is still held, and supervisor_io refuses this call
    # while the first helper can still write a pending marker.
    if _latch_exists():
        raise restart_recovery.RecoveryRefused('arming retry found retained state')
    return _arm_worker(supervisor_pid)


def _arm_worker_with_retry(stopping, started):
    supervisor_pid = os.getpid()
    try:
        return supervisor_io.run(_arm_worker, supervisor_pid, timeout=2)
    except TimeoutError as exc:
        if stopping():
            return None
        _diagnostic('ARM', 'DEFERRED', error=exc, started=started)
        time.sleep(1)
        if stopping():
            return None
        return supervisor_io.run(_retry_arm_worker, supervisor_pid, timeout=2)


def _clear_worker():
    _pending_file().unlink()
    _sync_state_directory()
    shadow_worker_liveness.clear()


def _sync_state_directory():
    directory = os.open(LATCH_FILE.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _write_marker(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(payload, sort_keys=True))
        stream.flush()
        os.fsync(stream.fileno())
    _sync_state_directory()


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
        if event_type == 'SHADOW_DEPENDENCY_UNAVAILABLE':
            from sentinel import shadow_dependency_notifications as notices
            notices.enqueue_warning(conn, payload)
            return
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
        if not expired:
            return
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


def _dependency_retry_alert(*, now: datetime | None = None) -> None:
    """A dependency deferral is not proof that a decision missed its open."""
    try:
        from sentinel import shadow_dependency_notifications as notices
        payload = notices.fallback_warning(now=now)
        target = payload['decision_session']
        _enqueue_alert(
            idempotency_key=f'shadow-dependency:{target}:unavailable',
            event_type='SHADOW_DEPENDENCY_UNAVAILABLE', severity='WARN',
            payload=payload)
    except Exception as exc:
        supervisor_io.report('WARNING: shadow dependency notification unavailable: '
                             + type(exc).__name__, file=sys.stderr)


def _terminate(child: subprocess.Popen, *, grace_seconds: float = 5.0) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=max(1.0, grace_seconds))


def _latch(reason: str, *, failures: int | None = None):
    payload = {
        "schema": "sentinel.shadow-supervisor-critical/1",
        "reason": str(reason),
        "failures": failures,
        "latched_at_unix": time.time(),
    }
    pending = _try_persist_latch(payload)
    _report_latch(reason, failures=failures)
    return pending


def _try_persist_latch(payload):
    try:
        supervisor_io.run(_persist_latch, payload, timeout=2)
    except Exception as exc:
        supervisor_io.report('CRITICAL: shadow latch persistence unavailable; '
                             'worker remains fenced: ' + type(exc).__name__)
        return payload
    return None


def _persist_latch(payload):
    try:
        _write_marker(LATCH_FILE, payload)
    except FileExistsError:
        pass  # The original refusal remains the incident evidence.


def _report_latch(reason, *, failures=None):
    # The latch remains the local fail-closed authority.  This best-effort
    # projection gives the independent dispatcher one durable critical event
    # when PostgreSQL is still available; inability to report never clears or
    # softens the latch.
    if _report_retained_interruption():
        supervisor_io.report('CRITICAL: shadow supervisor latched unhealthy: '+str(reason))
        return
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


def _retained_interruption():
    marker = LATCH_FILE if LATCH_FILE.exists() else _pending_file()
    raw = shadow_service_status._raw(marker)
    incident = hashlib.sha256(marker.name.encode()+b'\0'+raw).hexdigest()
    try:
        attempt = (shadow_service_status.pending(marker)
                   if marker == _pending_file() else None)
    except ValueError:
        attempt = None
    return {
        'incident_sha256': incident,
        'reason': ('UNACKNOWLEDGED_WORKER' if attempt is not None else
                   'UNREADABLE_PENDING_MARKER' if marker == _pending_file() else 'CRITICAL_LATCH'),
        'attempt_id': attempt['attempt_id'] if attempt is not None else None,
    }


def _report_retained_interruption() -> bool:
    try:
        incident = supervisor_io.run(_retained_interruption)
        _enqueue_alert(idempotency_key='shadow-retained-interruption:'+incident['incident_sha256'],
            event_type='SHADOW_SUPERVISOR_LATCHED', severity='CRITICAL', payload=incident)
        return True
    except Exception as exc:
        supervisor_io.report('CRITICAL: retained shadow interruption notification unavailable: '
                             + type(exc).__name__)
        return False


def _latched_wait(stopping, pending=None) -> int:
    heartbeat = _Heartbeat()
    notified = False
    next_notice = float('-inf')
    while not stopping():
        if pending is not None:
            pending = _try_persist_latch(pending)
            if pending is not None:
                time.sleep(1.0)
                continue  # Persistence loss cannot renew a positive heartbeat.
        if not notified and time.monotonic() >= next_notice:
            notified = _report_retained_interruption()
            next_notice = time.monotonic()+30
        heartbeat()
        time.sleep(1.0)
    return 0


def _health_failure(reason, message, error=None):
    if os.environ.get('SENTINEL_FEED_SERVICE_MODE') == 'SHADOW':
        supervisor_io.report_event('shadow', 'HEALTH_PROBE', 'FAILED', error=error,
                                   context={'state': reason}, container_log=True)
    supervisor_io.report(message, file=sys.stderr)
    return 1


def _close_worker(config):
    """Match the current authenticated attempt to the original live process."""
    try:
        value = shadow_service_status.read(LATCH_FILE.parent, config.database_url)
        now = datetime.now(timezone.utc)
        pending = shadow_service_status.pending(_pending_file())
        if (value['reason'] == 'ACTIVE_WORKER' and pending is not None
                and pending['schema'] == restart_recovery.SCHEMA
                and pending['attempt_id'] == value['attempt_id']
                and not LATCH_FILE.exists()
                and timedelta(0) <= now-value['observed_at'] <= timedelta(seconds=shadow_service_status.MAX_AGE_SECONDS)
                and now < value['worker_deadline']):
            live = shadow_worker_liveness.matched_worker(_pending_file(), signed_pending=pending)
            if live and not LATCH_FILE.exists():
                return {**value, 'live_worker': live,
                        'armed_at': datetime.fromtimestamp(pending['started_at_unix'], timezone.utc)}
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        pass
    return None


def _health(max_age_seconds: float, *, config=None) -> int:
    """Require supervisor liveness plus a safe shadow recovery state."""
    try:
        return supervisor_io.run(_health_snapshot, max_age_seconds, config, timeout=3)
    except Exception as exc:
        return _health_failure('DEPENDENCY', f"REFUSED: shadow health dependency unavailable: {type(exc).__name__}", exc)


def _health_snapshot(max_age_seconds, config, *, financial=True):
    try:
        age = time.time() - HEARTBEAT_FILE.stat().st_mtime
    except OSError as exc:
        return _health_failure('HEARTBEAT_ABSENT', f"REFUSED: shadow supervisor heartbeat absent: {exc}", exc)
    if age < 0 or age > max_age_seconds:
        return _health_failure('HEARTBEAT_STALE', f"REFUSED: shadow supervisor heartbeat stale ({age:.3f}s)")
    pending = _pending_file().exists()
    active = pending and shadow_worker_liveness.matches(_pending_file())
    if pending and not active and not LATCH_FILE.exists():
        return _health_failure('UNACKNOWLEDGED_WORKER', 'REFUSED: shadow supervisor has an unacknowledged worker outcome; '
                               'retained-state verification and operator recovery are required')
    if LATCH_FILE.exists():
        try:
            with LATCH_FILE.open(encoding="utf-8") as stream:
                detail = stream.read(4096)
        except OSError as exc:
            detail = f"critical latch or unacknowledged worker outcome: {exc}"
        return _health_failure('CRITICAL_LATCH', f"REFUSED: shadow supervisor critical latch: {detail}")
    if not financial:
        return 0  # Process readiness does not authorize a financial decision.
    from sentinel import shadow_health_projection
    try:
        resolved = config if config is not None else ShadowServiceConfig.from_env()
        owner = _close_worker(resolved) if active and getattr(resolved, 'operational_source_only', False) else None
        health = shadow_health_projection.health(
            resolved, fallback=service_health,
            observe_close_wait=owner is not None,
            target=LATCH_FILE.with_name('shadow-health-projection.json'))
        if health.get('service_health') == 'CLOSE_PUBLICATION_PENDING':
            after = _close_worker(resolved)
            if (owner and after and (after['incarnation'], after['attempt_id']) == (owner['incarnation'], owner['attempt_id'])
                    and owner['armed_at'] == after['armed_at'] <= health['job_created_at']
                    and owner['live_worker'] == after['live_worker']
                    and after['observed_at'] >= owner['observed_at']
                    and after['worker_deadline'] <= owner['worker_deadline']
                    and datetime.now(timezone.utc) < min(health['valid_until'], after['worker_deadline'])):
                return 0
            return _health_failure('CLOSE_WORKER_CHANGED', 'REFUSED: shadow close publisher changed during health observation')
        if health.get("service_health") == "RECONSTRUCTION_PENDING" and not active:
            return _health_failure('RECONSTRUCTION_PENDING', "REFUSED: shadow reconstruction is pending")
    except ShadowServiceWaiting as exc:
        if active:
            return 0  # Recovering worker is live; financial admission stays red.
        return _health_failure('FINANCIAL_PENDING', f"REFUSED: shadow financial readiness pending: {exc}", exc)
    except shadow_health_projection.ProjectionRenewalRequired as exc:
        cause = {'inventory': 'INVENTORY_CHANGED', 'config': 'CONFIG_CHANGED'}.get(exc.binding, 'HINT_RENEWAL')
        return _health_failure(cause, f"REFUSED: shadow frontier health failed: {type(exc).__name__}: {exc}", exc)
    except Exception as exc:  # structural corruption still fails health closed
        return _health_failure('FRONTIER', f"REFUSED: shadow frontier health failed: {type(exc).__name__}: {exc}", exc)
    return 0


def run() -> int:
    owned = False
    try:
        with restart_recovery.owner(LATCH_FILE.parent) as owner_fd:
            owned = True
            return _run_owned(owner_fd)
    except (OSError, restart_recovery.RecoveryRefused) as exc:
        _diagnostic('OWNED_RUN' if owned else 'OWNERSHIP', 'FAILED', error=exc)
        supervisor_io.report('REFUSED: shadow publisher ownership unavailable: '+type(exc).__name__)
        return EXIT_REFUSED


def _recover_startup(config, stopping, heartbeat):
    try:
        selected = supervisor_io.run(restart_recovery.eligible, LATCH_FILE.parent, timeout=2)
        if not selected:
            return False
    except Exception:
        return False  # Critical, malformed and legacy attempts remain fenced.
    deadline = time.monotonic()+restart_recovery.RECOVERY_SECONDS
    while not stopping() and time.monotonic() < deadline:
        heartbeat()
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            return False
        try:
            result = supervisor_io.run(restart_recovery.probe, config,
                timeout=min(restart_recovery.PROBE_SECONDS, remaining))
        except TimeoutError:
            result = {'status': 'WAITING'}
        except Exception:
            return False
        if result['status'] == 'VERIFIED':
            if stopping() or time.monotonic() >= deadline:
                return False
            try:
                recovered = supervisor_io.run(restart_recovery.archive, LATCH_FILE.parent,
                    result['proof'], selected['marker_sha256'],
                    timeout=min(2, deadline-time.monotonic()))
            except Exception as exc:
                raise restart_recovery.ArchiveUncertain('restart incident archive is uncertain') from exc
            supervisor_io.report('shadow restart recovered verified session '+recovered['session']+
                                 '; interrupted worker outcome remains UNKNOWN')
            return True
        if result['status'] != 'WAITING':
            return False
        wake = min(deadline, time.monotonic()+5)
        while not stopping() and time.monotonic() < wake:
            heartbeat()
            time.sleep(min(1, wake-time.monotonic()))
    return False


def _run_owned(owner_fd) -> int:
    global _STATUS_INCARNATION
    _STATUS_INCARNATION = uuid.uuid4().hex
    config = ShadowServiceConfig.from_env()
    try:
        deadline_seconds = shadow_budget.seconds()
    except ValueError as exc:
        supervisor_io.report("REFUSED: " + str(exc), file=sys.stderr)
        return EXIT_REFUSED
    failure_threshold = int(os.environ.get(
        "SENTINEL_SHADOW_FAILURE_THRESHOLD", "3"))
    if failure_threshold < 1 or failure_threshold > 100:
        supervisor_io.report("REFUSED: SENTINEL_SHADOW_FAILURE_THRESHOLD must be in [1,100]",
              file=sys.stderr)
        return EXIT_REFUSED

    heartbeat = _Heartbeat()
    stopping = False
    active: subprocess.Popen | None = None
    terminated = False
    consecutive_failures = 0
    close_at = None

    def stop(_signum=None, _frame=None):
        nonlocal stopping, terminated
        stopping = True
        if active is not None and active.poll() is None:
            terminated = True
            _terminate(active)

    idle_retention = _IdleRetention(config.database_url, lambda: stopping) if getattr(
        config, 'operational_source_only', False) else None
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        heartbeat()
        try:
            latched = supervisor_io.run(_latch_exists)
        except Exception as exc:
            supervisor_io.report(f"REFUSED: shadow latch state unavailable: {type(exc).__name__}")
            return EXIT_REFUSED
        if latched:
            try:
                recovered = _recover_startup(config, lambda: stopping, heartbeat)
            except restart_recovery.ArchiveUncertain:
                pending = _latch('restart incident archive requires operator inspection')
                return _latched_wait(lambda: stopping, pending)
            if not recovered:
                _report_retained_interruption()
                return _latched_wait(lambda: stopping)
        while not stopping:
            operational = getattr(config, 'operational_source_only', False)
            before = _observe_schedule(config, lambda: stopping) if operational else None
            if stopping:
                break
            arm_started = diagnostic_clock()
            _diagnostic('ARM', 'BEGIN', started=arm_started)
            try:
                attempt = _arm_worker_with_retry(lambda: stopping, arm_started)
            except Exception as exc:
                _diagnostic('ARM', 'FAILED', error=exc, started=arm_started)
                supervisor_io.report('REFUSED: shadow worker could not be durably armed: '
                                     + type(exc).__name__)
                return EXIT_REFUSED
            if attempt is None:
                if stopping:
                    break
                # An authenticated drain owns admission. Existing children
                # finished before acknowledgement; heartbeat is liveness only.
                heartbeat()
                time.sleep(1)
                continue
            _diagnostic('ARM', 'ACCEPTED', started=arm_started, attempt=attempt)
            started = time.monotonic()
            worker_started_at = shadow_budget.now()
            worker_env = dict(os.environ)
            worker_env[shadow_budget.DEADLINE_ENV] = (
                worker_started_at + timedelta(seconds=deadline_seconds)).isoformat()
            spawn_started = diagnostic_clock()
            try:
                active = subprocess.Popen(
                    [sys.executable, "-m", "sentinel.shadow_worker"],
                    stdin=subprocess.DEVNULL, env=worker_env, pass_fds=(owner_fd,))
            except OSError as exc:
                _diagnostic('SPAWN', 'FAILED', error=exc, started=spawn_started, attempt=attempt)
                raise
            if stopping:
                stop()  # A signal during arming/spawn must also terminate this child.
            if active.poll() is None:
                proof_started = diagnostic_clock()
                try:
                    supervisor_io.run(shadow_worker_liveness.record, attempt,
                                      os.getpid(), active.pid,
                                      started + deadline_seconds, timeout=2)
                except Exception as exc:
                    if active.poll() is None:
                        _diagnostic('ACTIVE_PROOF', 'FAILED', error=exc, started=proof_started,
                                    attempt=attempt, child_pid=getattr(active, 'pid', None))
                        supervisor_io.report('REFUSED: active worker proof unavailable: '
                                             + type(exc).__name__)
                        return EXIT_REFUSED  # finally reaps child; pending stays fenced.
            timed_out = False
            while not stopping and active.poll() is None:
                heartbeat()
                if time.monotonic() - started > deadline_seconds:
                    supervisor_io.report(
                        "shadow supervisor terminating overdue advance after "
                        f"{deadline_seconds:.0f}s", file=sys.stderr, flush=True)
                    _terminate(active)
                    timed_out = True
                    break
                time.sleep(1.0)
            code = active.poll()
            if (timed_out or terminated) and code in {-signal.SIGTERM, -signal.SIGKILL}:
                code = 124
            else:
                # A natural terminal refusal can race our termination request.
                # Only an observed signal termination earns the retryable outcome.
                code = int(code) if code is not None else -1
            backup_failed_at = shadow_budget.now() if code == EXIT_BACKUP_PROOF_BUSY else None
            active = None
            if code == EXIT_REFUSED:
                pending = _latch("shadow worker reported terminal integrity refusal")
                return _latched_wait(lambda: stopping, pending)
            if code not in {
                    0, EXIT_WAITING, EXIT_RETRY, EXIT_AVAILABILITY,
                    EXIT_DEPENDENCY_UNAVAILABLE, EXIT_BACKUP_PROOF_BUSY, 124}:
                pending = _latch(f"shadow worker exited unexpectedly with {code}")
                return _latched_wait(lambda: stopping, pending)

            if code == EXIT_RETRY:
                # A typed non-availability retry represents a local semantic failure
                # and remains bounded. A hard timeout is different: the child was
                # forcibly stopped at a known process boundary and the canonical
                # ingest/catch-up paths are restart-convergent, so timeout duration
                # alone cannot permanently poison an otherwise valid deployment.
                consecutive_failures += 1
                if consecutive_failures >= failure_threshold:
                    pending = _latch(
                        "shadow publisher exceeded bounded semantic retry threshold",
                        failures=consecutive_failures)
                    return _latched_wait(lambda: stopping, pending)
                _semantic_retry_alert()
            elif code in {EXIT_WAITING, EXIT_AVAILABILITY}:
                _source_recovery_alert()
                consecutive_failures = 0
            elif code in {EXIT_DEPENDENCY_UNAVAILABLE, EXIT_BACKUP_PROOF_BUSY}:
                _dependency_retry_alert()
                consecutive_failures = 0
            else:
                # Successful work and supervised deadlines remain restartable.
                consecutive_failures = 0

            acknowledgement_started = diagnostic_clock()
            try:
                supervisor_io.run(_clear_worker, timeout=2)
            except Exception as exc:
                _diagnostic('ACK', 'FAILED', error=exc, started=acknowledgement_started,
                            attempt=attempt)
                supervisor_io.report('REFUSED: shadow worker acknowledgement unavailable: '
                                     + type(exc).__name__)
                return EXIT_REFUSED
            if stopping:
                break

            heartbeat()
            deadline = time.monotonic() + config.poll_seconds
            if operational and (
                    close_at is None or worker_started_at >= close_at):
                close_at = _next_acquisition_close(worker_started_at)
            poll = dict(deadline=deadline, close_at=close_at,
                        stopping=lambda: stopping, heartbeat=heartbeat)
            if backup_failed_at is not None:
                from sentinel.backup_retry import completed_since

                poll["deadline"] = min(deadline, time.monotonic() + BUSY_RETRY_MAX_SECONDS)
                poll["backup_completed"] = lambda: completed_since(
                    config.database_url, backup_failed_at)
            elif operational and code in {
                    0, EXIT_WAITING, EXIT_AVAILABILITY, EXIT_DEPENDENCY_UNAVAILABLE}:
                poll['idle_work'] = idle_retention
            hint = None
            if code == 0 and before is not None:
                hint = _earned_schedule(before, _observe_schedule(config, lambda: stopping),
                    started=started, started_at=worker_started_at)
            _wait_for_next_attempt(poll, hint, config)
    finally:
        # Dispose of the active worker before any best-effort filesystem cleanup.
        if active is not None:
            _terminate(active)
        try:
            supervisor_io.run(shadow_worker_liveness.clear)
            supervisor_io.run(_remove_heartbeat)
        except Exception:
            pass
    return 0


def _remove_heartbeat():
    HEARTBEAT_FILE.unlink(missing_ok=True)
    shadow_service_status.publish(LATCH_FILE, _STATUS_INCARNATION, stopped=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    health = parser.add_mutually_exclusive_group()
    health.add_argument("--health", action="store_true")
    health.add_argument("--service-health", action="store_true")
    args = parser.parse_args(argv)
    if args.service_health:
        try:
            return supervisor_io.run(_service_health_snapshot, 30, timeout=3)
        except Exception as exc:
            supervisor_io.report('REFUSED: shadow process health unavailable: ' + type(exc).__name__)
            return 1
    if args.health:
        poll = float(os.environ.get("SENTINEL_SHADOW_POLL_SECONDS", "300"))
        return _health(max(10.0, min(30.0, poll)))
    return run()


def _service_health_snapshot(max_age_seconds):
    return _health_snapshot(max_age_seconds, None, financial=False)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
