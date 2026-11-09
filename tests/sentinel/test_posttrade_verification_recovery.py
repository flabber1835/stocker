"""Post-trade final observation preserves the expired attempt and financial state."""
from copy import deepcopy
from datetime import timedelta
import importlib

import pytest

from tests.scripts.test_sentinel_local_delivery_coordinator import coordinator, model, operation
from tests.scripts.test_install_verification_recovery import expired

recovery = importlib.import_module(coordinator.__package__+'.verification_recovery')


def post_trade(operation, monkeypatch):
    host, journal, delivery = operation
    selected = deepcopy(host.request)
    selected['handoff_mode'] = 'POST_TRADE'
    # Select this mode before the first installation record, not by rewriting
    # an expired request or receipt during recovery.
    assert journal.read()['stage'] == 'NEW'
    model.atomic_json(journal.folder/'request.json', selected)
    journal = model.Journal(journal.folder)
    host.request = selected
    delivery.journal = journal
    host.supports_post_trade = True
    host.supports_post_trade_verification_recovery = True
    host.state.update(plan={'plan_id':'completed-plan'},
        cycle=dict(cycle_id='completed-cycle',state='SUCCEEDED',plan_id='completed-plan',
            completed_at=model.utcnow().isoformat(),historical_state_only=False,
            failure_code=None,failure_detail=None,control_generation=77,
            last_clean_reconciliation_id=391),reconciliation={'seq':391})
    canonical=recovery.evidence.canonical_check
    settled=deepcopy(host.native)
    def completed_proof(h,*args):
        return dict(canonical(h,*args),settled_native_positions=deepcopy(settled))
    monkeypatch.setattr(recovery.evidence,'canonical_check',completed_proof)
    return expired((host,journal,delivery), monkeypatch)


@pytest.mark.parametrize('review_pending',[False,True])
def test_completed_posttrade_recovery_is_one_fresh_observation_without_restart_or_ack(operation,monkeypatch,review_pending):
    host,journal,delivery=post_trade(operation,monkeypatch)
    before=journal.read();calls=len(host.calls);canonical=host.canonical_count
    if review_pending:
        original=recovery.evidence.panel
        def pending(*a,**kw):
            return dict(original(*a,**kw),operational_ready=False,installation_review_pending=True,
                installation_scope='POST_TRADE_COMPATIBLE_APPLICATION_REPAIR_WITH_OPERATOR_REVIEW')
        monkeypatch.setattr(recovery.evidence,'panel',pending)
    with pytest.raises(model.DeliveryRefused,match='APPLICATION_READINESS_DEADLINE'):
        delivery.advance()
    result=recovery.recover(delivery,'posttrade-observation')
    assert result['stage']=='VERIFIED' and result['history'][:-1]==before['history']
    assert all(result['artifacts'][key]==value for key,value in before['artifacts'].items())
    assert host.canonical_count==canonical+1
    assert not any(isinstance(call,(tuple,list)) for call in host.calls[calls:])
    assert host.state==before['artifacts']['preserved']
    assert host.notifications=={'old':'immutable-payload'}
    intent=model.read_json(journal.folder/'verification-recovery-posttrade-observation.json')
    assert intent['handoff_mode']=='POST_TRADE' and intent['authority_effect']=='NONE'
    assert intent['original_receipt']==before
    assert intent['original_receipt_sha256']==model.digest(before)
    assert result['artifacts']['verification_recovery']['original_receipt_sha256']==model.digest(before)
    assert result['artifacts']['verification_recovery']['authority_effect']=='NONE'
    assert recovery.SECONDS==600
    if review_pending:
        assert result['artifacts']['operational_ready'] is False
        assert result['artifacts']['installation_scope']=='POST_TRADE_COMPATIBLE_APPLICATION_REPAIR_WITH_OPERATOR_REVIEW'
    assert delivery.advance()==result


@pytest.mark.parametrize('fault',['state','historical','completed','future','failure','plan','cycle',
    'generation','reconciliation','adapter','mode','request'])
def test_posttrade_scope_refuses_unsettled_or_foreign_completion_before_intent(operation,monkeypatch,fault):
    host,journal,delivery=post_trade(operation,monkeypatch)
    before=deepcopy(journal.read())
    if fault in {'adapter','mode','request'}:
        if fault=='adapter':host.supports_post_trade_verification_recovery=False
        elif fault=='mode':monkeypatch.setattr(recovery,'handoff_mode',lambda _:'POST_TRADE_SUCCESSOR')
        else:host.request=dict(host.request,operation_id='different-request')
    else:
        changed=deepcopy(before)
        state=changed['artifacts']['preserved'];cycle=state['cycle']
        if fault=='state':cycle['state']='RECONCILING'
        elif fault=='historical':cycle['historical_state_only']=True
        elif fault=='completed':cycle['completed_at']=None
        elif fault=='future':cycle['completed_at']=(model.utcnow()+timedelta(minutes=1)).isoformat()
        elif fault=='failure':cycle['failure_code']='UNRESOLVED_OUTCOME'
        elif fault=='plan':state['plan']['plan_id']='different-plan'
        elif fault=='cycle':cycle.pop('cycle_id')
        elif fault=='generation':cycle['control_generation']+=1
        elif fault=='reconciliation':state['reconciliation']['seq']+=1
        host.state=deepcopy(state)
        monkeypatch.setattr(journal,'read',lambda:deepcopy(changed))
    with pytest.raises(model.DeliveryRefused):
        recovery.recover(delivery,'unsettled')
    assert not list(journal.folder.glob('verification-recovery-*'))


@pytest.mark.parametrize('fault,reason',[
    ('canonical','CANONICAL_ECONOMIC'),('state','PRESERVED_STATE'),('native','NATIVE_HOLDINGS'),
    ('notifications','HISTORY_CHANGED'),('postgres','POSTGRES_CHANGED'),
    ('configuration','NON_RUNTIME_CONFIGURATION'),('source','SOURCE_CHANGED'),
    ('process','APPLICATION_STARTUP_PROCESS'),('deadline','RECOVERY_DEADLINE'),
    ('expired_panel','INSTALLATION_PANEL_EXPIRED'),('changed_after_panel','APPLICATION_STARTUP_PROCESS'),
    ('review_scope','RECOVERY_REVIEW_SCOPE_INVALID')])
def test_posttrade_recovery_refusals_preserve_receipt_and_old_deadline(operation,monkeypatch,fault,reason):
    host,journal,delivery=post_trade(operation,monkeypatch)
    before=journal.read()
    if fault=='canonical':monkeypatch.setattr(recovery.evidence,'canonical_check',lambda *a:{'changed':True})
    elif fault=='state':host.state['commands']='changed'
    elif fault=='native':host.native['native-id']='18'
    elif fault=='notifications':host.notifications['old']='changed'
    elif fault=='postgres':monkeypatch.setattr(host,'postgres',lambda:{'system':'different'})
    elif fault=='configuration':host.values['SECRET']='changed'
    elif fault=='source':monkeypatch.setattr(host,'verify_candidate',lambda:model.require(False,'SOURCE_CHANGED'))
    elif fault=='process':host.items['sentinel-panel']['RestartCount']+=1
    elif fault=='deadline':
        def proof(*a):host.clock+=recovery.SECONDS+1;return before['artifacts']['canonical_proof']
        monkeypatch.setattr(recovery.evidence,'canonical_check',proof)
    else:
        original=recovery.evidence.panel
        def panel(*a,**kw):
            result=original(*a,**kw)
            if fault=='expired_panel':result['installation_panel_valid_until']=model.utcnow().isoformat()
            elif fault=='changed_after_panel':host.items['sentinel-panel']['RestartCount']+=1
            else:result.update(installation_review_pending=True,operational_ready=True,
                installation_scope='POST_TRADE_COMPATIBLE_APPLICATION_REPAIR_WITH_OPERATOR_REVIEW')
            return result
        monkeypatch.setattr(recovery.evidence,'panel',panel)
    with pytest.raises(model.DeliveryRefused,match=reason):
        recovery.recover(delivery,'refusal')
    assert journal.read()==before
    result=model.read_json(journal.folder/'verification-recovery-refusal.result.json')
    assert result['outcome']=='REFUSED'
    with pytest.raises(model.DeliveryRefused,match='RECOVERY_ID_ALREADY_USED'):
        recovery.recover(delivery,'refusal')


def test_removing_posttrade_completion_guard_is_detected(operation,monkeypatch):
    real=recovery.require
    monkeypatch.setattr(recovery,'require',lambda ok,reason:
        None if reason=='RECOVERY_POST_TRADE_COMPLETION_REQUIRED' else real(ok,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_posttrade_scope_refuses_unsettled_or_foreign_completion_before_intent(operation,monkeypatch,'state')


def test_removing_posttrade_panel_expiry_guard_is_detected(operation,monkeypatch):
    real=recovery.require
    monkeypatch.setattr(recovery,'require',lambda ok,reason:
        None if reason=='INSTALLATION_PANEL_EXPIRED' else real(ok,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_posttrade_recovery_refusals_preserve_receipt_and_old_deadline(operation,monkeypatch,
            'expired_panel','INSTALLATION_PANEL_EXPIRED')
