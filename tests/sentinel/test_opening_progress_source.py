"""Only exact original callback and candidate metadata enter the display join."""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
import inspect
import textwrap

import pytest

from sentinel.panel import model, sources
from tests.sentinel.test_opening_health_continuity import NOW, OPEN, executing_panel, clean_skip_panel


def callback_case():
    page=executing_panel(stale_broker=True)
    current=page.row('trading_run');run=current.trading_run
    fact=page.row('broker').operational_fact
    cycle=dict(state='EXECUTING',cycle_id=run.intent.cycle_id,plan_id=run.intent.plan_id,
        updated_at=run.updated_at,execute_at=OPEN,execution_close_at=NOW.replace(hour=21,minute=0),
        observation_callback=dict(started_at=fact.opening.started_at,deadline=fact.opening.deadline))
    return cycle,current,page.row('broker')


def test_exact_fenced_callback_is_carried_without_borrowing_old_broker_liveness():
    cycle,current,broker=callback_case()
    fact=sources._execution_progress_fact(cycle,current,broker,now=NOW)
    assert fact.kind=='EXECUTION_PROGRESS' and fact.state=='EXECUTING'
    assert fact.opening.started_at==cycle['observation_callback']['started_at']
    assert fact.opening.deadline==cycle['observation_callback']['deadline']
    assert broker.is_stale(NOW) and broker.as_of<NOW-timedelta(hours=12)


@pytest.mark.parametrize('fault',['missing_callback','foreign_cycle','foreign_plan','wrong_state',
    'terminal','callback_failure','failure','expired','future_start','wrong_update','bad_broker',
    'expired_run','missing_run_bound'])
def test_unproved_callback_metadata_cannot_normalize_execution(fault):
    cycle,current,broker=callback_case()
    if fault=='missing_callback':cycle['observation_callback']=None
    elif fault=='foreign_cycle':cycle['cycle_id']='foreign'
    elif fault=='foreign_plan':cycle['plan_id']='foreign'
    elif fault=='wrong_state':cycle['state']='RETRY_WAIT'
    elif fault=='terminal':cycle['terminal_reason']='FAILED'
    elif fault=='callback_failure':cycle['callback_failure']='TimeoutError'
    elif fault=='failure':cycle['failure_code']='UNKNOWN'
    elif fault=='expired':cycle['observation_callback']['deadline']=NOW
    elif fault=='future_start':cycle['observation_callback']['started_at']=NOW+timedelta(seconds=1)
    elif fault=='wrong_update':cycle['updated_at']=NOW
    elif fault=='bad_broker':broker=replace(broker,status=model.FAIL)
    elif fault=='expired_run':current=replace(current,valid_until=NOW-timedelta(seconds=1))
    elif fault=='missing_run_bound':current=replace(current,valid_until=None)
    assert sources._execution_progress_fact(cycle,current,broker,now=NOW) is None


def idle_case():
    page=clean_skip_panel();current=page.row('trading_run');run=current.trading_run
    cycle=dict(cycle_id=run.intent.cycle_id,plan_id=run.intent.plan_id,state='SUPERSEDED',
        failure_code='POST_PLAN_CASH_ACTIVITY_RECONCILED',terminal_reason=None,updated_at=run.updated_at,
        clean_reconciliation_id='396',diagnostic=dict(clean=True,runtime_state='RUNNING',
            cash_plan_superseded=True,observation_id=396,unresolved=[],foreign_orders=[],
            foreign_positions=[],restricted_securities={}))
    return cycle,current,page.row('broker'),dict(counts={})


def test_idle_marker_is_only_a_candidate_for_independently_signed_paper_proof():
    cycle,current,broker,commands=idle_case()
    fact=sources._clean_idle_candidate(cycle,current,broker,commands,now=NOW)
    assert fact.state=='AWAITING_NEXT_DECISION' and fact.opening.observation_id==396
    assert fact.opening.deadline>NOW+timedelta(minutes=10)


@pytest.mark.parametrize('fault',['unknown_command','working_command','bad_broker','unproved_cash',
    'unclean','foreign_cycle','foreign_plan','wrong_observation','generic_supersession','expired_run'])
def test_candidate_requires_current_exact_safe_idle_metadata(fault):
    cycle,current,broker,commands=idle_case()
    if fault=='unknown_command':commands['counts']={'UNKNOWN':1}
    elif fault=='working_command':commands['counts']={'ACKNOWLEDGED':1}
    elif fault=='bad_broker':broker=replace(broker,status=model.FAIL)
    elif fault=='unproved_cash':cycle['diagnostic']['cash_plan_superseded']=False
    elif fault=='unclean':cycle['diagnostic']['clean']=False
    elif fault=='foreign_cycle':cycle['cycle_id']='foreign'
    elif fault=='foreign_plan':cycle['plan_id']='foreign'
    elif fault=='wrong_observation':cycle['diagnostic']['observation_id']=397
    elif fault=='generic_supersession':cycle['failure_code']='OTHER'
    elif fault=='expired_run':current=replace(current,valid_until=NOW-timedelta(seconds=1))
    assert sources._clean_idle_candidate(cycle,current,broker,commands,now=NOW) is None
