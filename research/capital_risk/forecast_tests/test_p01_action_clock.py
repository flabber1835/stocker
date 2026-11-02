"""Pure metadata, actual transport and inspection stubs; no local financial runtime."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
import gzip
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from system_campaign_parallel_discovery import compile_body
from system_campaign_parallel_discovery_probe import Fence
import p01_action_clock_contract as contract
import p01_action_clock_export as export
import p01_action_clock_parent as parent
import p01_action_clock_job as job


@dataclass(frozen=True)
class Term:
    session: str = contract.OLD
    security_id: str = contract.SID
    kind: str = 'CASH_MERGER'
    cash_per_share: None = None
    delivered_security_id: None = None
    delivered_ticker: None = None
    delivered_issuer_id: None = None
    exchange_ratio: None = None
    cash_in_lieu_price_per_delivered_share: None = None
    reference: str = 'actions/delisted'
    entitlement_aggregation: str = 'HOLDER'


@dataclass(frozen=True)
class Packet:
    day: str
    terminal: tuple
    bars: object
    meta: object
    sectors: object
    spy: object
    cash: object
    spins: object


def packet(day,terms=()):
    return Packet(day,terms,*[object() for _ in range(6)])


def proposal():
    return contract.proposal(parent.specification())


def receipt():
    return dict(schema='research.p01-action-clock-qualification-receipt/1',arm='P01',stage=export.STAGE,
        authority=contract.AUTHORITY,financial_authority=False,production_contacted=False,
        run_id='123',head='1'*40,request_sha256='2'*64,protocol_sha256='3'*64,
        strict_parent_outer_sha256=proposal().parent_outer,status='PREPARING')


def test_exact_remove_reinsert_preserves_every_unrelated_field_and_missing_term():
    adapter=contract.Clock(proposal());a=packet(contract.OLD,(Term(),Term(security_id='UNRELATED')))
    b=adapter.apply(a)
    assert b.terminal==(a.terminal[1],)
    assert all(getattr(a,n) is getattr(b,n) for n in ('bars','meta','sectors','spy','cash','spins'))
    c=packet(contract.NEW);d=adapter.apply(c)
    assert d.terminal==(replace(a.terminal[0],session=contract.NEW),)
    assert d.terminal[0].cash_per_share is None and d.terminal[0].exchange_ratio is None
    assert adapter.proof()['exact_original_incomplete_term_carried']
    with pytest.raises(ValueError):adapter.apply(packet('2019-10-02'))


@pytest.mark.parametrize('terms', [(),(Term(),Term()),(Term(cash_per_share=0),),
    (Term(reference='different'),),(Term(kind='CONVERSION'),)])
def test_native_preimage_missing_duplicate_or_changed_refuses(terms):
    with pytest.raises(ValueError):contract.Clock(proposal()).apply(packet(contract.OLD,terms))


def test_order_and_duplicate_candidate_refuse_without_skipping():
    adapter=contract.Clock(proposal())
    with pytest.raises(ValueError):adapter.apply(packet(contract.NEW))
    adapter.apply(packet(contract.OLD,(Term(),)))
    with pytest.raises(ValueError):adapter.apply(packet(contract.NEW,(Term(session=contract.NEW),)))
    assert adapter.sessions==[contract.OLD] and adapter.original.cash_per_share is None


def test_actual_preimage_guard_removal_falsifier():
    fn,=[n for n in ast.parse(Path(contract.__file__).read_bytes()).body
         if isinstance(n,ast.FunctionDef) and n.name=='check_native']
    fn.body=[ast.Pass()]
    mutated=compile_body(fn,vars(contract))
    bad=Term(cash_per_share=0)
    with pytest.raises(ValueError):contract.check_native(bad,proposal().native)
    mutated(bad,proposal().native)


@pytest.mark.parametrize('field,value',[('parent_outer','0'*64),('candidate_session','2019-10-02'),
    ('financial_input_admitted',True),('exact_exchange_last_trade_notice_admitted',True)])
def test_typed_proposal_rejects_other_parent_scope_or_admission(field,value):
    raw=proposal().model_dump();raw[field]=value
    with pytest.raises(ValueError):contract.Proposal.model_validate(raw)


def test_actual_encryption_marker_roundtrip(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    request=tmp_path/'request.json';request.write_text(json.dumps({'protocol_sha256':'2'*64}))
    proof=export.qualify_export(tmp_path/'probe',request)
    assert proof['source_adapter_sha256']==job.sha256_file(Path(export.__file__))
    assert proof['synthetic_marker_only'] and not proof['market_or_financial_state_processed']


def test_actual_parent_admission_prefix_uses_real_gcm_and_inventory(tmp_path,monkeypatch):
    """Synthetic marker through the actual adapted old admit function, not a rewritten decryptor."""
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    request=tmp_path/'request.json';request.write_text(json.dumps({'protocol_sha256':'2'*64}))
    source=tmp_path/'source';source.mkdir();(source/'marker.txt').write_bytes(b'SYNTHETIC TRANSPORT MARKER')
    key=b'k'*32;asset=export.sealed(source,tmp_path/'old.tar.crseal',key,request)
    probe=dict(source_adapter_sha256=json.loads((job.HERE/parent.PRIOR).read_bytes())['sources']['system_campaign_p01_accurate_export.py'],
        request_sha256=job.sha256_file(request),status='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED',
        synthetic_marker_only=True,market_or_financial_state_processed=False)
    raw_probe=json.dumps(probe).encode()
    raw_receipt=json.dumps(dict(schema='synthetic/1',run_id='123',head='1'*40,arm='P01',
        encrypted_output=asset,production_contacted=False,protocol_sha256='2'*64,
        request_sha256=job.sha256_file(request),status='ACCURATE_SEGMENT_HOSTED_REVIEW_PASSED_PENDING_CLIENT',
        encrypted_output_exported=True,export_qualification_sha256=parent.sha(raw_probe))).encode()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:
        z.writestr('receipt.json',raw_receipt);z.writestr('full-core-staging.json',b'{}')
        z.writestr('p01-accurate-export-qualification.json',raw_probe)
        z.write(tmp_path/'old.tar.crseal',asset['name'])
    raw_zip=buffer.getvalue()
    spec=dict(artifact_id=123,zip_bytes=len(raw_zip),zip_sha256=parent.sha(raw_zip),receipt_name='receipt.json',
        receipt_sha256=parent.sha(raw_receipt),receipt_schema='synthetic/1',run_id=123,head='1'*40,arm='P01',
        encrypted_output=asset,protocol_sha256='2'*64,request_sha256=job.sha256_file(request),stage=export.STAGE)
    destination=tmp_path/'admission';calls=[]
    monkeypatch.setattr(parent.crypto,'hosted_destination',lambda p:Path(p))
    monkeypatch.setattr(parent.crypto.subprocess,'run',lambda *a,**k:k['stdout'].write(raw_zip))
    def validate(s,inventory,dest):
        assert s==spec and set(inventory)=={'marker.txt'}
        assert (dest/'marker.txt').read_bytes()==b'SYNTHETIC TRANSPORT MARKER';calls.append('validated')
    fn=compile_body(parent.admission_tree(),dict(vars(parent.crypto),validate_parent=validate,
        HERE=parent.HERE,PRIOR=parent.PRIOR,sha=parent.sha))
    assert fn(spec,destination,key,max_zip_bytes=512*1024**2)==destination/'admitted'
    assert calls==['validated']
    # Hash-valid ZIP with an invalid cipher/tag must fail before the parsing callback.
    bad=bytearray(raw_zip)
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as z:
        values={n:z.read(n) for n in z.namelist()}
    cipher=bytearray(values[asset['name']]);cipher[-1]^=1;values[asset['name']]=bytes(cipher)
    changed=io.BytesIO()
    with zipfile.ZipFile(changed,'w') as z:
        for n,raw in values.items():z.writestr(n,raw)
    altered=changed.getvalue();spec2={**spec,'zip_bytes':len(altered),'zip_sha256':parent.sha(altered)}
    monkeypatch.setattr(parent.crypto.subprocess,'run',lambda *a,**k:k['stdout'].write(altered))
    with pytest.raises(Exception):fn(spec2,tmp_path/'tampered',key,max_zip_bytes=512*1024**2)
    assert calls==['validated']


@pytest.mark.parametrize('key,value',[('cash',50000),('daily',[]),('financial_authority',True),('arm','P02')])
def test_public_receipt_rejects_private_or_wrong_scope_fields(tmp_path,key,value):
    r=receipt();r[key]=value
    with pytest.raises(ValueError):export.write_receipt(tmp_path/'r.json',r)
    assert not (tmp_path/'r.json').exists()


def test_unknown_stop_never_encrypts_mutable_snapshot(tmp_path,monkeypatch):
    monkeypatch.setattr(export,'sealed',lambda *a:pytest.fail('UNKNOWN snapshot attempted'))
    r=receipt();export.finish(r,tmp_path,tmp_path/'r.json',None,tmp_path/'request',known=False)
    assert r['encrypted_output_exported'] is False and 'encrypted_output' not in r


def test_known_stop_export_failure_keeps_private_exception_out_of_receipt(tmp_path,monkeypatch):
    def fail(*a):raise RuntimeError('PRIVATE FINANCIAL PAYLOAD')
    monkeypatch.setattr(export,'sealed',fail);r=receipt()
    export.finish(r,tmp_path,tmp_path/'r.json',b'k'*32,tmp_path/'request',known=True)
    assert r['export_error']=={'type':'RuntimeError','code':'EXPORT_OPERATION_FAILED'}
    assert 'PRIVATE' not in (tmp_path/'r.json').read_text()


def inspection(name):
    return dict(Name='/'+name,Image=job.inspector_source.EXECUTION_IMAGE,Id='1'*64,
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Config=dict(Cmd=job.entrypoint(),WorkingDir='/variant',User='1001:1001',Env=[],
            Labels={'research.study':'full-system-search-20261029','research.role':'worker'}),
        Mounts=[dict(Destination=n,Type='bind',RW=n=='/out') for n in ['/variant','/frozen','/driver','/out','/old']])


def test_actual_inspector_enforces_resources_readonly_and_exact_entrypoint(monkeypatch):
    monkeypatch.setattr(job.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.os,'getgid',lambda:1001,raising=False)
    name='capital-system-p01-action-clock-worker-123-1';value=inspection(name)
    monkeypatch.setattr(job.inspector_source.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps([value]).encode()))
    assert job.inspect(name,'1'*64)==value
    for field,bad in [('NetworkMode','bridge'),('MemorySwap',0),('NanoCpus',4000000000)]:
        old=value['HostConfig'][field];value['HostConfig'][field]=bad
        with pytest.raises(ValueError):job.inspect(name,'1'*64)
        value['HostConfig'][field]=old
    value['Mounts'][0]['RW']=True
    with pytest.raises(ValueError):job.inspect(name,'1'*64)
    value['Mounts'][0]['RW']=False;value['Config']['Cmd']=['python','different.py']
    with pytest.raises(ValueError):job.inspect(name,'1'*64)


def test_actual_parent_stop_adapter_accepts_both_old_roles_and_rejects_nonzero(monkeypatch):
    spec=parent.specification()
    for role in ('worker','review'):
        name=f'capital-system-p01-accurate-{role}-{spec["run_id"]}-1';value=inspection(name)
        mode='review' if role=='review' else 'economic'
        value['Config']['Cmd']=['-B','-u','/driver/system_campaign_p01_accurate_run.py','--mode',mode,'--spec','/out/spec.json']
        if role=='review':value['Mounts'].append(dict(Destination='/evidence',Type='bind',RW=False))
        value['Id']=spec['actual_stops']['reviewer' if role=='review' else 'worker']['id']
        value['State']=dict(Running=False,OOMKilled=False,ExitCode=0)
        meta=spec['actual_stops']['reviewer' if role=='review' else 'worker']
        parent.old_stop(value,meta,role,spec)
        value['State']['ExitCode']=1
        with pytest.raises(ValueError):parent.old_stop(value,meta,role,spec)


def test_atomic_phase_note_excludes_exception_values_and_preserves_previous_phase(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path));monkeypatch.setattr(job,'memory_bytes',lambda:{'MemAvailable':10*1024**3})
    path=tmp_path/'phase.json';job.note(path,'BEFORE_PARENT_FETCH')
    try:raise ValueError('PRIVATE ACCOUNT NUMBERS')
    except ValueError as error:job.note(path,'FAILURE',error)
    value=json.loads(path.read_bytes())
    assert value['previous_phase']=='BEFORE_PARENT_FETCH' and value['exception_class']=='ValueError'
    assert value['invariant_code'] is None and value['code_locations']
    assert 'PRIVATE' not in path.read_text() and not path.with_suffix('.partial').exists()
    job.note(path,'FINISHED');final=json.loads(path.read_bytes())
    assert final['last_failure']['exception_class']=='ValueError'
    assert [s['phase'] for s in final['phase_history']]==['BEFORE_PARENT_FETCH','FAILURE','FINISHED']
    with pytest.raises(ValueError):job.note(path,'INVENTED')


def test_metadata_scope_never_claims_financial_admission_and_all402_bytes_unchanged():
    value=job.expected_request()
    assert len(value['sources'])==410 and value['original_inputs']==8 and value['financial_source_files']==515
    assert value['maximum_component_transitions']==2 and value['baseline_required_transitions']==0
    assert value['financial_authority'] is False and value['account_replay_performed'] is False
    assert not value['exact_exchange_last_trade_notice_admitted']
    import p01_action_clock_run as runner
    raw=Path(runner.__file__).read_text()
    assert 'DiscoveryContext(' not in raw and 'backtest.main(' not in raw and 'advance_account(' not in raw
    assert 'runtime.advance(run, baseline)' in raw and 'runtime.advance(run, published)' in raw


def test_qualification_wrapper_is_rejected_by_actual_strict_guard():
    import p01_action_clock_run as runner
    value=runner.wrapper({'state':{}},parent={'sha256':'1'*64},transitions=1)
    assert value['financial_predecessor_authorized'] is False
    from system_campaign_discovery_context import require_strict_checkpoint
    with pytest.raises(ValueError):require_strict_checkpoint(value)
