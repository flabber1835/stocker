"""Safe parent failure evidence precedes unchanged immutable warning reuse."""
from datetime import datetime, timezone
import errno
import io
import json
import os
import sys
from threading import Event

import psycopg
import pytest

from sentinel import execution_collector as collector, supervisor_io
from tests.support.postgres import _EphemeralPostgres


CANARY = 'postgresql://fixture:PRIVATE-CANARY@private-host/private-account?token=PRIVATE-CANARY'


def wrapped(kind='QueryCanceled', state='57014', number=None):
    return supervisor_io.DependencyError(dict(exception_type=kind, errno=number, sqlstate=state))


@pytest.fixture
def pipe(monkeypatch):
    reader, writer = os.pipe()
    stream = os.fdopen(writer, 'w', buffering=1)
    previous = sys.stderr
    os.set_blocking(reader, False)
    try:
        yield reader, writer, stream
    finally:
        monkeypatch.setattr(sys, 'stderr', previous)
        stream.close()
        os.close(reader)


def read_record(reader):
    raw = os.read(reader, supervisor_io.MAX_RECORD_BYTES)
    assert raw.endswith(b'\n') and len(raw) <= supervisor_io.MAX_RECORD_BYTES
    assert CANARY.encode() not in raw
    value = json.loads(raw)
    assert set(value) == {'schema', 'kind', 'stage', 'observed_at', 'monotonic_at', 'error'}
    assert value['schema'] == 'sentinel.execution-collector-diagnostic/1'
    assert datetime.fromisoformat(value['observed_at']).utcoffset().total_seconds() == 0
    assert value['monotonic_at'] >= 0
    assert set(value['error']) == {'exception_type', 'errno', 'sqlstate'}
    return value


def test_wrapped_original_sqlstate_survives_immediate_pipe_diagnostic(pipe, monkeypatch):
    monkeypatch.setattr(sys, 'stderr', pipe[2])
    failures = collector._FailureDiagnostics()
    assert failures.failure('FILL', 'COLLECT_JOB', wrapped()) is True
    value = read_record(pipe[0])
    assert value['error'] == dict(exception_type='QueryCanceled', errno=None, sqlstate='57014'), (
        'original wrapped SQLSTATE/type was lost')


def test_removed_original_unwrapping_has_an_executed_falsifier(pipe, monkeypatch):
    monkeypatch.setattr(supervisor_io, 'error_diagnostic', lambda error:
        dict(exception_type=type(error).__name__, errno=None, sqlstate=None))
    with pytest.raises(AssertionError, match='original wrapped SQLSTATE/type was lost'):
        test_wrapped_original_sqlstate_survives_immediate_pipe_diagnostic(pipe, monkeypatch)


def test_private_exception_message_and_errno_are_separated(pipe, monkeypatch):
    monkeypatch.setattr(sys, 'stderr', pipe[2])
    error = OSError(errno.EIO, CANARY)
    assert collector._FailureDiagnostics().failure('ACCOUNT', 'COLLECT_JOB', error)
    assert read_record(pipe[0])['error'] == dict(exception_type='OSError', errno=errno.EIO, sqlstate=None)


def test_unknown_error_fields_are_refused_without_pipe_output(monkeypatch):
    sent = []
    monkeypatch.setattr(supervisor_io, '_pipe_report', lambda value: sent.append(value) or True)
    monkeypatch.setattr(supervisor_io, 'error_diagnostic', lambda error:
        dict(exception_type='OSError', errno=errno.EIO, sqlstate=None, message=CANARY))
    assert collector._FailureDiagnostics().failure('FILL', 'COLLECT_JOB', OSError()) is False, (
        'unreviewed diagnostic fields reached the pipe')
    assert sent == []


def test_removed_closed_error_validation_has_an_executed_privacy_falsifier(monkeypatch):
    monkeypatch.setattr(supervisor_io, '_validate_diagnostic', lambda value: value)
    with pytest.raises(AssertionError, match='unreviewed diagnostic fields reached'):
        test_unknown_error_fields_are_refused_without_pipe_output(monkeypatch)


def test_full_pipe_never_forks_and_later_genuine_failure_can_be_observed(pipe, monkeypatch):
    monkeypatch.setattr(sys, 'stderr', pipe[2])
    monkeypatch.setattr(supervisor_io, 'run', lambda *a, **k: pytest.fail('diagnostic forked a helper'))
    os.set_blocking(pipe[1], False)
    while True:
        try:
            os.write(pipe[1], b'x'*4096)
        except BlockingIOError:
            break
    failures = collector._FailureDiagnostics()
    assert failures.failure('FILL', 'COLLECT_JOB', wrapped()) is False
    while True:
        try:
            os.read(pipe[0], 65536)
        except BlockingIOError:
            break
    assert failures.failure('FILL', 'COLLECT_JOB', wrapped()) is True
    assert read_record(pipe[0])['error']['sqlstate'] == '57014'


@pytest.mark.parametrize('sink', ['regular', 'unavailable_fileno'])
def test_nonpipe_or_unavailable_destination_has_no_child_or_stdout_fallback(tmp_path, monkeypatch, capsys, sink):
    stream = (tmp_path/'stderr').open('w') if sink == 'regular' else io.StringIO()
    previous = sys.stderr
    monkeypatch.setattr(supervisor_io, 'run', lambda *a, **k: pytest.fail('fallback child was started'))
    monkeypatch.setattr(sys, 'stderr', stream)
    try:
        assert collector._FailureDiagnostics().failure('FILL', 'COLLECT_JOB', wrapped()) is False
        assert stream.tell() == 0
        assert capsys.readouterr().out == ''
    finally:
        monkeypatch.setattr(sys, 'stderr', previous)
        stream.close()


@pytest.mark.parametrize('kind,stage', [('BROKER', 'COLLECT_JOB'), ('FILL', 'PRIVATE_CANARY')])
def test_unselected_kind_or_stage_is_never_serialized(monkeypatch, kind, stage):
    monkeypatch.setattr(supervisor_io, '_pipe_report', lambda *_: pytest.fail('unselected record emitted'))
    assert collector._FailureDiagnostics().failure(kind, stage, ValueError(CANARY)) is False


@pytest.mark.parametrize('clock', [float('nan'), float('inf'), -1, True])
def test_invalid_monotonic_clock_is_not_diagnostic_evidence(monkeypatch, clock):
    monkeypatch.setattr(collector.time, 'monotonic', lambda: clock)
    monkeypatch.setattr(supervisor_io, '_pipe_report', lambda *_: pytest.fail('invalid clock emitted'))
    assert collector._FailureDiagnostics().failure('FILL', 'COLLECT_JOB', wrapped()) is False


def run_fill_failures(monkeypatch, tmp_path, outcomes, *, record=None):
    from sentinel import local_paper
    from sentinel.execution import fill_notifications
    from sentinel.feed.issuer_refresh import CONTACT_ENV
    monkeypatch.setattr(collector, 'HEARTBEAT', tmp_path/'heartbeat')
    monkeypatch.setattr(collector.signal, 'signal', lambda *_: None)
    monkeypatch.setattr(local_paper, 'enabled', lambda: False)
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
    monkeypatch.setenv(fill_notifications.SINCE_ENV, '2031-04-21T00:00:00+00:00')
    monkeypatch.setattr(fill_notifications, 'POLL_SECONDS', 0)
    monkeypatch.delenv(CONTACT_ENV, raising=False)
    monkeypatch.delenv('SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY', raising=False)
    stop = Event()
    stop.wait = lambda seconds: stop.is_set()
    events, received = [], []
    def send(value):
        events.append(('diagnostic', json.loads(value)))
        return True
    monkeypatch.setattr(supervisor_io, '_pipe_report', send)
    monkeypatch.setattr(supervisor_io, 'report', lambda value: events.append(('legacy', value)))
    choices = iter(enumerate(outcomes))
    def runner(operation, *args, **options):
        assert options['start_method'] == 'spawn'
        if operation is collector.record_stall:
            assert options['timeout'] == 5
            received.append(args)
            events.append(('record', args))
            return record(*args) if record is not None else None
        assert operation is collector.collect_once and args == ('FILL',)
        assert options['timeout'] == 30
        index, value = next(choices)
        if index == len(outcomes)-1:
            stop.set()
        if isinstance(value, BaseException):
            raise value
        return value
    assert collector.run(stopped=stop, runner=runner, clock=lambda: 0) == 0
    return events, received


def test_primary_cause_precedes_legacy_log_and_unchanged_failure_record(monkeypatch, tmp_path):
    events, received = run_fill_failures(monkeypatch, tmp_path, [wrapped()])
    assert [kind for kind, _ in events] == ['diagnostic', 'legacy', 'record']
    assert events[0][1]['stage'] == 'COLLECT_JOB' and events[0][1]['error']['sqlstate'] == '57014'
    assert received == [('FILL', 'DependencyError')]
    assert CANARY not in json.dumps(events)


def test_secondary_recording_failure_cannot_replace_the_original_cause(monkeypatch, tmp_path):
    def failed_record(*args):
        raise wrapped('ConnectionFailure', '08006')
    events, _ = run_fill_failures(monkeypatch, tmp_path, [wrapped()], record=failed_record)
    records = [value for kind, value in events if kind == 'diagnostic']
    assert [(value['stage'], value['error']['sqlstate']) for value in records] == [
        ('COLLECT_JOB', '57014'), ('FAILURE_RECORD', '08006')]
    assert records[0]['observed_at'] <= records[1]['observed_at']


def test_repeated_failures_do_not_flood_or_clear_without_collected_recovery(monkeypatch, tmp_path):
    outcomes = [wrapped(), wrapped(), None, 'REFUSED', wrapped(), 'COLLECTED', wrapped()]
    events, received = run_fill_failures(monkeypatch, tmp_path, outcomes)
    assert len([value for kind, value in events if kind == 'diagnostic']) == 2
    assert len(received) == 4, 'diagnostic coalescing must not remove existing failure recording'


@pytest.mark.parametrize('result,clears', [
    ('REFUSED', False), (None, False), ({'status': 'CACHED'}, False),
    ({'status': 'DEFERRED'}, False), ({'status': 'REFRESHED'}, True),
])
def test_issuer_recovery_requires_its_actual_positive_result(monkeypatch, result, clears):
    sent = []
    monkeypatch.setattr(supervisor_io, '_pipe_report', lambda value: sent.append(value) or True)
    diagnostics = collector._FailureDiagnostics()
    assert diagnostics.failure('ISSUER', 'COLLECT_JOB', wrapped()) is True
    diagnostics.collected('ISSUER', result)
    assert diagnostics.failure('ISSUER', 'COLLECT_JOB', wrapped()) is clears
    assert len(sent) == (2 if clears else 1)


@pytest.fixture
def outbox_connection():
    from sentinel import schema
    server = _EphemeralPostgres()
    server.start()
    conn = psycopg.connect(server.sync_dsn)
    statements = [statement for statement in schema.DDL
                  if statement.startswith('CREATE TABLE IF NOT EXISTS sentinel_alert_outbox (')]
    assert len(statements) == 1
    conn.execute(statements[0])
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()
        server.stop()


def test_new_original_causes_do_not_rewrite_existing_real_outbox_occurrence(
        monkeypatch, tmp_path, outbox_connection):
    from sentinel.feed import store
    conn = outbox_connection
    monkeypatch.setenv('SENTINEL_DATABASE_URL', conn.info.dsn)
    monkeypatch.setattr(store, 'connect', lambda *a, **k: psycopg.connect(conn.info.dsn))
    collector.record_stall('FILL', 'DependencyError')
    before = conn.execute('SELECT * FROM sentinel_alert_outbox').fetchall()
    conn.rollback()
    events, received = run_fill_failures(monkeypatch, tmp_path,
        [wrapped(), wrapped('ConnectionFailure', '08006')], record=collector.record_stall)
    after = conn.execute('SELECT * FROM sentinel_alert_outbox').fetchall()
    assert before == after and len(after) == 1
    assert received == [('FILL', 'DependencyError'), ('FILL', 'DependencyError')]
    records = [value for kind, value in events if kind == 'diagnostic']
    assert [value['error']['sqlstate'] for value in records] == ['57014', '08006']
    assert all(value['stage'] == 'COLLECT_JOB' for value in records)
