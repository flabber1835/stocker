"""Completed current trading and immutable historical audit are separate facts."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
import pytest

from sentinel.panel import model, presentation
from sentinel.execution.contract import OrderTerms
from sentinel.paper_plan_preview import OpeningEstimate, PlanPreview, PlannedLeg
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


def post_activation_panel():
    """A new generation waits after the older generation completed today."""
    page=completed_panel()
    run=page.row('trading_run')
    recovery=model.RecoveryEvidence(phase='AUTOMATION_DISCOVERY',automatic=True,
        next_attempt_at=NOW+timedelta(seconds=2),deadline=NOW+timedelta(seconds=10))
    waiting=[model.Row(key,label,value,model.WARN,required_current=True,
        recovery=recovery,operational_fact=model.OperationalFact(
            kind='AUTOMATION_CYCLE',state='DISCOVERY_WAIT')) for key,label,value in (
            ('automation_cycle','Cycle','WAITING FOR NEXT DECISION'),
            ('automation_step_discovery','Discovery','WAITING FOR CYCLE'))]
    rows=[row for row in page.rows if row.key not in {
        'trading_run','automation_cycle','automation_step_complete','automation_alerts'}]
    rows += [replace(run,key='completed_trading_run'),*waiting,
        model.automation_alerts_row(installed=True,pending=0,dead_letter=0,
                                    unacknowledged=2,as_of=NOW)]
    review=page.operator_review.model_copy(update={
        'head':2,'reviewed_head':1,'status':'REVIEW','token':None})
    return replace(page,rows=rows,operator_review=review)


def test_post_activation_wait_can_offer_review_without_promoting_paper_authority():
    from sentinel.panel.render import render
    from sentinel.panel.serialization import public_payload
    page=post_activation_panel()
    assert presentation.health_facts(page)=={'active':[],'warnings':[]}
    before=public_payload(page)
    assert before['dashboard_health']['color']=='amber'
    assert before['dashboard_health']['label'].startswith('Acknowledgement required')
    assert before['operational']=='warn'
    paper=next(row for row in before['rows'] if row['key']=='paper_reconciliation')
    assert paper['status']=='warn' and paper['paper_alignment']=='COMPLETED_WITH_HISTORY'
    assert paper['value']=='PAPER NOT VERIFIED · PENDING'
    token=page.operator_review.model_copy(update={'token':'synthetic-review-view'})
    html=render(replace(page,operator_review=token))
    assert 'id="review-acknowledge"' in html and 'Historical paper audit' in html
    clean=page.operator_review.model_copy(update={
        'status':'CLEAN','head':3,'reviewed_head':3,'reviewed_at':NOW})
    acknowledged=replace(page,operator_review=clean)
    assert presentation.dashboard_health(acknowledged)['color']=='green'
    assert public_payload(acknowledged)['operational']=='warn'
    assert acknowledged.row('paper_reconciliation')==page.row('paper_reconciliation')


@pytest.mark.parametrize('fault', [None, 'retained', 'partial', 'unvalidated', 'shadow_changed',
                                   'broker_failure', 'receipt_expired'])
def test_post_activation_valuation_handoff_preserves_only_proven_human_health(fault):
    from sentinel.panel import delivery, serialization
    page = post_activation_panel()
    clean = page.operator_review.model_copy(update={'status':'CLEAN', 'head':3, 'reviewed_head':3})
    page = replace(page, operator_review=clean, observation_current=False,
        observation_changed_scopes=('PAPER',), observation_revalidated_keys=('paper_reconciliation',),
        observation_display_current=True, observation_display_keys=delivery.display_keys(page),
        observation_valid_until=NOW + timedelta(seconds=5))
    if fault == 'retained':
        page = replace(page, observation_retained=True)
    elif fault == 'partial':
        page = replace(page, observation_display_current=False)
    elif fault == 'unvalidated':
        page = replace(page, observation_revalidated_keys=())
    elif fault == 'shadow_changed':
        page = replace(page, observation_changed_scopes=('SHADOW','PAPER'))
    elif fault == 'broker_failure':
        page = changed_history_panel(page, 'broker', status=model.FAIL)
    elif fault == 'receipt_expired':
        page = changed_history_panel(page, 'paper_reconciliation', valid_until=NOW)
        # The HTTP reader resolves display currentness after applying its last clock.
        page = replace(page, observation_display_current=all(
            delivery.row_current(page, row) for row in page.rows))
    payload = serialization.public_payload(page)
    assert payload['observation']['strict_current'] is False
    assert payload['operational'] == model.UNKNOWN
    if fault:
        assert payload['operator_review'] is None
        assert payload['dashboard_health']['color'] != 'green'
    else:
        assert payload['operator_review'] == {**clean.model_dump(mode='json'), 'token': None}
        assert payload['dashboard_health']['color'] == 'green'
        assert payload['dashboard_health']['review_conditions'] == []


@pytest.mark.parametrize('fault',[
    'missing_history','wrong_session','wrong_decision','incomplete_run','unfilled_order',
    'active_cycle','successor_started','missing_discovery','unowned_discovery','saved_plan','pending_alert',
    'failed_alert','source_error','partial_observation',
])
def test_post_activation_context_cannot_borrow_unproved_history(fault):
    page=post_activation_panel()
    prior=page.row('completed_trading_run')
    run=prior.trading_run
    if fault=='missing_history':
        page=replace(page,rows=[r for r in page.rows if r.key!='completed_trading_run'])
    elif fault=='wrong_session':
        run=run.model_copy(update={'intent':run.intent.model_copy(update={
            'effective_session':run.intent.effective_session+timedelta(days=1)})})
    elif fault=='wrong_decision':
        run=run.model_copy(update={'intent':run.intent.model_copy(update={
            'decision_session':run.intent.decision_session-timedelta(days=3)})})
    elif fault=='incomplete_run':run=run.model_copy(update={'state':'RECONCILING'})
    elif fault=='unfilled_order':run=run.model_copy(update={'orders':[
        run.orders[0].model_copy(update={'state':'ACKNOWLEDGED'})]})
    elif fault=='active_cycle':page=changed_history_panel(page,'automation_cycle',
        operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE',state='EXECUTING'))
    elif fault=='successor_started':page=replace(page,rows=[*page.rows,
        model.Row('trading_run','Current run','EXECUTING',model.WARN)])
    elif fault=='missing_discovery':page=replace(page,rows=[r for r in page.rows
        if r.key!='automation_step_discovery'])
    elif fault=='unowned_discovery':page=changed_history_panel(page,'automation_step_discovery',
        recovery=model.RecoveryEvidence(phase='AUTOMATION_DISCOVERY',automatic=False,
            operator_required=True,deadline=NOW+timedelta(seconds=10)))
    elif fault=='saved_plan':page=changed_history_panel(page,'paper_plan',status=model.OK)
    elif fault=='pending_alert':page=changed_history_panel(page,'automation_alerts',
        value='1 pending · 0 DLQ · 2 unacked')
    elif fault=='failed_alert':page=changed_history_panel(page,'automation_alerts',
        value='0 pending · 1 DLQ · 2 unacked',status=model.FAIL)
    elif fault=='source_error':page=replace(page,source_errors=['unavailable'])
    elif fault=='partial_observation':page=replace(page,observation_current=False)
    if run is not prior.trading_run:
        page=changed_history_panel(page,'completed_trading_run',trading_run=run)
    facts=presentation.health_facts(page)
    assert facts['warnings'] or facts['active']
    assert presentation.dashboard_health(page)['color']!='green'


@pytest.mark.parametrize('key',presentation._HISTORY_CURRENT_FACTS)
def test_post_activation_context_needs_each_current_capability(key):
    page=post_activation_panel()
    page=replace(page,rows=[row for row in page.rows if row.key!=key])
    assert presentation.dashboard_health(page)['color']!='green'
    assert 'paper_reconciliation' in presentation.health_facts(page)['warnings']


def test_post_activation_context_expires_at_original_wait_deadline():
    page=post_activation_panel()
    clean=page.operator_review.model_copy(update={
        'status':'CLEAN','head':2,'reviewed_head':2,'reviewed_at':NOW})
    page=replace(page,operator_review=clean)
    assert presentation.dashboard_health(page)['valid_until']==(NOW+timedelta(seconds=10)).isoformat()
    assert presentation.dashboard_health(replace(page,now=NOW+timedelta(seconds=10)))['color']!='green'


def test_post_activation_context_stops_at_exchange_close_even_if_other_clocks_are_extended():
    from sentinel.feed import calendar

    page=post_activation_panel()
    close=calendar.session_window(str(page.row('completed_trading_run').trading_run.intent.effective_session))[1]
    longer=(close+timedelta(minutes=1)).astimezone(timezone.utc)
    page=replace(page,rows=[replace(row,valid_until=longer,freshness=None,
        recovery=replace(row.recovery,deadline=longer) if row.recovery is not None else None)
        for row in page.rows])
    assert presentation._post_activation_completion_normal(replace(page,now=close-timedelta(microseconds=1)))
    assert not presentation._post_activation_completion_normal(replace(page,now=close))


def test_removed_post_activation_source_binding_is_detected(monkeypatch):
    page=post_activation_panel()
    feed=page.row('feed')
    changed=feed.operational_fact.model_copy(update={
        'session':feed.operational_fact.session-timedelta(days=3)})
    page=changed_history_panel(page,'feed',operational_fact=changed)
    assert 'paper_reconciliation' in presentation.health_facts(page)['warnings']
    source=inspect.getsource(presentation._post_activation_completion_normal)
    guard='and _current_input_session(panel, decision)'
    assert source.count(guard)==1
    namespace=dict(vars(presentation))
    exec(compile(source.replace(guard,'and True'),'<unbound post-activation source>','exec'),namespace)
    monkeypatch.setattr(presentation,'_post_activation_completion_normal',
                        namespace['_post_activation_completion_normal'])
    assert 'paper_reconciliation' not in presentation.health_facts(page)['warnings']


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


def test_zero_share_opening_can_complete_without_reporting_a_fill():
    from sentinel.panel.overview import _run_html

    page=completed_panel()
    run=page.row('trading_run').trading_run
    leg=PlannedLeg(security_id='mtd',ticker='MTD',current_quantity=0,
        target_quantity=0,change_quantity=None,opening_dollars='2400.85',action='BUY')
    intent=run.intent.model_copy(update={'legs':[leg]})
    estimate=OpeningEstimate(account_budget='1339.716675',limit_price='1748.23',shares=0)
    updates={'intent':intent,'orders':[]}
    unknown=run.model_copy(update=updates)
    skipped=model.TradingRun(**{**run.model_dump(),**updates,'below_whole_share':{'mtd':estimate}})
    unsettled=changed_history_panel(page,'trading_run',trading_run=unknown)
    completed=changed_history_panel(page,'trading_run',trading_run=skipped)
    assert presentation.dashboard_health(unsettled)['color']=='amber'
    completed_health=presentation.dashboard_health(completed)
    assert completed_health['color']=='green'
    assert completed_health['label']=='Healthy · Run complete · No orders placed'
    html=_run_html(completed)
    assert 'Today’s run · no orders placed' in html
    assert 'MTD' in html and 'Skipped · budget below one share' in html
    assert '$1,339.72 paper budget' in html and '$2,400.85' in html
    assert 'filled' not in html
    with pytest.raises(ValueError,match='matching unsubmitted opening intent'):
        model.TradingRun(**{**run.model_dump(),**updates,
                          'below_whole_share':{'other':estimate}})


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
