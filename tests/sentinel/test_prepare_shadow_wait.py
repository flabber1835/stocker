"""Preparation evidence can defer PAPER while strict certification stays strict."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest

from sentinel import automation_runtime, prepare_shadow_wait as waiting
from sentinel import receipt_authentication, shadow_service_status as worker_status
from sentinel.automation.model import ClosingDataPending, SourceDataPending, NonRetryableCallbackRefused
from sentinel.feed import calendar, publication
from sentinel.feed.rolling_contract import PriceWindow, digest
from sentinel.feed.rolling_jobs import PreparationRequest


NOW = datetime(2026, 10, 27, 20, 40, tzinfo=timezone.utc)
CLOSE = datetime(2026, 10, 27, 20, 0, tzinfo=timezone.utc)
PUBLISHER_END = NOW + timedelta(hours=1)
WORKER_END = NOW + timedelta(minutes=50)
DSN = 'postgresql://isolated.invalid/preparation-proof'
REAL_WORKER = waiting._worker


class ProofConnection:
    def __init__(self, previous, timing):
        self.previous, self.timing, self.queries = previous, timing, []
        self.record_sha256 = 'b' * 64
        self.previous_record_sha256 = 'a' * 64

    def execute(self, sql, args):
        self.queries.append((sql, args))
        return self

    def fetchone(self):
        sql, _args = self.queries[-1]
        if "state->'checkpoint'" in sql:
            return ('2026-10-27', self.record_sha256, self.timing,
                    {'previous_record_sha256': self.previous_record_sha256})
        if 'sentinel_corpus_publications' in sql:
            p = self.previous
            return (p.version, p.previous_version, p.run_id, p.window_start, p.window_end, p.evidence)
        raise AssertionError('unexpected proof SQL: ' + sql)


@pytest.fixture
def facts(monkeypatch):
    runtime = waiting.runtime
    request = PreparationRequest(window=PriceWindow.through('2026-10-27'),
        expected_publication_version=7, strategy_sha256='c' * 64, dependencies_sha256='d' * 64)
    old = publication.Publication(7, 6, None, str(request.window.start), '2026-10-26', {'rolling_snapshot': {}})
    pub = publication.Publication(8, 7, None, str(request.window.start), '2026-10-27', {'rolling_snapshot': {}})
    authority = runtime.authority.Authority.model_construct(session='2026-10-26',
        observation_id='primary', record_sha256='a' * 64, publication_sha256=digest(old.to_dict()))
    binding = {'job_id': 'job-8', 'candidate_id': 'candidate-8'}
    checkpoint = SimpleNamespace(session='2026-10-26', publication=old.to_dict(), snapshot={'old': True})
    result = SimpleNamespace(session='2026-10-26', state=SimpleNamespace(last_processed_session='2026-10-26'),
        record_sha256='a' * 64)
    opened = calendar.session_window('2026-10-28')[0]
    timing = {'schema': 'sentinel.shadow-activation-timing/1', 'decision_session': '2026-10-27',
        'execution_session': '2026-10-28', 'observed_at': (NOW-timedelta(minutes=1)).isoformat(),
        'execution_open_at': opened.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'status': runtime.shadow.BEFORE_NEXT_OPEN}
    proof = ProofConnection(old, timing)
    value = SimpleNamespace(pub=pub, old=old, authority=authority, binding=binding,
        checkpoint=checkpoint, result=result, attested=authority, previous=None,
        owned=proof, calls=[], authorities=[authority], request=request,
        job={'job_id': 'job-8', 'candidate_id': 'candidate-8', 'state': 'PUBLISHED',
             'publication_version': 8, 'created_at': CLOSE.isoformat(),
             'deadline': PUBLISHER_END.isoformat(), 'request': request.model_dump(mode='json'),
             'request_sha256': request.request_sha256})

    @contextmanager
    def committed(caller):
        assert caller is value.caller
        value.calls.append('owned-proof')
        try:
            yield proof
        finally:
            value.calls.append('owned-proof-ended')

    @contextmanager
    def pinned(conn):
        assert conn is proof
        value.calls.append('pinned')
        yield value.pub

    def closure(conn, _context, *, status_only):
        assert conn is proof and status_only is True
        value.calls.append('authenticated-closure')
        return value.checkpoint, None, value.result, value.attested, value.previous

    value.caller = SimpleNamespace(rollback=lambda: pytest.fail('borrowed financial transaction ended'),
        close=lambda: pytest.fail('borrowed financial connection closed'))
    monkeypatch.setattr(waiting.committed_read, 'proof_connection', committed)
    monkeypatch.setattr(runtime.inputs, 'require_schemas', lambda conn: value.calls.append('schemas'))
    monkeypatch.setattr(runtime.inputs, 'pinned', pinned)
    monkeypatch.setattr(runtime.inputs, 'is_rolling', lambda pub: 'rolling_snapshot' in pub.evidence)
    monkeypatch.setattr(runtime.authority, 'latest', lambda *_: value.authorities)
    monkeypatch.setattr(runtime.initial, '_context', lambda *_: {'observation_id': 'primary'})
    monkeypatch.setattr(runtime, '_closure', closure)
    monkeypatch.setattr(runtime.inputs, 'validate_status', lambda *_args, **_kwargs: (value.binding, object()))
    monkeypatch.setattr(runtime.publication, '_validate_publication', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(waiting.rolling_jobs, 'status', lambda *_: value.job)
    monkeypatch.setattr(waiting, '_worker', lambda *_args, **_kwargs: WORKER_END)
    return value


def observe(facts, *, now=NOW):
    return waiting.observe(facts.caller, decision_session='2026-10-27', observation_id='primary',
        starting_cash=50000, state_dir='/private-state', database_url=DSN, now=now)


def candidate(facts):
    facts.checkpoint = SimpleNamespace(session='2026-10-27', publication=facts.pub.to_dict(), snapshot=facts.binding)
    facts.result = SimpleNamespace(session='2026-10-27', state=SimpleNamespace(last_processed_session='2026-10-27'),
        record_sha256='b' * 64)
    facts.attested, facts.previous = None, facts.authority


@pytest.mark.parametrize('phase', ['AWAITING_SHADOW', 'AWAITING_ATTESTATION'])
def test_authenticated_direct_successor_can_wait_without_returning_strategy_result_or_authority(facts, phase):
    if phase == 'AWAITING_ATTESTATION':candidate(facts)
    proof = observe(facts)
    assert proof is not None and proof.quiet_eligible is True
    assert proof.phase == phase and proof.previous_session == '2026-10-26'
    assert proof.decision_session == '2026-10-27'
    assert proof.publication_version == 8 and proof.previous_publication_version == 7
    assert proof.publisher_deadline == PUBLISHER_END and proof.worker_deadline == WORKER_END
    assert proof.deadline == WORKER_END-timedelta(microseconds=1)
    assert not hasattr(proof, 'result') and not hasattr(proof, 'state') and not hasattr(proof, 'shadow_verdict')
    assert facts.calls.count('authenticated-closure') == 1
    assert facts.calls[-1] == 'owned-proof-ended'
    assert all('SELECT ' in sql and 'UPDATE ' not in sql for sql, _ in facts.owned.queries)


def test_current_authority_fast_path_does_not_repeat_canonical_closure_or_worker_observation(facts, monkeypatch):
    facts.authorities = [facts.authority.model_copy(update={'session': '2026-10-27'})]
    monkeypatch.setattr(waiting, '_worker', lambda *_args, **_kwargs: pytest.fail('worker read on current authority'))
    assert observe(facts) is None
    assert 'authenticated-closure' not in facts.calls and 'pinned' not in facts.calls


@pytest.mark.parametrize('damage', ['missing_authority', 'reconstruction', 'old_gap', 'authority_ahead',
    'same_session_replacement', 'wrong_previous_publication', 'nonrolling', 'checkpoint_session',
    'unattested_previous', 'wrong_state_cursor', 'wrong_job_state', 'wrong_job_version',
    'wrong_job_candidate', 'changed_request', 'wrong_request_predecessor', 'wrong_request_window',
    'job_before_close', 'bad_job_deadline'])
def test_missing_or_changed_canonical_and_publication_bindings_do_not_gain_pending_interpretation(facts, damage):
    if damage == 'missing_authority':facts.authorities = []
    elif damage == 'reconstruction':facts.authorities = [waiting.runtime.authority.ReconstructionReceipt.model_construct(
        session='2026-10-26')]
    elif damage == 'old_gap':facts.authorities = [facts.authority.model_copy(update={'session': '2026-10-23'})]
    elif damage == 'authority_ahead':facts.authorities = [facts.authority.model_copy(update={'session': '2026-10-28'})]
    elif damage == 'same_session_replacement':facts.checkpoint.publication = {**facts.pub.to_dict(), 'version': 7}
    elif damage == 'wrong_previous_publication':
        facts.pub = publication.Publication(8, 6, None,
            facts.pub.window_start, facts.pub.window_end, facts.pub.evidence)
        request = facts.request.model_copy(update={'expected_publication_version': 6})
        facts.job.update(request=request.model_dump(mode='json'), request_sha256=request.request_sha256)
    elif damage == 'nonrolling':facts.pub = publication.Publication(8, 7, None,
        facts.pub.window_start, facts.pub.window_end, {})
    elif damage == 'checkpoint_session':facts.checkpoint.session = '2026-10-23'
    elif damage == 'unattested_previous':facts.attested = None
    elif damage == 'wrong_state_cursor':facts.result.state.last_processed_session = '2026-10-23'
    elif damage == 'wrong_job_state':facts.job['state'] = 'READY'
    elif damage == 'wrong_job_version':facts.job['publication_version'] = 7
    elif damage == 'wrong_job_candidate':facts.job['candidate_id'] = 'foreign'
    elif damage == 'changed_request':facts.job['request_sha256'] = 'e' * 64
    elif damage == 'wrong_request_predecessor':
        request = facts.request.model_copy(update={'expected_publication_version': 6})
        facts.job.update(request=request.model_dump(mode='json'), request_sha256=request.request_sha256)
    elif damage == 'wrong_request_window':
        request = facts.request.model_copy(update={'window': PriceWindow.through('2026-10-26')})
        facts.job.update(request=request.model_dump(mode='json'), request_sha256=request.request_sha256)
    elif damage == 'job_before_close':facts.job['created_at'] = (CLOSE-timedelta(seconds=1)).isoformat()
    else:facts.job['deadline'] = 'not a clock'
    assert observe(facts) is None, 'invalid binding acquired preparation interpretation'


@pytest.mark.parametrize('failure', ['checkpoint_authentication', 'readiness', 'receipt_chain'])
def test_integrity_failures_remain_on_unchanged_strict_status_path(facts, monkeypatch, failure):
    def refused(*_args, **_kwargs):raise ValueError('authenticated input changed')
    if failure == 'checkpoint_authentication':monkeypatch.setattr(waiting.runtime, '_closure', refused)
    elif failure == 'readiness':monkeypatch.setattr(waiting.runtime.inputs, 'validate_status', refused)
    else:
        candidate(facts)
        monkeypatch.setattr(waiting.runtime.publication, '_validate_publication', refused)
    assert observe(facts) is None


@pytest.mark.parametrize('damage', ['replacement', 'prior_publication_changed', 'precommit_after_open',
    'precommit_before_close', 'record_changed', 'previous_record_changed'])
def test_candidate_pending_requires_exact_current_publication_and_original_precommit_chain(facts, damage):
    candidate(facts)
    if damage == 'replacement':facts.checkpoint.publication = {**facts.pub.to_dict(), 'version': 9}
    elif damage == 'prior_publication_changed':facts.authority = facts.authority.model_copy(
        update={'publication_sha256': 'f' * 64});facts.authorities = [facts.authority];facts.previous = facts.authority
    elif damage == 'precommit_after_open':facts.owned.timing['observed_at'] = facts.owned.timing['execution_open_at']
    elif damage == 'precommit_before_close':facts.owned.timing['observed_at'] = (CLOSE-timedelta(seconds=1)).isoformat()
    elif damage == 'record_changed':facts.owned.record_sha256 = 'c' * 64
    else:facts.owned.previous_record_sha256 = 'c' * 64
    assert observe(facts) is None


@pytest.mark.parametrize('candidate_committed', [False, True])
def test_valid_canonical_gap_with_no_live_worker_warns_without_permanent_refusal(facts, monkeypatch, candidate_committed):
    if candidate_committed:candidate(facts)
    def unavailable(*_args, **_kwargs):raise ValueError('worker idle, stale, expired or missing')
    monkeypatch.setattr(waiting, '_worker', unavailable)
    proof = observe(facts)
    assert proof is not None and proof.quiet_eligible is False
    assert proof.worker_deadline is None and proof.publisher_deadline == PUBLISHER_END


def test_expired_original_job_budget_cannot_be_renewed_by_a_healthy_worker(facts):
    facts.job['deadline'] = NOW.isoformat()
    proof = observe(facts)
    assert proof is not None and proof.quiet_eligible is False
    assert proof.publisher_deadline == NOW and proof.deadline < NOW


@pytest.mark.parametrize('now', [CLOSE-timedelta(seconds=1), calendar.session_window('2026-10-28')[0]])
def test_preparation_interpretation_stays_inside_actual_close_to_following_open(facts, now):
    assert observe(facts, now=now) is None


def test_direct_publication_predecessor_gate_has_a_falsifier(facts, monkeypatch):
    source = inspect.getsource(waiting._observe_owned)
    guard = 'pub.previous_version != prior_version'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'False'), '<missing-direct-predecessor>', 'exec'), vars(waiting), namespace)
    monkeypatch.setattr(waiting, '_observe_owned', namespace['_observe_owned'])
    with pytest.raises(AssertionError, match='invalid binding acquired'):
        test_missing_or_changed_canonical_and_publication_bindings_do_not_gain_pending_interpretation(
            facts, 'wrong_previous_publication')


@pytest.fixture
def worker_env(monkeypatch):
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', 'a' * 40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'b' * 64)
    monkeypatch.setenv('SENTINEL_DATABASE_URL', DSN)
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', 'primary')
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'isolated-preparation-proof-key-' * 3)


def worker_snapshot(*, started=CLOSE+timedelta(minutes=1), observed=NOW-timedelta(seconds=2),
                    deadline=WORKER_END, state='RUNNING', reason='ACTIVE_WORKER'):
    pending = {'schema': 'sentinel.shadow-supervisor-pending/3', 'attempt_id': 'a' * 32,
        'started_at_unix': started.timestamp(), 'runtime_binding_sha256': worker_status.binding(DSN),
        'boot_id': 'a' * 8+'-'+'a' * 4+'-'+'a' * 4+'-'+'a' * 4+'-'+'a' * 12,
        'supervisor_pid': 1, 'supervisor_start_ticks': 1, 'pid_namespace': 1}
    signed = {**pending, 'hmac_sha256': receipt_authentication.sign({
        'purpose': pending['schema'], 'pending': pending})}
    status = worker_status.Status(binding_sha256=worker_status.binding(DSN), incarnation='b' * 32,
        state=state, reason=reason, observed_at=observed, attempt_id='a' * 32, worker_deadline=deadline)
    payload = status.model_dump(mode='json', by_alias=True)
    return {'critical': False, 'pending': json.dumps(signed).encode(),
        'latest_pending': json.dumps(signed).encode(), 'status': json.dumps({
            'status': payload, 'hmac_sha256': worker_status._signature(payload)}).encode()}


def worker(monkeypatch, snapshot):
    calls = []
    def finite(function, *args, **kwargs):
        calls.append((function, args, kwargs))
        return snapshot
    monkeypatch.setattr(waiting.supervisor_io, 'run', finite)
    result = waiting._worker('/private-state', DSN, closed=CLOSE, now=NOW)
    assert calls[0][0] is waiting.shadow_service_probe.observe
    assert calls[0][2] == {'timeout': 2, 'start_method': 'spawn'}
    return result


def test_signed_current_worker_and_both_pending_snapshots_establish_only_original_deadline(worker_env, monkeypatch):
    assert worker(monkeypatch, worker_snapshot()) == WORKER_END


@pytest.mark.parametrize('damage', ['stale', 'expired', 'earlier_close', 'future_status',
    'different_pending', 'missing_pending', 'missing_latest', 'unsigned_pending', 'unsigned_status',
    'foreign_runtime', 'critical'])
def test_unfresh_unsigned_foreign_or_changed_worker_evidence_cannot_earn_quiet(worker_env, monkeypatch, damage):
    if damage == 'stale':snapshot = worker_snapshot(observed=NOW-timedelta(seconds=61))
    elif damage == 'expired':snapshot = worker_snapshot(deadline=NOW)
    elif damage == 'earlier_close':snapshot = worker_snapshot(started=CLOSE-timedelta(seconds=1))
    elif damage == 'future_status':snapshot = worker_snapshot(observed=NOW+timedelta(seconds=1))
    else:snapshot = worker_snapshot()
    if damage == 'different_pending':
        changed = json.loads(snapshot['latest_pending']);changed['attempt_id'] = 'c' * 32
        snapshot['latest_pending'] = json.dumps(changed).encode()
    elif damage == 'missing_pending':snapshot['pending'] = None
    elif damage == 'missing_latest':snapshot['latest_pending'] = None
    elif damage == 'unsigned_pending':
        value = json.loads(snapshot['pending']);value['hmac_sha256'] = '0' * 64
        snapshot['pending'] = snapshot['latest_pending'] = json.dumps(value).encode()
    elif damage == 'unsigned_status':
        value = json.loads(snapshot['status']);value['hmac_sha256'] = '0' * 64
        snapshot['status'] = json.dumps(value).encode()
    elif damage == 'foreign_runtime':monkeypatch.setenv('SENTINEL_GIT_COMMIT', 'c' * 40)
    elif damage == 'critical':snapshot['critical'] = True
    with pytest.raises((ValueError, KeyError, TypeError)):
        worker(monkeypatch, snapshot)


def test_current_worker_start_gate_has_a_falsifier(worker_env, monkeypatch):
    source = inspect.getsource(waiting._worker)
    guard = 'closed <= started <= observed <= now < deadline'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'started <= observed <= now < deadline'),
        '<missing-current-worker-start>', 'exec'), vars(waiting), namespace)
    monkeypatch.setattr(waiting, '_worker', namespace['_worker'])
    with pytest.raises(pytest.fail.Exception):
        test_unfresh_unsigned_foreign_or_changed_worker_evidence_cannot_earn_quiet(
            worker_env, monkeypatch, 'earlier_close')


@pytest.mark.parametrize('publisher_expired_during_probe', [False, True])
def test_real_observer_samples_completion_after_closure_and_new_signed_heartbeat(
        facts, worker_env, monkeypatch, publisher_expired_during_probe):
    clock = [NOW]
    monkeypatch.setattr(waiting, '_now', lambda: clock[0])
    original_closure = waiting.runtime._closure

    def closure(*args, **kwargs):
        result = original_closure(*args, **kwargs)
        clock[0] = NOW+timedelta(seconds=5)
        return result

    monkeypatch.setattr(waiting.runtime, '_closure', closure)
    monkeypatch.setattr(waiting, '_worker', REAL_WORKER)
    snapshot = worker_snapshot(observed=NOW+timedelta(seconds=9))

    def finite(*_args, **_kwargs):
        clock[0] = NOW+timedelta(seconds=10)
        return snapshot

    monkeypatch.setattr(waiting.supervisor_io, 'run', finite)
    original_publisher = NOW+timedelta(seconds=8) if publisher_expired_during_probe else PUBLISHER_END
    facts.job['deadline'] = original_publisher.isoformat()
    proof = waiting.observe(facts.caller, decision_session='2026-10-27', observation_id='primary',
        starting_cash=50000, state_dir='/private-state', database_url=DSN)
    assert proof is not None
    assert proof.observed_at == NOW+timedelta(seconds=10)
    assert proof.publisher_deadline == original_publisher and proof.worker_deadline == WORKER_END
    assert proof.quiet_eligible is (not publisher_expired_during_probe)


def test_explicit_observer_clock_does_not_follow_real_time_during_probe(facts, worker_env, monkeypatch):
    monkeypatch.setattr(waiting, '_now', lambda: pytest.fail('explicit clock used live wall time'))
    monkeypatch.setattr(waiting, '_worker', REAL_WORKER)
    snapshot = worker_snapshot(observed=NOW+timedelta(seconds=9))
    monkeypatch.setattr(waiting.supervisor_io, 'run', lambda *_args, **_kwargs: snapshot)
    proof = observe(facts)
    assert proof is not None and proof.quiet_eligible is False
    assert proof.observed_at == NOW and proof.publisher_deadline == PUBLISHER_END


@pytest.mark.parametrize('crossing', ['open', 'next_close'])
def test_completion_rechecks_actual_open_and_current_decision_without_renewing_deadlines(facts, monkeypatch, crossing):
    clock = [NOW]
    monkeypatch.setattr(waiting, '_now', lambda: clock[0])
    opened, closed = calendar.session_window('2026-10-28')

    def worker_advance(*_args, **_kwargs):
        clock[0] = (opened if crossing == 'open' else closed)+timedelta(seconds=1)
        return WORKER_END

    monkeypatch.setattr(waiting, '_worker', worker_advance)
    proof = waiting.observe(facts.caller, decision_session='2026-10-27', observation_id='primary',
        starting_cash=50000, state_dir='/private-state', database_url=DSN)
    if crossing == 'next_close':
        assert proof is None
    else:
        assert proof is not None and proof.quiet_eligible is False
        assert proof.observed_at == clock[0] and proof.deadline < clock[0]
        assert proof.publisher_deadline == PUBLISHER_END and proof.worker_deadline == WORKER_END


@pytest.mark.parametrize('quiet', [True, False, None])
def test_actual_refresh_waits_with_separate_clocks_or_keeps_original_refusal(monkeypatch, quiet):
    from sentinel import dual_reconciliation
    from sentinel.automation import schedule
    from sentinel.automation.model import AutomationConfig
    cycle = schedule.for_decision_session('2026-10-27', AutomationConfig())
    worker = object.__new__(automation_runtime.ProductionAutomation)
    closed = []
    worker.connect = lambda: SimpleNamespace(close=lambda: closed.append(True))
    worker._assert_cycle_authority = lambda *_args, **_kwargs: (cycle, None)
    worker._operational_source_only, worker._dual_run_enabled = False, True
    worker._shadow_observation_id, worker._shadow_starting_cash = 'primary', 50000
    worker.sentinel_config = SimpleNamespace(state_dir='/private-state', database_url=DSN)
    monkeypatch.setattr(automation_runtime.feed_store, 'require_feed_schema', lambda *_args: None)
    monkeypatch.setattr(automation_runtime.schema, 'require_runtime_schema', lambda *_args: None)
    monkeypatch.setattr(automation_runtime, 'require_observation_integrity', lambda *_args: None)
    monkeypatch.setattr(automation_runtime.feed_inputs, 'current', lambda *_args:
        SimpleNamespace(window_end='2026-10-27'))
    monkeypatch.setattr(automation_runtime.feed_inputs, 'is_rolling', lambda *_args: True)
    monkeypatch.setattr(automation_runtime.feed_inputs, 'require_shadow_mode', lambda *_args: None)
    monkeypatch.setattr(waiting, 'observe', lambda *_args, **_kwargs: None if quiet is None else
        SimpleNamespace(quiet_eligible=quiet, publisher_deadline=PUBLISHER_END, worker_deadline=WORKER_END))
    def refused(*_args, **_kwargs):
        raise dual_reconciliation.DualReconciliationRefused('original strict publication refusal')
    monkeypatch.setattr(dual_reconciliation, 'verified_shadow_intent', refused)
    expected = NonRetryableCallbackRefused if quiet is None else SourceDataPending
    with pytest.raises(expected) as failure:
        asyncio.run(worker.refresh(object()))
    if quiet is True:
        assert type(failure.value) is ClosingDataPending
        assert failure.value.publisher_deadline_at == PUBLISHER_END
        assert failure.value.worker_deadline_at == WORKER_END
    elif quiet is False:
        assert type(failure.value) is SourceDataPending
    assert closed == [True]
