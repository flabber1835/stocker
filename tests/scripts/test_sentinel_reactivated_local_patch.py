"""Qualification of healthy, already-activated PAPER successor software delivery."""
from datetime import datetime, timedelta, timezone
import ast
import inspect

import pytest

from tests.scripts.test_sentinel_backed_local_patch import fixture, successor_host
from tests.scripts.test_sentinel_local_delivery_coordinator import coordinator, model, operation, request
from tests.scripts.test_install_verification_recovery import expired, recovery as verification_recovery
from sentinel_local_delivery import checks, reactivated, readiness


MODE = 'POST_TRADE_REACTIVATED'


def expired_reactivation(operation, monkeypatch, close_minutes=30):
    host, original, delivery = operation
    selected = dict(original.request, schema=model.REACTIVATED_SCHEMA, handoff_mode=MODE)
    model.atomic_json(original.folder/'request.json', selected)
    host.request = selected
    delivery.journal = model.Journal(original.folder)
    host.supports_post_trade = host.supports_post_trade_verification_recovery = True
    host.supports_post_trade_successor = host.supports_post_trade_reactivated = True
    host.state = reactivated_host().state
    cycle = host.state['cycle']
    # expired() advances the recovery clock 1000s after startup.
    cycle.update(completed_at=model.utcnow().isoformat(), execution_close_at=(
        model.utcnow()+timedelta(seconds=1000, minutes=close_minutes)).isoformat())
    def canonical(h, *args, timeout=300):
        h.canonical_count += 1
        assert 0 < timeout <= 300
        return dict(book='same', settled_native_positions=dict(h.native))
    def panel(h, state, *, wait_until):
        return dict(operational_ready=False, current_plan=state['plan']['plan_id'],
            completed_cycle=state['cycle']['cycle_id'], completed_plan=state['cycle']['plan_id'],
            installation_panel_valid_until=(model.utcnow()+timedelta(seconds=25)).isoformat())
    monkeypatch.setattr(coordinator.evidence, 'canonical_check', canonical)
    monkeypatch.setattr(coordinator.evidence, 'panel', panel)
    monkeypatch.setattr(coordinator.evidence, 'leader', lambda h:dict(
        current=True, holder='owner', generation=h.state['control']['generation'], fence=8, heartbeat=h.heartbeat))
    return expired((host, delivery.journal, delivery), monkeypatch)


def test_expired_reactivation_explicitly_reobserves_same_software_only_install(operation, monkeypatch):
    host, journal, delivery = expired_reactivation(operation, monkeypatch, close_minutes=18)
    before = journal.read()
    with pytest.raises(model.DeliveryRefused, match='APPLICATION_READINESS_DEADLINE'):
        delivery.advance()
    clock = model.utcnow()
    def now():
        return clock+timedelta(seconds=host.clock)
    monkeypatch.setattr(verification_recovery, 'utcnow', now)
    unchanged = delivery._unchanged
    after_native = []
    def slow_observation(artifacts, **kwargs):
        if kwargs.get('observation'):
            host.clock += 12
            after_native.append(now())
        return unchanged(artifacts, **kwargs)
    monkeypatch.setattr(delivery, '_unchanged', slow_observation)
    observed = coordinator.evidence.panel
    def short_publication(*args, **kwargs):
        assert after_native == [now()]
        return dict(observed(*args, **kwargs), installation_panel_valid_until=(now()+timedelta(seconds=2)).isoformat())
    monkeypatch.setattr(coordinator.evidence, 'panel', short_publication)
    calls, proofs = len(host.calls), host.canonical_count
    result = verification_recovery.recover(delivery, 'after-start')
    assert result['history'][:-1] == before['history'] and result['stage'] == 'VERIFIED'
    assert all(result['artifacts'][key]==value for key,value in before['artifacts'].items())
    assert result['artifacts']['installation_scope'] == 'POST_TRADE_REACTIVATED_SOFTWARE_ONLY'
    assert result['artifacts']['operational_ready'] is False
    intent = model.read_json(journal.folder/'verification-recovery-after-start.json')
    assert intent['original_receipt'] == before and intent['authority_effect'] == 'NONE'
    assert datetime.fromisoformat(intent['expires_at']) == (
        datetime.fromisoformat(host.state['cycle']['execution_close_at'])-timedelta(minutes=15))
    assert not any(isinstance(call, (tuple,list)) for call in host.calls[calls:])
    assert host.canonical_count == proofs+1 and host.state == before['artifacts']['preserved']


@pytest.mark.parametrize('fault,reason', [
    ('close','RECOVERY_CLOSE_MARGIN_EXPIRED'), ('late','RECOVERY_DEADLINE'),
    ('adapter','REACTIVATED_BACKED_ADAPTER_REQUIRED'), ('source','CANONICAL_ECONOMIC'),
    ('edge','REACTIVATED_CONTROL_LINEAGE_CHANGED'), ('successor','SUCCESSOR_DIRECT_LINEAGE_CHANGED'),
    ('prior_alert','REACTIVATED_HISTORICAL_FENCE_CHANGED'), ('reconciliation','POST_TRADE_COMPLETION_REQUIRED'),
    ('panel_subject','REACTIVATED_PANEL_SUBJECT_CHANGED'), ('leader','LEADERSHIP_CHANGED'),
    ('late_command','PRESERVED_STATE_CHANGED'), ('late_alert','HISTORY_CHANGED'),
    ('late_positions','NATIVE_HOLDINGS'), ('restart','APPLICATION_STARTUP_PROCESS')])
def test_refused_reactivation_recovery_preserves_original_receipt(operation, monkeypatch, fault, reason):
    from copy import deepcopy
    host, journal, delivery = expired_reactivation(operation, monkeypatch,
        close_minutes=15 if fault=='close' else 18)
    original = journal.read()
    before = deepcopy(original)
    state = before['artifacts']['preserved']
    if fault in {'edge','successor','prior_alert','reconciliation'}:
        if fault=='edge': state['reactivation']['events'][1]['action']='ACTIVATED'
        elif fault=='successor': state['successor']['original_plan']['superseded_by']='foreign'
        elif fault=='prior_alert': state['retained_incidents']['b'*64]['payload']['control_event_seq']=-1
        else: state['reconciliation']['seq']+=1
        monkeypatch.setattr(journal, 'read', lambda:deepcopy(before))
    elif fault=='adapter':host.supports_post_trade_reactivated=False
    elif fault=='source':monkeypatch.setattr(coordinator.evidence,'canonical_check',lambda *a,**kw:{})
    elif fault=='late':
        def expire(*a,timeout):
            assert 0 < timeout <= 180
            host.clock += 181
            return before['artifacts']['canonical_proof']
        monkeypatch.setattr(coordinator.evidence,'canonical_check',expire)
    elif fault in {'late_command','late_alert','late_positions'}:
        canonical=coordinator.evidence.canonical_check
        def changed_during_proof(*a,**kw):
            value=canonical(*a,**kw)
            if fault=='late_command':host.state['inflight']+=1
            elif fault=='late_alert':host.notifications['old']='changed'
            else:host.native['native-id']='18'
            return value
        monkeypatch.setattr(coordinator.evidence,'canonical_check',changed_during_proof)
    elif fault!='close':
        observed=coordinator.evidence.panel
        def changed(*a,**kw):
            value=observed(*a,**kw)
            if fault=='panel_subject':value['completed_plan']=value['current_plan']
            elif fault=='leader':monkeypatch.setattr(coordinator.evidence,'leader',lambda h:dict(
                current=True, holder='another', generation=h.state['control']['generation'], fence=9, heartbeat=h.heartbeat))
            else:host.items['sentinel-panel']['RestartCount']+=1
            return value
        monkeypatch.setattr(coordinator.evidence,'panel',changed)
    with pytest.raises(model.DeliveryRefused, match=reason):
        verification_recovery.recover(delivery, 'refusal')
    assert model.Journal(journal.folder).read()==original
    if fault in {'adapter','edge','successor','prior_alert','reconciliation','close'}:
        assert not list(journal.folder.glob('verification-recovery-*'))
    else:
        result=model.read_json(journal.folder/'verification-recovery-refusal.result.json')
        assert result['outcome']=='REFUSED'


def test_removing_reactivation_post_proof_preservation_is_detected(operation, monkeypatch):
    original=coordinator.Delivery._unchanged
    def missing_final_preservation(delivery, artifacts, **kwargs):
        if kwargs.get('observation'):return artifacts['postgres'],{}
        return original(delivery,artifacts,**kwargs)
    monkeypatch.setattr(coordinator.Delivery,'_unchanged',missing_final_preservation)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_refused_reactivation_recovery_preserves_original_receipt(operation,monkeypatch,
            'late_command','PRESERVED_STATE_CHANGED')


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


def panel(now=None):
    if now is None:
        now = datetime(2026,11,18,10,15,tzinfo=timezone(timedelta(hours=-8)))
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
    rows['paper_plan'].update(status='pending',color='amber',value='NOT PREPARED',required_current=False,paper_plan=None)
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


@pytest.mark.parametrize('producer', ['predecessor', 'current'])
def test_strict_software_observation_preserves_historical_review_and_uses_the_finite_real_expiry(producer):
    from sentinel.panel import model as panel_model, sources
    from sentinel.paper_plan_preview import PlanPreview

    page,rows,expected,now=panel()
    if producer=='current':
        completed=rows['completed_trading_run']['trading_run']
        intent=PlanPreview(**completed['intent'],execute_at=now-timedelta(hours=2),
            created_at=now-timedelta(days=1),observation_at=None,legs=[])
        run=panel_model.TradingRun(intent=intent,state='SUCCEEDED',updated_at=now,completed_at=now,orders=[])
        history=panel_model.Row('completed_trading_run','Completed','SUCCEEDED',panel_model.OK,as_of=now,trading_run=run)
        pending=sources._pending_next_plan(history,now=now)
        assert pending.value=='2026-11-19 · awaiting plan'
        rows['paper_plan'].update(value=pending.value,status=pending.status,paper_plan=pending.paper_plan)
    result=reactivated.verified_panel(page,'CURRENT',expected,now)
    assert result['operational_ready'] is False and result['completed_plan']=='original'
    assert result['current_plan']=='current' and result['installation_panel_valid_until']==page['observation']['valid_until']
    compile(checks.panel_program(MODE,observed=True),'<strict-observed>','exec')


@pytest.mark.parametrize('label',['NOT PREPARED','2026-11-19 · awaiting plan'])
def test_current_handoff_sample_can_be_read_across_new_york_midnight(label):
    sampled=datetime(2026,11,19,4,59,55,tzinfo=timezone.utc)
    page,rows,expected,_=panel(sampled)
    rows['completed_trading_run']['trading_run']['completed_at']='2026-11-18T15:10:00+00:00'
    rows['paper_plan']['value']=label
    assert reactivated.verified_panel(page,'CURRENT',expected,sampled+timedelta(seconds=10))['completed_plan']=='original'


def test_bounded_panel_wait_accepts_renewal_and_refuses_an_adverse_subject():
    page,rows,expected,now=panel(datetime.now(timezone.utc))
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
                                  'current_cycle','wrong_plan','wrong_date','generic_wait','adoption','attached_plan',
                                  'previous_session','dead_leader','sender_failed','changed_count'])
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
    if fault=='wrong_date': rows['paper_plan']['value']='2026-11-20 · awaiting plan'
    if fault=='generic_wait': rows['paper_plan']['value']='AWAITING NEXT PLAN'
    if fault=='adoption':
        from sentinel.panel.model import AWAITING_PLAN_ADOPTION
        rows['paper_plan']['value']=AWAITING_PLAN_ADOPTION
    if fault=='attached_plan': rows['paper_plan']['paper_plan']={'plan_id':'new'}
    if fault=='previous_session':
        expected['decision'],expected['effective']='2026-11-16','2026-11-17'
        rows['completed_trading_run']['trading_run']['intent'].update(
            decision_session=expected['decision'],effective_session=expected['effective'])
        rows['paper_plan']['value']='2026-11-18 · awaiting plan'
        rows['feed']['value']=expected['decision']+' · 0 sessions behind'
        rows['shadow_verification']['value']='SHADOW VERIFIED THROUGH '+expected['decision']
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
