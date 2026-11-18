"""Qualification of healthy, already-activated PAPER successor software delivery."""
from datetime import datetime, timedelta, timezone
import ast
import inspect

import pytest

from tests.scripts.test_sentinel_backed_local_patch import fixture, successor_host
from tests.scripts.test_sentinel_local_delivery_coordinator import coordinator, model, operation, request
from sentinel_local_delivery import checks, reactivated, readiness


MODE = 'POST_TRADE_REACTIVATED'


def reactivated_host():
    host = successor_host()
    host.supports_post_trade_reactivated = True
    host.request['handoff_mode'] = MODE
    state = host.state
    previous = state['control']['generation'] - 4
    state['cycle']['control_generation'] = previous
    actions = ['KILL_ENGAGED','DEACTIVATED','ACTIVATED','KILL_RELEASED']
    events = [dict(generation=previous+i, seq=120+i, action=action, actor='fixture',
                   reason='signed software rollout', detail={}) for i,action in enumerate(actions,1)]
    events[0]['reason'] = 'autonomous deploy fail-closed fence'
    state['reactivation'] = dict(events=events, unsettled_alerts=0, successor_commands=0)
    state['retained_incidents']['a'*64]['payload']['control_generation'] = previous
    fence = dict(events[0])
    fence['control_event_seq'] = fence.pop('seq')
    state['retained_incidents']['b'*64] = dict(event_type='AUTOMATION_KILL_ENGAGED',
        severity='CRITICAL', ack_state='UNACKNOWLEDGED', payload=fence)
    return host


def test_reactivated_request_schema_cannot_be_substituted_for_an_incident_or_regular_receipt(tmp_path):
    req = dict(request(tmp_path), schema=model.REACTIVATED_SCHEMA, handoff_mode=MODE)
    assert model.validate_request(req) == req
    for schema, mode in ((model.SUCCESSOR_SCHEMA,MODE),(model.SCHEMA,MODE),
                         (model.REACTIVATED_SCHEMA,'POST_TRADE_SUCCESSOR'),(model.REACTIVATED_SCHEMA,'PRE_OPEN')):
        with pytest.raises(RuntimeError, match='REQUEST_HANDOFF_MODE'):
            model.validate_request(dict(req, schema=schema, handoff_mode=mode))


@pytest.mark.parametrize('adverse', [None,'unhealthy_predecessor','positions_moved','expired_preflight'])
def test_coordinator_holds_fences_and_observes_both_software_handoffs(tmp_path, operation, monkeypatch, adverse):
    host, old, _ = operation
    subject = dict(old.request, schema=model.REACTIVATED_SCHEMA, handoff_mode=MODE)
    folder = tmp_path/'reactivated'
    folder.mkdir()
    model.write_new(folder/'request.json', subject)
    host.request = subject
    journal = model.Journal(folder)
    host.state['cycle'] = {'execution_close_at':(model.utcnow()+timedelta(
        minutes=14 if adverse=='expired_preflight' else 20)).isoformat()}
    if adverse=='unhealthy_predecessor':
        host.items['sentinel-automation']['State']['Restarting'] = True
    monkeypatch.setattr(coordinator.evidence, 'canonical_check', lambda *_:dict(book='verified',
        settled_native_positions={} if adverse=='positions_moved' else dict(host.native)))
    reports = []
    def observed(h, state, *, wait_until):
        assert h is host and state==host.state
        model.require(model.utcnow()<wait_until, 'APPLICATION_READINESS_DEADLINE')
        reports.append(h.items['sentinel-automation']['Image'])
        return dict(installation_panel_valid_until=(model.utcnow()+timedelta(seconds=20)).isoformat(),
                    operational_ready=False)
    monkeypatch.setattr(coordinator.evidence, 'panel', observed)
    delivery = coordinator.Delivery(host, journal, monotonic=lambda:host.clock, sleep=host.sleep)
    if adverse:
        with pytest.raises(RuntimeError):
            delivery.advance()
        assert journal.read()['stage']=='NEW' and reports==[]
    else:
        receipt=delivery.advance()
        assert receipt['stage']=='VERIFIED' and receipt['artifacts']['operational_ready'] is False
        assert receipt['artifacts']['installation_scope']=='POST_TRADE_REACTIVATED_SOFTWARE_ONLY'
        assert reports==[subject['predecessor']['image'],subject['candidate']['image']]


def test_healthy_successor_adopts_the_completed_lineage_and_accepts_prior_delivered_incidents():
    host = reactivated_host()
    assert fixture.evidence.snapshot(host) == host.state
    assert host.calls == [checks.snapshot_sql(MODE)]
    assert 'interval \'15 minutes\'' in host.calls[0] and 'successor_commands' in host.calls[0]
    assert checks.canonical_program(MODE) == checks.SUCCESSOR_CANONICAL
    host.request['handoff_mode'] = 'POST_TRADE_SUCCESSOR'
    with pytest.raises(RuntimeError, match='UNRELATED_INCIDENT'):
        fixture.evidence.snapshot(host)
    host.request['handoff_mode'] = MODE
    host.supports_post_trade_reactivated = False
    with pytest.raises(RuntimeError, match='REACTIVATED_BACKED_ADAPTER_REQUIRED'):
        fixture.evidence.snapshot(host)


@pytest.mark.parametrize(('path','value'), [
    (('reactivation','events',1,'action'),'KILL_RELEASED'), (('reactivation','events',2,'generation'),1000),
    (('reactivation','events',0,'reason'),'manual operator action'),
    (('reactivation','successor_commands'),1), (('reactivation','unsettled_alerts'),1),
    (('retained_incidents','b'*64,'payload','control_event_seq'),0),
    (('retained_incidents','a'*64,'event_type'),'UNKNOWN'), (('retained_incidents','a'*64,'payload','control_generation'),1),
    (('retained_incidents','a'*64,'payload','broker_outcome_unresolved'),1), (('successor','current_cycles'),1),
    (('successor','original_plan','superseded_by'),'unrelated'), (('other_active',),1), (('inflight',),1),
    (('reconciliation',),None), (('ready',),False), (('control','kill_switch_engaged'),True),
])
def test_active_or_unattributable_successor_refuses(path, value):
    host = reactivated_host()
    target = host.state
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(RuntimeError):
        fixture.evidence.snapshot(host)


def panel():
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-8)))
    stamp, until = now.isoformat(), (now+timedelta(seconds=25)).isoformat()
    keys = ('authority','runtime_identity','broker','alpaca_account','backup_restore','book','exposure',
            'terminals','shadow_verification','shadow_nav','shadow_return','shadow_worker','feed',
            'alert_dispatcher','automation_leader','automation','completed_trading_run','paper_plan',
            'automation_cycle','automation_step_discovery','automation_alerts','paper_reconciliation')
    rows = {k:dict(key=k, status='ok', color='green', value='', current=True, required_current=True,
                   stale=False, future=False, as_of=stamp, valid_until=until) for k in keys}
    rows['shadow_verification']['value']='SHADOW VERIFIED THROUGH 2026-11-17'
    rows['feed']['value']='2026-11-17 · 0 sessions behind'
    rows['automation']['value']='ENABLED · KILL RELEASED'
    expected=dict(plan='current',original_plan='original',cycle_id='completed',decision='2026-11-17',
                  effective='2026-11-18',retained_incidents={'a'*64:{},'b'*64:{}})
    rows['completed_trading_run']['trading_run']=dict(state='SUCCEEDED',completed_at=stamp,intent=dict(
        cycle_id='completed',plan_id='original',decision_session=expected['decision'],effective_session=expected['effective']))
    rows['paper_plan'].update(status='pending',color='amber',value='NOT PREPARED',required_current=False)
    for key,value in (('automation_cycle','WAITING FOR NEXT DECISION'),('automation_step_discovery','WAITING FOR CYCLE')):
        rows[key].update(status='warn',color='amber',value=value,recovery=dict(
            phase='AUTOMATION_DISCOVERY',automatic=True,operator_required=False,active=True,deadline=until))
    rows['paper_reconciliation'].update(status='warn',color='amber',paper_alignment='COMPLETED_WITH_HISTORY',
        operational_fact=dict(kind='PAPER_VERIFICATION',state='PENDING'))
    rows['automation_alerts'].update(status='warn',color='amber',value='0 pending · 0 DLQ · 2 unacked',required_current=False)
    page=dict(rows=list(rows.values()),source_errors=[],color='amber',as_of=stamp,
        observation=dict(current=True,strict_current=True,changed_scopes=[],revalidated_keys=[],valid_until=until),
        operator_review=dict(scope='a'*64,head=10,reviewed_head=7,status='REVIEW',observed_at=stamp,
                             active=[],warnings=['paper_reconciliation']),
        dashboard_health=dict(active_conditions=[],review_conditions=['paper_reconciliation'],status='warn',valid_until=until))
    return page,rows,expected,now


def test_strict_software_observation_preserves_historical_review_and_uses_the_finite_real_expiry():
    page,_,expected,now=panel()
    result=reactivated.verified_panel(page,'CURRENT',expected,now)
    assert result['operational_ready'] is False and result['completed_plan']=='original'
    assert result['current_plan']=='current' and result['installation_panel_valid_until']==page['observation']['valid_until']
    compile(checks.panel_program(MODE,observed=True),'<strict-observed>','exec')


def test_bounded_panel_wait_accepts_renewal_and_refuses_an_adverse_subject():
    page,rows,expected,now=panel()
    expected['handoff_mode']=MODE
    func=next(n for n in ast.parse(readiness.PANEL_WAIT).body if isinstance(n,ast.FunctionDef) and n.name=='pending')
    namespace=dict(expected=expected, datetime=datetime, timezone=timezone, timedelta=timedelta,
        startup={'automation_leader','alert_dispatcher','shadow_worker'}, maintenance_wait=lambda *_:False)
    exec(compile(ast.Module(body=[func],type_ignores=[]),'<installed-readiness-poll>','exec'),namespace)
    pending=namespace['pending']
    assert pending(page,'CURRENT') is None
    page['observation']['strict_current']=False
    assert pending(page,'CURRENT')==['dashboard_subject_revalidation']
    page['observation']['strict_current']=True
    deadline=(now+timedelta(seconds=10)).isoformat()
    rows['paper_reconciliation'].update(value='CHECK IN PROGRESS',valid_until=deadline,
        recovery=dict(phase='FINANCIAL_VERIFICATION',automatic=True,operator_required=False,deadline=deadline))
    assert pending(page,'CURRENT')==['paper_reconciliation']
    rows['broker'].update(color='red',status='fail')
    with pytest.raises(AssertionError, match='NONSTARTUP_READINESS_FAILURE'):
        pending(page,'CURRENT')


@pytest.mark.parametrize('fault', ['foreign_completion','unknown_cash','active_warning','expired','partial','unrelated_warning',
                                  'current_cycle','wrong_plan','dead_leader','sender_failed','changed_count'])
def test_software_panel_refuses_unproven_or_current_failures(fault):
    page,rows,expected,now=panel()
    if fault=='foreign_completion': rows['completed_trading_run']['trading_run']['intent']['plan_id']='new'
    if fault=='unknown_cash': rows['paper_reconciliation']['operational_fact']['state']='UNKNOWN'
    if fault=='active_warning': page['operator_review']['active']=['paper_reconciliation']
    if fault=='expired': now+=timedelta(minutes=1)
    if fault=='partial': page['observation']['strict_current']=False
    if fault=='unrelated_warning': rows['broker'].update(status='warn',color='amber')
    if fault=='current_cycle': rows['automation_cycle']['value']='EXECUTING'
    if fault=='wrong_plan': rows['paper_plan']['status']='ok'
    if fault=='dead_leader': rows['automation_leader']['as_of']=(now-timedelta(minutes=1)).isoformat()
    if fault=='sender_failed': rows['alert_dispatcher']['status']='fail'
    if fault=='changed_count': expected['retained_incidents'].clear()
    with pytest.raises(AssertionError):
        reactivated.verified_panel(page,'CURRENT',expected,now)


def test_removed_reactivation_incident_check_is_caught(monkeypatch):
    source=inspect.getsource(reactivated.require_lineage)
    guard="payload.get('control_event_seq') == event['seq']"
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard,'True'),'<removed-fence-identity>','exec'),vars(reactivated),namespace)
    monkeypatch.setattr(fixture.evidence.reactivated,'require_lineage',namespace['require_lineage'])
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_active_or_unattributable_successor_refuses(('retained_incidents','b'*64,'payload','control_event_seq'),0)
