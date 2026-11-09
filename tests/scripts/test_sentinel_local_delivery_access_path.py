"""Explicit post-schema canonical qualification uses real durable coordinator stages."""
from copy import deepcopy
from datetime import timedelta

import pytest

from tests.scripts import test_sentinel_local_delivery_coordinator as fixture

model=fixture.model
coordinator=fixture.coordinator
operation=fixture.operation


@pytest.fixture
def access_operation(operation,monkeypatch):
    host,old_journal,_=operation
    host.request.update(schema=model.ACCESS_PATH_SCHEMA,
        canonical_proof_phase=model.POST_SCHEMA_ACCESS_PATH)
    model.atomic_json(old_journal.folder/'request.json',host.request)
    journal=model.Journal(old_journal.folder)
    host.state['system']=host.request['predecessor']['system']
    host.supports_post_schema_access_path=True
    host.retained={'book':'same','proof':'same'}
    host.proof_result=deepcopy(host.retained)
    host.access_installed=False
    host.access_calls=[]
    host.installation_sha256='e'*64
    host.predecessor_canonical_proof=lambda state:deepcopy(host.retained)

    def bootstrap(state,retained):
        host.access_calls.append(('bootstrap',journal.read()['stage']))
        model.require(not host.access_installed,'ACCESS_ALREADY_INSTALLED')
        return dict(schema='sentinel.checkpoint-access-bootstrap/1',authority_effect='NONE',
            request_sha256=journal.subject,operation_id=host.request['operation_id'],
            predecessor={key:host.request['predecessor'][key] for key in ('commit','image')},
            candidate={key:host.request['candidate'][key] for key in ('commit','image','source_identity')},
            state_sha256=model.digest(state),predecessor_proof_sha256=model.digest(retained),
            system_identifier=state['system'],operational_installation_sha256='c'*64,
            access_contract_sha256='d'*64)

    def installed(state,contract):
        host.access_calls.append(('installed',journal.read()['stage']))
        model.require(host.access_installed,'ACCESS_NOT_INSTALLED')
        return dict(schema='sentinel.checkpoint-access-installed/1',authority_effect='NONE',
            **{key:contract[key] for key in ('request_sha256','state_sha256','system_identifier',
                'operational_installation_sha256','access_contract_sha256')},
            access_installation_sha256=host.installation_sha256)

    host.access_path_canonical_bootstrap=bootstrap
    host.verify_access_path_canonical_installation=installed
    migrate=coordinator.evidence.migrate_operational_schema
    def migration(h,*args):
        assert not any(item['State']['Running'] for item in h.items.values())
        result=migrate(h,*args)
        if result['complete']:h.access_installed=True
        return result
    monkeypatch.setattr(coordinator.evidence,'migrate_operational_schema',migration)

    def canonical(h,values,state):
        h.canonical_count+=1
        h.access_calls.append(('canonical',journal.read()['stage']))
        assert h.access_installed
        assert not any(item['State']['Running'] for item in h.items.values())
        assert values==h.candidate_values(h.load_values())
        assert state==h.state
        return deepcopy(h.proof_result)
    monkeypatch.setattr(coordinator.evidence,'canonical_check',canonical)
    delivery=coordinator.Delivery(host,journal,monotonic=lambda:host.clock,sleep=host.sleep)
    return host,journal,delivery


def advance_to(operation,stage):
    host,journal,delivery=operation
    for _ in range(len(model.STAGES)):
        if journal.read()['stage']==stage:return
        before=journal.read()['stage']
        delivery.step()
        assert journal.read()['stage']!=before
    raise AssertionError('bounded fixture did not reach '+stage)


def rewrite_artifacts(journal,change):
    """Keep journal hashes valid to exercise semantic admission, not file corruption."""
    record=journal.read()
    change(record['artifacts'])
    event=record['history'][-1]
    event['artifacts_sha256']=model.digest(record['artifacts'])
    event['sha256']=model.digest({key:value for key,value in event.items() if key!='sha256'})
    model.atomic_json(journal.folder/'receipt.json',record)
    assert journal.read()==record


def test_preflight_records_only_retained_predecessor_and_noneffect_contract(access_operation):
    host,journal,delivery=access_operation
    receipt=delivery.step()
    assert receipt['stage']=='PREFLIGHT_PASS'
    artifacts=receipt['artifacts']
    assert artifacts['predecessor_canonical_proof']==host.retained
    assert artifacts['access_path_canonical_contract']['authority_effect']=='NONE'
    assert 'canonical_proof' not in artifacts
    assert 'access_path_canonical_qualification' not in artifacts
    assert host.canonical_count==host.migration_count==0
    assert all(item['State']['Running'] for item in host.items.values())
    assert host.access_calls==[('bootstrap','NEW')]


def test_candidate_complete_proof_occurs_after_migration_before_any_compose_or_start(access_operation):
    host,journal,delivery=access_operation
    advance_to(access_operation,'SCHEMA_INSTALLED')
    original=deepcopy(journal.read()['artifacts'])
    assert host.canonical_count==0 and host.migration_count==1
    assert not any(item['State']['Running'] for item in host.items.values())
    receipt=delivery.step()
    assert receipt['stage']=='COMPOSE_INSTALL_REQUESTED'
    assert host.canonical_count==1 and 'install-compose' not in host.calls
    assert receipt['artifacts']['canonical_proof']==host.retained
    completion=receipt['artifacts']['access_path_canonical_qualification']
    assert completion['authority_effect']=='NONE'
    assert completion['contract_sha256']==model.digest(original['access_path_canonical_contract'])
    assert completion['canonical_proof_sha256']==model.digest(host.retained)
    assert all(receipt['artifacts'][key]==value for key,value in original.items())
    assert host.access_calls[-3:]==[('installed','SCHEMA_INSTALLED'),
        ('canonical','SCHEMA_INSTALLED'),('installed','SCHEMA_INSTALLED')]
    assert delivery.advance()['stage']=='VERIFIED'
    assert host.canonical_count==1
    assert journal.read()['artifacts']['preflight_at']==original['preflight_at']


def test_ordinary_path_retains_pre_drain_candidate_check_even_if_host_has_capability(operation):
    host,journal,delivery=operation
    host.supports_post_schema_access_path=True
    receipt=delivery.step()
    assert receipt['stage']=='PREFLIGHT_PASS' and host.canonical_count==2
    assert 'canonical_proof' in receipt['artifacts']
    assert 'access_path_canonical_contract' not in receipt['artifacts']
    assert host.migration_count==0


@pytest.mark.parametrize('retained',[None,{},False])
def test_missing_retained_proof_refuses_without_any_candidate_or_migration_fallback(access_operation,retained):
    host,journal,delivery=access_operation
    host.predecessor_canonical_proof=lambda state:retained
    with pytest.raises(model.DeliveryRefused,match='RETAINED_PREDECESSOR_PROOF_REQUIRED'):
        delivery.step()
    assert journal.read()['stage']=='NEW' and not journal.read()['history']
    assert host.canonical_count==host.migration_count==0
    assert not host.access_calls and not any(isinstance(call,tuple) for call in host.calls)


def test_plain_adapter_cannot_select_bootstrap(access_operation):
    host,journal,delivery=access_operation
    host.supports_post_schema_access_path=False
    before=list(host.calls)
    with pytest.raises(model.DeliveryRefused,match='BOOTSTRAP_UNSUPPORTED'):delivery.step()
    assert host.calls==before and not journal.read()['history']


@pytest.mark.parametrize('field',[
    'schema','authority_effect','request_sha256','operation_id','predecessor','candidate',
    'state_sha256','predecessor_proof_sha256','system_identifier',
    'operational_installation_sha256','access_contract_sha256','extra','missing'])
def test_bootstrap_contract_is_closed_and_bound_before_drain(access_operation,field):
    host,journal,delivery=access_operation
    original=host.access_path_canonical_bootstrap
    def changed(*args):
        value=original(*args)
        if field=='missing':value.pop('schema')
        else:value[field]='foreign'
        return value
    host.access_path_canonical_bootstrap=changed
    with pytest.raises(model.DeliveryRefused,match='ACCESS_PATH_CANONICAL_CONTRACT'):
        delivery.step()
    assert journal.read()['stage']=='NEW' and host.canonical_count==0


def test_pending_schema_pages_do_not_run_or_fabricate_candidate_proof(access_operation):
    host,journal,delivery=access_operation
    host.schema_complete=False
    with pytest.raises(model.DeliveryRefused,match='OPERATIONAL_BOOTSTRAP_PAGE_LIMIT'):
        delivery.advance()
    first=journal.read()
    assert first['stage']=='SCHEMA_INSTALL_REQUESTED' and host.migration_count==10
    stamp=first['artifacts']['preflight_at']
    assert host.canonical_count==0 and 'canonical_proof' not in first['artifacts']
    assert not any(item['State']['Running'] for item in host.items.values())
    host.schema_complete=True
    assert delivery.advance()['stage']=='VERIFIED'
    assert host.canonical_count==1 and journal.read()['artifacts']['preflight_at']==stamp


def assert_mismatched_candidate_refused(access_operation):
    host,journal,delivery=access_operation
    advance_to(access_operation,'SCHEMA_INSTALLED')
    host.proof_result['book']='different actual candidate result'
    with pytest.raises(model.DeliveryRefused,match='CANONICAL_ECONOMIC_PROOF_CHANGED'):
        delivery.step()
    assert journal.read()['stage']=='SCHEMA_INSTALLED'
    assert 'canonical_proof' not in journal.read()['artifacts']
    assert not any(item['State']['Running'] for item in host.items.values())
    assert 'install-compose' not in host.calls


def test_full_post_schema_canonical_comparison_is_mandatory(access_operation):
    assert_mismatched_candidate_refused(access_operation)


def test_removed_canonical_comparison_has_executed_falsifier(access_operation,monkeypatch):
    original=coordinator.require
    monkeypatch.setattr(coordinator,'require',lambda value,reason:
        None if reason=='CANONICAL_ECONOMIC_PROOF_CHANGED' else original(value,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        assert_mismatched_candidate_refused(access_operation)


@pytest.mark.parametrize('field',[
    'schema','authority_effect','request_sha256','state_sha256','system_identifier',
    'operational_installation_sha256','access_contract_sha256','access_installation_sha256','extra'])
def test_installed_metadata_must_authenticate_same_original_marker_and_component(access_operation,field):
    host,journal,delivery=access_operation
    advance_to(access_operation,'SCHEMA_INSTALLED')
    installed=host.verify_access_path_canonical_installation
    def changed(*args):
        value=installed(*args);value[field]='foreign';return value
    host.verify_access_path_canonical_installation=changed
    with pytest.raises(model.DeliveryRefused,match='INSTALLATION_CHANGED'):delivery.step()
    assert host.canonical_count==0 and journal.read()['stage']=='SCHEMA_INSTALLED'
    assert 'install-compose' not in host.calls


@pytest.mark.parametrize('fault',['state','native','postgres','configuration','history','application',
                                 'installation','clock'])
def test_changes_during_full_candidate_proof_prevent_completion(access_operation,monkeypatch,fault):
    host,journal,delivery=access_operation
    advance_to(access_operation,'SCHEMA_INSTALLED')
    canonical=coordinator.evidence.canonical_check
    def changing(*args):
        proof=canonical(*args)
        if fault=='state':host.state['commands']='changed'
        elif fault=='native':host.native['native-id']='18'
        elif fault=='postgres':host.postgres=lambda:{'changed':True}
        elif fault=='configuration':host.values['SECRET']='changed'
        elif fault=='history':host.notifications['old']='changed'
        elif fault=='application':host.items['sentinel-shadow']['State']['Running']=True
        elif fault=='installation':host.installation_sha256='f'*64
        else:monkeypatch.setattr(coordinator,'utcnow',lambda:model.utcnow()+timedelta(minutes=16))
        return proof
    monkeypatch.setattr(coordinator.evidence,'canonical_check',changing)
    with pytest.raises(model.DeliveryRefused):delivery.step()
    assert journal.read()['stage']=='SCHEMA_INSTALLED'
    assert 'access_path_canonical_qualification' not in journal.read()['artifacts']
    assert 'install-compose' not in host.calls


def test_expired_original_preflight_refuses_before_post_schema_probe(access_operation,monkeypatch):
    host,journal,delivery=access_operation
    advance_to(access_operation,'SCHEMA_INSTALLED')
    monkeypatch.setattr(coordinator,'utcnow',lambda:model.utcnow()+timedelta(minutes=16))
    before=list(host.access_calls)
    with pytest.raises(model.DeliveryRefused,match='INTERVAL_EXPIRED'):delivery.step()
    assert host.access_calls==before and host.canonical_count==0


def test_post_schema_source_change_refuses_before_canonical_probe(access_operation):
    host,journal,delivery=access_operation
    advance_to(access_operation,'SCHEMA_INSTALLED')
    def changed():raise model.DeliveryRefused('QUALIFIED_SOURCE_BYTES_CHANGED')
    host.verify_candidate=changed
    before=list(host.access_calls)
    with pytest.raises(model.DeliveryRefused,match='QUALIFIED_SOURCE_BYTES_CHANGED'):delivery.step()
    assert host.access_calls==before and host.canonical_count==0


def assert_missing_completion_refused(access_operation,stage):
    host,journal,delivery=access_operation
    advance_to(access_operation,stage)
    rewrite_artifacts(journal,lambda artifacts:artifacts.pop('access_path_canonical_qualification'))
    before=list(host.calls)
    with pytest.raises(model.DeliveryRefused,match='QUALIFICATION_REQUIRED'):delivery.step()
    assert host.calls==before and journal.read()['stage']==stage


@pytest.mark.parametrize('stage',sorted(coordinator.ACCESS_PATH_QUALIFIED_STAGES))
def test_every_compose_start_resume_and_final_route_requires_completion(access_operation,stage):
    assert_missing_completion_refused(access_operation,stage)


def test_removed_completion_gate_has_executed_falsifier(access_operation,monkeypatch):
    host,journal,delivery=access_operation
    advance_to(access_operation,'COMPOSE_INSTALL_REQUESTED')
    monkeypatch.setattr(delivery,'_require_access_path_qualification',lambda artifacts:None)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        assert_missing_completion_refused(access_operation,'COMPOSE_INSTALL_REQUESTED')


@pytest.mark.parametrize('field',[
    'schema','authority_effect','request_sha256','state_sha256','contract_sha256',
    'installation','canonical_proof_sha256','qualified_at','extra'])
def test_self_consistent_journal_cannot_use_malformed_or_foreign_completion(access_operation,field):
    host,journal,delivery=access_operation
    advance_to(access_operation,'COMPOSE_INSTALL_REQUESTED')
    def change(artifacts):artifacts['access_path_canonical_qualification'][field]='foreign'
    rewrite_artifacts(journal,change)
    before=list(host.calls)
    with pytest.raises(model.DeliveryRefused,match='ACCESS_PATH_CANONICAL_'):delivery.step()
    assert host.calls==before


@pytest.mark.parametrize('field',['canonical_proof','predecessor_canonical_proof','contract'])
def test_completion_is_bound_to_actual_equal_proofs_and_original_contract(access_operation,field):
    host,journal,delivery=access_operation
    advance_to(access_operation,'COMPOSE_INSTALL_REQUESTED')
    def change(artifacts):
        if field=='contract':artifacts['access_path_canonical_contract']['access_contract_sha256']='f'*64
        else:artifacts[field]['book']='forged'
    rewrite_artifacts(journal,change)
    before=list(host.calls)
    with pytest.raises(model.DeliveryRefused,match='ACCESS_PATH_CANONICAL_'):delivery.step()
    assert host.calls==before


def test_lost_completion_ack_reexecutes_whole_proof_without_renewing_original_clock(access_operation,monkeypatch):
    host,journal,delivery=access_operation
    advance_to(access_operation,'SCHEMA_INSTALLED')
    stamp=journal.read()['artifacts']['preflight_at']
    advance=journal.advance
    def lost(expected,stage,**artifacts):
        assert expected=='SCHEMA_INSTALLED' and stage=='COMPOSE_INSTALL_REQUESTED'
        assert artifacts['canonical_proof']==host.retained
        raise model.DeliveryRefused('LOST_COMPLETION_ACK')
    monkeypatch.setattr(journal,'advance',lost)
    with pytest.raises(model.DeliveryRefused,match='LOST_COMPLETION_ACK'):delivery.step()
    assert host.canonical_count==1 and journal.read()['stage']=='SCHEMA_INSTALLED'
    assert 'canonical_proof' not in journal.read()['artifacts']
    monkeypatch.setattr(journal,'advance',advance)
    assert delivery.step()['stage']=='COMPOSE_INSTALL_REQUESTED'
    assert host.canonical_count==2 and journal.read()['artifacts']['preflight_at']==stamp


def test_sql_and_whole_canonical_deadlines_remain_original():
    code=fixture.coordinator.evidence.checks.CANONICAL
    assert 'statement_timeout=15000 -c lock_timeout=1000' in code
    assert 'outer_deadline=started+300' in code
    assert 'canonical proof exceeded its original deadline' in code


def test_shared_pure_validators_accept_complete_evidence_without_changing_it(access_operation):
    host,journal,delivery=access_operation
    advance_to(access_operation,'COMPOSE_INSTALL_REQUESTED')
    artifacts=journal.read()['artifacts']
    before=deepcopy((host.request,artifacts))
    predicates=coordinator.access_path_qualification
    contract=predicates.require_contract(host.request,journal.subject,artifacts)
    completion=predicates.require_qualification(host.request,journal.subject,artifacts)
    assert contract is artifacts['access_path_canonical_contract']
    assert completion is artifacts['access_path_canonical_qualification']
    assert predicates.require_installation(contract,completion['installation']) is completion['installation']
    assert (host.request,artifacts)==before


@pytest.mark.parametrize('fault',['schema','phase','handoff','subject','rebound_request'])
def test_shared_receipt_predicate_requires_explicit_request_and_its_exact_subject(access_operation,fault):
    host,journal,delivery=access_operation
    advance_to(access_operation,'COMPOSE_INSTALL_REQUESTED')
    request=deepcopy(host.request)
    artifacts=journal.read()['artifacts']
    subject=journal.subject
    if fault=='schema':request['schema']=model.SCHEMA
    elif fault=='phase':request['canonical_proof_phase']='PRE_DRAIN'
    elif fault=='handoff':request['handoff_mode']='POST_TRADE'
    elif fault=='subject':subject='f'*64
    else:
        request['operation_id']='another-valid-operation'
        subject=model.digest(request)
    with pytest.raises(model.DeliveryRefused):
        coordinator.access_path_qualification.require_qualification(request,subject,artifacts)


def test_shared_receipt_predicate_does_not_turn_audit_time_into_a_new_handoff_clock(access_operation):
    host,journal,delivery=access_operation
    advance_to(access_operation,'COMPOSE_INSTALL_REQUESTED')
    artifacts=journal.read()['artifacts']
    artifacts['access_path_canonical_qualification']['qualified_at']='2000-01-01T00:00:00+00:00'
    original=artifacts['preflight_at']
    coordinator.access_path_qualification.require_qualification(host.request,journal.subject,artifacts)
    assert artifacts['preflight_at']==original
