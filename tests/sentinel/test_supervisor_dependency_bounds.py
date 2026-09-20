"""Independent watchdog progress under silent dependencies and repeated phases."""
import multiprocessing
import os
import time
import sys
from types import SimpleNamespace

import pytest

from sentinel import automation_supervisor as supervisor, supervisor_io, schema
from sentinel.automation import store
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg


def test_same_phase_invocations_get_separate_deadlines_but_one_cannot_renew():
    watch = supervisor.CallbackWatch()
    for tick in range(0, 1800, 2):
        started = tick // 300 * 300
        assert not supervisor._callback_deadline_expired(watch,
            state='RECOVER_CALLBACK', now_monotonic=tick, deadline_seconds=900,
            state_age_seconds=tick-started, invocation=('holder', started))
    # A bad/wall-clock-shifted age observation cannot move one deadline.
    assert supervisor._callback_deadline_expired(watch,
        state='RECOVER_CALLBACK', now_monotonic=2401, deadline_seconds=900,
        state_age_seconds=0, invocation=('holder', 1500))


def test_silent_dependency_process_is_killed_and_reaped():
    pid = multiprocessing.get_context('fork').Value('i', 0)
    def never_returns():
        pid.value = os.getpid()
        time.sleep(60)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match='wall-clock'):
        supervisor_io.run(never_returns, timeout=.15)
    assert time.monotonic() - started < 2
    assert pid.value > 0
    with pytest.raises(ProcessLookupError):
        os.kill(pid.value, 0)


def test_full_logging_pipe_cannot_block_supervisor(monkeypatch):
    reader, writer = os.pipe()
    try:
        os.set_blocking(writer, False)
        with pytest.raises(BlockingIOError):
            while True:
                os.write(writer, b'x' * 4096)
        os.set_blocking(writer, True)
        with os.fdopen(os.dup(writer), 'w') as stream:
            monkeypatch.setattr(sys, 'stderr', stream)
            started = time.monotonic()
            supervisor_io.report('overdue worker')
            assert time.monotonic() - started < 2
    finally:
        os.close(writer)
        os.close(reader)


def test_real_snapshot_lock_is_bounded_then_recovers(conn):
    schema.ensure_schema(conn)
    store.register_instance(conn, instance_id='bounded-observer', state='RECOVER_CALLBACK')
    conn.execute('LOCK TABLE sentinel_automation_service_instances IN ACCESS EXCLUSIVE MODE')
    started = time.monotonic()
    with pytest.raises((TimeoutError, RuntimeError), match='budget|timeout'):
        supervisor._snapshot(conn.info.dsn, 'bounded-observer')
    assert time.monotonic() - started < 3
    conn.rollback()
    first = supervisor._snapshot(conn.info.dsn, 'bounded-observer')
    assert first[0] == 'RECOVER_CALLBACK' and first[1] >= 0 and first[2].tzinfo
    store.register_instance(conn, instance_id='bounded-observer', state='RECOVER_CALLBACK')
    second = supervisor._snapshot(conn.info.dsn, 'bounded-observer')
    assert second[2] > first[2]


__all__ = ['conn', 'pg']
def test_persistent_shadow_latch_survives_restart_without_worker(tmp_path, monkeypatch):
    from sentinel import shadow_supervisor as supervisor
    latch = tmp_path / 'state' / 'shadow-supervisor-critical.json'
    monkeypatch.setattr(supervisor, 'LATCH_FILE', latch)
    monkeypatch.setattr(supervisor, 'HEARTBEAT_FILE', tmp_path / 'heartbeat')
    monkeypatch.setattr(supervisor, '_enqueue_alert', lambda **kwargs: None)
    monkeypatch.setattr(supervisor.supervisor_io, 'report', lambda *a, **k: None)
    monkeypatch.setattr(supervisor.ShadowServiceConfig, 'from_env', lambda: object())
    monkeypatch.setattr(supervisor.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(supervisor.subprocess, 'Popen', lambda *a, **k: pytest.fail('latched worker started'))
    monkeypatch.setattr(supervisor, '_latched_wait', lambda stopping: 91)
    supervisor._latch('original integrity refusal')
    original = latch.read_bytes()
    supervisor._latch('later refusal cannot replace evidence')
    assert latch.read_bytes() == original
    assert supervisor.run() == 91
    assert latch.read_bytes() == original


def test_reconstructed_shadow_is_not_green_health(tmp_path, monkeypatch):
    from sentinel import shadow_supervisor as supervisor
    heartbeat = tmp_path / 'heartbeat'
    heartbeat.touch()
    monkeypatch.setattr(supervisor, 'HEARTBEAT_FILE', heartbeat)
    monkeypatch.setattr(supervisor, 'LATCH_FILE', tmp_path / 'absent')
    monkeypatch.setattr(supervisor, 'service_health', lambda _: {'service_health': 'RECONSTRUCTION_PENDING'})
    assert supervisor._health(30, config=object()) == 1


def test_filesystem_heartbeat_stall_cannot_hold_the_worker_deadline(monkeypatch):
    from sentinel import shadow_supervisor as shadow
    original = supervisor_io.run
    monkeypatch.setattr(supervisor_io, 'run', lambda function, *args, **kwargs:
                        original(function, *args, timeout=.1))
    monkeypatch.setattr(shadow, '_write_heartbeat', lambda: time.sleep(20))
    monkeypatch.setattr(supervisor_io, 'report', lambda *a, **k: None)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match='wall-clock'):
        shadow._touch()
    assert time.monotonic() - started < 2


def test_entire_shadow_health_read_is_bounded(monkeypatch):
    from sentinel import shadow_supervisor as shadow
    original = supervisor_io.run
    monkeypatch.setattr(supervisor_io, 'run', lambda function, *args, **kwargs:
                        original(function, *args, timeout=.1))
    monkeypatch.setattr(shadow, '_health_snapshot', lambda *args: time.sleep(20))
    monkeypatch.setattr(supervisor_io, 'report', lambda *a, **k: None)
    started = time.monotonic()
    assert shadow._health(30, config=object()) == 1
    assert time.monotonic() - started < 2


def test_holder_file_stall_refuses_before_starting_worker(monkeypatch):
    original = supervisor_io.run
    monkeypatch.setattr(supervisor_io, 'run', lambda function, *args, **kwargs:
                        original(function, *args, timeout=.1))
    monkeypatch.setattr(supervisor, '_write_holder', lambda *args: time.sleep(20))
    monkeypatch.setattr(supervisor.subprocess, 'Popen', lambda *a, **k: pytest.fail('worker started'))
    with pytest.raises(TimeoutError):
        supervisor._spawn('stalled-filesystem')


def test_unreaped_dependency_prevents_replacement(monkeypatch):
    class Unreaped:
        def is_alive(self): return True
    monkeypatch.setattr(supervisor_io, '_UNREAPED', [Unreaped()])
    monkeypatch.setattr(supervisor_io.multiprocessing, 'get_context',
                        lambda *args: pytest.fail('replacement created'))
    with pytest.raises(TimeoutError, match='not reaped'):
        supervisor_io.run(lambda: None)


def test_unknown_shadow_latch_cannot_start_worker(monkeypatch):
    from sentinel import shadow_supervisor as shadow
    original = supervisor_io.run
    monkeypatch.setattr(supervisor_io, 'run', lambda function, *args, **kwargs:
                        original(function, *args, timeout=.1))
    monkeypatch.setattr(shadow, '_touch', lambda: None)
    monkeypatch.setattr(shadow, '_latch_exists', lambda: time.sleep(20))
    monkeypatch.setattr(shadow.ShadowServiceConfig, 'from_env', lambda: object())
    monkeypatch.setattr(shadow.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(supervisor_io, 'report', lambda *a, **k: None)
    monkeypatch.setattr(shadow.subprocess, 'Popen', lambda *a, **k: pytest.fail('worker started'))
    started = time.monotonic()
    assert shadow.run() == shadow.EXIT_REFUSED
    assert time.monotonic() - started < 2


@pytest.mark.parametrize('delay_before_create', [False, True])
@pytest.mark.parametrize('exit_code', [2, 42, 11])
def test_terminal_refusal_survives_latch_timeout_and_restart(
        tmp_path, monkeypatch, delay_before_create, exit_code):
    from sentinel import shadow_supervisor as shadow
    assert {shadow.EXIT_REFUSED, shadow.EXIT_RETRY} == {2, 11}
    latch = tmp_path / 'shadow-supervisor-critical.json'
    monkeypatch.setattr(shadow, 'LATCH_FILE', latch)
    monkeypatch.setattr(shadow, 'HEARTBEAT_FILE', tmp_path / 'heartbeat')
    monkeypatch.setattr(shadow.ShadowServiceConfig, 'from_env',
                        lambda: SimpleNamespace(poll_seconds=0))
    monkeypatch.setenv('SENTINEL_SHADOW_FAILURE_THRESHOLD', '1')
    monkeypatch.setattr(shadow, '_touch', lambda: None)
    reports = []
    monkeypatch.setattr(shadow, '_report_latch', lambda *a, **k: reports.append(a))
    monkeypatch.setattr(shadow, '_latched_wait', lambda *a: 91)
    monkeypatch.setattr(shadow.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(supervisor_io, 'report', lambda *a, **k: None)
    persisted, observed = shadow._persist_latch, supervisor_io.run
    def slow_write(payload):
        if delay_before_create:
            time.sleep(.3)
        persisted(payload)
    monkeypatch.setattr(shadow, '_persist_latch', slow_write)
    def bounded(function, *args, **kwargs):
        if function is slow_write:
            kwargs['timeout'] = .05
        return observed(function, *args, **kwargs)
    monkeypatch.setattr(supervisor_io, 'run', bounded)
    starts = []
    def spawn(*a, **k):
        assert shadow._pending_file().exists(), 'worker launched without durable guard'
        starts.append(True)
        return SimpleNamespace(poll=lambda: exit_code)
    monkeypatch.setattr(shadow.subprocess, 'Popen', spawn)
    assert shadow.run() == 91
    assert reports, 'persistence timeout swallowed the critical report'
    assert latch.exists() is not delay_before_create
    assert shadow._pending_file().exists()
    shadow.HEARTBEAT_FILE.touch()
    monkeypatch.setattr(shadow, 'service_health', lambda _: {'service_health': 'HEALTHY'})
    assert shadow._health(30, config=object()) == 1
    monkeypatch.setattr(shadow, '_persist_latch', persisted)
    assert shadow.run() == 91
    assert len(starts) == 1


def test_worker_arming_timeout_never_launches(tmp_path, monkeypatch):
    from sentinel import shadow_supervisor as shadow
    monkeypatch.setattr(shadow, 'LATCH_FILE', tmp_path / 'critical.json')
    monkeypatch.setattr(shadow.ShadowServiceConfig, 'from_env', lambda: object())
    monkeypatch.setattr(shadow.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(shadow, '_touch', lambda: None)
    monkeypatch.setattr(shadow, '_arm_worker', lambda: time.sleep(.3))
    observed = supervisor_io.run
    monkeypatch.setattr(supervisor_io, 'run', lambda f, *a, **k: observed(f, *a, timeout=.05))
    monkeypatch.setattr(supervisor_io, 'report', lambda *a, **k: None)
    monkeypatch.setattr(shadow.subprocess, 'Popen', lambda *a, **k: pytest.fail('worker launched'))
    assert shadow.run() == shadow.EXIT_REFUSED


@pytest.mark.parametrize('first_code', [0, 10, 11, 12])
def test_recoverable_worker_outcome_clears_guard_before_next_attempt(tmp_path, monkeypatch, first_code):
    from sentinel import shadow_supervisor as shadow
    assert first_code in {0, shadow.EXIT_RETRY, shadow.EXIT_WAITING, shadow.EXIT_AVAILABILITY}
    monkeypatch.setattr(shadow, 'LATCH_FILE', tmp_path / 'critical.json')
    monkeypatch.setattr(shadow.ShadowServiceConfig, 'from_env',
                        lambda: SimpleNamespace(poll_seconds=0))
    monkeypatch.setattr(shadow.signal, 'signal', lambda *a: None)
    for name in ('_touch', '_source_recovery_alert', '_semantic_retry_alert', '_report_latch'):
        monkeypatch.setattr(shadow, name, lambda *a, **k: None)
    monkeypatch.setattr(shadow, '_latched_wait', lambda *a: 91)
    starts = []
    def spawn(*a, **k):
        starts.append(True)
        assert len(starts) <= 2
        return SimpleNamespace(poll=lambda: first_code if len(starts) == 1 else shadow.EXIT_REFUSED)
    monkeypatch.setattr(shadow.subprocess, 'Popen', spawn)
    assert shadow.run() == 91
    assert len(starts) == 2  # Exclusive re-arming also proves the first guard was cleared.


def test_latched_wait_retries_failed_persistence_without_worker(tmp_path, monkeypatch):
    from sentinel import shadow_supervisor as shadow
    monkeypatch.setattr(shadow, 'LATCH_FILE', tmp_path / 'critical.json')
    shadow._arm_worker()
    monkeypatch.setattr(shadow, '_touch', lambda: None)
    monkeypatch.setattr(shadow.time, 'sleep', lambda _: None)
    monkeypatch.setattr(shadow.subprocess, 'Popen', lambda *a, **k: pytest.fail('worker launched'))
    assert shadow._latched_wait(lambda: shadow.LATCH_FILE.exists(), {'reason': 'refusal'}) == 0
    assert shadow._pending_file().exists()


def test_semantic_retry_threshold_survives_normal_guard_clear(tmp_path, monkeypatch):
    from sentinel import shadow_supervisor as shadow
    monkeypatch.setattr(shadow, 'LATCH_FILE', tmp_path / 'critical.json')
    monkeypatch.setattr(shadow.ShadowServiceConfig, 'from_env',
                        lambda: SimpleNamespace(poll_seconds=0))
    monkeypatch.setenv('SENTINEL_SHADOW_FAILURE_THRESHOLD', '3')
    monkeypatch.setattr(shadow.signal, 'signal', lambda *a: None)
    for name in ('_touch', '_semantic_retry_alert', '_report_latch'):
        monkeypatch.setattr(shadow, name, lambda *a, **k: None)
    monkeypatch.setattr(shadow, '_latched_wait', lambda *a: 91)
    starts = []
    def spawn(*a, **k):
        starts.append(True)
        assert len(starts) <= 3, 'semantic failure budget reset'
        return SimpleNamespace(poll=lambda: shadow.EXIT_RETRY)
    monkeypatch.setattr(shadow.subprocess, 'Popen', spawn)
    assert shadow.run() == 91
    assert len(starts) == 3
    assert shadow._pending_file().exists()


@pytest.mark.parametrize('stop_by_signal', [False, True])
@pytest.mark.parametrize('refusal_races_termination', [False, True])
def test_supervised_termination_acknowledges_worker_and_allows_restart(
        tmp_path, monkeypatch, stop_by_signal, refusal_races_termination):
    from sentinel import shadow_supervisor as shadow
    monkeypatch.setattr(shadow, 'LATCH_FILE', tmp_path / 'critical.json')
    monkeypatch.setattr(shadow.ShadowServiceConfig, 'from_env',
                        lambda: SimpleNamespace(poll_seconds=0))
    monkeypatch.setenv('SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS', '30')
    handlers, starts = {}, []
    monkeypatch.setattr(shadow.signal, 'signal', lambda sig, fn: handlers.update({sig: fn}))
    monkeypatch.setattr(shadow, '_touch', lambda: None)
    monkeypatch.setattr(shadow, '_report_latch', lambda *a, **k: None)
    monkeypatch.setattr(shadow, '_latched_wait', lambda *a: 91)
    monkeypatch.setattr(supervisor_io, 'report', lambda *a, **k: None)
    clock = iter([0, 31, 31, 31])
    monkeypatch.setattr(shadow, 'time', SimpleNamespace(
        time=time.time, monotonic=lambda: next(clock, 31), sleep=time.sleep))
    class Child:
        code = None
        def poll(self): return self.code
        def terminate(self): self.code = shadow.EXIT_REFUSED if refusal_races_termination else -15
        def wait(self, **kwargs): return self.code
    def spawn(*a, **k):
        if starts:
            # A second launch proves exclusive arming after a deadline worked.
            handlers[shadow.signal.SIGTERM]()
            return SimpleNamespace(poll=lambda: 0)
        starts.append(True)
        return Child()
    monkeypatch.setattr(shadow.subprocess, 'Popen', spawn)
    if stop_by_signal:
        # Stop on the next supervisor heartbeat, after assigning active child.
        def heartbeat():
            if starts:
                handlers[shadow.signal.SIGTERM]()
        monkeypatch.setattr(shadow, '_touch', heartbeat)
    assert shadow.run() == (91 if refusal_races_termination else 0)
    assert shadow._pending_file().exists() is refusal_races_termination
    assert shadow.LATCH_FILE.exists() is refusal_races_termination
