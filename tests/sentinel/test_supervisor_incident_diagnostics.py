"""Causal diagnostics survive the real process boundary without private values."""
import errno
import fcntl
import json
import os
import sys
import time
from types import SimpleNamespace

import pytest

from sentinel import supervisor_io

CANARY = 'synthetic-private-password-never-emit'


def private_failure():
    raise OSError(errno.EIO, CANARY, '/private/'+CANARY)


def test_original_child_type_survives_real_ipc_without_exception_values():
    with pytest.raises(supervisor_io.DependencyError) as caught:
        supervisor_io.run(private_failure)
    error = caught.value
    assert isinstance(error, RuntimeError)
    assert error.diagnostic == {'exception_type': 'OSError', 'errno': errno.EIO, 'sqlstate': None}
    assert CANARY not in str(error) and CANARY not in repr(error.diagnostic)


def test_actual_statement_cancellation_retains_safe_sqlstate():
    from psycopg.errors import QueryCanceled
    def cancelled():
        raise QueryCanceled(CANARY)
    with pytest.raises(supervisor_io.DependencyError, match='timeout') as caught:
        supervisor_io.run(cancelled)
    assert caught.value.diagnostic == {'exception_type': 'QueryCanceled', 'errno': None, 'sqlstate': '57014'}
    assert CANARY not in str(caught.value)


@pytest.mark.parametrize('diagnostic', [
    CANARY, {'exception_type': CANARY},
    {'exception_type': 'OSError', 'errno': True, 'sqlstate': None},
    {'exception_type': 'OSError', 'errno': 4096, 'sqlstate': None},
    {'exception_type': 'OSError', 'errno': None, 'sqlstate': CANARY},
    {'exception_type': 'OSError', 'errno': None, 'sqlstate': None, 'message': CANARY},
])
def test_malformed_child_diagnostic_is_refused_without_echo(diagnostic):
    with pytest.raises(RuntimeError, match='malformed') as caught:
        supervisor_io.DependencyError(diagnostic)
    assert CANARY not in str(caught.value)


def test_malformed_real_ipc_is_refused_and_child_reaped(monkeypatch):
    def malformed(channel, *args):
        channel.send(('error', {'exception_type': 'OSError', 'errno': None,
                                'sqlstate': None, 'message': CANARY}))
        channel.close()
    monkeypatch.setattr(supervisor_io, '_call', malformed)
    with pytest.raises(RuntimeError, match='malformed'):
        supervisor_io.run(lambda: None)


def _refuses_extra_private_field():
    value = {'exception_type': 'OSError', 'errno': None, 'sqlstate': None, 'message': CANARY}
    try:
        supervisor_io.DependencyError(value)
    except RuntimeError:
        return
    raise AssertionError('private diagnostic field admitted')


def test_removed_closed_envelope_guard_is_detected(monkeypatch):
    _refuses_extra_private_field()
    monkeypatch.setattr(supervisor_io, '_validate_diagnostic', lambda value: dict(value))
    with pytest.raises(AssertionError, match='private diagnostic field admitted'):
        _refuses_extra_private_field()


@pytest.fixture
def pipe(monkeypatch):
    reader, writer = os.pipe()
    stream = os.fdopen(os.dup(writer), 'w')
    monkeypatch.setattr(sys, 'stderr', stream)
    monkeypatch.setattr(supervisor_io, 'run', lambda *a, **k: pytest.fail('diagnostic forked'))
    try:
        yield reader, writer, stream
    finally:
        stream.close()
        os.close(reader)
        os.close(writer)


def test_pipe_event_is_one_atomic_write_without_fork_or_inherited_flag_change(pipe, monkeypatch):
    reader, writer, stream = pipe
    monkeypatch.setattr(sys, 'stderr', stream)
    before = fcntl.fcntl(writer, fcntl.F_GETFL)
    writes = []
    original = os.write
    def write(descriptor, raw):
        writes.append(len(raw))
        return original(descriptor, raw)
    monkeypatch.setattr(os, 'write', write)
    assert supervisor_io.report_event('shadow', 'ARM', 'FAILED',
        error=OSError(errno.EIO, CANARY), context={'incarnation': 'a'*32, 'attempt': 'b'*32})
    value = os.read(reader, 4096)
    assert CANARY.encode() not in value
    event = json.loads(value)
    assert event['stage'] == 'ARM' and event['error']['exception_type'] == 'OSError'
    assert writes == [len(value)] and len(value) <= os.fpathconf(writer, 'PC_PIPE_BUF')
    assert before == fcntl.fcntl(writer, fcntl.F_GETFL)


def test_full_pipe_returns_false_without_wait_fork_or_inherited_flag_change(pipe, monkeypatch):
    reader, writer, stream = pipe
    monkeypatch.setattr(sys, 'stderr', stream)
    os.set_blocking(writer, False)
    try:
        while True:
            os.write(writer, b'x'*4096)
    except BlockingIOError:
        pass
    os.set_blocking(writer, True)
    before = fcntl.fcntl(writer, fcntl.F_GETFL)
    started = time.monotonic()
    assert supervisor_io.report_event('automation', 'IDLE_STALL', 'TERMINATING', immediate=True) is False
    assert time.monotonic()-started < .1
    assert fcntl.fcntl(writer, fcntl.F_GETFL) == before


def test_pretermination_event_never_falls_back_when_pipe_unavailable(monkeypatch):
    monkeypatch.setattr(supervisor_io, '_pipe_report', lambda _: None)
    monkeypatch.setattr(supervisor_io, 'report', lambda *a, **k: pytest.fail('termination used fallback'))
    assert supervisor_io.report_event('automation', 'IDLE_STALL', 'TERMINATING', immediate=True) is False


def test_broken_pipe_returns_false_without_fork_or_wait(monkeypatch):
    reader, writer = os.pipe()
    os.close(reader)
    try:
        with os.fdopen(os.dup(writer), 'w') as stream:
            monkeypatch.setattr(sys, 'stderr', stream)
            monkeypatch.setattr(supervisor_io, 'run', lambda *a, **k: pytest.fail('broken sink forked'))
            started = time.monotonic()
            assert supervisor_io.report_event('shadow', 'ARM', 'FAILED') is False
            assert time.monotonic()-started < .1
    finally:
        os.close(writer)


def test_arm_result_cannot_wait_on_a_nonpipe_diagnostic_fallback(monkeypatch):
    from sentinel import shadow_drain, shadow_supervisor as shadow
    monkeypatch.setattr(shadow_drain, 'arm_or_drain', lambda path, database, incarnation, arm: arm())
    monkeypatch.setattr(shadow, '_write_marker', lambda *a: None)
    monkeypatch.setattr(shadow.restart_recovery, 'make_pending', lambda *a: {})
    monkeypatch.setattr(supervisor_io, '_pipe_report', lambda _: None)
    monkeypatch.setattr(supervisor_io, 'run', lambda *a, **k: pytest.fail('arming diagnostic forked'))
    assert len(shadow._arm_worker(123)) == 32


def test_removed_immediate_arm_emission_guard_is_detected(monkeypatch):
    original = supervisor_io.report_event
    def fallback(*args, **kwargs):
        return original(*args, **{**kwargs, 'immediate': False})
    monkeypatch.setattr(supervisor_io, 'report_event', fallback)
    with pytest.raises(pytest.fail.Exception, match='arming diagnostic forked'):
        test_arm_result_cannot_wait_on_a_nonpipe_diagnostic_fallback(monkeypatch)


def test_event_rejects_arbitrary_or_nonfinite_context(pipe, monkeypatch):
    reader, _writer, stream = pipe
    monkeypatch.setattr(sys, 'stderr', stream)
    assert supervisor_io.report_event('shadow', 'ARM', 'FAILED', context={'message': CANARY}) is False
    assert supervisor_io.report_event('shadow', 'ARM', 'FAILED', context={'started': float('nan')}) is False
    os.set_blocking(reader, False)
    with pytest.raises(BlockingIOError):
        os.read(reader, 4096)


def test_unselected_feed_proof_context_is_refused_without_output(pipe, monkeypatch):
    reader, _writer, stream = pipe
    monkeypatch.setattr(sys, 'stderr', stream)
    context = {'snapshot_sha256': 'a'*64, 'candidate_id': '00000000-0000-0000-0000-000000000001',
               'backend_pid': 123, 'role': 'VERIFIER'}
    assert supervisor_io.report_event('feed', 'SNAPSHOT_VERIFY_BEGIN', 'BEGIN', context=context, immediate=True) is False
    os.set_blocking(reader, False)
    with pytest.raises(BlockingIOError):
        os.read(reader, 4096)


@pytest.mark.parametrize('stage', ['ARM', 'ACTIVE_PROOF', 'SPAWN', 'ACK'])
def test_shadow_failure_stage_does_not_change_original_refusal_or_cleanup(monkeypatch, stage):
    from sentinel import shadow_supervisor as shadow
    events = []
    monkeypatch.setattr(shadow.ShadowServiceConfig, 'from_env', lambda: SimpleNamespace(poll_seconds=0))
    monkeypatch.setattr(shadow.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(shadow, '_Heartbeat', lambda: lambda: None)
    monkeypatch.setattr(shadow, '_terminate', lambda child: events.append(('REAP', child.pid)))
    monkeypatch.setattr(supervisor_io, 'report', lambda *a, **k: True)
    monkeypatch.setattr(supervisor_io, 'report_event', lambda component, name, outcome, **kwargs:
        events.append((name, outcome)) or True)
    def observe(function, *args, **kwargs):
        target = ('ARM' if function is shadow._arm_worker else
                  'ACTIVE_PROOF' if function is shadow.shadow_worker_liveness.record else
                  'ACK' if function is shadow._clear_worker else None)
        if target == stage:
            raise supervisor_io.DependencyError({'exception_type': 'OSError', 'errno': errno.EIO, 'sqlstate': None})
        return 'a'*32 if target == 'ARM' else False if function is shadow._latch_exists else None
    monkeypatch.setattr(supervisor_io, 'run', observe)
    child = SimpleNamespace(pid=123, poll=lambda: None if stage == 'ACTIVE_PROOF' else 0)
    def spawn(*a, **k):
        if stage == 'SPAWN':
            raise OSError(errno.EAGAIN, CANARY)
        return child
    monkeypatch.setattr(shadow.subprocess, 'Popen', spawn)
    if stage == 'SPAWN':
        with pytest.raises(OSError):
            shadow._run_owned(456)
    else:
        assert shadow._run_owned(456) == shadow.EXIT_REFUSED
    assert (stage, 'FAILED') in events
    assert (('REAP', 123) in events) is (stage == 'ACTIVE_PROOF')


@pytest.mark.parametrize('confirmation_fails', [False, True])
def test_automation_records_confirmation_and_exact_facts_before_termination(monkeypatch, confirmation_fails):
    from sentinel import automation_supervisor as automation
    class Finished(BaseException):
        pass
    events = []
    monkeypatch.setattr(automation.SentinelConfig, 'from_env', lambda: SimpleNamespace(database_url='private'))
    monkeypatch.setattr(automation, 'config_from_env', lambda: SimpleNamespace(lease_seconds=12, callback_deadline_seconds=900))
    monkeypatch.setenv('SENTINEL_AUTOMATION_SUPERVISOR_STARTUP_GRACE_SECONDS', '0')
    monkeypatch.setattr(automation.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(automation, 'time', SimpleNamespace(monotonic=lambda: 1000.0,
        sleep=lambda seconds: (_ for _ in ()).throw(Finished())))
    child = SimpleNamespace(pid=123, poll=lambda: None)
    monkeypatch.setattr(automation, '_spawn', lambda holder: child)
    monkeypatch.setattr(automation, '_terminate', lambda child: events.append(('terminate', child.pid)))
    monkeypatch.setattr(supervisor_io, 'report', lambda *a, **k: True)
    monkeypatch.setattr(supervisor_io, 'report_event', lambda component, stage, outcome, **kwargs:
        events.append(('diagnostic', stage, outcome, kwargs)) or True)
    readings = iter([automation.InstanceSnapshot('WAITING', 13.0),
                     automation.InstanceSnapshot('WAITING', 13.5)])
    def observe(*args):
        events.append(('probe',))
        if confirmation_fails and sum(event[0] == 'probe' for event in events) == 2:
            raise supervisor_io.DependencyError({'exception_type': 'QueryCanceled', 'errno': None, 'sqlstate': '57014'})
        return next(readings)
    monkeypatch.setattr(automation, '_snapshot', observe)
    with pytest.raises(Finished):
        automation.main()
    assert sum(event[0] == 'probe' for event in events) == 2
    diagnostic = next(event for event in events if event[0] == 'diagnostic')
    assert diagnostic[1:3] == (('CONFIRMATION', 'FAILED') if confirmation_fails else ('IDLE_STALL', 'TERMINATING'))
    if confirmation_fails:
        assert not any(event[0] == 'terminate' for event in events)
        assert diagnostic[3]['error'].diagnostic['exception_type'] == 'QueryCanceled'
    else:
        assert events.index(diagnostic) < events.index(('terminate', 123))
        assert diagnostic[3]['immediate'] is True
        context = diagnostic[3]['context']
        assert {key: context[key] for key in ('child_pid', 'state', 'heartbeat_age_seconds', 'lease_seconds',
            'started', 'completed', 'decision_at', 'worker_started')} == {
                'child_pid': 123, 'state': 'WAITING', 'heartbeat_age_seconds': 13.5, 'lease_seconds': 12,
                'started': 1000.0, 'completed': 1000.0, 'decision_at': 1000.0, 'worker_started': 1000.0}
