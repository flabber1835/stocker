"""Post-publication UI waits never become current financial observations."""
from datetime import datetime, timedelta, timezone
import inspect
from types import SimpleNamespace

import pytest

from sentinel import prepare_shadow_wait
from sentinel.automation import closing_data_notifications
from sentinel.feed import calendar, store
from sentinel.panel import model, observer_codec, presentation, read_projection, render
from sentinel.panel import postclose_feed_wait, retry_status, shadow_source_wait, verification_service

NOW = datetime(2026, 10, 27, 20, 45, tzinfo=timezone.utc)
END = NOW + timedelta(minutes=20)


def proof(**changes):
    return SimpleNamespace(**{
        'decision_session': '2026-10-27', 'previous_session': '2026-10-26',
        'publication_version': 8, 'previous_publication_version': 7,
        'record_sha256': 'a' * 64, 'phase': 'AWAITING_SHADOW',
        'publisher_deadline': NOW + timedelta(hours=1), 'worker_deadline': END,
        'observed_at': NOW, 'deadline': END - timedelta(microseconds=1),
        'quiet_eligible': True, **changes})


@pytest.mark.parametrize('paper', [False, True])
def test_positive_preparation_rows_are_warn_unverified_and_expire_red(paper):
    rows = shadow_source_wait.preparation_rows(proof(), include_paper=paper)
    expected = read_projection.PAPER_KEYS if paper else read_projection.SHADOW_KEYS
    envelope = observer_codec.pack(rows, [], observed_at=NOW)
    observer_codec.validate_envelope(envelope, expected)
    assert all(row.status == model.WARN for row in rows)
    assert all(row.shadow_book is None and row.paper_alignment is None for row in rows)
    assert all('Last verified strategy session: 2026-10-26' in row.detail for row in rows)
    assert all('Current portfolio verification, values and holdings are unavailable' in row.detail for row in rows)
    assert all(row.recovery.phase == 'SHADOW_ATTESTATION' for row in rows)
    assert all(row.valid_until == END - timedelta(microseconds=1) for row in rows)
    assert all(row.effective_status(END) == model.FAIL for row in rows)


@pytest.mark.parametrize('changes', [
    {'quiet_eligible': False}, {'worker_deadline': None},
    {'deadline': NOW}, {'phase': 'UNKNOWN'},
])
def test_missing_expired_or_unqualified_worker_proof_cannot_create_healthy_wait(changes):
    with pytest.raises(ValueError):
        shadow_source_wait.preparation_rows(proof(**changes), include_paper=False)


def test_warning_only_tier_guard_removal_is_detected(monkeypatch):
    source = inspect.getsource(shadow_source_wait.preparation_rows)
    guard = "getattr(proof, 'quiet_eligible', False) is not True\n            or "
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, ''), '<missing-worker-proof-tier>', 'exec'),
         vars(shadow_source_wait), namespace)
    monkeypatch.setattr(shadow_source_wait, 'preparation_rows', namespace['preparation_rows'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_missing_expired_or_unqualified_worker_proof_cannot_create_healthy_wait({'quiet_eligible': False})


def test_presentation_distinguishes_published_data_from_pending_strategy_attestation():
    rows = shadow_source_wait.preparation_rows(proof(), include_paper=False)
    row = next(row for row in rows if row.key == 'shadow_verification')
    _label, value, detail = presentation.describe(row, model.WARN)
    assert value == 'Preparing strategy verification'
    assert 'Closing data is published' in detail
    assert 'Market data for the next decision is still pending' not in detail
    page = render.render(model.Panel(rows=rows, now=NOW))
    assert 'Preparing strategy verification' in page
    assert 'Current strategy attestation is still pending' in page


class Connection:
    rolled_back = False
    closed = False

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def observer_setup(monkeypatch, result, subjects=None):
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual')
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', 'primary')
    monkeypatch.setenv('SENTINEL_SHADOW_STARTING_CASH', '50000')
    owned = Connection()
    calls = []
    monkeypatch.setattr(store, 'connect', lambda dsn, **kwargs: (
        calls.append(('connect', dsn, kwargs)) or owned))
    def observe(conn, **kwargs):
        assert conn is owned
        calls.append(('observe', kwargs))
        return result
    monkeypatch.setattr(prepare_shadow_wait, 'observe', observe)
    names = iter(subjects or ['key', 'key'])
    monkeypatch.setattr(read_projection, 'subject_for', lambda *args: next(names))
    return owned, calls


def test_background_observer_uses_one_owned_bounded_connection_and_canonical_proof(monkeypatch):
    owned, calls = observer_setup(monkeypatch, proof())
    result = shadow_source_wait.observe_preparation('private', False, 'key')
    assert result is not None and owned.rolled_back and owned.closed
    assert calls[0] == ('connect', 'private', {'connect_timeout': 3, 'statement_timeout_ms': 3000})
    assert calls[1][1]['database_url'] == 'private'
    assert calls[1][1]['observation_id'] == 'primary'
    assert calls[1][1]['starting_cash'] == '50000'
    assert len(calls) == 2


@pytest.mark.parametrize('result', [None, proof(quiet_eligible=False)])
def test_current_or_unqualified_proof_retains_canonical_financial_observation(monkeypatch, result):
    owned, _ = observer_setup(monkeypatch, result)
    assert shadow_source_wait.observe_preparation('private', False, 'key') is None
    assert owned.rolled_back and owned.closed


def test_changed_projection_subject_cannot_publish_wait(monkeypatch):
    observer_setup(monkeypatch, proof(), subjects=['key', 'other'])
    with pytest.raises(ValueError, match='subject changed'):
        shadow_source_wait.observe_preparation('private', False, 'key')


def test_positive_background_proof_skips_expensive_financial_closure(monkeypatch):
    answer = object()
    monkeypatch.setattr(shadow_source_wait, 'observe_preparation', lambda *args: answer)
    monkeypatch.setattr(verification_service, '_observe_once',
                        lambda *args: pytest.fail('duplicate financial closure'))
    assert verification_service.observe('private', False, 'key') is answer


def test_unrelated_integrity_refusal_is_not_masked_when_preparation_proof_absent(monkeypatch):
    monkeypatch.setattr(shadow_source_wait, 'observe_preparation', lambda *args: None)
    monkeypatch.setattr(verification_service.financial, 'retry_corpus_lock', lambda operation: operation())
    def refused(*args):
        raise ValueError('unrelated immutable binding changed')
    monkeypatch.setattr(verification_service, '_observe_once', refused)
    with pytest.raises(ValueError, match='unrelated immutable binding changed'):
        verification_service.observe('private', False, 'key')


def test_attestation_wait_never_changes_successful_feed_status_or_hides_worker_failure():
    financial = shadow_source_wait.preparation_rows(proof(), include_paper=False)
    worker = model.Row('shadow_worker', 'Worker', 'RUNNING', model.OK, as_of=NOW,
        required_current=True, valid_until=NOW + timedelta(seconds=60))
    assert postclose_feed_wait.attestation_deadline(financial, worker, now=NOW) == proof().deadline
    failed = model.Row('shadow_worker', 'Worker', 'HALTED', model.FAIL,
        as_of=NOW, required_current=True, valid_until=END)
    assert postclose_feed_wait.attestation_deadline(financial, failed, now=NOW) is None


def test_automation_shadow_wait_uses_shortest_original_worker_deadline():
    closed = calendar.session_window('2026-10-27')[1]
    opened, ended = calendar.session_window('2026-10-28')
    worker_end = NOW + timedelta(minutes=5)
    publisher_end = NOW + timedelta(hours=1)
    cycle = SimpleNamespace(decision_session='2026-10-27', effective_session='2026-10-28',
        decision_close_at=closed, prepare_at=closed + timedelta(minutes=1),
        execution_open_at=opened, execute_at=opened + timedelta(minutes=1), execution_close_at=ended)
    retry = NOW + timedelta(seconds=30)
    marker = closing_data_notifications.marker(cycle=cycle, observed_at=NOW,
        next_retry_at=retry, publisher_deadline_at=publisher_end, worker_deadline_at=worker_end)
    diagnostic = {'retry_phase': 'REFRESH', 'callback_failure': 'SOURCE_DATA_PENDING',
        'exception_type': closing_data_notifications.EXCEPTION_TYPE,
        'notifier_action': 'RETRY_SCHEDULED', 'next_retry_at': retry.isoformat(),
        'latest_failure_at': NOW.isoformat(), 'closing_data_wait': marker}
    value = {**vars(cycle), 'state': 'RETRY_WAIT', 'failure_code': 'ClosingDataPending',
        'next_wake_at': retry, 'diagnostic': diagnostic, 'availability_retry_unbounded': True,
        'phase_attempt_count': 1, 'terminal_reason': None,
        **{key: diagnostic[key] for key in ('retry_phase', 'callback_failure', 'exception_type')}}
    recovery = retry_status.availability_recovery(value)
    assert recovery.phase == 'AUTOMATION_SHADOW_ATTESTATION'
    assert recovery.deadline == worker_end - timedelta(microseconds=1)
    assert not recovery.active(worker_end)


def test_original_worker_deadline_guard_removal_is_detected(monkeypatch):
    source = inspect.getsource(retry_status._closing_data_recovery)
    guard = "('publisher_deadline_at', 'worker_deadline_at')"
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, "('publisher_deadline_at',)"),
                 '<missing-panel-worker-deadline>', 'exec'), vars(retry_status), namespace)
    monkeypatch.setattr(retry_status, '_closing_data_recovery', namespace['_closing_data_recovery'])
    with pytest.raises(AssertionError):
        test_automation_shadow_wait_uses_shortest_original_worker_deadline()
