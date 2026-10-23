"""The composed opening screen, including the October 23 moving snapshot."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import inspect

import pytest

from sentinel.panel import model,overview,run_progress,sources
from sentinel.panel.render import render
from sentinel.execution.contract import OrderTerms
from test_panel_plan_first_render import example_panel

NOW=datetime(2026,10,23,13,34,15,tzinfo=timezone.utc)
FIRST=NOW.replace(minute=33,second=37)
START=NOW.replace(minute=31,second=0)
TERMS=OrderTerms().to_dict()


def run(state='EXECUTING'):
    intent=example_panel().row('paper_plan').paper_plan
    orders=[]
    for ticker,qty,filled in [('ATI',8,7),('ATEX',12,6)]:
        orders.append(model.RunOrder(security_id=ticker,ticker=ticker,client_key='key-'+ticker,
            broker_order_id='native-'+ticker,side='SELL',quantity=Decimal(qty),
            filled_quantity=Decimal(filled),state='PARTIALLY_FILLED',observed_at=NOW-timedelta(seconds=14),
            filled_average_price=Decimal('155.56') if ticker=='ATI' else Decimal('71.11'),
            order_terms=TERMS))
    return model.TradingRun(intent=intent,state=state,updated_at=START,orders=orders)


def args():
    current=run()
    raw={'id':'native-ATEX','key':'key-ATEX','qty':'12','side':'SELL','state':'PARTIALLY_FILLED',
         'filled':'6','symbol':'ATEX','security_id':'ATEX','order_terms':deepcopy(TERMS)}
    return dict(run=current,observation=dict(observed_at=NOW-timedelta(seconds=4),
        completeness='INCONSISTENT',runtime_state='RECONCILING',
        positions={'ATI':'0','ATEX':'6','PANW':'0','NAT':'225'},orders=[raw]),
        callback=dict(started_at=START,deadline=START+timedelta(minutes=5)),
        first_inconsistent=FIRST,now=NOW)


def test_screenshot_snapshot_is_bounded_amber_and_current_plan_stays_visible():
    values=args()
    wait=run_progress.moving_snapshot_recovery(**values)
    assert wait is not None and wait.deadline==FIRST+timedelta(seconds=120)
    broker=model.broker_row(available=True,positions=13,completeness='INCONSISTENT',
        runtime_state='RECONCILING',working_orders=1,as_of=values['observation']['observed_at'])
    assert broker.effective_status(NOW)==model.FAIL  # No blanket INCONSISTENT downgrade.
    broker=replace(broker,status=model.WARN,recovery=wait,valid_until=wait.deadline)
    current=model.Row('trading_run','Today’s paper trading','EXECUTING',model.WARN,
        as_of=START,valid_until=NOW+timedelta(hours=6),trading_run=values['run'])
    panel=model.Panel(now=NOW,rows=[broker,current])
    html=render(panel)
    assert panel.operational==model.WARN
    assert 'Reconciling fills</span>' in html and 'Checks needing attention' not in html
    assert 'Today’s trading plan' in html and '7/8 submitted shares filled' in html
    assert '6/12 submitted shares filled' in html and 'Awaiting submission' in html
    assert 'No current saved plan available.' not in html
    expired=replace(panel,now=wait.deadline+timedelta(microseconds=1))
    assert expired.operational==model.FAIL and 'Needs attention' in render(expired)


@pytest.mark.parametrize('fault',[
 'no_callback','callback_expired','first_expired','first_missing','first_future','callback_future',
 'wrong_cycle_state','terminal_failure','complete_missing','foreign_runtime','unknown_command',
 'cancel_pending','send_pending','foreign_order','wrong_native_id','wrong_security','wrong_side',
 'wrong_symbol','wrong_terms','wrong_qty','overfilled','replacement','foreign_position',
 'unexpected_hold_change','position_outside_envelope','no_working_order','no_commands','future_command'])
def test_unsafe_or_expired_snapshots_keep_the_original_red(fault):
    values=args(); observation=values['observation']; raw=observation['orders'][0]
    if fault=='no_callback': values['callback']=None
    elif fault=='callback_expired': values['callback']['deadline']=NOW
    elif fault=='first_expired': values['first_inconsistent']=NOW-timedelta(seconds=120)
    elif fault=='first_missing': values['first_inconsistent']=None
    elif fault=='first_future': values['first_inconsistent']=NOW+timedelta(seconds=1)
    elif fault=='callback_future': values['callback']['started_at']=NOW+timedelta(seconds=1)
    elif fault=='wrong_cycle_state': values['run']=values['run'].model_copy(update={'state':'SUCCEEDED'})
    elif fault=='terminal_failure': values['failure_code']='FOREIGN_ACTIVITY'
    elif fault=='complete_missing': observation['completeness']='UNAVAILABLE'
    elif fault=='foreign_runtime': observation['runtime_state']='FOREIGN_ACTIVITY'
    elif fault in {'unknown_command','cancel_pending','send_pending','future_command'}:
        change={'state':{'unknown_command':'UNKNOWN','cancel_pending':'CANCEL_PENDING',
                         'send_pending':'SEND_PENDING'}.get(fault,'PARTIALLY_FILLED')}
        if fault=='future_command': change={'observed_at':NOW+timedelta(seconds=6)}
        orders=[values['run'].orders[0].model_copy(update=change),values['run'].orders[1]]
        values['run']=values['run'].model_copy(update={'orders':orders})
    elif fault=='foreign_order': raw['key']='foreign-key'
    elif fault=='wrong_native_id': raw['id']='wrong-native'
    elif fault=='wrong_security': raw['security_id']='ATI'
    elif fault=='wrong_side': raw['side']='BUY'
    elif fault=='wrong_symbol': raw['symbol']='WRONG'
    elif fault=='wrong_terms': raw['order_terms']={'order_type':'limit'}
    elif fault=='wrong_qty': raw['qty']='13'
    elif fault=='overfilled': raw['filled']='13'
    elif fault=='replacement': raw['external_replacement']=True
    elif fault=='foreign_position': observation['positions']['FOREIGN']='1'
    elif fault=='unexpected_hold_change': observation['positions']['NAT']='224'
    elif fault=='position_outside_envelope': observation['positions']['ATEX']='13'
    elif fault=='no_working_order': observation['orders']=[]
    elif fault=='no_commands': values['run']=values['run'].model_copy(update={'orders':[]})
    assert run_progress.moving_snapshot_recovery(**values) is None


def test_first_observation_clock_cannot_be_renewed_by_page_reads():
    values=args()
    one=run_progress.moving_snapshot_recovery(**values)
    values['now']=NOW+timedelta(seconds=60)
    two=run_progress.moving_snapshot_recovery(**values)
    assert one.deadline==two.deadline
    values['now']=one.deadline
    assert run_progress.moving_snapshot_recovery(**values) is None


@pytest.mark.parametrize('before,after',[
 ("or raw.get('id') != command.broker_order_id",'or False'),
 ("or raw.get('order_terms') != command.order_terms",'or False'),
 ("if not now < deadline:", 'if False:'),
 ("if sid not in legs:", 'if False:'),
])
def test_admission_guard_removal_falsifiers(before,after):
    source=inspect.getsource(run_progress.moving_snapshot_recovery)
    assert before in source
    scope=dict(run_progress.__dict__)
    exec(source.replace(before,after),scope)
    broken=scope['moving_snapshot_recovery']
    values=args()
    if 'order_terms' in before: values['observation']['orders'][0]['order_terms']={}
    elif "raw.get('id')" in before: values['observation']['orders'][0]['id']='wrong'
    elif 'deadline' in before: values['now']=FIRST+timedelta(seconds=120)
    else:
        # Remove the ownership guard and make the dependent lookup valid to
        # expose an actual admitted foreign holding rather than only a crash.
        values['observation']['positions']['FOREIGN']='1'
    assert run_progress.moving_snapshot_recovery(**values) is None
    if 'sid not in legs' in before:
        with pytest.raises(KeyError): broken(**values)
    else:
        assert broken(**values) is not None


def test_full_execution_sequence_keeps_intent_and_displays_recorded_fills():
    original=run()
    for state in ('WAITING_OPEN','EXECUTING','RECONCILING','SUCCEEDED'):
        orders=original.orders
        if state=='SUCCEEDED':
            orders=[item.model_copy(update={'state':'FILLED','filled_quantity':item.quantity}) for item in orders]
            orders.append(model.RunOrder(security_id='PANW',ticker='PANW',client_key='key-PANW',
                broker_order_id='native-PANW',side='BUY',quantity='3',filled_quantity='3',state='FILLED',
                observed_at=NOW,filled_average_price='354.52',order_terms=OrderTerms(
                    order_type='limit',time_in_force='day',limit_price=Decimal('354.58')).to_dict()))
        current=original.model_copy(update={'state':state,'orders':orders})
        row=model.Row('trading_run','Run',state,as_of=NOW,
            valid_until=NOW+timedelta(hours=8),trading_run=current)
        html=overview.overview_html(model.Panel(now=NOW,rows=[row]))
        assert 'No current saved plan available.' not in html
        assert 'ATI' in html and 'ATEX' in html and 'PANW' in html
        assert current.intent==original.intent
        if state=='SUCCEEDED':
            assert 'Today’s trades · completed' in html
            assert '8/8 submitted shares filled' in html and '3/3 submitted shares filled' in html
            assert 'avg $354.52' in html and 'Limit $354.58' in html


@pytest.mark.parametrize('state',['UNKNOWN','REJECTED','CANCELLED','CANCEL_PENDING'])
def test_uncertain_and_unfilled_outcomes_are_not_rendered_as_success(state):
    current=run()
    orders=[current.orders[0].model_copy(update={'state':state,'filled_quantity':Decimal(0)}),current.orders[1]]
    current=current.model_copy(update={'orders':orders})
    row=model.Row('trading_run','Run',current.state,model.FAIL,as_of=NOW,trading_run=current)
    html=overview.overview_html(model.Panel(now=NOW,rows=[row]))
    expected={'UNKNOWN':'Outcome uncertain','REJECTED':'Rejected',
              'CANCELLED':'Ended unfilled','CANCEL_PENDING':'Cancellation pending'}[state]
    assert expected in html and 'Today’s trades · completed' not in html


def test_daily_run_withdraws_at_next_new_york_date_or_future_command_clock():
    row=model.Row('trading_run','Run','EXECUTING',as_of=NOW,
        valid_until=NOW+timedelta(days=3),trading_run=run())
    assert row.can_show_trading_run(NOW)
    assert not row.can_show_trading_run(NOW+timedelta(days=1))
    future=run().model_copy(update={'orders':[run().orders[0].model_copy(
        update={'observed_at':NOW+timedelta(seconds=6)})]})
    assert not replace(row,trading_run=future).can_show_trading_run(NOW)


def test_current_run_reader_is_account_generation_bound_and_does_not_change_future_reader():
    source=inspect.getsource(sources._current_trading_run)
    for guard in ('c.control_generation=a.generation','c.broker_account_id=a.broker_account_id',
                  'c.takeover_epoch=a.takeover_epoch','c.config_sha256=a.config_sha256',
                  'c.certificate_sha256=a.certificate_sha256','p.superseded_by IS NULL',
                  "AT TIME ZONE 'America/New_York'",'c.historical_state_only'):
        assert guard in source
    assert 'INSERT ' not in source and 'UPDATE ' not in source
    from sentinel import paper_plan_preview
    assert 'c.execute_at>clock_timestamp()' in inspect.getsource(paper_plan_preview.read)


def test_original_intent_is_not_resized_from_current_filled_positions():
    original=run()
    intent=original.intent
    plan=dict(cycle_id=intent.cycle_id,plan_id=intent.plan_id,plan_fingerprint='fingerprint',
        state='SUCCEEDED',updated_at=NOW,completed_at=NOW,broker='alpaca',broker_account_id='paper',
        execute_at=intent.execute_at,created_at=intent.created_at,
        decision_session=intent.decision_session,effective_session=intent.effective_session,
        target_basket={leg.security_id:str(leg.target_quantity) for leg in intent.legs})
    authority=dict(plan_id=intent.plan_id,plan_fingerprint='fingerprint',
        tickers={leg.security_id:leg.ticker for leg in intent.legs},
        broker_observation=dict(completeness='COMPLETE',observed_at=intent.observation_at,
            account_identity=dict(broker='alpaca',account_id='paper'),positions=[
            dict(instrument=dict(security_id=leg.security_id),quantity=str(leg.current_quantity))
            for leg in intent.legs if leg.current_quantity]))
    projected=run_progress.project_run(plan,authority,[])
    assert {leg.ticker:leg.change_quantity for leg in projected.intent.legs}=={
        'ATI':Decimal(-8),'ATEX':Decimal(-12),'PANW':Decimal(3),'NAT':Decimal(0)}
    for key,value in [('plan_fingerprint','wrong'),('plan_id','wrong')]:
        invalid=dict(authority,**{key:value})
        with pytest.raises(ValueError): run_progress.project_run(plan,invalid,[])
    invalid=deepcopy(authority)
    invalid['broker_observation']['account_identity']['account_id']='foreign'
    with pytest.raises(ValueError): run_progress.project_run(plan,invalid,[])


def test_actual_source_composition_recovers_the_screenshot_then_cleans_up(monkeypatch):
    from sentinel import paper_plan_preview
    from test_panel import TestRuntimeRowsAreDurableFacts
    values=args()
    fixture=TestRuntimeRowsAreDurableFacts()
    fixture._install_sources(monkeypatch,observation=values['observation'],
        commands=dict(counts={'PARTIALLY_FILLED':2},updated_at=NOW-timedelta(seconds=14)))
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE','dual')
    current=model.Row('trading_run','Today’s paper trading','EXECUTING',model.WARN,
        as_of=START,valid_until=NOW+timedelta(hours=8),trading_run=values['run'])
    monkeypatch.setattr(sources,'_current_trading_run',lambda _:current)
    monkeypatch.setattr(sources,'_first_inconsistent_observation',lambda *a,**kw:FIRST)
    monkeypatch.setattr(sources,'_latest_automation_cycle',lambda _:dict(
        cycle_id=values['run'].intent.cycle_id,state='EXECUTING',execute_at=START,
        observation_callback=values['callback']))
    monkeypatch.setattr(paper_plan_preview,'read',lambda _:None)
    rows,errors=sources._runtime_projection('fixture',now=NOW)
    assert not errors
    broker=next(item for item in rows if item.key=='broker')
    assert broker.effective_status(NOW)==model.WARN
    assert broker.recovery.phase=='BROKER_FILL_SNAPSHOT'
    # Other runtime facts are deliberately absent in this source fixture; only
    # the two actual projected rows under test participate in this headline.
    html=render(model.Panel(now=NOW,rows=[row for row in rows
                                       if row.key in {'broker','trading_run'}]))
    assert 'Reconciling fills</span>' in html
    assert '6/12 submitted shares filled' in html
    # The original observation, not a rewritten complete snapshot, is retained.
    assert 'saved observation INCONSISTENT' in html
    assert values['observation']['completeness']=='INCONSISTENT'
    values['observation'].update(completeness='COMPLETE',runtime_state='RUNNING',orders=[])
    rows,errors=sources._runtime_projection('fixture',now=NOW)
    assert not errors
    broker=next(item for item in rows if item.key=='broker')
    assert broker.effective_status(NOW)==model.OK


@pytest.mark.parametrize('state,filled',[('ACKNOWLEDGED','0'),('PARTIALLY_FILLED','1'),('FILLED','8')])
def test_confirmed_progress_requires_native_identity(state,filled):
    value=run().orders[0].model_dump()
    value.update(state=state,filled_quantity=filled,broker_order_id=None)
    with pytest.raises(ValueError): model.RunOrder(**value)


@pytest.mark.parametrize('completed',[None,START-timedelta(seconds=1)])
def test_success_requires_a_real_completion_after_its_execute_clock(completed):
    value=run().model_dump()
    value.update(state='SUCCEEDED',completed_at=completed)
    with pytest.raises(ValueError): model.TradingRun(**value)
