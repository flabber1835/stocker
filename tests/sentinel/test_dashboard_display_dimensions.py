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
from sentinel.panel.presentation import dashboard_health
from sentinel.panel.render import render
from sentinel.panel.styles import CSS
from tests.sentinel.test_operational_dashboard_snapshot import panel as rich_panel
from tests.sentinel.test_panel_styles import _rules, _specificity
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


def _brand_border(html, *, browser_state=None, css=CSS):
    """Apply the actual brand cascade to its finite body/lifecycle attributes."""
    body = re.search(r'<body\b([^>]*)>',html)[1]
    attributes = dict(re.findall(r'([\w-]+)="([^"]*)"',body))
    winner = None
    for order,(selector,content,_media) in enumerate(_rules(css)):
        if selector != '.brand' and not selector.endswith(' .brand'):
            continue
        if selector.startswith('.') and selector != '.brand':
            if selector.split()[0][1:] != browser_state:
                continue
        exclusions = re.findall(r':not\(\[([\w-]+)="([^"]*)"\]\)',selector)
        if any(attributes.get(key)==value for key,value in exclusions):
            continue
        positive = re.sub(r':not\([^)]*\)','',selector)
        if any(attributes.get(key)!=value for key,value in
               re.findall(r'\[([\w-]+)="([^"]*)"\]',positive)):
            continue
        declarations = dict(part.strip().split(':',1) for part in content.split(';') if ':' in part)
        color = declarations.get('border-color')
        if color is None and 'border' in declarations:
            color = declarations['border'].split()[-1]
        if color is not None:
            priority = (_specificity(selector),order)
            if winner is None or priority >= winner[0]:
                winner = (priority,color)
    assert winner is not None
    return winner[1]


def test_proved_display_is_current_without_strict_machine_or_ack_currentness(monkeypatch):
    page = display_page()
    assert dashboard_health(page)['color']=='green'
    payload = serialization.public_payload(page)
    assert payload['observation']['current'] is True
    assert payload['observation']['display_current'] is True
    assert payload['observation']['strict_current'] is False
    assert payload['operational']==model.UNKNOWN and payload['operator_review'] is None
    assert all(row['current'] for row in payload['rows'])
    html = render(page)
    assert 'data-observation-current="true"' in html
    assert 'data-strict-observation-current="false"' in html
    assert 'id="review-acknowledge"' not in html
    assert _brand_border(html)=='var(--ok)'
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
    assert payload['dashboard_health']['color']=='neutral'
    assert _brand_border(render(page))=='#8b8b93'


def test_completed_run_stays_visible_during_independently_proved_account_change():
    page=completed_page()
    payload=serialization.public_payload(page)
    run=next(row for row in payload['rows'] if row['key']=='trading_run')
    assert run['current'] and run['trading_run']['state']=='SUCCEEDED'
    html=render(page)
    assert 'Today’s trades · completed' in html
    assert 'Next trading plan pending.' not in html
    assert 'Last known account' not in html


@pytest.mark.parametrize('browser_state',[None,'not-current','refreshing-status'])
def test_partial_current_negative_is_red_until_browser_freshness_is_lost(browser_state,monkeypatch):
    page=display_page(current=False)
    failure=model.Row('paper_reconciliation','Paper','MISMATCH',model.FAIL,
        as_of=page.now,valid_until=page.now+timedelta(seconds=20))
    page=replace(page,rows=[*page.rows,failure],
        observation_revalidated_keys=('paper_reconciliation',))
    assert dashboard_health(page)['color']=='red'
    html=render(page)
    assert 'data-observation-current="false"' in html
    assert _brand_border(html,browser_state=browser_state)==(
        'var(--fail)' if browser_state is None else '#8b8b93')
    app=importlib.import_module('sentinel.panel.app')
    monkeypatch.setattr(app,'_read_panel',lambda:page)
    machine=app.operational_health()
    assert machine.status_code==503 and json.loads(machine.body)['color']=='red'


def test_removed_current_negative_border_guard_is_detected():
    page=display_page(current=False)
    failure=model.Row('paper_reconciliation','Paper','MISMATCH',model.FAIL,as_of=page.now)
    page=replace(page,rows=[*page.rows,failure],observation_revalidated_keys=('paper_reconciliation',))
    guard=':not([data-health="red"])'
    assert CSS.count(guard)==1
    broken=CSS.replace(guard,'')
    with pytest.raises(AssertionError):
        assert _brand_border(render(page),css=broken)=='var(--fail)'


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
class Clock extends Date {static now(){return p.now;}}
const card={dataset:{current:String(p.card)}};
const counter={dataset:{marketOpenAt:new Date(p.end).toISOString()},textContent:'',closest:()=>card};
vm.runInNewContext(p.script+';updateMarketCountdown();',{
 document:{body:{dataset:{observationCurrent:'false'}},getElementById:()=>counter},
 Date:Clock,originalCurrent:()=>p.fresh,invalidated:false,refreshDelayed:p.delayed});
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
