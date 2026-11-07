"""A due same-call retry cannot erase an uncommitted financial failure."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import inspect
import textwrap
from threading import Event
import time

import pytest

from sentinel.panel import (
    attempt_store, authority_reader, model, observer_codec, observer_failure, review_schema,
    review_store, verification_service as verifier,
)
from tests.sentinel.test_dashboard_review import conn, pg  # noqa: F401
from tests.sentinel.test_observer_attempt_store import owner
from tests.sentinel.test_observer_failure_review import install_receipts


@pytest.fixture(autouse=True)
def runtime(monkeypatch):
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'2'*64)


class Scenario:
    def __init__(self, *, retain=True, retry_negative=False):
        self.tick = 0.0
        self.now = datetime.now(timezone.utc)-timedelta(seconds=70)
        self.calls = 0
        self.release = Event()
        self.retry_started = Event()
        self.retry_negative = retry_negative
        self.reader = authority_reader.Reader(
            runner=self.run, clock=lambda: self.tick, wall_clock=lambda: self.now,
            evidence_reader=lambda *_: 'b'*64, key_factory=lambda *_: 'b'*64,
            expected_keys=frozenset({'paper_reconciliation'}),
            retain_failed_attempt=retain)

    def run(self, *_args, **_kwargs):
        self.calls += 1
        call = self.calls
        if call == 2:
            self.retry_started.set()
            assert self.release.wait(10), 'test retry was not released'
        failed = call == 1 or call == 2 and self.retry_negative
        row = model.Row('paper_reconciliation', 'Paper alignment',
            'UNKNOWN' if failed else 'VERIFIED', model.UNKNOWN if failed else model.OK,
            'controlled failed financial result' if failed else 'current verified result',
            as_of=self.now, required_current=True)
        return observer_codec.pack([row], [], observed_at=self.now)

    def advance(self):
        self.tick += authority_reader.RETRY_SECONDS+1
        self.now += timedelta(seconds=authority_reader.RETRY_SECONDS+1)

    def finish(self):
        with self.reader.lock:
            pending = self.reader.pending
        if pending is not None:
            pending.join(5)
        assert self.reader.pending is None, 'test financial observation did not finish'

    def first_closed(self):
        self.reader.read('private-fixture')
        self.finish()
        state = self.reader.attempt_state()
        assert state['outcome'] == 'COMPLETED'
        self.advance()
        return state

    def close(self):
        self.release.set()
        self.finish()


def refresh(conn, owned, scenario, previous, monkeypatch):
    # Exercise actual diagnostic+review SQL and transaction ownership. Financial
    # publication is independently covered; no synthetic financial authority is
    # written by these diagnostic-handoff tests.
    monkeypatch.setattr(verifier, 'snapshot', lambda *_args, **_kwargs: None)
    verifier._refresh_readers(conn, {'PAPER': scenario.reader}, 'private-fixture',
        owned, previous, Event(), time.monotonic()+30)


def history(conn):
    return attempt_store.read_owned(conn, scope='PAPER', now=review_store.database_now(conn))


def review_events(conn):
    return conn.execute(f'SELECT payload FROM {review_schema.EVENTS} '
                        "WHERE event_key LIKE 'verification-failure:PAPER:%' ORDER BY sequence").fetchall()


def assert_first_history(conn, original, *, expected_failures=1):
    saved = history(conn)
    assert len(saved['failures']) == expected_failures
    first = saved['failures'][0]['first']
    assert first['attempt_id'] == original['attempt_id']
    assert first['admitted_at'] == original['admitted_at']
    assert first['deadline'] == original['deadline']
    assert first['completed_at'] == original['completed_at']
    assert first['diagnostic']['code'] == 'NEGATIVE_RESULT'
    assert saved['financial_authority'] is False
    assert len(review_events(conn)) == expected_failures
    return saved


def test_same_call_retry_commits_original_failure_and_distinct_current_attempt(conn, monkeypatch):
    owned = install_receipts(conn)
    scenario = Scenario()
    published = []
    original_publish = attempt_store.publish_owned
    def capture(*args, **kwargs):
        published.append(deepcopy(kwargs['attempt']))
        return original_publish(*args, **kwargs)
    monkeypatch.setattr(attempt_store, 'publish_owned', capture)
    try:
        original = scenario.first_closed()
        previous = {}
        refresh(conn, owned, scenario, previous, monkeypatch)
        assert scenario.retry_started.wait(2)
        assert scenario.calls == 2
        assert published[0]['attempt_id'] == original['attempt_id']
        assert published[0]['outcome'] == 'FAILED'
        assert published[1]['attempt_id'] != original['attempt_id']
        assert published[1]['outcome'] in {'QUEUED', 'RUNNING'}
        assert published[1]['diagnostic'] is None
        assert published[1]['latched_failure'] == published[0]['diagnostic']
        assert scenario.reader.pending_failed_attempt() is None
        saved = assert_first_history(conn, original)
        assert saved['latest']['attempt_id'] == published[1]['attempt_id']
        # The current displayed negative proof keeps its original timestamp;
        # the new retry and historical failure do not redate it.
        assert scenario.reader.completed[2] == datetime.fromisoformat(original['completed_at'])
        assert scenario.reader.completed[0][0].status == model.UNKNOWN
        assert conn.execute('SELECT scope FROM '+attempt_store.schema.RECEIPTS).fetchall() == [
            ('DIAGNOSTIC:PAPER',)]
    finally:
        scenario.close()


@pytest.mark.parametrize('fault', ['owner_refusal', 'precommit', 'commit'])
def test_refusal_or_rollback_retains_failure_until_next_confirmed_commit(conn, monkeypatch, fault):
    owned = install_receipts(conn)
    scenario = Scenario()
    real_publish = attempt_store.publish_owned
    previous = {}
    class RefuseCommit:
        def __getattr__(self, key):
            return getattr(conn, key)
        def commit(self):
            raise RuntimeError('controlled precommit failure')
    try:
        original = scenario.first_closed()
        if fault == 'owner_refusal':
            owner(conn)
        elif fault == 'precommit':
            def refuse_after_sql(*args, **kwargs):
                result = real_publish(*args, **kwargs)
                if kwargs['attempt']['attempt_id'] != original['attempt_id']:
                    raise RuntimeError('controlled precommit failure')
                return result
            monkeypatch.setattr(attempt_store, 'publish_owned', refuse_after_sql)
        with pytest.raises((attempt_store.DiagnosticsRefused, RuntimeError)):
            refresh(RefuseCommit() if fault == 'commit' else conn, owned,
                    scenario, previous, monkeypatch)
        conn.rollback()
        retained = scenario.reader.pending_failed_attempt()
        assert retained['attempt_id'] == original['attempt_id']
        assert retained['outcome'] == 'FAILED'
        assert previous == {}
        assert conn.execute('SELECT count(*) FROM '+attempt_store.schema.RECEIPTS).fetchone()[0] == 0
        assert review_events(conn) == []
        conn.rollback()
        monkeypatch.setattr(attempt_store, 'publish_owned', real_publish)
        scenario.release.set()
        scenario.finish()
        scenario.advance()
        owned = owner(conn)
        refresh(conn, owned, scenario, previous, monkeypatch)
        assert scenario.calls == 2
        assert scenario.reader.pending_failed_attempt() is None
        saved = assert_first_history(conn, original)
        assert saved['latest']['outcome'] == 'VERIFIED'
    finally:
        scenario.close()


def test_occupied_slot_cannot_be_replaced_by_another_closed_failure(conn, monkeypatch):
    owned = install_receipts(conn)
    scenario = Scenario(retry_negative=True)
    try:
        original = scenario.first_closed()
        scenario.reader.read('private-fixture')
        assert scenario.retry_started.wait(2)
        retained = scenario.reader.pending_failed_attempt()
        scenario.release.set()
        scenario.finish()
        second = scenario.reader.attempt_state()
        scenario.advance()
        scenario.reader.read('private-fixture')
        assert scenario.calls == 2, 'occupied diagnostic slot admitted another replacement'
        assert scenario.reader.attempt_state()['attempt_id'] == second['attempt_id']
        assert scenario.reader.pending_failed_attempt() == retained
        assert not scenario.reader.ack_failed_attempt('f'*32)
        assert scenario.reader.pending_failed_attempt() == retained
        refresh(conn, owned, scenario, {}, monkeypatch)
        assert_first_history(conn, original, expected_failures=2)
        assert scenario.reader.pending_failed_attempt() is None
    finally:
        scenario.close()


def test_committed_but_unacknowledged_history_replays_after_owner_restart_without_duplicate_review(
        conn, monkeypatch):
    owned = install_receipts(conn)
    scenario = Scenario()
    class LostCommitReply:
        def __getattr__(self, key):
            return getattr(conn, key)
        def commit(self):
            conn.commit()
            raise RuntimeError('controlled lost commit reply')
    try:
        original = scenario.first_closed()
        with pytest.raises(RuntimeError, match='lost commit reply'):
            refresh(LostCommitReply(), owned, scenario, {}, monkeypatch)
        conn.rollback()
        assert scenario.reader.pending_failed_attempt()['attempt_id'] == original['attempt_id']
        first = assert_first_history(conn, original)['failures'][0]
        conn.rollback()
        owned = owner(conn)
        refresh(conn, owned, scenario, {}, monkeypatch)
        assert scenario.reader.pending_failed_attempt() is None
        saved = assert_first_history(conn, original)
        assert saved['failures'][0]['first'] == first['first']
        assert saved['failures'][0]['first_recorded_at'] == first['first_recorded_at']
        conn.rollback()
        # Replayed existing IDs under the new owner still cannot append REVIEW.
        for attempt in (first['first'], saved['latest']):
            attempt_store.publish_owned(conn, owner_id=owned, scope='PAPER', attempt=attempt,
                                        now=review_store.database_now(conn))
        conn.commit()
        assert len(review_events(conn)) == 1
    finally:
        scenario.close()


def test_retained_write_cannot_leave_latest_failed_when_current_attempt_is_cached(conn, monkeypatch):
    owned = install_receipts(conn)
    scenario = Scenario()
    try:
        original = scenario.first_closed()
        scenario.reader.read('private-fixture')
        assert scenario.retry_started.wait(2)
        current = scenario.reader.attempt_state()
        assert current['attempt_id'] != original['attempt_id']
        assert scenario.reader.pending_failed_attempt()['attempt_id'] == original['attempt_id']
        # A previously cached current diagnostic does not describe the retained
        # FAILED write that this iteration must publish before it.
        attempt_store.publish_owned(conn, owner_id=owned, scope='PAPER', attempt=current,
                                    now=review_store.database_now(conn))
        conn.commit()
        previous = {attempt_store.scope_key('PAPER'): current}
        refresh(conn, owned, scenario, previous, monkeypatch)
        saved = assert_first_history(conn, original)
        assert saved['latest'] == current
        assert scenario.reader.pending_failed_attempt() is None
    finally:
        scenario.close()


def test_default_reader_keeps_existing_same_call_retry_behavior():
    scenario = Scenario(retain=False)
    try:
        original = scenario.first_closed()
        scenario.reader.read('private-fixture')
        assert scenario.retry_started.wait(2)
        assert scenario.reader.attempt_state()['attempt_id'] != original['attempt_id']
        assert scenario.reader.pending_failed_attempt() is None
    finally:
        scenario.close()


def test_parent_failed_attempt_without_completion_time_keeps_original_null_clock(conn, monkeypatch):
    owned = install_receipts(conn)
    scenario = Scenario()
    try:
        scenario.first_closed()
        with scenario.reader.lock:
            scenario.reader.answer = None
            scenario.reader.attempt_completed_at = None
            scenario.reader.attempt_outcome = 'FAILED'
            scenario.reader.diagnostic = observer_failure.failure('OBSERVER_EXCEPTION', 'OBSERVATION')
            scenario.reader.failure_diagnostic = scenario.reader.diagnostic
            scenario.reader.failure = 'controlled parent-classified failure'
        original = scenario.reader.attempt_state()
        assert original['completed_at'] is None
        refresh(conn, owned, scenario, {}, monkeypatch)
        saved = history(conn)
        assert saved['failures'][0]['first'] == original
        assert saved['latest']['attempt_id'] != original['attempt_id']
        assert saved['failures'][0]['first']['completed_at'] is None
        assert len(review_events(conn)) == 1
    finally:
        scenario.close()


def test_initial_parent_failure_does_not_invent_an_attempt_identity():
    scenario = Scenario()
    try:
        def unreadable(*_):
            raise ValueError('controlled identity failure')
        scenario.reader.evidence_reader = unreadable
        scenario.reader.read('private-fixture')
        assert scenario.reader.attempt_state() is None
        scenario.reader.evidence_reader = lambda *_: 'b'*64
        scenario.reader.read('private-fixture')
        assert scenario.reader.attempt_state() is not None
        assert scenario.reader.pending_failed_attempt() is None
    finally:
        scenario.close()


def test_removed_failure_capture_is_detected_by_real_postgres_handoff(conn, monkeypatch):
    source = inspect.getsource(authority_reader.Reader.read)
    guard = ('self._failed_attempt_handoff = observer_failure.Attempt.model_validate_json(\n'
             '                        json.dumps(failed, allow_nan=False))')
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(textwrap.dedent(source.replace(guard, 'pass')),
                 '<lost-failure-handoff>', 'exec'), vars(authority_reader), namespace)
    monkeypatch.setattr(authority_reader.Reader, 'read', namespace['read'])
    with pytest.raises(AssertionError):
        test_same_call_retry_commits_original_failure_and_distinct_current_attempt(conn, monkeypatch)


def test_removed_occupied_slot_guard_is_detected(conn, monkeypatch):
    source = inspect.getsource(authority_reader.Reader.read)
    guard = '                    and (not self.retain_failed_attempt or self._failed_attempt_handoff is None)\n'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(textwrap.dedent(source.replace(guard, '')),
                 '<unbounded-failure-handoff>', 'exec'), vars(authority_reader), namespace)
    monkeypatch.setattr(authority_reader.Reader, 'read', namespace['read'])
    with pytest.raises(AssertionError):
        test_occupied_slot_cannot_be_replaced_by_another_closed_failure(conn, monkeypatch)


def test_removed_current_republish_guard_is_detected(conn, monkeypatch):
    source = inspect.getsource(verifier._refresh_readers)
    guard = '(retained is not None or previous.get(diagnostic_key) != attempt)'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'previous.get(diagnostic_key) != attempt'),
                 '<cached-current-after-failed-write>', 'exec'), vars(verifier), namespace)
    monkeypatch.setattr(verifier, '_refresh_readers', namespace['_refresh_readers'])
    with pytest.raises(AssertionError):
        test_retained_write_cannot_leave_latest_failed_when_current_attempt_is_cached(conn, monkeypatch)
