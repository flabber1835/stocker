"""Completed current trading and immutable historical audit are separate facts."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
import pytest

from sentinel.panel import model, presentation
from sentinel.execution.contract import OrderTerms
from sentinel.paper_plan_preview import PlanPreview, PlannedLeg
from test_panel_historical_mirror_schedule import healthy_history_panel, changed_history_panel

NOW = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
OPEN = NOW.replace(hour=14, minute=31)
DONE = NOW.replace(hour=14, minute=37)


def completed_panel():
    page=healthy_history_panel(now=NOW,execute_at=OPEN)
    leg=PlannedLeg(security_id='synthetic-exit',ticker='EXIT',current_quantity=Decimal(2),
        target_quantity=Decimal(0),change_quantity=Decimal(-2),action='SELL')
    intent=PlanPreview(cycle_id='completed-current-cycle',plan_id='completed-current-plan',
        decision_session=page.row('paper_plan').paper_plan.decision_session,
        effective_session=NOW.date(),execute_at=OPEN,created_at=OPEN-timedelta(hours=12),
        observation_at=OPEN-timedelta(hours=12,seconds=5),legs=[leg])
    order=model.RunOrder(security_id=leg.security_id,ticker=leg.ticker,client_key='synthetic-command',
        broker_order_id='synthetic-native-order',side='SELL',quantity=Decimal(2),
        filled_quantity=Decimal(2),state='FILLED',observed_at=DONE-timedelta(seconds=10),
        filled_average_price=Decimal(100),order_terms=OrderTerms().to_dict())
    run=model.TradingRun(intent=intent,state='SUCCEEDED',updated_at=DONE,completed_at=DONE,orders=[order])
    history=model.Row('paper_reconciliation','Paper reconciliation','PAPER NOT VERIFIED · PENDING',model.WARN,
        'One authenticated earlier-plan mismatch remains; current cycle completed; post-close verification pending.',
        as_of=NOW,required_current=True,valid_until=NOW+timedelta(minutes=10),paper_alignment='COMPLETED_WITH_HISTORY')
    rows=[r for r in page.rows if r.key not in {'paper_reconciliation','paper_plan','automation_cycle','automation_step_open','automation_step_transport'}]
    rows += [history,model.Row('paper_plan','Next plan','NOT PREPARED',model.PENDING),
        model.Row('trading_run','Today',run.state,model.OK,as_of=DONE,
                  valid_until=NOW.replace(hour=23,minute=59),trading_run=run),
        model.Row('automation_cycle','Cycle','SUCCEEDED',model.OK,as_of=DONE,required_current=True,
            operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE',state='SUCCEEDED')),
        model.Row('automation_step_complete','Completion','SUCCEEDED',model.OK,as_of=DONE,required_current=True,
            operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE',state='SUCCEEDED'))]
    return replace(page,rows=rows)


def test_reproduced_completed_history_is_expected_health_not_a_new_material_warning():
    from sentinel.panel.render import render
    page=completed_panel();before=deepcopy(page)
    health=presentation.dashboard_health(page)
    assert health['color']=='green' and health['label']=='Healthy · Today’s trading complete'
    assert health['plan_readiness']=='pending'
    assert presentation.health_facts(page)=={'active':[],'warnings':[]}
    assert page.overall==page.operational==model.WARN
    assert page.row('paper_reconciliation').paper_alignment=='COMPLETED_WITH_HISTORY'
    assert page.row('paper_reconciliation').effective_status(NOW)==model.WARN
    html=render(page)
    assert 'Historical paper audit' in html and 'post-close verification' in html
    assert 'class="row warn" id="status-paper_reconciliation"' in html
    assert page==before


def test_reproduced_owned_check_and_completed_history_do_not_flap_material_health():
    page=completed_panel();deadline=NOW+timedelta(minutes=3)
    checking=model.Row('paper_reconciliation','Paper alignment','CHECK IN PROGRESS',model.WARN,
        required_current=True,valid_until=deadline,
        recovery=model.RecoveryEvidence(phase='FINANCIAL_VERIFICATION',automatic=True,deadline=deadline),
        operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION',state='CHECKING'))
    running=replace(page,rows=[checking if r.key=='paper_reconciliation' else r for r in page.rows])
    assert presentation.health_facts(page)==presentation.health_facts(running)=={'active':[],'warnings':[]}


def test_completed_json_preserves_the_unverified_financial_verdict(monkeypatch):
    from fastapi.testclient import TestClient
    from sentinel.panel import app
    page=completed_panel()
    monkeypatch.setattr(app,'_read_panel',lambda:page)
    with TestClient(app.app) as client:
        body=client.get('/panel.json').json()
    assert body['dashboard_health']['color']=='green'
    assert body['overall']==body['operational']=='warn'
    audit=next(row for row in body['rows'] if row['key']=='paper_reconciliation')
    assert audit['status']=='warn' and audit['paper_alignment']=='COMPLETED_WITH_HISTORY'
    assert audit['value']==page.row('paper_reconciliation').value
    assert audit['valid_until']==page.row('paper_reconciliation').valid_until.isoformat()


@pytest.mark.parametrize('key',[*presentation._HISTORY_CURRENT_FACTS,'trading_run','automation_cycle','automation_step_complete'])
def test_missing_current_proof_cannot_borrow_completed_history(key):
    page=completed_panel();page=replace(page,rows=[r for r in page.rows if r.key!=key])
    assert presentation.dashboard_health(page)['color']!='green'


@pytest.mark.parametrize('key',['alpaca_account','broker','feed','authority','automation_leader','shadow_worker','trading_run'])
@pytest.mark.parametrize('fault',['unknown','expired','future','undated'])
def test_stale_unreadable_or_undated_current_fact_still_wins(key,fault):
    page=completed_panel();changes={'unknown':{'status':model.UNKNOWN},
        'expired':{'valid_until':NOW-timedelta(seconds=1)},'future':{'as_of':NOW+timedelta(seconds=6)},
        'undated':{'as_of':None}}[fault]
    page=changed_history_panel(page,key,**changes)
    assert presentation.dashboard_health(page)['color']!='green'


@pytest.mark.parametrize('fault',['normal_release','duplicate','source_error','kill','other_warning',
    'untyped_history','wrong_history_type','expired_history','wrong_cycle','incomplete_step',
    'wrong_completion_clock','run_incomplete','run_other_date','unknown_order','rejected_order','unfilled_order',
    'missing_actionable_order'])
def test_completion_does_not_waive_current_failure_or_completion_contract(fault):
    page=completed_panel();run=page.row('trading_run').trading_run
    if fault=='normal_release':page=replace(page,local_paper_mode=False)
    elif fault=='duplicate':page=replace(page,rows=[*page.rows,page.row('authority')])
    elif fault=='source_error':page=replace(page,source_errors=['unavailable'])
    elif fault=='kill':page=changed_history_panel(page,'automation',value='ENABLED · KILLED',status=model.FAIL)
    elif fault=='other_warning':page=replace(page,rows=[*page.rows,model.Row('other','Other','WARNING',model.WARN)])
    elif fault=='untyped_history':page=changed_history_panel(page,'paper_reconciliation',paper_alignment=None)
    elif fault=='wrong_history_type':page=changed_history_panel(page,'paper_reconciliation',paper_alignment='SCHEDULED_WITH_HISTORY')
    elif fault=='expired_history':page=changed_history_panel(page,'paper_reconciliation',valid_until=NOW)
    elif fault=='wrong_cycle':page=changed_history_panel(page,'automation_cycle',value='RECONCILING',
        operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE',state='RECONCILING'))
    elif fault=='incomplete_step':page=changed_history_panel(page,'automation_step_complete',value='NOT REACHED',operational_fact=None)
    elif fault=='wrong_completion_clock':page=changed_history_panel(page,'automation_cycle',as_of=DONE+timedelta(seconds=1))
    elif fault=='run_incomplete':run=run.model_copy(update={'state':'RECONCILING'})
    elif fault=='run_other_date':run=run.model_copy(update={'intent':run.intent.model_copy(update={'effective_session':NOW.date()-timedelta(days=1)})})
    elif fault in ['unknown_order','rejected_order','unfilled_order']:
        order=run.orders[0].model_copy(update={'state':{'unknown_order':'UNKNOWN','rejected_order':'REJECTED','unfilled_order':'ACKNOWLEDGED'}[fault]})
        run=run.model_copy(update={'orders':[order]})
    elif fault=='missing_actionable_order':run=run.model_copy(update={'orders':[]})
    page=changed_history_panel(page,'trading_run',trading_run=run)
    assert presentation.dashboard_health(page)['color']!='green'


def test_no_change_completed_plan_needs_no_invented_order():
    page=completed_panel();run=page.row('trading_run').trading_run
    leg=run.intent.legs[0].model_copy(update={'action':'HOLD','target_quantity':Decimal(2),'change_quantity':Decimal(0)})
    run=run.model_copy(update={'orders':[],'intent':run.intent.model_copy(update={'legs':[leg]})})
    assert presentation.dashboard_health(changed_history_panel(page,'trading_run',trading_run=run))['color']=='green'


def test_original_capability_and_history_boundaries_are_not_retimed():
    page=completed_panel()
    assert presentation.dashboard_health(page)['valid_until']==(NOW+timedelta(seconds=12)).isoformat()
    page=changed_history_panel(page,'paper_reconciliation',valid_until=NOW+timedelta(seconds=4))
    assert presentation.dashboard_health(page)['valid_until']==(NOW+timedelta(seconds=4)).isoformat()
    assert presentation.dashboard_health(replace(page,now=NOW+timedelta(seconds=4)))['color']!='green'


def test_completed_proof_cannot_automatically_acknowledge_history():
    page=completed_panel();review=page.operator_review.model_copy(update={'head':2,'reviewed_head':1,'status':'REVIEW'})
    assert presentation.dashboard_health(replace(page,operator_review=review))['color']=='amber'
    assert presentation.health_facts(page)=={'active':[],'warnings':[]}


def test_removed_completion_guard_has_executed_false_green_falsifier(monkeypatch):
    source=inspect.getsource(presentation._completed_work_normal)
    guard="run.state != 'SUCCEEDED'"
    assert source.count(guard)==1
    ns=dict(vars(presentation));exec(compile(source.replace(guard,'False'),'<removed completed-state guard>','exec'),ns)
    monkeypatch.setattr(presentation,'_completed_work_normal',ns['_completed_work_normal'])
    with pytest.raises(AssertionError):test_completion_does_not_waive_current_failure_or_completion_contract('run_incomplete')
