"""Registered clock schema, identity/role falsifiers and actual transport; no local finance."""
import ast
from copy import deepcopy
from dataclasses import dataclass, replace
import json
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from system_campaign_parallel_discovery_probe import Fence
from system_campaign_parallel_discovery import compile_body
import p01_clock_input_codec as codec
import p01_clock_input_job as job
import p01_clock_input_export as export


@dataclass(frozen=True)
class Term:
    session: str='2019-09-30'
    security_id: str='718647188059134933'
    kind: str='CASH_MERGER'
    cash_per_share: None=None
    delivered_security_id: None=None
    delivered_ticker: None=None
    delivered_issuer_id: None=None
    exchange_ratio: None=None
    cash_in_lieu_price_per_delivered_share: None=None
    reference: str='actions/delisted'
    entitlement_aggregation: str='HOLDER'


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


def loaded(tmp_path):
    p=tmp_path/'clock.json';p.write_bytes((json.dumps(codec.document(),sort_keys=True,indent=2)+'\n').encode())
    return p,codec.parse(p,resume_session='2019-09-27',predecessor_checkpoint_sha256=codec.INNER)


def registered(tmp_path):
    path,obj=loaded(tmp_path);context=codec.InputCodec(Term());context.objects.append(obj)
    return context,obj


def state(*,held=False,pending=False,selected=False,hash_value=None):
    return SimpleNamespace(wealth_core={'episodes':{'0':{'security_id':codec.SID}} if held else {}},
        pending=[{'security_id':codec.SID}] if pending else [],
        median5={'selected':[codec.SID] if selected else []},state_hash=hash_value or codec.NEXT_STATES[codec.OLD])


def test_distinct_schema_roundtrips_original_inner_binding_and_missing_native_terms(tmp_path):
    p,obj=loaded(tmp_path)
    assert obj.model_dump(by_alias=True)==codec.document() and obj.sha256==codec.sha(p.read_bytes())
    assert obj.earliest_affected_session=='2019-09-30' and obj.native.cash_per_share is None
    assert obj.schema_id!='terminal-repair/1'


@pytest.mark.parametrize('cursor,parent',[('2019-09-30',codec.INNER),('2019-08-30',codec.INNER),
    ('2019-09-27','0'*64)])
def test_wrong_or_consumed_predecessor_refuses(tmp_path,cursor,parent):
    p,_=loaded(tmp_path)
    with pytest.raises(ValueError):codec.parse(p,resume_session=cursor,predecessor_checkpoint_sha256=parent)


@pytest.mark.parametrize('field,value',[('economic_session','2019-10-02'),('predecessor_outer_sha256','0'*64),
    ('require_no_oct1_leadership',False),('require_exact_qualified_state_hashes',1),
    ('require_unheld_unordered_both_days',1)])
def test_typed_scope_rejects_other_dates_parents_false_or_integer_booleans(field,value):
    raw=codec.document();raw[field]=value
    with pytest.raises(ValueError):codec.ClockInput.model_validate(raw)


def test_source_only_transform_preserves_missing_terms_and_all_other_packet_objects(tmp_path):
    ctx,obj=registered(tmp_path);other=Term(security_id='OTHER')
    source=packet(codec.OLD,(Term(),other));changed=ctx.apply(source,obj)
    assert changed.terminal==(other,)
    for field in ('bars','meta','sectors','spy','cash','spins'):
        assert getattr(changed,field) is getattr(source,field)
    following=ctx.apply(packet(codec.NEW),obj)
    assert following.terminal==(replace(Term(),session=codec.NEW),)
    assert following.terminal[0].cash_per_share is None
    with pytest.raises(ValueError):ctx.apply(source,deepcopy(obj))


def test_exact_source_preimage_and_duplicate_effective_day_falsifiers(tmp_path):
    ctx,obj=registered(tmp_path)
    for terms in ((),(Term(),Term()),(Term(cash_per_share=0.0),)):
        with pytest.raises(ValueError):ctx.apply(packet(codec.OLD,terms),obj)
    with pytest.raises(ValueError):ctx.apply(packet(codec.NEW,(replace(Term(),session=codec.NEW),)),obj)


@pytest.mark.parametrize('key',['held','pending','selected'])
def test_oct1_material_roles_refuse(key):
    with pytest.raises(ValueError):codec.require_roles(state(**{key:True}),codec.NEW)
    codec.require_roles(state(selected=True),codec.OLD)


def test_runtime_guard_checks_before_and_after_prior_to_returning_to_accounting():
    guard=codec.RoleGuard();calls=[]
    guard.original=lambda run,published:calls.append(published.session) or SimpleNamespace(
        state=state(hash_value=codec.NEXT_STATES[published.session]))
    with pytest.raises(ValueError):guard.advance(SimpleNamespace(state=state(held=True)),SimpleNamespace(session=codec.OLD))
    assert not calls
    result=guard.advance(SimpleNamespace(state=state(selected=True)),SimpleNamespace(session=codec.OLD))
    assert result.state.state_hash==codec.NEXT_STATES[codec.OLD] and len(guard.observed)==1
    guard.original=lambda *a:SimpleNamespace(state=state(hash_value='0'*64))
    with pytest.raises(ValueError,match='FULL_CANONICAL_STATE'):guard.advance(
        SimpleNamespace(state=state()),SimpleNamespace(session=codec.NEW))


def test_actual_full_state_gate_removal_falsifier():
    tree=ast.parse(Path(codec.__file__).read_bytes());cls,=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='RoleGuard']
    fn,=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='advance']
    for node in ast.walk(fn):
        if isinstance(node,ast.If):node.body=[n for n in node.body if not (
            isinstance(n,ast.Expr) and any(isinstance(v,ast.Constant) and v.value==
                'P01_CLOCK_INPUT_FULL_CANONICAL_STATE_MATCHES_QUALIFICATION' for v in ast.walk(n)))]
    changed=compile_body(fn,vars(codec));guard=codec.RoleGuard()
    guard.original=lambda *a:SimpleNamespace(state=state(hash_value='0'*64))
    run=SimpleNamespace(state=state());publication=SimpleNamespace(session=codec.NEW)
    with pytest.raises(ValueError):guard.advance(run,publication)
    assert changed(guard,run,publication).state.state_hash=='0'*64


def test_actual_marker_encrypt_authenticate_decrypt_roundtrip(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    request=tmp_path/'request.json';request.write_text(json.dumps({'protocol_sha256':'2'*64}))
    proof=export.qualify_export(tmp_path/'marker',request)
    assert proof['source_adapter_sha256']==job.sha256_file(Path(export.__file__))
    assert proof['synthetic_marker_only'] and not proof['market_or_financial_state_processed']


def receipt():
    return dict(schema='research.p01-economic-clock-financial-receipt/1',arm='P01',stage=export.STAGE,
        run_id='123',head='1'*40,request_sha256='2'*64,protocol_sha256='3'*64,
        strict_parent_outer_sha256=codec.PARENT,status='NOT_STARTED',production_contacted=False)


def test_financial_unknown_keeps_already_stopped_qualification_without_new_snapshot(tmp_path,monkeypatch):
    r=receipt();r['qualification_exported']=True;r['qualification_encrypted_output']=dict(
        name='qualification.crseal',bytes=10,sha256='1'*64,manifest_sha256='2'*64,compression='TAR_GZIP_V1')
    monkeypatch.setattr(export,'sealed',lambda *a,**k:pytest.fail('UNKNOWN mutable snapshot attempted'))
    export.finish(r,tmp_path,tmp_path/'receipt.json',b'k'*32,tmp_path/'request',known=False)
    assert r['qualification_exported'] and r['encrypted_output_exported'] is False
    assert r['qualification_encrypted_output']['name']=='qualification.crseal'


def test_public_financial_receipt_rejects_payload_and_wrong_scope(tmp_path):
    for key,value in [('cash',50000),('arm','P02'),('production_contacted',True)]:
        r=receipt();r[key]=value
        with pytest.raises(ValueError):export.write_receipt(tmp_path/'receipt.json',r)


@pytest.mark.parametrize('mode',['qualify','economic','review'])
def test_actual_inspector_accepts_only_exact_mode_entrypoint_and_fences(monkeypatch,mode):
    monkeypatch.setattr(job.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.os,'getgid',lambda:1001,raising=False)
    role='review' if mode=='review' else 'qualify' if mode=='qualify' else 'worker'
    name=f'capital-system-p01-clock-input-{role}-123-1'
    value=dict(Name='/'+name,Image=job.inspector_source.EXECUTION_IMAGE,Id='1'*64,
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Config=dict(Cmd=job.entrypoint(mode),WorkingDir='/variant',User='1001:1001',Env=[],
            Labels={'research.study':'full-system-search-20261029','research.role':'review' if mode=='review' else 'worker'}),
        Mounts=[dict(Destination=n,Type='bind',RW=n=='/out') for n in
            ['/variant','/frozen','/driver','/out','/old']+(['/evidence'] if mode=='review' else [])])
    monkeypatch.setattr(job.inspector_source.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps([value]).encode()))
    assert job.inspect(name,'1'*64)==value
    value['HostConfig']['MemorySwap']=0
    with pytest.raises(ValueError):job.inspect(name,'1'*64)
    value['HostConfig']['MemorySwap']=8*1024**3;value['Config']['Cmd']=job.entrypoint('review' if mode!='review' else 'economic')
    with pytest.raises(ValueError):job.inspect(name,'1'*64)


def test_metadata_scope_original438_new9_and_precelg37_no_qualifier_adoption():
    request=job.expected_request()
    assert len(request['sources'])==418 and request['original_inputs']==8 and request['new_typed_clock_inputs']==1
    assert request['processing_endpoint']=='2019-11-19' and request['maximum_financial_transitions']==37
    assert request['source515_unchanged'] and not request['qualification_state_adoption']
    assert request['retain_stopped_qualification_before_financial_launch']


def test_actual_separate_qualification_export_gcm_roundtrip_and_financial_book_refusal(tmp_path,monkeypatch):
    from seal import decrypt
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    root=tmp_path/'known-stopped-proof';root.mkdir();(root/'qualification').mkdir()
    for n in ('spec.json','request.json','source-bindings.json'):(root/n).write_text('{}')
    names=('clock-input.json','zero-session-startup-proof.json','prefix-and-tail-proof.json',
        'actual-codec-component-path.json.gz','qualification-input-checkpoint.json',
        'qualification-summary.json','worker-inspect.json','worker.log')
    for n in names:(root/'qualification'/n).write_text('SYNTHETIC_MARKER_ONLY')
    (root/'qualification/qualification-input-checkpoint.json').write_text(json.dumps(dict(
        financial_authority=False,financial_predecessor_authorized=False)))
    request=tmp_path/'source-request.json';request.write_text(json.dumps({'protocol_sha256':'2'*64}))
    r=receipt();r['qualification_worker']=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None)
    export.preserve_qualification(r,root,tmp_path/'public.json',b'k'*32,request)
    asset=r['qualification_encrypted_output'];plain=tmp_path/'qualified.tar.gz'
    decrypt(tmp_path/asset['name'],plain,b'k'*32,asset['sha256'])
    with tarfile.open(plain,'r:gz') as archive:
        manifest=json.load(archive.extractfile('manifest.json'))
        assert manifest['stage']==export.QUALIFICATION_STAGE and manifest['arm']=='P01'
        assert len(manifest['members'])==11
    (root/'book').mkdir();(root/'book/daily.jsonl').write_text('SYNTHETIC_FINANCIAL_ROW')
    with pytest.raises(ValueError,match='NO_DISPOSABLE_FINANCIAL_BOOK'):
        export.preserve_qualification(r,root,tmp_path/'public.json',b'k'*32,request)
    fn,=[n for n in ast.parse(Path(export.__file__).read_bytes()).body
         if isinstance(n,ast.FunctionDef) and n.name=='preserve_qualification']
    fn.body=[n for n in fn.body if not (isinstance(n,ast.Expr) and any(isinstance(v,ast.Constant)
        and v.value=='P01_CLOCK_INPUT_ONLY_QUALIFICATION_PROOFS_NO_DISPOSABLE_FINANCIAL_BOOK_EXPORT' for v in ast.walk(n)))]
    mutated=compile_body(fn,dict(vars(export),sealed=lambda *a,**k:asset))
    mutated(r,root,tmp_path/'mutated-public.json',b'k'*32,request)
    assert json.loads((tmp_path/'mutated-public.json').read_bytes())['qualification_exported']


def test_actual_zero_session_adoption_validator_accepts_only_input_identity_change():
    from system_campaign_pxd_pause import adoption
    overlay='d'*64
    original=dict(base={'inert':True},source_cursor='2019-09-27',completed=438,
        economics={'inert_cash':'123'},stats={'rows':3},spy_base='1',retries={'count':0},
        repairs=[{'sha256':str(i)*64} for i in range(1,9)],chain='a'*64,
        journals={n:dict(bytes=0,prefix_sha256=codec.sha(b'')) for n in ('daily','formation','watch','monthly')},
        run=dict(state={'inert_controller':'UNCHANGED'},state_sha256='b'*64,input_sha256=codec.INPUT,
            checkpoint_sha256=codec.INNER))
    after=deepcopy(original)
    desc=dict(filename=overlay+'.json',sha256=overlay,resume_session='2019-09-27',
        predecessor_checkpoint_sha256=codec.INNER)
    after['repairs'].append(desc);after['run']['input_sha256']=codec.digest(dict(base=after['base'],repairs=after['repairs']))
    event=dict(schema='research.pooled-action-successor/1',predecessor_checkpoint_sha256=codec.INNER,
        unchanged_through='2019-09-27',earliest_affected_session=codec.OLD,state_sha256='b'*64,
        overlay=desc,predecessor_input_sha256=codec.INPUT,successor_input_sha256=after['run']['input_sha256'])
    after['chain']=codec.digest(dict(previous=original['chain'],event=event))
    after['journals']['watch']['bytes']=1
    def hashes(value):
        value['run']['checkpoint_sha256']=codec.digest({k:v for k,v in value['run'].items() if k!='checkpoint_sha256'})
        value['sha256']=codec.digest({k:v for k,v in value.items() if k!='sha256'})
    hashes(after)
    assert adoption(after,original,overlay,codec.OLD)==event
    for kind in ('economics','controller','daily'):
        bad=deepcopy(after)
        if kind=='economics':bad['economics']['inert_cash']='124'
        elif kind=='controller':bad['run']['state']['inert_controller']='CHANGED'
        else:bad['journals']['daily']['bytes']=1
        hashes(bad)
        with pytest.raises(ValueError):adoption(bad,original,overlay,codec.OLD)


def test_own_phase_metadata_distinguishes_financial_roles_and_keeps_error_values_private(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path))
    monkeypatch.setattr(job.previous,'memory_bytes',lambda:{'MemAvailable':10*1024**3})
    p=tmp_path/'phase.json';job.note(p,'QUALIFIER_STOPPED');job.note(p,'FINANCIAL_LAUNCH_ATTEMPTED')
    try:raise ValueError('PRIVATE_SOURCE_VALUE')
    except ValueError as error:job.note(p,'FAILURE',error)
    job.note(p,'FINISHED');value=json.loads(p.read_bytes())
    assert value['authority']=='NONFINANCIAL_HOST_PHASE_METADATA'
    assert value['schema']=='research.p01-clock-input-public-phase/1'
    assert value['last_failure']['exception_class']=='ValueError' and 'PRIVATE' not in p.read_text()
