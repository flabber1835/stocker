"""A missed old open remains visible without claiming a present trading halt."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import inspect

import pytest

from sentinel.automation.model import AutomationRefused, CycleState
from sentinel.panel import model, observer_codec, sources


NOW = datetime(2026, 11, 24, 16, tzinfo=timezone.utc)
OLD = NOW - timedelta(hours=1)
NEXT = NOW + timedelta(hours=5)
BOUND = NOW + timedelta(seconds=20)


def _wait():
    return model.RecoveryEvidence(
        phase='AWAITING_NEXT_DECISION', automatic=True,
        next_attempt_at=NOW + timedelta(seconds=5), deadline=BOUND)


def _paper():
    return model.Row(
        'paper_reconciliation', 'Paper mirror', 'OPEN MISSED', model.WARN,
        as_of=OLD, required_current=True, valid_until=BOUND,
        recovery=_wait(), paper_alignment='MISSED_OPEN_UNATTENDED',
        next_eligible_decision_at=NEXT,
        operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION', state='PENDING'))


def _rows():
    cycle = dict(
        cycle_id='old-cycle', state='SUPERSEDED',
        failure_code='CONTROL_GENERATION_SUPERSEDED',
        decision_session='2026-11-23', effective_session='2026-11-24',
        updated_at=OLD, completed_at=OLD)
    old = model.automation_cycle_row(installed=True, enabled=True, **cycle)
    steps = model.automation_step_rows(installed=True, enabled=True, cycle=cycle,
        events=[dict(to_state='PLAN_READY', at=OLD-timedelta(minutes=5))])
    return [
        _paper(), old, *steps,
        model.Row('broker', 'Broker', '0 positions · 0 working', model.OK,
                  as_of=OLD-timedelta(minutes=15),
                  valid_until=OLD-timedelta(minutes=5), required_current=True,
                  broker_working_orders=0, broker_active_commands=0,
                  broker_uncertain_commands=0),
        *[model.Row(key, key, 'READY', model.OK, as_of=NOW,
                    valid_until=BOUND, required_current=True)
          for key in ('automation', 'automation_leader', 'authority', 'alpaca_account')],
    ]


def test_exact_signed_missed_open_is_bounded_and_old_trial_remains_failed():
    from sentinel.panel import read_projection

    paper = _paper()
    decoded = observer_codec.row_from_observation(
        observer_codec.pack([paper], [], observed_at=NOW)['rows'][0])
    assert decoded.effective_status(NOW) == model.WARN
    assert decoded.next_eligible_decision_at == NEXT
    assert decoded.effective_status(BOUND + timedelta(microseconds=1)) == model.FAIL
    receipt_row = read_projection._json_row(paper)
    assert receipt_row['next_eligible_decision_at'] == NEXT.isoformat()
    assert read_projection._decode_row(receipt_row).next_eligible_decision_at == NEXT
    with pytest.raises(ValueError, match='alignment fact'):
        observer_codec.row_from_observation({
            **observer_codec.pack([paper], [], observed_at=NOW)['rows'][0],
            'next_eligible_decision_at': None})

    rows = sources._project_missed_open_idle(_rows(), now=NOW, source_errors=[])
    keyed = {row.key: row for row in rows}
    assert {key for key, row in keyed.items() if row.status == model.WARN} == {
        'paper_reconciliation', 'automation_cycle', 'automation_step_open',
        'automation_step_complete', 'broker'}
    assert keyed['broker'].is_stale(NOW)
    assert keyed['broker'].effective_status(NOW) == model.WARN
    assert model.Panel(rows=rows, now=NOW).operational == model.WARN
    assert keyed['automation_cycle'].effective_status(BOUND + timedelta(microseconds=1)) == model.FAIL

    failed = model.trial_verification_row(
        verdict='NOT_VERIFIED', session='2026-11-23',
        reason_codes=('CURRENT_CYCLE_CONTROL_GENERATION_SUPERSEDED',))
    assert failed.status == model.FAIL
    assert failed.trial_reason_codes == ('CURRENT_CYCLE_CONTROL_GENERATION_SUPERSEDED',)

    generated_reasons = sources._current_trial_operational_failures(
        latest_session=date(2026, 11, 23),
        control=SimpleNamespace(enabled=True, kill_switch_engaged=False),
        cycle=SimpleNamespace(effective_session=date(2026, 11, 24),
            state='SUPERSEDED', failure_code='CONTROL_GENERATION_SUPERSEDED',
            failure_detail='old pre-transport plan retired',
            execution_close_at=NEXT))
    assert tuple(generated_reasons) == failed.trial_reason_codes


def test_later_clean_idle_broker_snapshot_does_not_revive_old_panic():
    rows = _rows()
    rows = [replace(row, as_of=NOW-timedelta(minutes=1),
                    valid_until=NOW+timedelta(minutes=9))
            if row.key == 'broker' else row for row in rows]
    result = {row.key: row for row in sources._project_missed_open_idle(
        rows, now=NOW, source_errors=[])}
    assert result['automation_cycle'].effective_status(NOW) == model.WARN
    assert result['broker'].effective_status(NOW) == model.OK


@pytest.mark.parametrize('fault', [
    'unsigned', 'expired', 'wrong_cycle', 'leader', 'authority', 'account',
    'broker_hazard', 'broker_working', 'broker_command', 'broker_unknown',
    'active_run', 'missing_step', 'source_error',
])
def test_missed_open_does_not_hide_an_unproved_or_current_stop(fault):
    rows = _rows()
    source_errors = []
    keyed = {row.key: row for row in rows}
    if fault == 'unsigned':
        keyed['paper_reconciliation'] = replace(keyed['paper_reconciliation'],
            paper_alignment=None)
    elif fault == 'expired':
        keyed['paper_reconciliation'] = replace(keyed['paper_reconciliation'],
            valid_until=NOW-timedelta(seconds=1))
    elif fault == 'wrong_cycle':
        keyed['automation_cycle'] = replace(keyed['automation_cycle'],
            as_of=OLD+timedelta(seconds=1))
    elif fault in {'leader', 'authority', 'account'}:
        key = {'leader': 'automation_leader', 'authority': 'authority',
               'account': 'alpaca_account'}[fault]
        keyed[key] = replace(keyed[key], status=model.FAIL)
    elif fault == 'broker_hazard':
        keyed['broker'] = replace(keyed['broker'], status=model.FAIL)
    elif fault in {'broker_working', 'broker_command', 'broker_unknown'}:
        field = {'broker_working': 'broker_working_orders',
                 'broker_command': 'broker_active_commands',
                 'broker_unknown': 'broker_uncertain_commands'}[fault]
        keyed['broker'] = replace(keyed['broker'], **{field: 1})
    elif fault == 'active_run':
        keyed['trading_run'] = model.Row('trading_run', 'Run', 'EXECUTING', model.WARN)
    elif fault == 'missing_step':
        del keyed['automation_step_open']
    elif fault == 'source_error':
        source_errors = ['financial source unavailable']
    result = sources._project_missed_open_idle(
        list(keyed.values()), now=NOW, source_errors=source_errors)
    assert next(row for row in result if row.key == 'automation_cycle').status == model.FAIL
    assert next(row for row in result if row.key == 'broker').effective_status(NOW) == model.FAIL


def _safe_case(monkeypatch):
    from sentinel import local_paper
    from sentinel.automation import env_config, health, store, unsent_recovery
    from sentinel.automation.model import AutomationConfig

    default_config = AutomationConfig()
    monkeypatch.setattr(env_config, 'config_from_env', lambda: default_config)

    cycle = dict(cycle_id='old-cycle', state='SUPERSEDED',
        failure_code='CONTROL_GENERATION_SUPERSEDED', attempt_count=0,
        updated_at=OLD, terminal_reason=None)
    previous = SimpleNamespace(
        cycle_id='old-cycle', state=CycleState.SUPERSEDED,
        failure_code='CONTROL_GENERATION_SUPERSEDED', attempt_count=0,
        historical_state_only=False,
        updated_at=OLD, control_generation=4,
        deployment_id='paper-deployment', broker='alpaca',
        broker_account_id='paper-1', takeover_epoch=1,
        config_sha256=default_config.fingerprint,
        decision_session=date(2026, 11, 23),
        effective_session=date(2026, 11, 24),
        diagnostic={'adopting_control_generation': 5,
                    'originating_control_generation': 4})
    control = SimpleNamespace(
        generation=5, broker='alpaca', broker_account_id='paper-1',
        takeover_epoch=1, binding=SimpleNamespace(
            deployment_id='paper-deployment', broker='alpaca',
            broker_account_id='paper-1', takeover_epoch=1),
        config_sha256=default_config.fingerprint)
    current = SimpleNamespace(
        database_now=NOW, healthy=True, operational_ready=True,
        policy_state='LEADER_ACTIVE', leader_active=True,
        service_heartbeat_fresh=True, authority_verdict='PASS',
        authority_lifecycle_current=True,
        latest_cycle_id='old-cycle', latest_cycle_state='SUPERSEDED',
        latest_failure_code='CONTROL_GENERATION_SUPERSEDED',
        broker_outcome_unresolved=0, control_generation=5,
        config_sha256=default_config.fingerprint,
        broker='alpaca', broker_account_id='paper-1', takeover_epoch=1,
        leader_holder='worker-1', leader_expires_at=BOUND)
    observation = dict(completeness='COMPLETE', runtime_state='RUNNING',
        observed_at=OLD, orders=[])
    monkeypatch.setattr(local_paper, 'require_bound_account', lambda _c: True)
    monkeypatch.setattr(health, 'read_health', lambda *_a, **_k: current)
    monkeypatch.setattr(store, 'load_control', lambda _c: control)
    monkeypatch.setattr(store, 'load_cycle', lambda _c, _id: previous)
    monkeypatch.setattr(unsent_recovery, 'require_unsent', lambda *_a, **_k: None)
    monkeypatch.setattr(sources, '_active_commands', lambda _c: {'counts': {}})
    monkeypatch.setattr(sources, '_latest_observation', lambda _c: observation)
    monkeypatch.setattr(sources, '_latest_account_evidence',
        lambda _c: {'observed_at': NOW})
    monkeypatch.setattr(model, 'alpaca_account_row', lambda **_k: model.Row(
        'alpaca_account', 'Account', 'READY', model.OK,
        as_of=NOW, valid_until=NOW+timedelta(minutes=10)))
    monkeypatch.setattr(sources, '_latest_automation_instance', lambda *_a, **_k: {
        'instance_id': 'worker-1', 'state': 'WAITING',
        'heartbeat_at': NOW-timedelta(seconds=1),
        'next_wake_at': NOW+timedelta(seconds=5), 'last_error': None})
    return cycle, current


def test_safe_supersession_requires_exact_current_owner_and_unsent_proof(monkeypatch):
    from sentinel.automation import health, unsent_recovery

    cycle, current = _safe_case(monkeypatch)
    observation = dict(completeness='COMPLETE', runtime_state='RUNNING',
                       observed_at=OLD, orders=[])
    assert sources._recoverable_superseded_wait(object(), cycle) is not None

    for changed in (
            dict(failure_code='OTHER_SUPERSESSION'), dict(attempt_count=1),
            dict(state='BLOCKED')):
        assert sources._recoverable_superseded_wait(object(), {**cycle, **changed}) is None
    monkeypatch.setattr(sources, '_active_commands',
        lambda _c: {'counts': {'UNKNOWN': 1}})
    assert sources._recoverable_superseded_wait(object(), cycle) is None
    monkeypatch.setattr(sources, '_active_commands', lambda _c: {'counts': {}})
    monkeypatch.setattr(sources, '_latest_observation', lambda _c: {
        **observation, 'orders': [{'state': 'ACKNOWLEDGED'}]})
    assert sources._recoverable_superseded_wait(object(), cycle) is None
    monkeypatch.setattr(sources, '_latest_observation', lambda _c: observation)
    monkeypatch.setattr(unsent_recovery, 'require_unsent',
        lambda *_a, **_k: (_ for _ in ()).throw(AutomationRefused('command exists')))
    assert sources._recoverable_superseded_wait(object(), cycle) is None
    monkeypatch.setattr(unsent_recovery, 'require_unsent', lambda *_a, **_k: None)
    monkeypatch.setattr(health, 'read_health', lambda *_a, **_k: replace_namespace(
        current, operational_ready=False))
    assert sources._recoverable_superseded_wait(object(), cycle) is None


def test_next_decision_uses_validated_nondefault_runtime_timing(monkeypatch):
    from sentinel.automation import env_config, schedule, store
    from sentinel.automation.model import AutomationConfig
    from sentinel.execution.target_reprojection import TargetProjectionRefused

    parse_runtime_config = env_config.config_from_env
    cycle, current = _safe_case(monkeypatch)
    control = store.load_control(object())
    configured = parse_runtime_config({
        'SENTINEL_AUTOMATION_PUBLICATION_DELAY_SECONDS': '1800'})
    assert configured.publication_delay_seconds != AutomationConfig().publication_delay_seconds
    monkeypatch.setattr(env_config, 'config_from_env', lambda: configured)
    assert sources._recoverable_superseded_wait(object(), cycle) is None

    control.config_sha256 = configured.fingerprint
    current.config_sha256 = configured.fingerprint
    wait = sources._recoverable_superseded_wait(object(), cycle)
    assert wait is not None
    assert wait.next_decision_at == schedule.for_decision_session(
        date(2026, 11, 24), configured).prepare_at
    monkeypatch.setattr(env_config, 'config_from_env',
        lambda: (_ for _ in ()).throw(ValueError('invalid runtime timing')))
    assert sources._recoverable_superseded_wait(object(), cycle) is None
    monkeypatch.setattr(env_config, 'config_from_env',
        lambda: (_ for _ in ()).throw(TargetProjectionRefused('invalid BUY policy')))
    assert sources._recoverable_superseded_wait(object(), cycle) is None


@pytest.mark.parametrize('code', [
    'MISSED_EXECUTION_WINDOW', 'MAX_EXECUTION_LATENESS_EXCEEDED'])
def test_same_generation_unsent_missed_window_has_bounded_next_decision(
        monkeypatch, code):
    from sentinel.automation import store

    cycle, current = _safe_case(monkeypatch)
    control = store.load_control(object())
    previous = store.load_cycle(object(), cycle['cycle_id'])
    cycle['failure_code'] = code
    current.latest_failure_code = code
    previous.failure_code = code
    previous.control_generation = control.generation
    previous.diagnostic = {}
    assert sources._recoverable_superseded_wait(object(), cycle) is not None

    previous.config_sha256 = '0' * 64
    assert sources._recoverable_superseded_wait(object(), cycle) is None
    previous.config_sha256 = control.config_sha256
    previous.broker_account_id = 'wrong-account'
    assert sources._recoverable_superseded_wait(object(), cycle) is None
    previous.broker_account_id = control.broker_account_id
    previous.attempt_count = 1
    assert sources._recoverable_superseded_wait(object(), cycle) is None


@pytest.mark.parametrize('fault,guard', [
    ('config', 'or previous.config_sha256 != control.config_sha256'),
    ('binding', 'or not store.adoption_identity_matches(previous, control)'),
])
def test_same_generation_identity_guards_are_required(monkeypatch, fault, guard):
    from sentinel.automation import store

    cycle, current = _safe_case(monkeypatch)
    control = store.load_control(object())
    previous = store.load_cycle(object(), cycle['cycle_id'])
    cycle['failure_code'] = 'MISSED_EXECUTION_WINDOW'
    current.latest_failure_code = 'MISSED_EXECUTION_WINDOW'
    previous.failure_code = 'MISSED_EXECUTION_WINDOW'
    previous.control_generation = control.generation
    previous.diagnostic = {}
    if fault == 'config':
        previous.config_sha256 = '0' * 64
    else:
        previous.broker_account_id = 'wrong-account'

    def mismatched_identity_must_refuse(candidate):
        assert candidate(object(), cycle) is None

    mismatched_identity_must_refuse(sources._recoverable_superseded_wait)
    source = inspect.getsource(sources._recoverable_superseded_wait)
    assert source.count(guard) == 1
    namespace = dict(vars(sources))
    exec(compile(source.replace(guard, 'or False'),
                 '<removed same-generation identity guard>', 'exec'), namespace)
    with pytest.raises(AssertionError):
        mismatched_identity_must_refuse(namespace['_recoverable_superseded_wait'])


@pytest.mark.parametrize('changed,guard', [
    ({'broker_outcome_unresolved': 1}, 'or health.broker_outcome_unresolved != 0'),
    ({'latest_cycle_id': 'different-owner'}, "or health.latest_cycle_id != cycle['cycle_id']"),
])
def test_current_owner_and_unresolved_guard_removal_fails_falsifier(
        monkeypatch, changed, guard):
    from sentinel.automation import health

    cycle, current = _safe_case(monkeypatch)
    monkeypatch.setattr(health, 'read_health', lambda *_a, **_k: replace_namespace(
        current, **changed))

    def unsafe_must_refuse(candidate):
        assert candidate(object(), cycle) is None

    unsafe_must_refuse(sources._recoverable_superseded_wait)
    source = inspect.getsource(sources._recoverable_superseded_wait)
    assert source.count(guard) == 1
    namespace = dict(vars(sources))
    exec(compile(source.replace(guard, 'or False'),
                 '<removed safe-continuity guard>', 'exec'), namespace)
    with pytest.raises(AssertionError):
        unsafe_must_refuse(namespace['_recoverable_superseded_wait'])


def replace_namespace(value, **changes):
    return SimpleNamespace(**{**vars(value), **changes})
