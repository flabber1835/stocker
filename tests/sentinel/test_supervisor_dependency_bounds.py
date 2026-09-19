"""Independent watchdog progress under silent dependencies and repeated phases."""
import multiprocessing
import os
import time
import sys

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
    monkeypatch.setattr(shadow, '_touch_file', lambda: time.sleep(20))
    monkeypatch.setattr(supervisor_io, 'report', lambda *a, **k: None)
    started = time.monotonic()
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
