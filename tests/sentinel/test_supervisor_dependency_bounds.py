"""Independent watchdog progress under silent dependencies and repeated phases."""
import json
import multiprocessing
import os
import time
import sys
from types import SimpleNamespace

import pytest

from sentinel import automation_supervisor as supervisor, supervisor_io, schema
from sentinel.automation import store
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg


@pytest.fixture(autouse=True)
def reviewed_shadow_attempt_binding(monkeypatch):
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'2'*64)
    monkeypatch.setenv('SENTINEL_DATABASE_URL', 'postgresql://qualification/sentinel')


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
    store.register_instance(conn, instance_id='bounded-observer', state='RECOVER_CALLBACK',
                            callback_deadline_seconds=900)
    conn.execute('LOCK TABLE sentinel_automation_service_instances IN ACCESS EXCLUSIVE MODE')
    started = time.monotonic()
    with pytest.raises((TimeoutError, RuntimeError), match='budget|timeout'):
        supervisor._snapshot(conn.info.dsn, 'bounded-observer')
    assert time.monotonic() - started < 3
    conn.rollback()
    first = supervisor._snapshot(conn.info.dsn, 'bounded-observer')
    assert first[0] == 'RECOVER_CALLBACK' and first[1] >= 0 and first[2].tzinfo
    store.register_instance(conn, instance_id='bounded-observer', state='RECOVER_CALLBACK',
                            callback_deadline_seconds=900)
    second = supervisor._snapshot(conn.info.dsn, 'bounded-observer')
    assert second[2] > first[2]


def test_warm_watchdog_connection_is_reused_and_replaced_after_lock(conn, monkeypatch):
    schema.ensure_schema(conn)
    holder = 'warm-watchdog'
    store.register_instance(conn, instance_id=holder, state='RECOVER_CALLBACK',
                            callback_deadline_seconds=900)
    connects = multiprocessing.get_context('fork').RawValue('i', 0)
    connect = supervisor.feed_store.connect

    def counted_connect(*args, **kwargs):
        connects.value += 1
        return connect(*args, **kwargs)

    monkeypatch.setattr(supervisor.feed_store, 'connect', counted_connect)
    reader = supervisor.SnapshotReader(conn.info.dsn)
    try:
        first = reader.read(conn.info.dsn, holder)
        pid = reader.process.pid
        store.register_instance(conn, instance_id=holder, state='RECOVER_CALLBACK',
                                callback_deadline_seconds=900)
        second = reader.read(conn.info.dsn, holder)
        assert second.invocation > first.invocation
        assert reader.process.pid == pid
        assert connects.value == 1

        conn.execute('LOCK TABLE sentinel_automation_service_instances IN ACCESS EXCLUSIVE MODE')
        started = time.monotonic()
        try:
            with pytest.raises((TimeoutError, supervisor_io.DependencyError), match='timeout|timed out'):
                reader.read(conn.info.dsn, holder)
        finally:
            conn.rollback()
        assert time.monotonic() - started < 1.5
        assert reader.stage.value == 2
        assert reader.process is None
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert reader.read(conn.info.dsn, holder).invocation == second.invocation
        assert connects.value == 2
    finally:
        reader.close()


def test_warm_watchdog_drops_unresponsive_reader_before_next_observation(monkeypatch):
    monkeypatch.setattr(supervisor, 'SNAPSHOT_SECONDS', .18)
    context = multiprocessing.get_context('fork')
    reads = context.RawValue('i', 0)
    monkeypatch.setattr(supervisor.feed_store, 'connect', lambda *a, **k: SimpleNamespace(close=lambda: None))

    def query(_conn, _holder, stage):
        reads.value += 1
        stage.value = 2
        if reads.value == 1:
            time.sleep(10)
        return supervisor.InstanceSnapshot('fresh', 0.)

    monkeypatch.setattr(supervisor, '_query_snapshot', query)
    reader = supervisor.SnapshotReader('test-db')
    try:
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            reader.read('test-db', 'holder')
        assert time.monotonic() - started < .7
        assert reader.process is None
        assert reader.read('test-db', 'holder').state == 'fresh'
        assert reads.value == 2
    finally:
        reader.close()


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


@pytest.fixture
def shadow_arming(tmp_path, monkeypatch):
    from sentinel import shadow_supervisor as shadow
    monkeypatch.setattr(shadow, 'LATCH_FILE', tmp_path / 'critical.json')
    monkeypatch.setattr(shadow, 'HEARTBEAT_FILE', tmp_path / 'heartbeat')
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-arming-fixture-' * 3)
    monkeypatch.setattr(shadow.ShadowServiceConfig, 'from_env', lambda: SimpleNamespace(poll_seconds=0))
    monkeypatch.setattr(shadow, '_touch', lambda: None)
    monkeypatch.setattr(supervisor_io, 'report', lambda *a, **k: None)
    handlers = {}
    monkeypatch.setattr(shadow.signal, 'signal', lambda number, handler: handlers.update({number: handler}))

    observe = supervisor_io.run
    observations = []

    def bounded(function, *args, **kwargs):
        if function in (shadow._arm_worker, shadow._retry_arm_worker):
            observations.append((function, shadow._STATUS_INCARNATION, kwargs['timeout']))
            kwargs['timeout'] = .5
        return observe(function, *args, **kwargs)

    monkeypatch.setattr(supervisor_io, 'run', bounded)
    return shadow, handlers, observations


def test_worker_arming_timeout_never_launches(shadow_arming, monkeypatch):
    shadow, _, observations = shadow_arming
    monkeypatch.setattr(shadow, '_arm_worker', lambda *a: time.sleep(30))
    monkeypatch.setattr(shadow, 'time', SimpleNamespace(sleep=lambda _: None))
    monkeypatch.setattr(shadow.subprocess, 'Popen', lambda *a, **k: pytest.fail('worker launched'))
    assert shadow.run() == shadow.EXIT_REFUSED
    assert [item[0] for item in observations] == [shadow._arm_worker, shadow._retry_arm_worker]
    assert [item[2] for item in observations] == [2, 2]


def test_transient_admission_lock_timeout_recovers_in_same_supervisor(shadow_arming, tmp_path, monkeypatch):
    import fcntl
    from sentinel import shadow_drain

    shadow, handlers, observations = shadow_arming
    helper_pid = multiprocessing.get_context('fork').RawValue('i', 0)
    arm = shadow._arm_worker

    def record_helper(pid):
        helper_pid.value = os.getpid()
        return arm(pid)

    monkeypatch.setattr(shadow, '_arm_worker', record_helper)
    starts = []

    def spawn(*args, **kwargs):
        assert kwargs['pass_fds']
        marker = shadow.restart_recovery.decode_pending(json.loads(shadow._pending_file().read_bytes()))
        assert marker['supervisor_pid'] == os.getpid()
        starts.append(shadow._STATUS_INCARNATION)
        handlers[shadow.signal.SIGTERM]()
        return SimpleNamespace(poll=lambda: 0)

    monkeypatch.setattr(shadow.subprocess, 'Popen', spawn)
    with (tmp_path / shadow_drain.LOCK_NAME).open('w+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        def release(seconds):
            assert seconds == 1
            assert not starts and not shadow._pending_file().exists()
            assert helper_pid.value > 0
            with pytest.raises(ProcessLookupError):
                os.kill(helper_pid.value, 0)
            fcntl.flock(lock, fcntl.LOCK_UN)

        monkeypatch.setattr(shadow, 'time', SimpleNamespace(monotonic=time.monotonic, sleep=release))
        assert shadow.run() == 0

    assert len(starts) == 1 and not shadow._pending_file().exists()
    assert observations == [(record_helper, starts[0], 2), (shadow._retry_arm_worker, starts[0], 2)]


def test_timeout_after_durable_arm_preserves_marker_without_launch(shadow_arming, monkeypatch):
    shadow, _, observations = shadow_arming
    write_marker = shadow._write_marker
    writes = multiprocessing.get_context('fork').RawValue('i', 0)
    retained = []

    def stall_after_sync(path, payload):
        writes.value += 1
        write_marker(path, payload)
        time.sleep(30)

    def record_retained(seconds):
        assert seconds == 1
        retained.append(shadow._pending_file().read_bytes())

    monkeypatch.setattr(shadow, '_write_marker', stall_after_sync)
    monkeypatch.setattr(shadow, 'time', SimpleNamespace(sleep=record_retained))
    monkeypatch.setattr(shadow.subprocess, 'Popen', lambda *a, **k: pytest.fail('worker launched'))
    assert shadow.run() == shadow.EXIT_REFUSED
    assert [item[0] for item in observations] == [shadow._arm_worker, shadow._retry_arm_worker]
    assert writes.value == 1
    assert shadow._pending_file().read_bytes() == retained[0]
    shadow.restart_recovery.decode_pending(json.loads(retained[0]))


@pytest.mark.parametrize('boundary', ['dangling-critical', 'read-error', 'shutdown'])
def test_arming_retry_refuses_uncertain_state_and_respects_shutdown(shadow_arming, boundary, monkeypatch):
    shadow, handlers, observations = shadow_arming
    arm = shadow._arm_worker
    monkeypatch.setattr(shadow, '_arm_worker', lambda *a: time.sleep(30))

    def change_state(seconds):
        assert seconds == 1
        monkeypatch.setattr(shadow, '_arm_worker', arm)
        if boundary == 'dangling-critical':
            shadow.LATCH_FILE.symlink_to('missing')
        elif boundary == 'read-error':
            path_type = type(shadow.LATCH_FILE)
            lstat = path_type.lstat

            def unreadable(path, *args, **kwargs):
                if path == shadow.LATCH_FILE:
                    raise PermissionError('unreadable marker')
                return lstat(path, *args, **kwargs)

            monkeypatch.setattr(path_type, 'lstat', unreadable)
        else:
            handlers[shadow.signal.SIGTERM]()

    monkeypatch.setattr(shadow, 'time', SimpleNamespace(sleep=change_state))
    monkeypatch.setattr(shadow.subprocess, 'Popen', lambda *a, **k: pytest.fail('worker launched'))
    assert shadow.run() == (0 if boundary == 'shutdown' else shadow.EXIT_REFUSED)
    assert len(observations) == (1 if boundary == 'shutdown' else 2)
    assert not shadow._pending_file().exists()


@pytest.mark.parametrize('first_code', [0, 10, 11, 12, 13])
def test_recoverable_worker_outcome_clears_guard_before_next_attempt(tmp_path, monkeypatch, first_code):
    from sentinel import shadow_supervisor as shadow
    assert first_code in {0, shadow.EXIT_RETRY, shadow.EXIT_WAITING, shadow.EXIT_AVAILABILITY,
                          shadow.EXIT_DEPENDENCY_UNAVAILABLE}
    monkeypatch.setattr(shadow, 'LATCH_FILE', tmp_path / 'critical.json')
    monkeypatch.setattr(shadow.ShadowServiceConfig, 'from_env',
                        lambda: SimpleNamespace(poll_seconds=0))
    monkeypatch.setattr(shadow.signal, 'signal', lambda *a: None)
    for name in ('_touch', '_source_recovery_alert', '_dependency_retry_alert', '_semantic_retry_alert', '_report_latch'):
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
        pid = 1
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
    monkeypatch.setattr(shadow.shadow_worker_liveness, 'record', lambda *args: None)
    if stop_by_signal:
        # Stop on the next supervisor heartbeat, after assigning active child.
        def heartbeat():
            if starts:
                handlers[shadow.signal.SIGTERM]()
        monkeypatch.setattr(shadow, '_touch', heartbeat)
    assert shadow.run() == (91 if refusal_races_termination else 0)
    assert shadow._pending_file().exists() is refusal_races_termination
    assert shadow.LATCH_FILE.exists() is refusal_races_termination
