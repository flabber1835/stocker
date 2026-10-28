"""Only positive current closing-data waits suppress ordinary retry notices."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest

from sentinel import automation_runtime as runtime
from sentinel.automation import closing_data_notifications as policy, outbox, service
from sentinel.automation.model import (
    AutomationConfig, ClosingDataPending, CycleState, SoftwareDefect,
    SourceDataPending, TransientInfrastructureFailure,
)
from sentinel.dual_reconciliation import DualReconciliationPending
from sentinel.feed.rolling_go_inputs import RollingSourceFrontierPending
from sentinel.shadow_runtime import ShadowRuntimeRefused
from tests.sentinel.test_automation_service_fault_paths import child, scheduled_record


def closing_cycle(day=date(2026, 10, 27)):
    cfg = AutomationConfig()
    cycle, permit = scheduled_record(cfg, CycleState.REFRESHING_DATA, decision_session=day)
    return cfg, cycle, permit


def quiet_detail():
    _cfg, cycle, _permit = closing_cycle()
    observed = cycle.decision_close_at + timedelta(minutes=2)
    retry = observed + timedelta(seconds=30)
    marker = policy.marker(cycle=cycle, observed_at=observed, next_retry_at=retry)
    assert marker is not None
    return {'failure_code': 'ClosingDataPending', 'next_wake_at': retry.isoformat(),
        'diagnostic': {'notifier_action': 'RETRY_SCHEDULED', 'retry_phase': 'REFRESH',
            'callback_failure': 'SOURCE_DATA_PENDING', 'exception_type': policy.EXCEPTION_TYPE,
            'latest_failure_at': observed.isoformat(), 'next_retry_at': retry.isoformat(),
            'first_failure_at': observed.isoformat(), 'closing_data_wait': marker}}


@pytest.mark.parametrize('day', [date(2026, 10, 27), date(2026, 10, 30), date(2026, 11, 27)])
def test_marker_uses_actual_close_and_following_open_across_dst_and_half_day(day):
    _cfg, cycle, _permit = closing_cycle(day)
    observed = cycle.decision_close_at + timedelta(minutes=1)
    marker = policy.marker(cycle=cycle, observed_at=observed,
        next_retry_at=observed + timedelta(seconds=30))
    assert marker is not None
    assert datetime.fromisoformat(marker['decision_close_at']) == cycle.decision_close_at
    assert datetime.fromisoformat(marker['execution_open_at']) == cycle.execution_open_at
    assert marker['effective_session'] == cycle.effective_session.isoformat()


@pytest.mark.parametrize('damage', ['before_close', 'at_open', 'retry_at_open', 'retry_after_open',
    'close_changed', 'open_changed', 'effective_changed', 'prepare_changed', 'missing_clock'])
def test_marker_refuses_unverified_cycle_or_deadline_risk(damage):
    _cfg, cycle, _permit = closing_cycle()
    observed = cycle.decision_close_at + timedelta(minutes=2)
    retry = observed + timedelta(seconds=30)
    if damage == 'before_close':observed = cycle.decision_close_at - timedelta(seconds=1)
    elif damage == 'at_open':observed, retry = cycle.execution_open_at, cycle.execution_open_at + timedelta(seconds=30)
    elif damage == 'retry_at_open':retry = cycle.execution_open_at
    elif damage == 'retry_after_open':retry = cycle.execution_open_at + timedelta(seconds=1)
    elif damage == 'close_changed':cycle = cycle.model_copy(update={'decision_close_at': observed})
    elif damage == 'open_changed':cycle = cycle.model_copy(update={'execution_open_at': retry})
    elif damage == 'effective_changed':cycle = cycle.model_copy(update={'effective_session': date(2026, 10, 29)})
    elif damage == 'prepare_changed':cycle = cycle.model_copy(update={'prepare_at': cycle.execution_open_at})
    else:cycle = cycle.model_copy(update={'execution_close_at': None})
    assert policy.marker(cycle=cycle, observed_at=observed, next_retry_at=retry) is None


def test_original_publisher_deadline_cannot_be_renewed_or_crossed_by_retry():
    _cfg, cycle, _permit = closing_cycle()
    observed = cycle.decision_close_at + timedelta(minutes=2)
    retry = observed + timedelta(seconds=30)
    for deadline in (observed - timedelta(seconds=1), observed, retry):
        assert policy.marker(cycle=cycle, observed_at=observed, next_retry_at=retry,
            publisher_deadline_at=deadline) is None
    marker = policy.marker(cycle=cycle, observed_at=observed, next_retry_at=retry,
        publisher_deadline_at=retry + timedelta(seconds=1))
    assert marker['publisher_deadline_at'] == (retry + timedelta(seconds=1)).isoformat()


def test_original_worker_deadline_is_separate_and_cannot_be_crossed_by_retry():
    _cfg, cycle, _permit = closing_cycle()
    observed = cycle.decision_close_at + timedelta(minutes=2)
    retry = observed + timedelta(seconds=30)
    publisher = retry + timedelta(hours=1)
    assert policy.marker(cycle=cycle, observed_at=observed, next_retry_at=retry,
        publisher_deadline_at=publisher, worker_deadline_at=retry) is None
    marker = policy.marker(cycle=cycle, observed_at=observed, next_retry_at=retry,
        publisher_deadline_at=publisher, worker_deadline_at=retry+timedelta(seconds=1))
    assert marker['publisher_deadline_at'] == publisher.isoformat()
    assert marker['worker_deadline_at'] == (retry+timedelta(seconds=1)).isoformat()


def test_worker_deadline_gate_has_a_falsifier(monkeypatch):
    source = inspect.getsource(policy._valid)
    needle = 'quiet_until = min(quiet_until, _instant(worker_deadline))'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'quiet_until = quiet_until'),
        'missing-closing-worker-deadline', 'exec'), vars(policy), namespace)
    monkeypatch.setattr(policy, '_valid', namespace['_valid'])
    with pytest.raises(AssertionError):
        test_original_worker_deadline_is_separate_and_cannot_be_crossed_by_retry()


def test_publisher_deadline_gate_has_a_falsifier(monkeypatch):
    source = inspect.getsource(policy._valid)
    needle = 'quiet_until = min(opened, _instant(publisher_deadline)) if publisher_deadline is not None else opened'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'quiet_until = opened'),
        'missing-closing-publisher-deadline', 'exec'), vars(policy), namespace)
    monkeypatch.setattr(policy, '_valid', namespace['_valid'])
    with pytest.raises(AssertionError):
        test_original_publisher_deadline_cannot_be_renewed_or_crossed_by_retry()


def test_exact_event_marker_suppresses_only_its_durable_retry():
    detail = quiet_detail()
    assert policy.quiet_event(detail, state='RETRY_WAIT')
    assert outbox._cycle_event_alert((1, 'cycle', 'RETRY_WAIT', 1, 1, detail)) is None
    assert not policy.quiet_event(detail, state='BLOCKED')


@pytest.mark.parametrize('damage', ['generic_type', 'generic_failure_code', 'other_phase',
    'infrastructure', 'missing_marker', 'missing_clock', 'changed_wake', 'changed_latest',
    'invalid_marker_schema', 'retry_at_open'])
def test_quiet_classification_cannot_hide_other_causes_or_inconsistent_event(damage):
    detail = quiet_detail()
    diagnostic = detail['diagnostic']
    if damage == 'generic_type':diagnostic['exception_type'] = 'sentinel.automation.model.SourceDataPending'
    elif damage == 'generic_failure_code':detail['failure_code'] = 'SourceDataPending'
    elif damage == 'other_phase':diagnostic['retry_phase'] = 'PREPARE'
    elif damage == 'infrastructure':diagnostic['callback_failure'] = 'TRANSIENT_INFRASTRUCTURE'
    elif damage == 'missing_marker':diagnostic.pop('closing_data_wait')
    elif damage == 'missing_clock':detail.pop('next_wake_at')
    elif damage == 'changed_wake':detail['next_wake_at'] = '2026-10-27T21:00:00+00:00'
    elif damage == 'changed_latest':diagnostic['latest_failure_at'] = '2026-10-27T21:00:00+00:00'
    elif damage == 'invalid_marker_schema':diagnostic['closing_data_wait']['schema'] = 'unknown'
    else:
        opened = diagnostic['closing_data_wait']['execution_open_at']
        diagnostic['closing_data_wait']['next_retry_at'] = opened
        diagnostic['next_retry_at'] = detail['next_wake_at'] = opened
    alert = outbox._cycle_event_alert((1, 'cycle', 'RETRY_WAIT', 1, 1, detail))
    assert alert is not None and alert['severity'] == 'WARN'


def test_source_type_notification_guard_has_a_falsifier(monkeypatch):
    source = inspect.getsource(policy.quiet_event)
    needle = "diagnostic.get('exception_type') == EXCEPTION_TYPE"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'True'), 'missing-closing-source-type', 'exec'),
        vars(policy), namespace)
    monkeypatch.setattr(policy, 'quiet_event', namespace['quiet_event'])
    with pytest.raises(AssertionError):
        test_quiet_classification_cannot_hide_other_causes_or_inconsistent_event('generic_type')


@pytest.mark.parametrize('exception,phase,quiet', [
    (ClosingDataPending('closing frontier pending'), 'REFRESH', True),
    (SourceDataPending('invalid provider row'), 'REFRESH', False),
    (TransientInfrastructureFailure('database unavailable'), 'REFRESH', False),
    (ClosingDataPending('closing frontier pending'), 'PREPARE', False),
    (ClosingDataPending('publisher attempt expired',
        publisher_deadline_at=datetime(2026, 10, 27, tzinfo=timezone.utc)), 'REFRESH', False),
])
def test_service_persists_positive_classification_only_for_reviewed_refresh_wait(monkeypatch, exception, phase, quiet):
    cfg, cycle, permit = closing_cycle()
    events = []

    def transition(_conn, **changes):
        events.append(deepcopy(changes))
        return cycle.model_copy(update={'state': changes['to_state'], 'diagnostic': changes['diagnostic']})

    monkeypatch.setattr(service.store, 'transition_cycle', transition)
    worker = service.AutomationService(config=cfg, holder_id='quiet-test', refresh=None,
        prepare=None, execute=None, recover=None)
    worker._handle_callback_failure(object(), now=cycle.decision_close_at + timedelta(minutes=2),
        cycle=cycle, permit=permit, phase=phase, exc=exception)
    detail = events[0]
    assert ('closing_data_wait' in detail['diagnostic']) is quiet
    assert policy.quiet_event(detail, state='RETRY_WAIT') is quiet
    assert detail['failure_code'] == type(exception).__name__


@pytest.mark.parametrize('has_deadlines', [True, False])
def test_closing_exception_and_original_job_deadline_survive_actual_child_codec(monkeypatch, has_deadlines):
    deadline = datetime(2026, 10, 27, 22, 2, 40, tzinfo=timezone.utc) if has_deadlines else None
    worker_deadline = deadline-timedelta(minutes=1) if deadline is not None else None

    async def callback(_context):
        raise ClosingDataPending('publication has the source pin',
            retry_after_seconds=17, publisher_deadline_at=deadline,
            worker_deadline_at=worker_deadline)

    channel = child(monkeypatch, callback)
    envelope = json.loads(channel.payloads[0])
    assert envelope['publisher_deadline_at'] == (deadline.isoformat() if deadline is not None else None)
    assert envelope['worker_deadline_at'] == (worker_deadline.isoformat() if worker_deadline is not None else None)
    with pytest.raises(ClosingDataPending) as failure:
        service._decode_child_callback(channel.payloads[0])
    assert type(failure.value) is ClosingDataPending
    assert failure.value.publisher_deadline_at == deadline
    assert failure.value.worker_deadline_at == worker_deadline
    assert failure.value.retry_after_seconds == 17


def test_unreviewed_closing_exception_subclass_cannot_acquire_quiet_type_through_child(monkeypatch):
    class UnknownClosing(ClosingDataPending):
        pass

    async def callback(_context):
        raise UnknownClosing('unreviewed', publisher_deadline_at=datetime(2026, 10, 27, tzinfo=timezone.utc))

    channel = child(monkeypatch, callback)
    with pytest.raises(SourceDataPending) as failure:
        service._decode_child_callback(channel.payloads[0])
    assert type(failure.value) is SourceDataPending


@pytest.mark.parametrize('deadline', ['2026-10-27T22:02:40', 'unknown', 17, True])
def test_child_invalid_publisher_deadline_is_a_defect_not_quiet_wait(deadline):
    envelope = {'kind': 'error', 'reviewed': True, 'module': ClosingDataPending.__module__,
        'qualname': ClosingDataPending.__qualname__, 'publisher_deadline_at': deadline}
    with pytest.raises(SoftwareDefect, match='invalid publisher deadline'):
        service._decode_child_callback(json.dumps(envelope).encode())


@pytest.mark.parametrize('deadline', ['2026-10-27T22:02:40', 'unknown', 17, True])
def test_child_invalid_worker_deadline_is_a_defect_not_quiet_wait(deadline):
    envelope = {'kind': 'error', 'reviewed': True, 'module': ClosingDataPending.__module__,
        'qualname': ClosingDataPending.__qualname__, 'worker_deadline_at': deadline}
    with pytest.raises(SoftwareDefect, match='invalid worker deadline'):
        service._decode_child_callback(json.dumps(envelope).encode())


def test_only_bounded_reviewed_explicit_frontier_cause_chain_gets_closing_type():
    def classify(failure):
        return runtime._closing_frontier_wait(failure,
            frontier='2026-10-26', decision_session='2026-10-27')

    native = RollingSourceFrontierPending('source-final frontier')
    wrapped = ShadowRuntimeRefused('shadow waiting')
    wrapped.__cause__ = native
    outer = DualReconciliationPending('paper waiting')
    outer.__cause__ = wrapped
    assert type(classify(outer)) is ClosingDataPending
    for failure in (DualReconciliationPending('handover approval pending'),
                    DualReconciliationPending('has not attested the decision close')):
        failure.__context__ = native
        assert type(classify(failure)) is SourceDataPending
    unknown = RuntimeError('unreviewed wrapper')
    unknown.__cause__ = native
    outer.__cause__ = unknown
    assert type(classify(outer)) is SourceDataPending
    outer.__cause__ = outer
    assert type(classify(outer)) is SourceDataPending
    current = native
    for _ in range(8):
        wrapper = DualReconciliationPending('deep')
        wrapper.__cause__, current = current, wrapper
    assert type(classify(current)) is SourceDataPending


@pytest.mark.parametrize('frontier', [None, 'unknown', '2026-10-23', '2026-10-27', '2026-10-28'])
def test_typed_rolling_wait_cannot_quiet_an_unproven_or_multiple_missing_close(frontier):
    failure = DualReconciliationPending('waiting for source-final data')
    failure.__cause__ = RollingSourceFrontierPending('source-final frontier')
    assert type(runtime._closing_frontier_wait(failure,
        frontier=frontier, decision_session='2026-10-27')) is SourceDataPending


def test_rolling_frontier_guard_has_a_falsifier(monkeypatch):
    source = inspect.getsource(runtime._closing_frontier_wait)
    needle = 'calendar.next_session(str(frontier)) != str(decision_session)'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'False'), 'missing-one-close-frontier', 'exec'),
        vars(runtime), namespace)
    monkeypatch.setattr(runtime, '_closing_frontier_wait', namespace['_closing_frontier_wait'])
    with pytest.raises(AssertionError):
        test_typed_rolling_wait_cannot_quiet_an_unproven_or_multiple_missing_close('2026-10-23')


@pytest.mark.parametrize('frontier,quiet', [('2026-10-26', True), ('2026-10-23', False), (None, False)])
def test_actual_rolling_refresh_binds_native_wait_to_already_read_publication(monkeypatch, frontier, quiet):
    from sentinel import dual_reconciliation

    _cfg, cycle, _permit = closing_cycle()
    closed = []
    worker = object.__new__(runtime.ProductionAutomation)
    worker.connect = lambda: SimpleNamespace(close=lambda: closed.append(True))
    worker._assert_cycle_authority = lambda *_args, **_kwargs: (cycle, None)
    worker._operational_source_only = False
    worker._dual_run_enabled = True
    worker._shadow_observation_id = 'test-observation'
    worker._shadow_starting_cash = 1
    monkeypatch.setattr(runtime.feed_store, 'require_feed_schema', lambda _conn: None)
    monkeypatch.setattr(runtime.schema, 'require_runtime_schema', lambda _conn: None)
    monkeypatch.setattr(runtime, 'require_observation_integrity', lambda _conn: None)
    monkeypatch.setattr(runtime.feed_inputs, 'current', lambda _conn:
        SimpleNamespace(window_end=frontier))
    monkeypatch.setattr(runtime.feed_inputs, 'is_rolling', lambda _current: True)
    monkeypatch.setattr(runtime.feed_inputs, 'require_shadow_mode', lambda *_args: None)

    def pending(*_args, **_kwargs):
        raise DualReconciliationPending('source-final data pending') from RollingSourceFrontierPending('native frontier')

    monkeypatch.setattr(dual_reconciliation, 'verified_shadow_intent', pending)
    with pytest.raises(SourceDataPending) as failure:
        asyncio.run(worker.refresh(object()))
    assert (type(failure.value) is ClosingDataPending) is quiet
    assert closed == [True]


@pytest.mark.parametrize('frontier,decision,quiet', [
    ('2026-10-26', '2026-10-27', True), ('2026-10-23', '2026-10-27', False),
    ('2026-10-28', '2026-10-27', False), ('unknown', '2026-10-27', False)])
def test_dedicated_publisher_wait_is_quiet_only_for_one_missing_close(frontier, decision, quiet):
    assert (type(runtime._dedicated_publisher_wait(frontier, decision)) is ClosingDataPending) is quiet


@pytest.mark.parametrize('proof_kind', ['live', 'absent', 'other_session', 'unreadable'])
def test_refresh_contention_needs_exact_type_and_matching_fresh_publication_proof(monkeypatch, proof_kind):
    from sentinel import source_publication_wait
    from sentinel.feed.publication import CorpusLockUnavailable

    cfg, cycle, _permit = closing_cycle()
    observed = cycle.decision_close_at + timedelta(minutes=2)
    deadline = observed + timedelta(hours=2)
    calls = []

    def observe(database_url, *, decision_session):
        calls.append((database_url, decision_session))
        if proof_kind == 'unreadable':raise OSError('probe unavailable')
        if proof_kind == 'absent':return None
        return source_publication_wait.PublicationWaitProof(
            decision_session if proof_kind == 'live' else '2026-10-26',
            deadline - timedelta(microseconds=1), deadline, observed)

    monkeypatch.setattr(source_publication_wait, 'observe', observe)
    actual = runtime._publication_closing_wait(CorpusLockUnavailable('publication busy'),
        database_url='private-test-db', cycle=cycle)
    assert (actual is not None) is (proof_kind == 'live')
    if actual is not None:assert actual.publisher_deadline_at == deadline
    assert calls == [('private-test-db', '2026-10-27')]
    calls.clear()
    assert runtime._publication_closing_wait(RuntimeError('snapshot reader cannot pin during publication or retirement'),
        database_url='private-test-db', cycle=cycle) is None
    assert not calls


def test_actual_refresh_translates_only_confirmed_publication_pin_and_preserves_caller_connection(monkeypatch):
    from sentinel import source_publication_wait
    from sentinel.feed.publication import CorpusLockUnavailable

    _cfg, cycle, _permit = closing_cycle()
    observed = cycle.decision_close_at + timedelta(minutes=2)
    deadline = observed + timedelta(hours=2)
    closed = []
    conn = SimpleNamespace(close=lambda: closed.append(True),
        rollback=lambda: pytest.fail('notification proof rolled back the financial connection'))
    worker = object.__new__(runtime.ProductionAutomation)
    worker.sentinel_config = SimpleNamespace(database_url='private-test-db')
    worker.connect = lambda: conn
    worker._assert_cycle_authority = lambda *_args, **_kwargs: (cycle, None)
    monkeypatch.setattr(runtime.feed_store, 'require_feed_schema', lambda _conn: None)
    monkeypatch.setattr(runtime.schema, 'require_runtime_schema', lambda _conn: None)
    monkeypatch.setattr(runtime, 'require_observation_integrity', lambda _conn: None)

    def pin(_conn):
        raise CorpusLockUnavailable('publication busy')

    monkeypatch.setattr(runtime.feed_inputs, 'current', pin)
    monkeypatch.setattr(source_publication_wait, 'observe', lambda *_args, **_kwargs:
        source_publication_wait.PublicationWaitProof('2026-10-27', deadline, deadline, observed))
    with pytest.raises(ClosingDataPending) as failure:
        asyncio.run(worker.refresh(object()))
    assert failure.value.publisher_deadline_at == deadline and closed == [True]


@pytest.mark.parametrize('proof_kind', ['live', 'absent', 'other_session', 'unreadable'])
def test_real_early_authority_wrapper_keeps_the_closing_cycle(monkeypatch, proof_kind):
    from sentinel import source_publication_wait
    from sentinel.feed.publication import CorpusLockUnavailable

    cfg, cycle, permit = closing_cycle()
    conn = SimpleNamespace(close=lambda: None, rollback=lambda: None)
    worker = object.__new__(runtime.ProductionAutomation)
    worker.automation_config = cfg
    worker.sentinel_config = SimpleNamespace(database_url='private-test-db')
    worker.connect = lambda: conn
    monkeypatch.setattr(runtime.feed_store, 'require_feed_schema', lambda _c: None)
    monkeypatch.setattr(runtime.schema, 'require_runtime_schema', lambda _c: None)
    monkeypatch.setattr(runtime, 'require_observation_integrity', lambda _c: None)
    monkeypatch.setattr(runtime.store, 'require_leader', lambda *_a: permit)
    monkeypatch.setattr(runtime.store, 'load_control', lambda _c: SimpleNamespace(
        binding=object(), generation=permit.control_generation, config_sha256=cfg.fingerprint))
    monkeypatch.setattr(runtime, 'load_rollout_state', lambda _c: object())
    native = CorpusLockUnavailable('snapshot reader cannot pin during publication or retirement')
    def busy(_c):
        raise native
    monkeypatch.setattr(runtime.feed_inputs, 'require_current', busy)
    observed = cycle.decision_close_at + timedelta(minutes=2)
    deadline = observed + timedelta(hours=2)
    def proof(*_a, **_kw):
        if proof_kind == 'unreadable':raise OSError('probe unavailable')
        if proof_kind == 'absent':return None
        return source_publication_wait.PublicationWaitProof(
            str(cycle.decision_session) if proof_kind == 'live' else '2026-10-26',
            deadline-timedelta(microseconds=1), deadline, observed)
    monkeypatch.setattr(source_publication_wait, 'observe', proof)
    with pytest.raises(TransientInfrastructureFailure) as failure:
        asyncio.run(worker.refresh(SimpleNamespace(cycle=cycle, permit=permit,
                                                  require_active=lambda: None)))
    assert (type(failure.value) is ClosingDataPending) is (proof_kind == 'live')
    if proof_kind == 'live':assert failure.value.publisher_deadline_at == deadline


@pytest.mark.parametrize('damage', ['different_detail', 'unreviewed_wrapper', 'no_cause'])
def test_only_the_exact_reviewed_lock_wrapper_can_be_quiet(monkeypatch, damage):
    from sentinel.feed.publication import CorpusLockUnavailable
    from sentinel import source_publication_wait
    _cfg, cycle, _permit = closing_cycle()
    native = CorpusLockUnavailable('publication busy')
    wrapped = runtime.classify_dependency_failure(native)
    if damage == 'different_detail':wrapped = TransientInfrastructureFailure('unrelated failure')
    if damage == 'unreviewed_wrapper':wrapped = RuntimeError(str(wrapped))
    if damage != 'no_cause':wrapped.__cause__ = native
    monkeypatch.setattr(source_publication_wait, 'observe', lambda *_a, **_kw:
                        pytest.fail('unreviewed exception reached quiet proof'))
    assert runtime._publication_closing_wait(wrapped, database_url='private-test-db', cycle=cycle) is None
