"""A temporary source-pin refusal never changes measured feed evidence."""
from datetime import datetime, timezone
import inspect
from types import SimpleNamespace

import pytest

from sentinel.feed import calendar, readers, store
from sentinel.feed.publication import CorpusLockUnavailable
from sentinel.panel import model, sources


class Clock:
    now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= sources.FEED_PIN_POLL_SECONDS
        self.now += seconds


class Connection:
    rollbacks = 0
    closed = False

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_reacquires_snapshot_and_keeps_negative_verdict_and_original_clock(monkeypatch):
    clock, conn, calls, timeouts = Clock(), Connection(), [], []
    original = ('2026-10-22', SimpleNamespace(ready=False,
        computed_at=datetime(2026, 10, 22, 22, tzinfo=timezone.utc)))

    def attempt(_):
        calls.append(True)
        if len(calls) == 1:
            raise CorpusLockUnavailable('publication owns the pin')
        return original

    monkeypatch.setattr(readers, 'status_snapshot', attempt)
    monkeypatch.setattr(sources, '_set_statement_timeout', lambda _, ms: timeouts.append(ms))
    assert sources._feed_status_snapshot(conn, clock=clock, sleep=clock.sleep) is original
    assert len(calls) == 2 and conn.rollbacks == 1
    assert original[1].ready is False
    assert timeouts[1] < timeouts[0] <= 2000


def test_persistent_lock_expires_at_original_deadline(monkeypatch):
    clock, conn, timeouts = Clock(), Connection(), []

    def busy(_):
        raise CorpusLockUnavailable('still owned')

    monkeypatch.setattr(readers, 'status_snapshot', busy)
    monkeypatch.setattr(sources, '_set_statement_timeout', lambda _, ms: timeouts.append(ms))
    with pytest.raises(CorpusLockUnavailable):
        sources._feed_status_snapshot(conn, clock=clock, sleep=clock.sleep)
    assert clock.now == sources.FEED_PIN_RETRY_SECONDS
    assert conn.rollbacks == len(timeouts) <= 21
    assert all(0 < timeout <= 2000 for timeout in timeouts)


@pytest.mark.parametrize('error', [ValueError('bad publication receipt'), TimeoutError('slow read')])
def test_integrity_and_timeouts_are_not_retried(monkeypatch, error):
    clock, conn, calls = Clock(), Connection(), []

    def fail(_):
        calls.append(True)
        raise error

    monkeypatch.setattr(readers, 'status_snapshot', fail)
    monkeypatch.setattr(sources, '_set_statement_timeout', lambda *_: None)
    with pytest.raises(type(error)):
        sources._feed_status_snapshot(conn, clock=clock, sleep=clock.sleep)
    assert len(calls) == 1 and clock.now == 0 and conn.rollbacks == 0


@pytest.mark.parametrize('persistent', [False, True])
def test_full_feed_projection_recovers_or_stays_red_without_erasing_ingest(monkeypatch, persistent):
    conn, clock, calls = Connection(), Clock(), []
    now = datetime(2026, 10, 23, 14, tzinfo=timezone.utc)
    snapshot = SimpleNamespace(ready=True, checks_passed=7, checks_total=7, computed_at=now)

    def attempt(_):
        calls.append(True)
        if persistent or len(calls) == 1:
            raise CorpusLockUnavailable('snapshot reader cannot pin during publication or retirement')
        return '2026-10-22', snapshot

    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual')
    monkeypatch.setattr(store, 'connect', lambda *_: conn)
    monkeypatch.setattr(sources, '_set_statement_timeout', lambda *_: None)
    monkeypatch.setattr(sources, '_operational_acquisition', lambda _: [dict(
        kind='daily', status='success', current_chunk='PUBLISHED publication 5', updated_at=now)])
    monkeypatch.setattr(calendar, 'freshness', lambda _: SimpleNamespace(sessions_behind=0, ahead=False))
    monkeypatch.setattr(readers, 'status_snapshot', attempt)
    original = sources._feed_status_snapshot
    monkeypatch.setattr(sources, '_feed_status_snapshot', lambda conn: original(
        conn, clock=clock, sleep=clock.sleep))
    rows, errors = sources._feed_rows('dbname=fixture')
    feed, ingest = rows
    assert not errors and ingest.status == model.OK and conn.closed
    assert feed.status == (model.UNKNOWN if persistent else model.OK)
    assert feed.as_of == now
    if persistent:
        assert 'CorpusLockUnavailable' in feed.detail
    else:
        assert '2026-10-22' in feed.value and len(calls) == 2


def _mutate(monkeypatch, before, after):
    source = inspect.getsource(sources._feed_status_snapshot)
    assert before in source
    namespace = {}
    exec(compile(source.replace(before, after), 'mutated-feed-pin', 'exec'), vars(sources), namespace)
    monkeypatch.setattr(sources, '_feed_status_snapshot', namespace['_feed_status_snapshot'])


def test_removing_deadline_breaks_its_falsifier(monkeypatch):
    _mutate(monkeypatch, 'if remaining <= 0:', 'if False:')
    with pytest.raises(AssertionError):
        test_persistent_lock_expires_at_original_deadline(monkeypatch)


def test_retrying_integrity_errors_breaks_its_falsifier(monkeypatch):
    _mutate(monkeypatch, 'except CorpusLockUnavailable as exc:', 'except Exception as exc:')
    with pytest.raises((AssertionError, CorpusLockUnavailable)):
        test_integrity_and_timeouts_are_not_retried(monkeypatch, ValueError('bad receipt'))


def test_omitting_reacquisition_rollback_breaks_its_falsifier(monkeypatch):
    _mutate(monkeypatch, 'conn.rollback()', 'pass')
    with pytest.raises(AssertionError):
        test_reacquires_snapshot_and_keeps_negative_verdict_and_original_clock(monkeypatch)


def test_bypassing_retry_in_full_feed_reader_breaks_its_falsifier(monkeypatch):
    monkeypatch.setattr(sources, '_feed_status_snapshot', readers.status_snapshot)
    with pytest.raises((AssertionError, CorpusLockUnavailable)):
        test_full_feed_projection_recovers_or_stays_red_without_erasing_ingest(monkeypatch, False)
