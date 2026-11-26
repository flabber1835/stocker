"""Human display continuity never grants strict financial or ACK currentness."""
from dataclasses import replace
from datetime import timedelta
import importlib
import json
import re
import shutil
import subprocess

import pytest

from sentinel.panel import model, serialization
from sentinel.panel.banner import BANNER_SCRIPT
from sentinel.panel.presentation import dashboard_health
from sentinel.panel.render import render
from sentinel.panel.styles import CSS
from tests.sentinel.test_operational_dashboard_snapshot import panel as rich_panel
from tests.sentinel.test_panel_banner import execute as run_banner
from tests.support.dashboard_review import reviewed_panel


def display_page(*, current=True):
    rich = rich_panel()
    page = reviewed_panel(now=rich.now, local_paper_mode=True,
        rows=[row for row in rich.rows if row.key != 'paper_reconciliation'])
    return replace(page, observation_current=False,
        observation_changed_scopes=('PAPER',), observation_display_current=current,
        observation_display_keys=tuple(row.key for row in page.rows),
        observation_valid_until=page.now+timedelta(seconds=20))


def completed_page():
    page = display_page()
    original = page.row('paper_plan').paper_plan
    intent = type(original).model_validate({**original.model_dump(),
        'decision_session':page.now.date()-timedelta(days=1),
        'effective_session':page.now.date(), 'execute_at':page.now-timedelta(hours=1),
        'created_at':page.now-timedelta(hours=2),
        'observation_at':page.now-timedelta(hours=3)})
    finished = page.now-timedelta(minutes=30)
    run = model.TradingRun(intent=intent, state='SUCCEEDED', updated_at=finished,
                           completed_at=finished, orders=[])
    rows = [row for row in page.rows if row.key not in {'paper_plan','trading_run','ingest'}]
    rows += [model.Row('paper_plan','Plan','NOT PREPARED',model.PENDING),
        model.Row('trading_run','Run','SUCCEEDED',model.OK,as_of=finished,
            valid_until=page.now+timedelta(hours=1),trading_run=run)]
    return replace(page,rows=rows,observation_display_keys=tuple(row.key for row in rows))


def _marquee(html, *, browser_state=None, script=BANNER_SCRIPT):
    """Run the shipped resource controller against the rendered status."""
    body = re.search(r'<body\b([^>]*)>',html)[1]
    attributes = dict(re.findall(r'([\w-]+)="([^"]*)"',body))
    result = run_banner('selection', script, health=attributes['data-health'],
                        refreshPending=attributes['data-refresh-pending'] == 'true',
                        browserState=browser_state)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    return state['src'], state['unknown']


def test_valuation_handoff_retains_review_history_and_withholds_the_action_token():
    page = display_page()
    review = page.operator_review.model_copy(update={'status':'REVIEW', 'token':'old-action-secret'})
    handoff = replace(page, operator_review=review)
    assert serialization.public_payload(replace(handoff, observation_current=True))['operator_review']['token'] == review.token
    assert serialization.public_payload(handoff)['operator_review'] == {**review.model_dump(mode='json'), 'token':None}
    assert review.token not in render(handoff)


@pytest.mark.parametrize('status,record', [
    ('FAILED', {'active': ['broker']}),
    ('REVIEW', {'warnings': ['paper_reconciliation']}),
])
def test_display_handoff_withdraws_review_when_a_recorded_condition_clears(status, record):
    page = display_page()
    review = page.operator_review.model_copy(update={'status': status, **record})
    payload = serialization.public_payload(replace(page, operator_review=review))
    assert payload['dashboard_health']['active_conditions'] == []
    assert payload['dashboard_health']['review_conditions'] == []
    assert payload['operator_review'] is None


def test_proved_display_is_current_without_strict_machine_or_ack_currentness(monkeypatch):
    page = display_page()
    assert dashboard_health(page)['color']=='green'
    payload = serialization.public_payload(page)
    assert payload['observation']['current'] is True
    assert payload['observation']['display_current'] is True
    assert payload['observation']['strict_current'] is False
    assert payload['operational'] == model.UNKNOWN
    assert payload['operator_review'] == {**page.operator_review.model_dump(mode='json'), 'token': None}
    for withdrawn in (replace(page, observation_display_current=False),
                      replace(page, observation_retained=True),
                      replace(page, observation_changed_scopes=('SHADOW',))):
        assert serialization.public_payload(withdrawn)['operator_review'] is None
    assert all(row['current'] for row in payload['rows'])
    html = render(page)
    assert 'data-observation-current="true"' in html
    assert 'data-strict-observation-current="false"' in html
    assert 'id="review-acknowledge"' not in html
    assert _marquee(html) == ('/static/caesars-status-green.gif', False)
    app = importlib.import_module('sentinel.panel.app')
    monkeypatch.setattr(app,'_read_panel',lambda:page)
    monkeypatch.setattr(app,'_config',lambda:('/private','unused'))
    assert app.panel().headers['X-Sentinel-Panel-Status']=='CURRENT'
    assert app.panel_json().headers['X-Sentinel-Panel-Status']=='CURRENT'
    machine = app.operational_health()
    assert machine.status_code==503
    assert json.loads(machine.body)['current'] is False
    assert json.loads(machine.body)['color']=='neutral'
    from sentinel.panel import projection_service,review_store
    class NoQueries:
        def execute(self,*_):pytest.fail('non-strict ACK must refuse before database work')
    with pytest.raises(review_store.ReviewRefused):
        projection_service.guard_acknowledgement(NoQueries(),page,'unused')


def test_unproved_display_remains_partial_and_cannot_turn_green():
    page=display_page(current=False)
    payload=serialization.public_payload(page)
    assert payload['observation']['current'] is False
    assert payload['observation']['strict_current'] is False
    assert payload['dashboard_health']['color']=='blue'
    assert _marquee(render(page)) == ('/static/caesars-status-green-still.gif', True)


def test_completed_run_stays_visible_during_independently_proved_account_change():
    page=completed_page()
    payload=serialization.public_payload(page)
    run=next(row for row in payload['rows'] if row['key']=='trading_run')
    assert run['current'] and run['trading_run']['state']=='SUCCEEDED'
    html=render(page)
    assert 'Today’s run · no orders placed' in html
    assert 'Next trading plan pending.' not in html
    assert 'Last known account' not in html


@pytest.mark.parametrize('browser_state',[None,'not-current','checking-status'])
def test_partial_current_negative_is_red_until_browser_freshness_is_lost(browser_state,monkeypatch):
    page=display_page(current=False)
    failure=model.Row('paper_reconciliation','Paper','MISMATCH',model.FAIL,
        as_of=page.now,valid_until=page.now+timedelta(seconds=20))
    page=replace(page,rows=[*page.rows,failure],
        observation_revalidated_keys=('paper_reconciliation',))
    assert dashboard_health(page)['color']=='red'
    html=render(page)
    assert 'data-observation-current="false"' in html
    assert _marquee(html,browser_state=browser_state) == {
        None: ('/static/caesars-status-red.gif', False),
        'checking-status': ('/static/caesars-status-red-still.gif', False),
        'not-current': ('/static/caesars-status-green-still.gif', True),
    }[browser_state]
    app=importlib.import_module('sentinel.panel.app')
    monkeypatch.setattr(app,'_read_panel',lambda:page)
    machine=app.operational_health()
    assert machine.status_code==503 and json.loads(machine.body)['color']=='red'


def test_json_reuses_one_human_health_computation(monkeypatch):
    page=display_page();calls=[]
    health=serialization.dashboard_health
    def counted(value):
        calls.append(value);return health(value)
    monkeypatch.setattr(serialization,'dashboard_health',counted)
    payload=serialization.public_payload(page)
    assert calls==[page] and payload['dashboard_health']['color']=='green'


def _countdown(page,*,fresh=True,card=True,delayed=False,add_global_gate=False):
    html=render(page)
    function=re.search(r'  function updateMarketCountdown\(\)\{(.+?)\n  \}\n  window',html,re.S)
    assert function is not None
    script='function updateMarketCountdown(){'+function[1]+'\n}'
    if add_global_gate:
        script=script.replace("card && card.dataset.current === 'true'",
            "document.body.dataset.observationCurrent === 'true' && card && card.dataset.current === 'true'")
    node=shutil.which('node')
    assert node is not None,'Node is required to execute the real countdown controller'
    now=int(page.now.timestamp()*1000)
    data=dict(script=script,now=now,end=now+3600000,fresh=fresh,card=card,delayed=delayed)
    harness=r'''const vm=require('node:vm'),fs=require('node:fs');
const p=JSON.parse(fs.readFileSync(0,'utf8'));
class Clock extends Date {static now(){return p.now+3600000;}}
const card={dataset:{current:String(p.card)}};
const counter={dataset:{marketOpenAt:new Date(p.end).toISOString()},textContent:'',closest:()=>card};
vm.runInNewContext(p.script+';updateMarketCountdown();',{
 document:{body:{dataset:{observationCurrent:'false'}},getElementById:()=>counter},
 Date:Clock,generated:p.now-500,evidenceAge:()=>500,
 originalCurrent:()=>p.fresh,invalidated:false,refreshDelayed:p.delayed});
process.stdout.write(counter.textContent);'''
    result=subprocess.run([node,'-e',harness],input=json.dumps(data),text=True,
                          capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    return result.stdout


@pytest.mark.parametrize('fresh,card,delayed,expected',[
    (True,True,False,'Market open in 1 hour 0 minutes'),
    (False,True,False,'Market-open time not current'),
    (True,False,False,'Market-open time not current'),
    (True,True,True,'Market-open time not current')])
def test_countdown_uses_its_own_card_and_browser_bounds(fresh,card,delayed,expected):
    assert _countdown(display_page(current=False),fresh=fresh,card=card,delayed=delayed)==expected


def test_reintroduced_global_countdown_gate_is_detected():
    with pytest.raises(AssertionError):
        assert _countdown(display_page(current=False),add_global_gate=True).startswith('Market open in')


@pytest.mark.parametrize('cutoff', ['market', 'execution'])
def test_signed_opening_boundary_shows_checking_without_current_plan_or_machine_readiness(cutoff, monkeypatch):
    page = display_page(current=False)
    plan_row = page.row('paper_plan')
    opened = page.now if cutoff == 'market' else page.now - timedelta(minutes=1)
    execute = opened + timedelta(minutes=1)
    preview = plan_row.paper_plan.model_copy(update={'execution_open_at':opened, 'execute_at':execute})
    plan_row = replace(plan_row, paper_plan=preview, valid_until=execute)
    cycle = model.Row('automation_cycle', 'Cycle', 'WAITING_OPEN', model.WARN,
        operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE', state='WAITING_OPEN'))
    changed = ('PAPER',) if cutoff == 'execution' else ()
    page = replace(page, observation_generated_at=page.now-timedelta(milliseconds=500),
        observation_changed_scopes=changed, observation_retained=True, observation_display_keys=(),
        rows=[row for row in page.rows if row.key not in {'paper_plan','automation_cycle'}] + [plan_row, cycle])
    health = dashboard_health(page)
    assert health['color'] == 'blue' and health['opening_refresh'] is True
    assert health['plan_readiness'] == 'unavailable'
    html = render(page)
    assert 'id="operational-state" class="state checking"' in html
    assert _marquee(html) == ('/static/caesars-status-green-still.gif', True)
    assert _marquee(html, browser_state='not-current') == ('/static/caesars-status-green-still.gif', True)
    module = importlib.import_module('sentinel.panel.app')
    monkeypatch.setattr(module,'_read_panel',lambda:page)
    assert module.panel_json().headers['X-Sentinel-Panel-Status']=='PARTIAL'
    machine = module.operational_health()
    assert machine.status_code==503 and json.loads(machine.body)['color']=='neutral'

    assert dashboard_health(replace(page, observation_changed_scopes=('SHADOW',)))['color']=='blue'
    assert dashboard_health(replace(page, now=page.observation_valid_until))['color']=='blue'
    failure = model.Row('backup_restore', 'Backup', 'Proof failed', model.FAIL)
    adverse = replace(page, rows=[row for row in page.rows if row.key != 'backup_restore'] + [failure])
    assert dashboard_health(adverse)['color']=='red'


def test_partial_execution_refresh_requires_original_finite_callback():
    page = display_page(current=False)
    preview = page.row('paper_plan').paper_plan.model_copy(
        update={'execute_at':page.now-timedelta(seconds=5)})
    run = model.TradingRun(intent=preview, state='EXECUTING', updated_at=preview.execute_at)
    cycle = model.Row('automation_cycle', 'Cycle', 'EXECUTING', model.WARN,
        operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE', state='EXECUTING'))
    trading = model.Row('trading_run', 'Run', 'EXECUTING', model.WARN, trading_run=run)
    recovery = model.RecoveryEvidence(phase='BROKER_CALLBACK_REFRESH', automatic=True,
        next_attempt_at=page.now+timedelta(seconds=1), attempt=1, maximum_attempts=2)
    broker = model.Row('broker', 'Broker', 'Refreshing', model.WARN, recovery=recovery)
    base = [row for row in page.rows if row.key not in {'broker','automation_cycle','trading_run'}]
    page = replace(page, observation_generated_at=page.now-timedelta(seconds=1),
        observation_display_keys=(), rows=base + [broker, cycle, trading])
    assert dashboard_health(page)['color'] == 'blue'

    deadline = page.now+timedelta(seconds=5)
    broker = replace(broker, recovery=replace(recovery, deadline=deadline))
    page = replace(page, rows=base + [broker, cycle, trading])
    assert dashboard_health(page)['opening_refresh'] is True
    assert dashboard_health(replace(page, now=deadline))['color'] == 'blue'


@pytest.mark.parametrize('action,online,health_color,current,expected_class,expected_badge', [
    ('pendingRefresh', True, 'green', True, '', 'state ok'),
    ('showResume', True, 'green', True, '', 'state ok'),
    ('showResume', True, 'green', False, 'checking-status', 'state checking'),
    ('invalidate', True, 'green', False, 'checking-status', 'state checking'),
    ('invalidate', False, 'green', False, 'not-current', 'state neutral'),
    ('pendingRefresh', True, 'red', True, '', 'state fail'),
    ('showResume', True, 'red', True, '', 'state fail'),
    ('showResume', True, 'red', False, 'checking-status', 'state fail'),
    ('invalidate', True, 'red', False, 'checking-status', 'state fail'),
    ('invalidate', False, 'red', False, 'not-current', 'state fail'),
])
def test_browser_refresh_preserves_valid_color_then_distinguishes_checking_from_offline(
        action, online, health_color, current, expected_class, expected_badge):
    page = display_page()
    if health_color == 'red':
        failed = model.Row('backup_restore', 'Backup', 'FAILED', model.FAIL)
        page = replace(page, rows=[row for row in page.rows
                                   if row.key != 'backup_restore'] + [failed])
    html = render(page)
    functions = []
    for name in ('pendingRefresh', 'showResume', 'invalidate', 'showLastVerifiedStatus', 'rememberWarning'):
        start = html.index('  function '+name+'(')
        end = html.index('\n  function ', start+2)
        functions.append(html[start:end])
    node = shutil.which('node')
    assert node is not None
    harness = r'''const vm=require('node:vm'),fs=require('node:fs');
const p=JSON.parse(fs.readFileSync(0,'utf8'));
const classes=new Set(p.online?[]:['checking-status']);
const badge={className:p.health==='red'?'state fail':'state ok',textContent:'Current status'};
const heartbeat={textContent:''};
const context={document:{body:{dataset:{health:p.health}},documentElement:{classList:{
  add:(...values)=>values.forEach(value=>classes.add(value)), remove:(...values)=>values.forEach(value=>classes.delete(value)),
  contains:(value)=>classes.has(value)}}},
  navigator:{onLine:p.online},badge,heartbeat,generated:p.generated,verifiedWarning:null,
  invalidated:!p.online,hardFailure:false,refreshDelayed:false,originalCurrent:()=>p.current,
  withdrawPreparation:()=>{},clockReversed:()=>false,refreshDocument:()=>{}};
vm.runInNewContext(p.script+';rememberWarning();'+p.action+'(false,false);',context);
process.stdout.write(JSON.stringify({classes:[...classes],badge:badge.className,text:badge.textContent}));'''
    result = subprocess.run([node, '-e', harness], input=json.dumps({
        'script':'\n'.join(functions), 'action':action, 'online':online,
        'health':health_color, 'current':current, 'generated':int(page.now.timestamp()*1000)}),
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    expected_classes = [expected_class] if expected_class else []
    if action == 'invalidate' and online:
        expected_classes.append('expired-status')
    assert state['classes'] == expected_classes
    assert state['badge'] == expected_badge
    if current:
        assert state['text'] == 'Current status'
    elif health_color == 'red':
        assert state['text'].startswith('LAST KNOWN TRADING STOP')
        assert page.now.date().isoformat() in state['text']
    if not online or (expected_class and health_color == 'green'):
        expected_image = ('/static/caesars-status-green-still.gif', True)
    else:
        suffix = '-still' if expected_class else ''
        expected_image = (f'/static/caesars-status-{health_color}{suffix}.gif', False)
    assert _marquee(html, browser_state=expected_class or None) == expected_image
    if not online:
        assert _marquee(render(page, refresh_pending=True),
                        browser_state='not-current') == ('/static/caesars-status-green-still.gif', True)


def test_refresh_cannot_replace_the_red_sign_with_the_neutral_sign():
    page = display_page()
    retained = render(page, refresh_pending=True)
    assert _marquee(retained) == ('/static/caesars-status-green-still.gif', True)
    assert 'id="operational-state" class="state checking"' in retained
    failed = model.Row('backup_restore', 'Backup', 'FAILED', model.FAIL)
    page = replace(page, rows=[row for row in page.rows
                               if row.key != 'backup_restore'] + [failed])
    html = render(page, refresh_pending=True)
    assert 'id="operational-state" class="state fail"' in html
    assert 'Last known trading stop · checking for an update' in html
    assert '.brand img.unknown-sign{filter:grayscale(1) sepia(.75)}' in CSS
    assert '.not-current .brand img.unknown-sign{filter:grayscale(1)}' in CSS
    expected = ('/static/caesars-status-red-still.gif', False)
    assert _marquee(html, browser_state='checking-status') == expected
    guard = "(checking && color === 'green')"
    assert BANNER_SCRIPT.count(guard) == 1
    broken = BANNER_SCRIPT.replace(guard, 'checking')
    assert _marquee(html, browser_state='checking-status', script=broken) != expected
