"""Completed transport may retain amber history without certifying performance."""
import ast
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import inspect
from types import SimpleNamespace

import pytest

from sentinel import local_paper, informational_paper_mirror
from sentinel.automation import health
from sentinel.execution import journal
from sentinel.panel import model, sources, observer_codec
from sentinel.paper_plan_preview import PlanPreview

NOW = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)


@pytest.fixture
def completed(monkeypatch):
    cycle = dict(state='SUCCEEDED', cycle_id='current-cycle', plan_id='current-plan',
        plan_fingerprint='a'*64, completed_at=NOW-timedelta(minutes=5),
        clean_reconciliation_id=19, failure_code=None, failure_detail=None,
        terminal_reason=None)
    h = SimpleNamespace(healthy=True, operational_ready=True, enabled=True,
        kill_switch_engaged=False, policy_state='LEADER_ACTIVE', authority_verdict='PASS',
        authority_lifecycle_current=True, broker_outcome_unresolved=0,
        latest_cycle_id='current-cycle', latest_cycle_state='SUCCEEDED')
    intent = PlanPreview(cycle_id='current-cycle', plan_id='current-plan',
        decision_session=date(2026,10,30), effective_session=date(2026,11,2),
        execute_at=NOW-timedelta(minutes=29), created_at=NOW-timedelta(days=1),
        observation_at=NOW-timedelta(days=1), legs=[])
    run = model.TradingRun(intent=intent, state='SUCCEEDED',
        updated_at=cycle['completed_at'], completed_at=cycle['completed_at'])
    row = model.Row('trading_run', 'Run', 'SUCCEEDED', model.OK,
        as_of=run.updated_at, valid_until=NOW+timedelta(hours=10), trading_run=run)
    account = model.Row('alpaca_account', 'Account', 'ACTIVE', model.OK,
        as_of=NOW-timedelta(seconds=3), freshness=timedelta(seconds=60))
    plan = SimpleNamespace(fingerprint=lambda: 'a'*64, data_version=8)
    values = dict(cycle=cycle, health=h, row=row, account=account,
        plan=plan, local=True, account_available=True, publication=SimpleNamespace(version=8))
    monkeypatch.setattr(local_paper, 'require_bound_account', lambda _: values['local'])
    monkeypatch.setattr(health, 'read_health', lambda _: values['health'])
    monkeypatch.setattr(sources, '_current_trading_run', lambda _: values['row'])
    monkeypatch.setattr(journal, 'load_plan', lambda *_: values['plan'])
    monkeypatch.setattr(sources, '_latest_account_evidence',
        lambda _: {} if not values['account_available'] else {'test_account': True})
    monkeypatch.setattr(sources, '_bound_account_id', lambda _: 'paper-account')
    monkeypatch.setattr(model, 'alpaca_account_row', lambda **_: values['account'])
    return values


def observe(values):
    return sources._completed_postopen_mirror(object(), values['cycle'],
        values['publication'], '2026-10-30', now=NOW)


def test_completed_current_cycle_is_amber_pending_with_original_account_bound(completed):
    row = observe(completed)
    assert row.status == row.effective_status(NOW) == model.WARN
    assert row.value == 'PAPER NOT VERIFIED · PENDING'
    assert 'completed' in row.detail and 'post-close' in row.detail
    assert row.required_current and row.recovery is None
    assert row.as_of == completed['account'].as_of
    assert row.valid_until == completed['account'].as_of+timedelta(seconds=60)
    assert row.effective_status(row.valid_until+timedelta(microseconds=1)) == model.FAIL


@pytest.mark.parametrize('defect', [
    'failed_cycle', 'missing_clean', 'failure', 'terminal', 'ordinary_mode',
    'unhealthy', 'not_ready', 'disabled', 'killed', 'passive', 'authority',
    'expired_authority', 'unknown_outcome', 'foreign_cycle', 'different_health_state',
    'missing_run', 'failed_run', 'expired_run', 'foreign_run_plan', 'foreign_run_cycle',
    'wrong_completion', 'different_frontier', 'missing_plan', 'changed_plan',
    'changed_publication', 'no_account', 'bad_account', 'stale_account', 'future_account',
    'missing_account_bound', 'expired_account_boundary',
])
def test_unproved_current_completion_keeps_existing_refusal(completed, defect):
    v=completed
    if defect=='failed_cycle':v['cycle']['state']='BLOCKED'
    elif defect=='missing_clean':v['cycle']['clean_reconciliation_id']=None
    elif defect=='failure':v['cycle']['failure_code']='SOURCE_REFUSED'
    elif defect=='terminal':v['cycle']['terminal_reason']='UNKNOWN'
    elif defect=='ordinary_mode':v['local']=False
    elif defect=='unhealthy':v['health'].healthy=False
    elif defect=='not_ready':v['health'].operational_ready=False
    elif defect=='disabled':v['health'].enabled=False
    elif defect=='killed':v['health'].kill_switch_engaged=True
    elif defect=='passive':v['health'].policy_state='STANDBY'
    elif defect=='authority':v['health'].authority_verdict='FAIL'
    elif defect=='expired_authority':v['health'].authority_lifecycle_current=False
    elif defect=='unknown_outcome':v['health'].broker_outcome_unresolved=1
    elif defect=='foreign_cycle':v['health'].latest_cycle_id='foreign'
    elif defect=='different_health_state':v['health'].latest_cycle_state='RECONCILING'
    elif defect=='missing_run':v['row']=None
    elif defect=='failed_run':v['row']=replace(v['row'], status=model.FAIL)
    elif defect=='expired_run':v['row']=replace(v['row'], valid_until=NOW-timedelta(seconds=1))
    elif defect in {'foreign_run_plan','foreign_run_cycle','different_frontier'}:
        run=v['row'].trading_run
        change={'plan_id':'foreign'} if defect=='foreign_run_plan' else (
            {'cycle_id':'foreign'} if defect=='foreign_run_cycle' else {'decision_session':date(2026,10,29)})
        v['row']=replace(v['row'], trading_run=run.model_copy(update={
            'intent':run.intent.model_copy(update=change)}))
    elif defect=='wrong_completion':v['cycle']['completed_at']=NOW-timedelta(minutes=4)
    elif defect=='missing_plan':v['plan']=None
    elif defect=='changed_plan':v['plan'].fingerprint=lambda: 'b'*64
    elif defect=='changed_publication':v['publication'].version=9
    elif defect=='no_account':v['account_available']=False
    elif defect=='bad_account':v['account']=replace(v['account'], status=model.FAIL)
    elif defect=='stale_account':v['account']=replace(v['account'], as_of=NOW-timedelta(minutes=5))
    elif defect=='future_account':v['account']=replace(v['account'], as_of=NOW+timedelta(minutes=1))
    elif defect=='missing_account_bound':v['account']=replace(v['account'], freshness=None)
    elif defect=='expired_account_boundary':v['account']=replace(v['account'], valid_until=NOW-timedelta(seconds=1))
    assert observe(v) is None


def test_completed_history_retains_count_and_cannot_be_clean_or_verified(monkeypatch, completed):
    monkeypatch.setattr(sources, '_scheduled_preopen_mirror', lambda *_: None)
    actual = observe(completed)
    monkeypatch.setattr(sources, '_completed_postopen_mirror', lambda *_: actual)
    mirror = {'status':informational_paper_mirror.MISMATCH, 'historical_mismatch_count':3}
    before = deepcopy(mirror)
    row = sources._scheduled_paper_mirror(object(), completed['cycle'],
        completed['publication'], '2026-10-30', mirror)
    assert row.status == model.WARN and 'NOT VERIFIED' in row.value
    assert '3 historical' in row.detail and 'earlier transported plans' in row.detail
    assert row.as_of == actual.as_of and row.valid_until == actual.valid_until
    assert mirror == before


@pytest.mark.parametrize('count', [None, True, 0, -1])
def test_unproven_history_count_never_reaches_completion_exception(monkeypatch, completed, count):
    monkeypatch.setattr(sources, '_completed_postopen_mirror',
        lambda *_: pytest.fail('invalid historical evidence was admitted'))
    row = sources._scheduled_paper_mirror(object(), completed['cycle'],
        completed['publication'], '2026-10-30', {'status':informational_paper_mirror.MISMATCH,'historical_mismatch_count':count})
    assert row.status == model.FAIL


def test_completed_history_roundtrips_without_granting_green(completed):
    row=observe(completed)
    encoded=observer_codec.pack([row],[],observed_at=NOW)['rows'][0]
    decoded=observer_codec.row_from_observation(encoded)
    assert decoded==row and decoded.effective_status(NOW)==model.WARN
    assert decoded.effective_status(row.valid_until)==model.FAIL


@pytest.mark.parametrize('changes', [
    {'paper_alignment':'UNKNOWN_HISTORY'}, {'valid_until':None}, {'as_of':None},
    {'as_of':NOW.replace(tzinfo=None)}, {'valid_until':NOW.replace(tzinfo=None)},
    {'required_current':False}, {'status':model.OK}, {'key':'other'},
    {'recovery':{'phase':'AUTOMATION_OPEN','automatic':True,'deadline':NOW+timedelta(seconds=10)}},
])
def test_malformed_completion_display_fact_refuses(completed, changes):
    encoded=observer_codec.pack([observe(completed)],[],observed_at=NOW)['rows'][0]
    encoded.update(changes)
    with pytest.raises(ValueError):observer_codec.row_from_observation(encoded)


@pytest.mark.parametrize('changes', [
    {'as_of':None}, {'as_of':'untrusted'}, {'as_of':NOW.replace(tzinfo=None)},
    {'as_of':NOW+timedelta(minutes=1)}, {'valid_until':None},
    {'valid_until':NOW.replace(tzinfo=None)}, {'valid_until':NOW},
    {'required_current':False}, {'status':model.OK}, {'key':'other'},
    {'recovery':model.RecoveryEvidence(phase='AUTOMATION_OPEN',automatic=True,
        deadline=NOW+timedelta(seconds=10))},
])
def test_internal_completion_clock_or_shape_refuses_before_clock_arithmetic(completed, changes):
    assert replace(observe(completed), **changes).effective_status(NOW)==model.FAIL


def test_removed_completion_guard_is_detected(monkeypatch, completed):
    tree=ast.parse(inspect.getsource(sources._completed_postopen_mirror))
    guard=next(n for n in tree.body[0].body if isinstance(n,ast.If))
    guard.test=ast.Constant(False)
    scope=dict(vars(sources));exec(compile(ast.fix_missing_locations(tree),
        '<removed-completed-cycle-guard>','exec'),scope)
    monkeypatch.setattr(sources,'_completed_postopen_mirror',scope['_completed_postopen_mirror'])
    with pytest.raises(AssertionError):
        test_unproved_current_completion_keeps_existing_refusal(completed,'failed_cycle')
