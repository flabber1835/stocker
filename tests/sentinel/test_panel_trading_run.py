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
    assert 'Next trading plan pending.' not in html
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
        assert 'Next trading plan pending.' not in html
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
    rows,errors=sources._runtime_projection('postgresql://fixture@isolated.invalid/fixture',now=NOW)
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
    rows,errors=sources._runtime_projection('postgresql://fixture@isolated.invalid/fixture',now=NOW)
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


@pytest.mark.parametrize('state',['EXECUTING','SUCCEEDED'])
def test_dual_surface_keeps_today_run_through_full_panel_assembly(monkeypatch,state):
    current=run().model_copy(update={'state':state,'completed_at':NOW if state=='SUCCEEDED' else None})
    row=model.Row('trading_run','Today’s paper trading',state,as_of=NOW,
        valid_until=NOW+timedelta(hours=8),trading_run=current)
    broker=model.Row('broker','Broker','13 positions · 0 working',as_of=NOW)
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE','dual')
    monkeypatch.setattr(sources,'_runtime_projection',lambda *a,**kw:([
        model.Row('book','Unscaled book','Existing shadow reader owns this'),broker,row],[]))
    monkeypatch.setattr(sources,'_bounded_dual_authority_rows',lambda *a,**kw:([
        model.Row('shadow_verification','Shadow','SHADOW VERIFIED THROUGH 2026-10-22',as_of=NOW)],{},[],[]))
    monkeypatch.setattr(sources,'_ownership',lambda *a:model.Row('ownership','Account','Owned',as_of=NOW))
    monkeypatch.setattr(sources,'_feed_rows',lambda *a:([],[]))
    monkeypatch.setattr(sources,'_automation_rows',lambda *a:([
        model.Row('automation','Automation','Enabled',as_of=NOW),
        model.Row('automation_leader','Leader','Current',as_of=NOW)],[]))
    monkeypatch.setattr(sources,'_operator_evidence_rows',lambda *a,**kw:([],[]))
    monkeypatch.setattr(sources,'_shadow_worker_row',lambda *a:model.Row('shadow_worker','Worker','Running',as_of=NOW))
    panel=sources.build_panel(state_dir='fixture',database_url='fixture',now=NOW)
    assert not panel.source_errors and panel.row('trading_run')==row
    assert panel.row('book') is None  # Do not duplicate the independently admitted shadow book.
    html=render(panel)
    assert 'Next trading plan pending.' not in html
    assert '6/12 submitted shares filled' in html
    assert ('Today’s trades · completed' if state=='SUCCEEDED' else 'Today’s trading plan') in html
    source=inspect.getsource(sources._runtime_rows)
    changed=source.replace("'broker','paper_plan','trading_run'","'broker','paper_plan'")
    assert changed != source
    scope=dict(sources.__dict__);exec(changed,scope)
    monkeypatch.setattr(sources,'_runtime_rows',scope['_runtime_rows'])
    broken=sources.build_panel(state_dir='fixture',database_url='fixture',now=NOW)
    assert broken.row('trading_run') is None
    assert 'Next trading plan pending.' in render(broken)


def completed_history(*, status=model.OK):
    recorded=run().model_copy(update={'state':'SUCCEEDED','completed_at':NOW})
    return model.Row('completed_trading_run','Today’s recorded completed run','SUCCEEDED',
        status,as_of=NOW,valid_until=NOW+timedelta(hours=8),trading_run=recorded)


def test_completed_history_is_distinct_in_html_and_json_and_keeps_original_intent(monkeypatch):
    import json
    from pathlib import Path
    from sentinel.panel import app
    history=completed_history()
    page=model.Panel(now=NOW,rows=[history,model.Row('automation_cycle','Automation',
        'WAITING FOR NEXT DECISION',model.WARN)])
    html=render(page)
    assert 'Today’s trades · completed' in html
    assert 'The next trading plan is pending.' in html
    assert 'Next trading plan pending.' not in html
    assert '7/8 submitted shares filled' in html
    assert '6/12 submitted shares filled' in html
    assert page.operational==model.WARN  # Completed history grants no current readiness.
    monkeypatch.setattr(app,'_config',lambda:(Path('/synthetic/completed-run'),''))
    monkeypatch.setattr(app,'_read_panel',lambda:page)
    payload=json.loads(app.panel_json().body)
    saved=next(row for row in payload['rows'] if row['key']=='completed_trading_run')
    assert saved['paper_plan'] is None
    assert saved['trading_run']['state']=='SUCCEEDED'
    assert saved['trading_run']['intent']['plan_id']==history.trading_run.intent.plan_id
    assert saved['trading_run']['completed_at']==NOW.isoformat().replace('+00:00','Z')
    assert page.row('trading_run') is None and page.row('paper_plan') is None


def test_historical_run_cannot_hide_a_current_failed_run_or_an_unreadable_current_row():
    history=completed_history()
    failed=run().model_copy(update={'state':'FAILED'})
    current=model.Row('trading_run','Today’s trading','FAILED',model.FAIL,as_of=NOW,
        valid_until=NOW+timedelta(hours=8),trading_run=failed)
    for row in (current,model.Row('trading_run','Today’s trading','UNAVAILABLE',
                                model.UNKNOWN,detail='current evidence unreadable')):
        page=model.Panel(now=NOW,rows=[row,history])
        assert page.operational in {model.FAIL,model.UNKNOWN}
        assert 'The next trading plan is pending.' not in render(page)
        assert 'Today’s trades · completed' not in render(page)
        if row.trading_run is None:
            assert 'Saved trading plan unavailable.' in render(page)


def test_future_plan_leads_without_falsely_saying_it_is_pending():
    history=completed_history()
    future=history.trading_run.intent.model_copy(update={
        'decision_session':NOW.date(),'effective_session':(NOW+timedelta(days=1)).date(),
        'execute_at':NOW+timedelta(days=1),'created_at':NOW})
    planned=model.Row('paper_plan','Next paper plan','Ready',as_of=NOW,
        valid_until=future.execute_at,paper_plan=future)
    html=render(model.Panel(now=NOW,rows=[planned,history]))
    assert html.index('Next trading plan')<html.index('Today’s trades · completed')
    assert 'The next trading plan is pending.' not in html


@pytest.mark.parametrize('status',[model.FAIL,model.UNKNOWN])
def test_completed_history_does_not_relabel_an_unavailable_next_plan_as_pending(status):
    history=completed_history()
    next_plan=model.Row('paper_plan','Next paper plan','UNAVAILABLE',status,
                        detail='current plan evidence unreadable')
    panel=model.Panel(now=NOW,rows=[history,next_plan])
    html=render(panel)
    assert 'Today’s trades · completed' in html
    assert 'The next trading plan is unavailable.' in html
    assert 'The next trading plan is pending.' not in html
    assert panel.operational in {model.FAIL,model.UNKNOWN}


def test_completed_history_keeps_the_original_session_and_clock_withdrawal():
    history=completed_history()
    assert history.can_show_trading_run(NOW)
    for instant in (history.valid_until+timedelta(microseconds=1),NOW+timedelta(days=1)):
        assert not history.can_show_trading_run(instant)
        assert 'Today’s trades · completed' not in render(model.Panel(now=instant,rows=[history]))
    future=history.trading_run.model_copy(update={'completed_at':NOW+timedelta(seconds=6)})
    assert not replace(history,trading_run=future).can_show_trading_run(NOW)


def test_noncompleted_history_is_withdrawn_and_guard_removal_is_detected():
    import textwrap
    history=completed_history()
    invalid=replace(history,trading_run=history.trading_run.model_copy(update={'state':'FAILED'}))
    assert not invalid.can_show_trading_run(NOW)
    source=textwrap.dedent(inspect.getsource(model.Row.can_show_trading_run))
    guard="(self.key != 'completed_trading_run' or self.trading_run.state == 'SUCCEEDED')"
    assert source.count(guard)==1
    scope=dict(model.__dict__)
    exec(source.replace(guard,'True'),scope)
    with pytest.raises(AssertionError):
        assert not scope['can_show_trading_run'](invalid,NOW)


def test_historical_fallback_is_only_read_after_an_absent_error_free_current_run(monkeypatch):
    from sentinel import paper_plan_preview
    from test_panel import TestRuntimeRowsAreDurableFacts
    fixture=TestRuntimeRowsAreDurableFacts()
    fixture._install_sources(monkeypatch,commands=dict(counts={},updated_at=NOW))
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE','dual')
    monkeypatch.setattr(paper_plan_preview,'read',lambda _:None)
    history=completed_history();calls=[]
    monkeypatch.setattr(sources,'_completed_trading_run',lambda conn:(calls.append(conn) or history))
    rows,errors=sources._runtime_projection('postgresql://fixture@isolated.invalid/fixture',now=NOW)
    assert not errors and next(row for row in rows if row.key=='completed_trading_run') is history
    assert len(calls)==1
    # The dual-mode assembly must not discard the separately named historical row.
    monkeypatch.setattr(sources,'_runtime_projection',lambda *a,**kw:(rows,errors))
    kept,_=sources._runtime_rows('postgresql://fixture@isolated.invalid/fixture')
    assert history in kept


@pytest.mark.parametrize('current',['failed','unreadable'])
def test_current_failure_prevents_the_historical_reader_from_running(monkeypatch,current):
    from sentinel import paper_plan_preview
    from test_panel import TestRuntimeRowsAreDurableFacts
    fixture=TestRuntimeRowsAreDurableFacts()
    fixture._install_sources(monkeypatch,commands=dict(counts={},updated_at=NOW))
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE','dual')
    monkeypatch.setattr(paper_plan_preview,'read',lambda _:None)
    def forbidden(_):
        pytest.fail('historical success was queried after a current negative fact')
    monkeypatch.setattr(sources,'_completed_trading_run',forbidden)
    if current=='failed':
        row=model.Row('trading_run','Today’s trading','FAILED',model.FAIL,as_of=NOW,
            trading_run=run().model_copy(update={'state':'FAILED'}))
        monkeypatch.setattr(sources,'_current_trading_run',lambda _:row)
    else:
        def unreadable(_):
            raise ValueError('current run evidence unreadable')
        monkeypatch.setattr(sources,'_current_trading_run',unreadable)
    rows,errors=sources._runtime_projection('postgresql://fixture@isolated.invalid/fixture',now=NOW)
    assert not any(row.key=='completed_trading_run' for row in rows)
    assert next(row for row in rows if row.key=='trading_run').status in {model.FAIL,model.UNKNOWN}
    assert bool(errors)==(current=='unreadable')


@pytest.fixture
def historical_run_db(monkeypatch):
    """Temporary query-only fixtures on the explicitly supplied private test server."""
    import os
    psycopg=pytest.importorskip('psycopg')
    dsn=os.environ.get('TEST_DATABASE_URL') or os.environ.get('SENTINEL_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('an explicitly configured private PostgreSQL is required')
    conn=psycopg.connect(dsn)
    try:
        conn.execute('''CREATE TEMP TABLE sentinel_automation_control(
            id integer,generation bigint,deployment_id text,broker text,broker_account_id text,
            takeover_epoch bigint,certificate_sha256 text,config_sha256 text,
            enabled boolean,kill_switch_engaged boolean)''')
        conn.execute('''CREATE TEMP TABLE sentinel_account_binding(
            id integer,ownership_state text,deployment_id text,broker text,
            broker_account_id text,takeover_epoch bigint)''')
        conn.execute('''CREATE TEMP TABLE sentinel_execution_plans(
            plan_id text,created_at timestamptz,decision_session date,effective_session date,
            target_basket jsonb,broker text,broker_account_id text,deployment_id text,
            takeover_epoch bigint,superseded_by text)''')
        conn.execute('''CREATE TEMP TABLE sentinel_automation_cycles(
            cycle_id text,state text,execute_at timestamptz,updated_at timestamptz,
            completed_at timestamptz,plan_id text,plan_fingerprint text,created_at timestamptz,
            decision_session date,effective_session date,control_generation bigint,
            deployment_id text,broker text,broker_account_id text,takeover_epoch bigint,
            certificate_sha256 text,config_sha256 text,historical_state_only boolean,
            failure_code text,last_clean_reconciliation_id text)''')
        conn.execute("INSERT INTO sentinel_automation_control VALUES(1,86,'deployment','alpaca','paper',1,'new-cert','new-config',true,false)")
        conn.execute("INSERT INTO sentinel_account_binding VALUES(1,'SENTINEL_OWNED','deployment','alpaca','paper',1)")
        conn.execute('''INSERT INTO sentinel_execution_plans VALUES('old-plan',
            clock_timestamp()-interval '3 minutes',
            (clock_timestamp() AT TIME ZONE 'America/New_York')::date-1,
            (clock_timestamp() AT TIME ZONE 'America/New_York')::date,
            '{}'::jsonb,'alpaca','paper','deployment',1,'new-plan')''')
        conn.execute('''INSERT INTO sentinel_automation_cycles VALUES('old-cycle','SUCCEEDED',
            clock_timestamp()-interval '2 minutes',clock_timestamp()-interval '1 minute',
            clock_timestamp()-interval '1 minute','old-plan','original-fingerprint',
            clock_timestamp()-interval '3 minutes',
            (clock_timestamp() AT TIME ZONE 'America/New_York')::date-1,
            (clock_timestamp() AT TIME ZONE 'America/New_York')::date,
            82,'deployment','alpaca','paper',1,'old-cert','old-config',false,NULL,'277')''')
        calls=[]
        def project(connection,row,*,completed_history=False):
            assert connection is conn
            calls.append((row,completed_history))
            return {'cycle_id':row[0],'completed_history':completed_history}
        monkeypatch.setattr(sources,'_trading_run_row',project)
        yield conn,calls
    finally:
        conn.rollback();conn.close()


def test_real_query_recovers_only_prior_generation_completed_today_history(historical_run_db):
    conn,calls=historical_run_db
    assert sources._current_trading_run(conn) is None
    assert sources._completed_trading_run(conn)=={'cycle_id':'old-cycle','completed_history':True}
    assert len(calls)==1 and calls[0][1] is True
    assert conn.execute('SELECT superseded_by FROM sentinel_execution_plans').fetchone()[0]=='new-plan'
    assert conn.execute('SELECT generation FROM sentinel_automation_control').fetchone()[0]==86


_HISTORICAL_REFUSALS={
    'same_generation':"UPDATE sentinel_automation_cycles SET control_generation=86",
    'future_generation':"UPDATE sentinel_automation_cycles SET control_generation=87",
    'unfinished':"UPDATE sentinel_automation_cycles SET state='RECONCILING'",
    'failed':"UPDATE sentinel_automation_cycles SET state='FAILED'",
    'historical_only':"UPDATE sentinel_automation_cycles SET historical_state_only=true",
    'missing_completion':"UPDATE sentinel_automation_cycles SET completed_at=NULL",
    'completion_before_execution':"UPDATE sentinel_automation_cycles SET completed_at=execute_at-interval '1 second'",
    'future_completion':"UPDATE sentinel_automation_cycles SET completed_at=clock_timestamp()+interval '1 hour'",
    'failure_code':"UPDATE sentinel_automation_cycles SET failure_code='FOREIGN_ACTIVITY'",
    'missing_reconciliation':"UPDATE sentinel_automation_cycles SET last_clean_reconciliation_id=NULL",
    'prior_session':"UPDATE sentinel_automation_cycles SET effective_session=effective_session-1; UPDATE sentinel_execution_plans SET effective_session=effective_session-1",
    'next_session':"UPDATE sentinel_automation_cycles SET effective_session=effective_session+1; UPDATE sentinel_execution_plans SET effective_session=effective_session+1",
    'foreign_control_account':"UPDATE sentinel_automation_control SET broker_account_id='foreign'",
    'foreign_binding_account':"UPDATE sentinel_account_binding SET broker_account_id='foreign'",
    'foreign_control_epoch':"UPDATE sentinel_automation_control SET takeover_epoch=2",
    'foreign_binding_epoch':"UPDATE sentinel_account_binding SET takeover_epoch=2",
    'foreign_control_deployment':"UPDATE sentinel_automation_control SET deployment_id='foreign'",
    'foreign_binding_deployment':"UPDATE sentinel_account_binding SET deployment_id='foreign'",
    'foreign_plan_account':"UPDATE sentinel_execution_plans SET broker_account_id='foreign'",
    'foreign_plan_epoch':"UPDATE sentinel_execution_plans SET takeover_epoch=2",
    'unowned':"UPDATE sentinel_account_binding SET ownership_state='UNOWNED'",
}


@pytest.mark.parametrize('fault',_HISTORICAL_REFUSALS)
def test_real_historical_query_refuses_nonhistorical_or_foreign_evidence(historical_run_db,fault):
    conn,calls=historical_run_db
    conn.execute(_HISTORICAL_REFUSALS[fault])
    assert sources._completed_trading_run(conn) is None
    assert not calls


def test_real_historical_query_refuses_ambiguous_completed_runs(historical_run_db):
    conn,calls=historical_run_db
    conn.execute("INSERT INTO sentinel_automation_cycles SELECT 'second-cycle',state,execute_at,updated_at,completed_at,plan_id,plan_fingerprint,created_at,decision_session,effective_session,control_generation,deployment_id,broker,broker_account_id,takeover_epoch,certificate_sha256,config_sha256,historical_state_only,failure_code,last_clean_reconciliation_id FROM sentinel_automation_cycles")
    with pytest.raises(ValueError,match='multiple|ambiguous'):
        sources._completed_trading_run(conn)
    assert not calls


@pytest.mark.parametrize('guard,fault',[
    ("c.control_generation<a.generation",'same_generation'),
    ("c.broker_account_id=a.broker_account_id",'foreign_control_account'),
    ("b.broker_account_id=c.broker_account_id",'foreign_binding_account'),
    ("c.takeover_epoch=a.takeover_epoch",'foreign_control_epoch'),
    ("b.ownership_state='SENTINEL_OWNED'",'unowned'),
    ("c.state='SUCCEEDED'",'unfinished'),
    ("c.completed_at<=clock_timestamp()",'future_completion'),
    ("c.failure_code IS NULL",'failure_code'),
    ("c.last_clean_reconciliation_id IS NOT NULL",'missing_reconciliation'),
])
def test_real_historical_query_guard_removal_is_detected(historical_run_db,guard,fault):
    conn,_calls=historical_run_db
    conn.execute(_HISTORICAL_REFUSALS[fault])
    source=inspect.getsource(sources._completed_trading_run)
    assert source.count(guard)==1,guard
    scope=dict(sources.__dict__)
    exec(source.replace(guard,'TRUE'),scope)
    assert sources._completed_trading_run(conn) is None
    with pytest.raises(AssertionError):
        assert scope['_completed_trading_run'](conn) is None
