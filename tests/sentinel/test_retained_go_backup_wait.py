"""Foreground retained GO waits without granting metadata WAL authority."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sentinel import backup_runtime_authority as backup, retained_go, shadow_budget
from sentinel.feed import rolling_jobs


@pytest.fixture
def process(monkeypatch):
    now = [datetime(2026, 10, 8, 9, 30, tzinfo=timezone.utc)]
    context = dict(observation_id='primary', starting_cash='50000', runtime={
        'validated_source_identity_sha256': 'a'*64,
        'validated_shadow_config_sha256': 'b'*64,
        'validated_data_publication_sha256': 'c'*64})
    class Connection:
        pending = False
        rollbacks = 0
        def rollback(self):
            self.pending = False
            self.rollbacks += 1
    conn = Connection()
    waits = []
    def sleep(seconds):
        assert not conn.pending, 'GO slept with an open transaction'
        assert 0 <= seconds <= 10
        waits.append(seconds)
        now[0] += timedelta(seconds=seconds)
    monkeypatch.setattr(shadow_budget, 'now', lambda: now[0])
    monkeypatch.setattr(retained_go.time, 'sleep', sleep)
    return conn, now, context, waits


def test_metadata_wait_recovers_with_exact_deadline_and_no_backup_creation(process, monkeypatch):
    conn, now, context, waits = process
    deadline = now[0]+timedelta(seconds=25)
    calls = []
    result = object()
    def advance(connection, **kw):
        assert connection is conn
        calls.append(kw)
        conn.pending = True
        if len(calls) <= 2:
            # Use the actual classifier. Backup history is not a WAL segment.
            backup._require_segment_frontier('000000010000001000000052.00000248.backup',
                segment_size=16*1024*1024, operation='operational publication preflight')
        return result
    monkeypatch.setattr(retained_go.rolling_runtime, 'service_advance', advance)
    assert retained_go._advance_with_backup_wait(conn, target_session='2026-10-07',
        context=context, deadline=deadline) is result
    assert waits == [10., 10.] and conn.rollbacks == 2
    assert len(calls) == 3 and all(call == dict(through='2026-10-07',
        observation_id='primary', starting_cash='50000', acquisition_deadline=deadline) for call in calls)


def test_persistent_unavailability_exhausts_original_cutoff(process, monkeypatch):
    conn, now, context, waits = process
    deadline = now[0]+timedelta(seconds=15)
    calls = []
    def unavailable(connection, **kw):
        calls.append(kw)
        conn.pending = True
        raise backup.BackupRuntimeUnavailable('missing media remains fenced')
    monkeypatch.setattr(retained_go.rolling_runtime, 'service_advance', unavailable)
    with pytest.raises(rolling_jobs.JobDeadlineExceeded):
        retained_go._advance_with_backup_wait(conn, target_session='2026-10-07',
            context=context, deadline=deadline)
    assert waits == [10., 5.] and len(calls) == 2 and conn.rollbacks == 2
    assert now[0] == deadline and all(call['acquisition_deadline'] == deadline for call in calls)


@pytest.mark.parametrize('error', [backup.BackupRuntimeRefused('bad checksum'),
    backup.BackupHorizonExceeded('renewal required'), RuntimeError('foreign lineage')])
def test_structural_refusal_and_horizon_are_not_reclassified_as_availability(process, monkeypatch, error):
    conn, now, context, waits = process
    def refused(*a, **kw):
        raise error
    monkeypatch.setattr(retained_go.rolling_runtime, 'service_advance', refused)
    with pytest.raises(type(error)) as caught:
        retained_go._advance_with_backup_wait(conn, target_session='2026-10-07',
            context=context, deadline=now[0]+timedelta(seconds=60))
    assert caught.value is error and not waits


@pytest.mark.parametrize('same_session', [False, True])
def test_public_retained_dispatch_waits_for_continuation_and_lost_ack(process, monkeypatch, same_session):
    conn, now, context, waits = process
    deadline = now[0]+timedelta(seconds=30)
    runtime = context['runtime']
    checkpoint = SimpleNamespace(runtime_identity=runtime)
    frontier = ['2026-10-07' if same_session else '2026-10-06']
    attested = [None]
    calls = []
    monkeypatch.setattr(retained_go.origin, 'read', lambda c: checkpoint)
    monkeypatch.setattr(retained_go.runtime_admission, 'current_context', lambda **kw: context)
    monkeypatch.setattr(retained_go.runtime_admission, '_require_context', lambda *a: None)
    monkeypatch.setattr(retained_go.runtime_admission, 'process_binding', lambda value: value)
    monkeypatch.setattr(retained_go.rolling_runtime, '_closure',
                        lambda *a: (SimpleNamespace(session=frontier[0]), None, None, attested[0], None))
    def advance(c, **kw):
        calls.append(kw)
        if len(calls) == 1:
            c.pending = True
            raise backup.BackupRuntimeUnavailable('waiting for archived segment')
        frontier[0] = '2026-10-07'
        attested[0] = object()
        return SimpleNamespace(session=frontier[0])
    monkeypatch.setattr(retained_go.rolling_runtime, 'service_advance', advance)
    @contextmanager
    def pinned(c):
        yield object()
    monkeypatch.setattr(retained_go.inputs, 'pinned', pinned)
    monkeypatch.setattr(retained_go.rolling_runtime, '_current', lambda *a: None)
    monkeypatch.setattr(retained_go.inputs, 'prepare', lambda *a, **kw: pytest.fail('retained GO created a fresh book'))
    assert retained_go.prepare(conn,target_session='2026-10-07',absolute_deadline=deadline)['status'] == 'RETAINED_STATE_VERIFIED'
    assert len(calls) == 2 and waits == [10.] and attested[0] is not None


def test_expired_budget_never_invokes_a_transition(process, monkeypatch):
    conn, now, context, waits = process
    monkeypatch.setattr(retained_go.rolling_runtime, 'service_advance',
                        lambda *a, **kw: pytest.fail('expired GO mutated state'))
    with pytest.raises(rolling_jobs.JobDeadlineExceeded):
        retained_go._advance_with_backup_wait(conn,target_session='2026-10-07',
            context=context,deadline=now[0])
    assert not waits
