"""Native writer priority survives supervised IPC without creating or renewing proof."""
from datetime import timedelta
from functools import partial
import inspect
import time

import psycopg
import pytest

from sentinel import snapshot_scan_admission as gate
from sentinel.execution.journal import WRITER_LOCK_KEY
from sentinel.panel import authority_reader, model, observer_failure, verification_service as verifier
from tests.sentinel.test_observer_failure_diagnostics import NOW, positive
from tests.sentinel.test_rolling_snapshot_publisher import pg  # noqa: F401


def _native_observation(database_url, _paper, _key, *, observed):
    def measure():
        with psycopg.connect(database_url) as conn, gate.discretionary(), gate.admitted(conn):
            return positive(observed)
    return observer_failure.capture(measure)


def wait_until(predicate):
    deadline = time.monotonic()+20
    while not predicate() and time.monotonic()<deadline:
        time.sleep(.01)
    assert predicate()


def test_native_writer_yield_through_spawn_preserves_subject_rows_then_waits_until_release(pg, monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','private-yield-fixture-key-'*3)
    tick = [0]
    wall = lambda: NOW+timedelta(seconds=tick[0])
    key = 'a'*64
    slot = verifier._ObserverSlot()
    reader = authority_reader.Reader(
        clock=lambda: tick[0], wall_clock=wall, execution_slot=slot, retain_failed_attempt=True,
        evidence_reader=lambda *_: key, observer=partial(_native_observation, observed=NOW+timedelta(seconds=340)))
    old = NOW-timedelta(seconds=301)
    reader.answer = key, positive(old), None, NOW
    with psycopg.connect(pg.sync_dsn, autocommit=True) as writer:
        writer.execute('SELECT pg_advisory_lock(%s)', (WRITER_LOCK_KEY,))
        try:
            reader.read(pg.sync_dsn, include_paper=False, scan_occupied=True)
            wait_until(lambda: reader.attempt_state()['outcome']=='DEFERRED')
            initial = reader.attempt_state()
            assert initial['diagnostic']['code'] == 'FOREGROUND_BUSY'
            assert initial['latched_failure'] is None and reader.failure is None
            assert not slot.busy() and reader.pending_failed_attempt() is None
            original_deadline = reader.attempt_deadline
            same = reader.read(pg.sync_dsn, include_paper=False, scan_occupied=True)
            assert same[0][0].status == model.OK and same[0][0].as_of == old
            tick[0] = 300  # prior 600-second positive proof expired one second ago
            waiting = reader.read(pg.sync_dsn, include_paper=False, scan_occupied=True)
            assert not waiting[3]
            for row in waiting[0]:
                assert row.status == model.WARN and row.valid_until == original_deadline
            assert waiting[0][0].recovery.phase == 'FINANCIAL_VERIFICATION'
            encoded, _ = verifier.snapshot(reader, waiting, scope='SHADOW', now=wall())
            assert encoded['observed_at'] == NOW.isoformat() and encoded['valid_until'] == original_deadline.isoformat()
            assert reader.attempt_state()['attempt_id'] == initial['attempt_id']
        finally:
            writer.execute('SELECT pg_advisory_unlock(%s)', (WRITER_LOCK_KEY,))
            tick[0] = 340
            reader.read(pg.sync_dsn, include_paper=False)
            wait_until(lambda: reader.pending is None)
        completed = reader.read(pg.sync_dsn, include_paper=False, allow_start=False)
        assert completed[0][0].status == model.OK and completed[0][0].as_of == wall()
        assert reader.attempt_state()['outcome'] == 'VERIFIED' and reader.failure is None
        assert reader.attempt_state()['attempt_id'] == initial['attempt_id']


@pytest.mark.parametrize('change', ['timeout', 'subject', 'latched_failure'])
def test_yield_cannot_renew_original_budget_or_erase_known_failure(change):
    tick = [0]
    key = ['a'*64]
    response = [observer_failure.classify(gate.DiscretionaryScanDeferred('financial writer'))]
    reader = authority_reader.Reader(clock=lambda: tick[0], wall_clock=lambda: NOW+timedelta(seconds=tick[0]),
        execution_slot=verifier._ObserverSlot(),
        evidence_reader=lambda *_: key[0], runner=lambda *_a, **_kw: response[0].model_dump(mode='json', by_alias=True))
    if change == 'latched_failure':
        response[0] = observer_failure.classify(psycopg.errors.LockNotAvailable('real SQL error'))
        reader.read('test', include_paper=False)
        wait_until(lambda: reader.pending is None)
        assert reader.read('test', include_paper=False, allow_start=False)[0][0].status == model.UNKNOWN
        tick[0] += 30
        response[0] = observer_failure.classify(gate.DiscretionaryScanDeferred('financial writer'))
    reader.read('test', include_paper=False)
    wait_until(lambda: reader.attempt_state()['outcome']=='DEFERRED')
    original = reader.attempt_deadline
    tick[0] += 1
    if change == 'subject':
        key[0] = 'b'*64
    rows = reader.read('test', include_paper=False, scan_occupied=True)[0]
    if change == 'latched_failure':
        assert rows[0].status == model.UNKNOWN and 'READ_LOCK_UNAVAILABLE' in rows[0].detail
    else:
        assert rows[0].status == model.WARN and rows[0].valid_until == original
    tick[0] = int((original-NOW).total_seconds())
    wait_until(lambda: reader.pending is None)
    rows = reader.read('test', include_paper=False, scan_occupied=True, allow_start=False)[0]
    assert rows[0].status == model.UNKNOWN and rows[0].recovery is None


def test_resumed_worker_gets_only_remaining_work_and_keeps_its_original_admission():
    tick = [0]
    budgets = []
    def yield_worker(*_args, timeout, **_kwargs):
        budgets.append(timeout)
        tick[0] += 260 if len(budgets) == 1 else 40
        return observer_failure.classify(gate.DiscretionaryScanDeferred('native writer')).model_dump(
            mode='json', by_alias=True)
    reader = authority_reader.Reader(clock=lambda: tick[0], wall_clock=lambda: NOW+timedelta(seconds=tick[0]),
        execution_slot=verifier._ObserverSlot(), runner=yield_worker, evidence_reader=lambda *_: 'a'*64)
    reader.read('test', include_paper=False)
    wait_until(lambda: reader.attempt_state()['outcome']=='DEFERRED')
    original = reader.attempt_state()['attempt_id']
    tick[0] += 80
    reader.read('test', include_paper=False)
    wait_until(lambda: reader.pending is None)
    reader.read('test', include_paper=False, allow_start=False)
    assert budgets == [300, 40] and reader.attempt_state()['attempt_id'] == original
    assert reader.failure_diagnostic.code == 'FOREGROUND_WAIT_EXHAUSTED'


def test_only_exact_native_yield_can_request_parent_scheduling():
    def assert_yield():
        diagnostic = observer_failure.classify(gate.DiscretionaryScanDeferred('native writer'))
        assert diagnostic.outcome == 'DEFERRED'
        return diagnostic.model_dump(mode='json', by_alias=True)
    encoded = assert_yield()
    with pytest.raises(ValueError):
        observer_failure.decode({**encoded, 'exception_type':'LockNotAvailable'})
    class UnreviewedYield(gate.DiscretionaryScanDeferred):
        pass
    assert observer_failure.classify(UnreviewedYield('unreviewed')).outcome == 'FAILED'
    assert observer_failure.classify(gate.DiscretionaryScanDeferred('broken IPC'), transport=True).outcome == 'FAILED'


def test_removing_native_deferral_classification_recreates_the_rehearsal_failure(monkeypatch):
    source = inspect.getsource(observer_failure.classify)
    guard = 'if type(error) is DiscretionaryScanDeferred:'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'if False:'), '<lost native deferral>', 'exec'),
        vars(observer_failure), namespace)
    monkeypatch.setattr(observer_failure, 'classify', namespace['classify'])
    with pytest.raises(AssertionError):
        test_only_exact_native_yield_can_request_parent_scheduling()
