"""Original dependency evidence survives wrapping; recovery needs verified state."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import shadow_dependency_notifications as notices, shadow_worker, shadow_supervisor
from sentinel.automation import outbox
from sentinel.feed import calendar, rolling_publisher
from sentinel.feed.publication import CorpusLockUnavailable
from sentinel.feed.rolling_jobs import JobDeadlineExceeded
from sentinel.execution.journal import WriterLockUnavailable
from sentinel.shadow_service import ShadowServiceRetry, ShadowServiceRefused
from tests.sentinel.test_automation_outbox import conn, pg

NOW = datetime(2026, 10, 23, 21, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(minutes=3)
CONFIG = SimpleNamespace(database_url='isolated', observation_id='primary')


@pytest.fixture(autouse=True)
def runtime(monkeypatch):
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', 'a' * 40)
    monkeypatch.setenv('SENTINEL_IMAGE_SOURCE_REVISION', 'a' * 40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:' + 'b' * 64)
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', 'primary')
    monkeypatch.setattr(notices.supervisor_io, 'report', lambda *_args, **_kwargs: None)


@pytest.mark.parametrize('error,cause', [
    (CorpusLockUnavailable('secret-url'), 'CORPUS_LOCK_BUSY'),
    (WriterLockUnavailable('secret-url'), 'WRITER_LOCK_BUSY'),
    (psycopg.errors.QueryCanceled('secret-url'), 'DATABASE_UNAVAILABLE'),
    (JobDeadlineExceeded('secret-url'), 'WORKER_BUDGET_EXHAUSTED'),
])
def test_typed_original_survives_wrapper_and_retains_first_phase(error, cause):
    notices.capture_stage(error, 'ACQUISITION_LOCK', now=EARLIER)
    notices.capture_stage(error, 'PUBLICATION', now=NOW)
    wrapped = ShadowServiceRetry('generic source/backup unavailable')
    wrapped.__cause__ = error
    payload = notices.warning_payload(wrapped, CONFIG, now=NOW)
    assert payload['cause_code'] == cause
    assert payload['operation_stage'] == 'ACQUISITION_LOCK'
    assert payload['observed_at'] == EARLIER.isoformat()
    assert payload['exception_type'] == type(error).__module__ + '.' + type(error).__qualname__
    assert 'secret-url' not in json.dumps(payload)
    assert 'generic source/backup' not in json.dumps(payload)
    if isinstance(error, psycopg.errors.QueryCanceled):
        assert payload['sqlstate'] == '57014'


def test_arbitrary_context_and_terminal_cause_are_not_diagnoses():
    refusal = ShadowServiceRefused('integrity')
    refusal.__cause__ = CorpusLockUnavailable('prior availability')
    outer = ShadowServiceRetry('outer retry')
    outer.__cause__ = refusal
    outer.__context__ = psycopg.errors.QueryCanceled('incidental context')
    assert notices.warning_payload(outer, CONFIG, now=NOW)['cause_code'] == 'DEPENDENCY_UNAVAILABLE'
    assert not shadow_worker._availability_failure(outer)


def test_dependency_context_walk_falsifier(monkeypatch):
    monkeypatch.setattr(notices, '_chain', lambda exc: (exc, exc.__context__))
    with pytest.raises(AssertionError):
        test_arbitrary_context_and_terminal_cause_are_not_diagnoses()


def test_invalid_stage_and_forged_context_cannot_appear_in_payload():
    failure = CorpusLockUnavailable('private')
    notices.capture_stage(failure, 'https://secret.invalid')
    failure._sentinel_dependency_context = {'stage': 'private', 'observed_at': EARLIER}
    payload = notices.warning_payload(failure, CONFIG, now=NOW)
    assert payload['operation_stage'] == 'SHADOW_ADVANCE'
    assert payload['observed_at'] == NOW.isoformat()
    class Unreviewed(CorpusLockUnavailable):
        pass
    assert notices.warning_payload(Unreviewed('private'), CONFIG, now=NOW)['exception_type'] == 'UNAVAILABLE'


def test_database_reporting_failure_keeps_original_safe_log_and_exit(monkeypatch):
    logs = []
    attempts = []
    original_utc = notices._utc
    monkeypatch.setattr(notices, '_utc', lambda value=None: original_utc(value or NOW))
    monkeypatch.setattr(notices.supervisor_io, 'report', logs.append)
    def unavailable(*_args, **_kwargs):
        attempts.append((_args, _kwargs))
        raise psycopg.OperationalError('credential-bearing private URL')
    monkeypatch.setattr(notices.supervisor_io, 'run', unavailable)
    failure = CorpusLockUnavailable('original-private-message')
    notices.capture_stage(failure, 'SOURCE_REFERENCES', now=EARLIER)
    wrapped = ShadowServiceRetry('unhelpful wrapper')
    wrapped.__cause__ = failure
    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, 'from_env', lambda: CONFIG)
    monkeypatch.setattr(shadow_worker, 'advance_once', lambda _: (_ for _ in ()).throw(wrapped))
    assert shadow_worker.main() == shadow_worker.EXIT_DEPENDENCY_UNAVAILABLE
    structured = [json.loads(item.removeprefix(notices.PREFIX)) for item in logs if item.startswith(notices.PREFIX)]
    assert structured and all(item['cause_code'] == 'CORPUS_LOCK_BUSY' for item in structured)
    assert all(item['observed_at'] == EARLIER.isoformat() for item in structured)
    assert len(attempts) == 1 and attempts[0][0][0] is notices._write_warning
    assert attempts[0][0][1]['observed_at'] == EARLIER.isoformat()
    assert attempts[0][1] == {'timeout': 1.0}
    assert 'credential-bearing' not in json.dumps(logs)
    assert 'original-private-message' not in json.dumps(logs)


def test_integrity_refusal_stays_terminal_and_does_not_report_retry(monkeypatch):
    failure = ShadowServiceRefused('authenticated state changed')
    failure.__cause__ = psycopg.errors.QueryCanceled('earlier timeout')
    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, 'from_env', lambda: CONFIG)
    monkeypatch.setattr(shadow_worker, 'advance_once', lambda _: (_ for _ in ()).throw(failure))
    monkeypatch.setattr(notices, 'report_failure', lambda *_: pytest.fail('terminal error softened'))
    assert shadow_worker.main() == shadow_worker.EXIT_REFUSED


def test_publisher_records_original_acquisition_lock_before_cleanup(monkeypatch):
    failure = CorpusLockUnavailable('original')
    cleanup = RuntimeError('independent cleanup failure')
    logs = []
    monkeypatch.setattr(notices.supervisor_io, 'report', logs.append)
    monkeypatch.setattr(rolling_publisher.runtime_schema, 'require_feed_schema', lambda _: None)
    from sentinel.feed import operational_snapshot
    monkeypatch.setattr(operational_snapshot, 'registered', lambda *_: True)
    monkeypatch.setattr(operational_snapshot, 'published', lambda *_: None)
    monkeypatch.setattr(rolling_publisher.identity, 'require_feed_producer_identity', lambda: {})
    monkeypatch.setattr(rolling_publisher.jobs, 'claim', lambda *_args, **_kwargs: SimpleNamespace(owner='owner'))
    monkeypatch.setattr(rolling_publisher.jobs, 'status', lambda *_: {'request': {}, 'state': 'ACQUIRING'})
    monkeypatch.setattr(rolling_publisher.jobs.PreparationRequest, 'model_validate', lambda _: SimpleNamespace())
    @contextmanager
    def locked(_):
        raise failure
        yield
    monkeypatch.setattr(rolling_publisher.store, 'acquisition_write_lock', locked)
    recorded = []
    monkeypatch.setattr(rolling_publisher, '_record_failure', lambda _c, _l, exc, **_: recorded.append(exc))
    monkeypatch.setattr(rolling_publisher.staging, 'clear', lambda *_args, **_kwargs: (_ for _ in ()).throw(cleanup))
    connection = SimpleNamespace(commit=lambda: None, rollback=lambda: None)
    with pytest.raises(RuntimeError, match='independent cleanup failure'):
        rolling_publisher._prepare(connection, 'job', operational=True)
    assert recorded == [failure]
    context = getattr(failure, '_sentinel_dependency_context', None)
    assert isinstance(context, notices.FailureContext)
    assert context.stage == 'ACQUISITION_LOCK'
    cleanup.__context__ = failure
    assert not shadow_worker._availability_failure(cleanup)
    diagnostic = json.loads(next(item for item in logs if item.startswith(notices.PREFIX)).removeprefix(notices.PREFIX))
    assert diagnostic['cause_code'] == 'CORPUS_LOCK_BUSY'
    assert diagnostic['operation_stage'] == 'ACQUISITION_LOCK'


def test_original_stage_capture_falsifier(monkeypatch):
    monkeypatch.setattr(notices, 'capture_stage', lambda *_args, **_kwargs: None)
    with pytest.raises(AssertionError):
        test_publisher_records_original_acquisition_lock_before_cleanup(monkeypatch)


def _payload():
    error = CorpusLockUnavailable('private')
    notices.capture_stage(error, 'ACQUISITION_LOCK', now=EARLIER)
    return notices.warning_payload(error, CONFIG, now=EARLIER)


def _delivered(conn, warning, *, receipt=True):
    # An isolated notification fixture, not a live transport or broker fixture.
    conn.execute("UPDATE sentinel_alert_outbox SET state='DELIVERED',created_at=%s,delivered_at=%s WHERE alert_id=%s",
                 (EARLIER, EARLIER + timedelta(seconds=1), warning.alert_id))
    if receipt:
        conn.execute("INSERT INTO sentinel_web_push_subscriptions(subscription_id,endpoint,p256dh,auth)"
                     " VALUES (%s,'https://push.invalid/device','fixture-key','fixture-auth') ON CONFLICT DO NOTHING", ('c' * 64,))
        conn.execute("INSERT INTO sentinel_web_push_deliveries(alert_id,subscription_id,state,delivered_at)"
                     " VALUES(%s,%s,'DELIVERED',%s)",
                     (warning.alert_id, 'c' * 64, EARLIER + timedelta(seconds=1)))
    conn.commit()


def _result():
    return {'session': '2026-10-23', 'live_frontier': '2026-10-23', 'sessions_lag': 0,
            'shadow_verdict': 'SHADOW_GO', 'verification': 'VERIFIED',
            'record_sha256': 'd' * 64, 'state_sha256': 'e' * 64,
            'runtime_identity_sha256': 'f' * 64, 'runtime_authority_sha256': '1' * 64}


def test_warning_first_payload_survives_worker_retry_and_supervisor_fallback(conn, monkeypatch):
    first = notices.enqueue_warning(conn, _payload())
    retry = dict(_payload(), cause_code='DATABASE_UNAVAILABLE', observed_at=NOW.isoformat())
    assert notices.enqueue_warning(conn, retry).payload == first.payload
    assert notices.enqueue_warning(conn, notices.fallback_warning(now=NOW)).payload == first.payload
    # The actual supervisor routes its fallback through the same durable helper.
    from sentinel.feed import store
    class Borrowed:
        def __getattr__(self, key): return getattr(conn, key)
        def close(self): pass
    monkeypatch.setattr(store, 'connect', lambda *_args, **_kwargs: Borrowed())
    from sentinel.config import SentinelConfig
    monkeypatch.setattr(SentinelConfig, 'from_env', lambda: SimpleNamespace(database_url='isolated'))
    shadow_supervisor._write_alert(notices.warning_key('2026-10-23'), notices.WARNING, 'WARN', notices.fallback_warning(now=NOW))
    assert outbox.load_alert(conn, first.alert_id).payload == first.payload
    assert conn.execute('SELECT COUNT(*) FROM sentinel_alert_outbox').fetchone()[0] == 1


def test_verified_recovery_is_unique_and_keeps_original_warning(conn, monkeypatch):
    first = notices.enqueue_warning(conn, _payload())
    _delivered(conn, first)
    monkeypatch.setattr(notices, '_verified_result', lambda *_: True)
    before = outbox.load_alert(conn, first.alert_id)
    recovered = notices.enqueue_recoveries(conn, CONFIG, _result(), now=NOW)
    assert len(recovered) == 1
    assert recovered[0].event_type == notices.RECOVERED and recovered[0].severity == 'INFO'
    assert recovered[0].payload['warning_alert_id'] == first.alert_id
    assert recovered[0].payload['warning_observed_at'] == EARLIER.isoformat()
    assert notices.enqueue_recoveries(conn, CONFIG, _result(), now=NOW + timedelta(seconds=30)) == []
    assert outbox.load_alert(conn, first.alert_id) == before
    assert conn.execute('SELECT COUNT(*) FROM sentinel_alert_outbox').fetchone()[0] == 2


def test_historical_and_malformed_warnings_cannot_recover_or_starve_current(conn, monkeypatch):
    old = notices.enqueue_warning(conn, {**_payload(), 'decision_session': '2026-10-22'})
    _delivered(conn, old)
    for number in range(40):
        outbox.enqueue(conn, idempotency_key=f'foreign-old-{number}', event_type=notices.WARNING,
                       severity='WARN', payload={'decision_session': 'malformed'})
    monkeypatch.setattr(notices, '_verified_result', lambda *_: True)
    assert notices.enqueue_recoveries(conn, CONFIG, _result(), now=NOW) == []
    current = notices.enqueue_warning(conn, _payload())
    _delivered(conn, current)
    recovered = notices.enqueue_recoveries(conn, CONFIG, _result(), now=NOW)
    assert len(recovered) == 1 and recovered[0].payload['warning_alert_id'] == current.alert_id


@pytest.mark.parametrize('invalid', ['no_receipt', 'pending', 'wrong_observation', 'future_warning',
                                   'bad_stage', 'bad_cause', 'bad_key', 'future_receipt', 'unverified'])
def test_recovery_cannot_promote_missing_or_mismatched_evidence(conn, monkeypatch, invalid):
    payload = _payload()
    if invalid == 'wrong_observation': payload['observation_id'] = 'other'
    if invalid == 'future_warning': payload['observed_at'] = (NOW + timedelta(seconds=1)).isoformat()
    if invalid == 'bad_stage': payload['operation_stage'] = 'secret-stage'
    if invalid == 'bad_cause': payload['cause_code'] = 'secret-cause'
    first = notices.enqueue_warning(conn, payload)
    _delivered(conn, first, receipt=invalid != 'no_receipt')
    if invalid == 'pending':
        conn.execute("UPDATE sentinel_alert_outbox SET state='PENDING' WHERE alert_id=%s", (first.alert_id,))
    if invalid == 'bad_key':
        conn.execute("UPDATE sentinel_alert_outbox SET idempotency_key='foreign' WHERE alert_id=%s", (first.alert_id,))
    if invalid == 'future_receipt':
        conn.execute('UPDATE sentinel_web_push_deliveries SET delivered_at=%s WHERE alert_id=%s', (NOW + timedelta(seconds=1), first.alert_id))
    conn.commit()
    monkeypatch.setattr(notices, '_verified_result', lambda *_: invalid != 'unverified')
    assert notices.enqueue_recoveries(conn, CONFIG, _result(), now=NOW) == []
    assert conn.execute("SELECT COUNT(*) FROM sentinel_alert_outbox WHERE event_type=%s", (notices.RECOVERED,)).fetchone()[0] == 0


@pytest.mark.parametrize('observation,extra,allowed', [('primary', {}, True), ('other', {}, False),
                                                   ('primary', {'unexpected': 'field'}, False)])
def test_legacy_warning_only_has_unambiguous_primary_recovery(conn, monkeypatch, observation, extra, allowed):
    payload = {**notices.fallback_warning(now=EARLIER), **extra}
    first = notices.enqueue_warning(conn, payload)
    _delivered(conn, first)
    monkeypatch.setattr(notices, '_verified_result', lambda *_: True)
    result = notices.enqueue_recoveries(conn, SimpleNamespace(observation_id=observation), _result(), now=NOW)
    assert bool(result) == allowed
    assert outbox.load_alert(conn, first.alert_id).payload == payload
    if result:
        assert 'cause_code' not in result[0].payload
        assert result[0].payload['warning_observed_at'] == EARLIER.isoformat()


def test_result_requires_actual_authenticated_authority_and_current_publication(monkeypatch):
    from sentinel import rolling_authority
    from sentinel.feed import rolling_go_inputs
    from sentinel.feed.rolling_contract import digest
    value = SimpleNamespace(observation_id='primary', session='2026-10-23', record_sha256='d' * 64,
                            state_sha256='e' * 64, runtime_sha256='f' * 64,
                            publication_sha256=digest({'version': 9}), model_dump=lambda **_: {'receipt': 'bound'})
    result = {**_result(), 'runtime_authority_sha256': digest(value.model_dump())}
    monkeypatch.setattr(rolling_authority, 'latest', lambda *_: [value])
    monkeypatch.setattr(rolling_go_inputs, 'current', lambda _: SimpleNamespace(to_dict=lambda: {'version': 9}))
    assert notices._verified_result(None, CONFIG, result, NOW)
    for changed in ({'verification': 'CANDIDATE'}, {'shadow_verdict': 'NOT_DEPLOYABLE'},
                    {'session': '2026-10-22'}, {'live_frontier': '2026-10-22'},
                    {'sessions_lag': 1}, {'runtime_authority_sha256': '0' * 64},
                    {'runtime_identity_sha256': '0' * 64}, {'record_sha256': '0' * 64}):
        assert not notices._verified_result(None, CONFIG, {**result, **changed}, NOW)
    value.observation_id = 'other'
    assert not notices._verified_result(None, CONFIG, result, NOW)
    value.observation_id = 'primary'
    monkeypatch.setattr(rolling_go_inputs, 'current', lambda _: SimpleNamespace(to_dict=lambda: {'version': 10}))
    assert not notices._verified_result(None, CONFIG, result, NOW)


def test_current_authority_guard_falsifier(monkeypatch):
    monkeypatch.setattr(notices, '_verified_result', lambda *_: True)
    with pytest.raises(AssertionError):
        test_result_requires_actual_authenticated_authority_and_current_publication(monkeypatch)


def test_successful_worker_uses_canonical_result_for_finite_recovery_only(monkeypatch):
    result = _result()
    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, 'from_env', lambda: CONFIG)
    monkeypatch.setattr(shadow_worker, 'advance_once', lambda _: result)
    calls = []
    def failed(function, *args, **kwargs):
        calls.append((function, args, kwargs))
        raise TimeoutError('private failure')
    monkeypatch.setattr(notices.supervisor_io, 'run', failed)
    assert shadow_worker.main() == 0
    assert len(calls) == 1 and calls[0][0] is notices._write_recoveries
    assert calls[0][1][:2] == (CONFIG, result)
    assert calls[0][2]['timeout'] == 1.0


def test_source_wait_never_sends_dependency_recovery(monkeypatch):
    from sentinel.shadow_service import ShadowServiceWaiting
    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, 'from_env', lambda: CONFIG)
    monkeypatch.setattr(shadow_worker, 'advance_once', lambda _: (_ for _ in ()).throw(ShadowServiceWaiting('source pending')))
    monkeypatch.setattr(notices, 'report_recovery', lambda *_: pytest.fail('waiting is not recovery'))
    assert shadow_worker.main() == shadow_worker.EXIT_WAITING
