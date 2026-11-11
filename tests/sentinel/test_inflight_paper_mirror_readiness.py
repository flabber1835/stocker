"""The actual opening diagnostic must not confuse history with current transport."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta
from decimal import Decimal
import inspect,textwrap
import pytest
from sentinel.panel import sources,model,observer_codec,observer_failure
from sentinel import informational_paper_mirror as mirror
from sentinel.paper_plan_preview import PlannedLeg
from sentinel.execution.contract import OrderTerms
from tests.sentinel.test_postopen_paper_mirror_readiness import completed,NOW
from tests.sentinel.test_panel_command_progress import cycle,NOW as PROGRESS_NOW


@pytest.fixture
def ongoing(completed):
    v=completed;c=cycle()
    for k,value in c.items():
        if isinstance(value,datetime):c[k]=value+(NOW-PROGRESS_NOW)
    c.update(cycle_id='current-cycle',plan_id='current-plan',plan_fingerprint='a'*64)
    c['diagnostic']['plan']['plan_id']='current-plan'
    v['cycle']=c;v['health'].latest_cycle_state='RECONCILING';v['health'].broker_outcome_unresolved=1
    old=v['row'].trading_run
    intent=old.intent.model_copy(update={'execute_at':c['execute_at'],'legs':[PlannedLeg(security_id='PBR.A',ticker='PBR.A',
        current_quantity=Decimal(71),target_quantity=Decimal(0),change_quantity=Decimal(-71),action='SELL')]})
    order=model.RunOrder(security_id='PBR.A',ticker='PBR.A',client_key='synthetic-key',
        broker_order_id='native-id',side='SELL',quantity=Decimal(71),filled_quantity=Decimal(0),
        state='ACKNOWLEDGED',observed_at=NOW-timedelta(seconds=5),order_terms=OrderTerms().to_dict())
    run=model.TradingRun(intent=intent,state='RECONCILING',updated_at=c['updated_at'],orders=[order])
    v['row']=replace(v['row'],status=model.WARN,trading_run=run,as_of=order.observed_at)
    return v


def observe(v):
    return sources._in_progress_paper_mirror(object(),v['cycle'],v['publication'],'2026-10-30',now=NOW)


def test_known_submitted_transport_is_pending_with_original_wake(ongoing):
    row=observe(ongoing)
    assert row.status==model.WARN and 'PENDING' in row.value and 'NOT VERIFIED' in row.value
    assert row.recovery.phase=='PAPER_TRANSPORT' and row.valid_until==ongoing['cycle']['next_wake_at']
    assert row.effective_status(row.valid_until+timedelta(microseconds=1))==model.FAIL
    assert observer_codec.row_from_observation(observer_codec.pack([row],[],observed_at=NOW)['rows'][0])==row


def test_executing_before_submission_is_not_a_mirror_mismatch(ongoing):
    v=ongoing;v['cycle'].update(state='EXECUTING',failure_code=None,failure_detail=None)
    v['health'].latest_cycle_state='EXECUTING';v['health'].broker_outcome_unresolved=0
    v['cycle']['observation_callback']={'started_at':v['cycle']['updated_at'],'deadline':NOW+timedelta(minutes=2)}
    v['row']=replace(v['row'],trading_run=v['row'].trading_run.model_copy(update={'state':'EXECUTING','orders':[]}))
    assert observe(v).status==model.WARN


def test_due_recovery_wake_uses_actual_fenced_callback_deadline(ongoing):
    c=ongoing['cycle'];c['next_wake_at']=NOW-timedelta(seconds=20)
    c['observation_callback']={'started_at':NOW-timedelta(seconds=15),'deadline':NOW+timedelta(minutes=2)}
    assert observe(ongoing).valid_until==c['observation_callback']['deadline']
    for callback in ({'started_at':NOW-timedelta(minutes=5),'deadline':NOW+timedelta(minutes=2)},
                     {'started_at':NOW-timedelta(seconds=15),'deadline':NOW},
                     {'started_at':NOW+timedelta(seconds=1),'deadline':NOW+timedelta(minutes=2)}):
        c['observation_callback']=callback
        assert observe(ongoing) is None


@pytest.mark.parametrize('fault',['unknown','rejected','missing_order','foreign_order','uncovered',
 'no_local','disabled','authority','unhealthy','foreign_cycle','failed_cycle','different_run',
 'different_plan','publication','frontier','no_plan','stale_run','expired_wake','naive_clock',
 'missing_clean','adverse_preflight','missing_asof'])
def test_uncertain_or_unproved_transport_keeps_refusal(ongoing,fault):
    v=ongoing;c=v['cycle'];run=v['row'].trading_run
    if fault in {'unknown','rejected'}:
        order=run.orders[0].model_copy(update={'state':'UNKNOWN' if fault=='unknown' else 'REJECTED'})
        v['row']=replace(v['row'],trading_run=run.model_copy(update={'orders':[order]}))
    elif fault=='missing_order':v['row']=replace(v['row'],trading_run=run.model_copy(update={'orders':[]}))
    elif fault=='foreign_order':v['row']=replace(v['row'],trading_run=run.model_copy(update={'orders':[run.orders[0].model_copy(update={'client_key':'foreign'})]}))
    elif fault=='uncovered':v['health'].broker_outcome_unresolved=2
    elif fault=='no_local':v['local']=False
    elif fault=='disabled':v['health'].enabled=False
    elif fault=='authority':v['health'].authority_lifecycle_current=False
    elif fault=='unhealthy':v['health'].operational_ready=False
    elif fault=='foreign_cycle':v['health'].latest_cycle_id='foreign'
    elif fault=='failed_cycle':c['state']='BLOCKED'
    elif fault=='different_run':v['row']=replace(v['row'],trading_run=run.model_copy(update={'state':'EXECUTING'}))
    elif fault=='different_plan':v['plan'].fingerprint=lambda:'b'*64
    elif fault=='publication':v['publication'].version=9
    elif fault=='frontier':v['row']=replace(v['row'],trading_run=run.model_copy(update={'intent':run.intent.model_copy(update={'decision_session':run.intent.decision_session-timedelta(days=1)})}))
    elif fault=='no_plan':v['plan']=None
    elif fault=='stale_run':v['row']=replace(v['row'],valid_until=NOW-timedelta(seconds=1))
    elif fault=='expired_wake':c['next_wake_at']=NOW
    elif fault=='naive_clock':c['execute_at']=c['execute_at'].replace(tzinfo=None)
    elif fault=='missing_clean':c['clean_reconciliation_id']=None
    elif fault=='adverse_preflight':c['diagnostic']['preflight']['unresolved']=['unknown']
    elif fault=='missing_asof':v['row']=replace(v['row'],as_of=None)
    assert observe(v) is None


def test_opening_negative_fingerprint_reconstructs_exact_history_dispatch_bug():
    material=dict(errors=[],rows=[dict(key='paper_reconciliation',status='fail',
      value='PAPER NOT VERIFIED · MISMATCH · BLOCKED',
      detail='historical mirror warning remains recorded; current scheduled readiness is unproved · cycle RECONCILING')])
    import json
    failure=observer_failure.failure('NEGATIVE_RESULT','VALIDATION',
        material=json.dumps(material,sort_keys=True,separators=(',',':')).encode())
    assert failure.fingerprint=='f9cc1c37a8a1519c90f31454a0f35562867375e397131e5567b19313e324b656'


def test_history_count_and_warning_remain_during_proven_progress(ongoing,monkeypatch):
    monkeypatch.setattr(sources,'_scheduled_preopen_mirror',lambda *_:None)
    actual=observe(ongoing)
    monkeypatch.setattr(sources,'_in_progress_paper_mirror',lambda *_:actual)
    row=sources._scheduled_paper_mirror(object(),ongoing['cycle'],ongoing['publication'],
      '2026-10-30',{'status':mirror.MISMATCH,'historical_mismatch_count':3})
    assert row.status==model.WARN and '3 historical' in row.detail and 'earlier transported plans' in row.detail
    assert row.valid_until==actual.valid_until and row.recovery==actual.recovery


def test_removed_order_state_guard_fails_oracle(ongoing,monkeypatch):
    code=textwrap.dedent(inspect.getsource(sources._in_progress_paper_mirror))
    guard="any(order.state not in {'ACKNOWLEDGED', 'PARTIALLY_FILLED', 'FILLED'} for order in run.orders)"
    assert guard in code;scope=dict(vars(sources));exec(code.replace(guard,'False'),scope)
    monkeypatch.setattr(sources,'_in_progress_paper_mirror',scope['_in_progress_paper_mirror'])
    with pytest.raises(AssertionError):test_uncertain_or_unproved_transport_keeps_refusal(ongoing,'unknown')
