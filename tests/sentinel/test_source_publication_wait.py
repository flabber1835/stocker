"""The operational publication proof owns only its finite read-only connection."""
from datetime import datetime, timedelta, timezone
import inspect

import pytest

from sentinel import source_publication_wait as waiting
from sentinel.feed import calendar
from sentinel.feed.publication import CORPUS_LOCK_KEY
from sentinel.feed.rolling_contract import PriceWindow, digest
from sentinel.feed.rolling_jobs import PreparationRequest

NOW = datetime(2026, 10, 26, 20, 50, tzinfo=timezone.utc)
END = NOW + timedelta(hours=1)


def record():
    request = PreparationRequest(window=PriceWindow.through('2026-10-26'),
        strategy_sha256='a' * 64, dependencies_sha256='b' * 64).model_dump(mode='json')
    return [request, digest(request), 'READY', NOW - timedelta(minutes=40), END,
            NOW - timedelta(minutes=15), NOW - timedelta(minutes=25), 'active', NOW]


class Connection:
    def __init__(self, rows, *, unreadable=False):
        self.rows, self.unreadable = rows, unreadable
        self.queries = []
        self.rolled_back = self.closed = False

    def execute(self, query, args=None):
        self.queries.append((query, args))
        if self.unreadable:
            raise RuntimeError('bounded proof unavailable')
        return self

    def fetchall(self):
        return self.rows

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def observe(monkeypatch, rows, *, decision='2026-10-26', unreadable=False):
    owned = Connection(rows, unreadable=unreadable)
    calls = []
    def connect(dsn, **kwargs):
        calls.append((dsn, kwargs))
        return owned
    monkeypatch.setattr(waiting.store, 'connect', connect)
    result = waiting.observe('postgresql://isolated.invalid/proof',
                             decision_session=decision, now=NOW)
    assert calls == [('postgresql://isolated.invalid/proof', {
        'connect_timeout': 3, 'statement_timeout_ms': 3000})]
    assert owned.rolled_back and owned.closed
    assert owned.queries[0] == ('BEGIN TRANSACTION READ ONLY', None)
    if not unreadable:
        assert owned.queries == [('BEGIN TRANSACTION READ ONLY', None),
                                (waiting.PROOF_SQL, (CORPUS_LOCK_KEY,))]
    return result


def test_finite_owned_read_returns_original_and_bounded_deadlines(monkeypatch):
    proof = observe(monkeypatch, [record()])
    assert proof.decision_session == '2026-10-26'
    assert proof.publisher_deadline == END
    assert proof.deadline == END - timedelta(microseconds=1)
    assert proof.observed_at == NOW


def test_later_publisher_deadline_cannot_extend_the_following_open(monkeypatch):
    pending = record()
    pending[4] = NOW + timedelta(days=2)
    proof = observe(monkeypatch, [pending])
    assert proof.publisher_deadline == pending[4]
    assert proof.deadline == calendar.session_window('2026-10-27')[0] - timedelta(microseconds=1)


@pytest.mark.parametrize('rows,decision', [([], '2026-10-26'),
    ([record(), record()], '2026-10-26'), ([record()], '2026-10-23'),
    ([('malformed',)], '2026-10-26')])
def test_missing_conflicting_foreign_or_malformed_proof_cannot_quiet_a_failure(monkeypatch, rows, decision):
    assert observe(monkeypatch, rows, decision=decision) is None


def test_unreadable_proof_preserves_original_failure_and_closes_only_owned_connection(monkeypatch):
    caller_financial_connection = Connection([])
    assert observe(monkeypatch, [record()], unreadable=True) is None
    assert caller_financial_connection.queries == []
    assert not caller_financial_connection.rolled_back and not caller_financial_connection.closed


def test_expired_job_is_not_a_current_publication_explanation():
    expired = record()
    expired[4] = NOW
    assert waiting.deadline_from_record(expired, now=NOW) is None


def test_expiry_guard_removal_is_detected(monkeypatch):
    source = inspect.getsource(waiting.deadline_from_record)
    guard = 'or not created <= sampled < deadline or '
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'or '), '<publication-proof-expiry-falsifier>', 'exec'),
         waiting.__dict__, namespace)
    monkeypatch.setattr(waiting, 'deadline_from_record', namespace['deadline_from_record'])
    with pytest.raises(AssertionError):
        test_expired_job_is_not_a_current_publication_explanation()


def test_panel_public_aliases_share_operational_sql_and_record_validator():
    from sentinel.panel import publication_wait
    assert publication_wait.PROOF_SQL == waiting.PROOF_SQL
    assert publication_wait.deadline_from_record is waiting.deadline_from_record
