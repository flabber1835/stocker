"""Pure byte/schema/math and stub guards only; no local canonical finance."""
import ast
from copy import deepcopy
from dataclasses import asdict,dataclass,replace,make_dataclass
from fractions import Fraction
import json
from pathlib import Path
import signal
import sys
import tarfile
from types import SimpleNamespace
from types import ModuleType

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import p01_celg_bridge_payload as payload
import p01_celg_bridge_gate as gate
import p01_celg_bridge_codec as codec
import p01_celg_bridge_accounting as accounting
import p01_celg_bridge_source as source
import p01_celg_bridge_job as job
import p01_celg_bridge_export as export
from p01_celg_bridge_pause import SourcePause
import test_p01_celg_component as stub


def fake_quote():
    """Different synthetic prices, never a fixture presented as actual input."""
    return dict(identity=payload.identity(),session=payload.SESSION,source_timestamp='2019-11-21T05:00:00Z',
        authority=payload.QUOTE_AUTHORITY,raw_open='3.75',raw_close='4.05',adjustment='raw',feed='sip',
        observed_market_data=True,gzip_sha256=payload.QUOTE_GZIP_SHA,raw_sha256=payload.QUOTE_RAW_SHA,
        capture_sha256=payload.CAPTURE_SHA,manifest_sha256='a'*64,ciphertext_sha256='b'*64,
        input_identity_sha256='c'*64)


@pytest.fixture
def market(monkeypatch):
    monkeypatch.setattr(payload,'hosted',lambda:None);monkeypatch.setattr(payload,'_MARKET_QUOTE',None)
    q=fake_quote();payload.bind_market_quote(q,expected_sha256=payload.digest(q))
    monkeypatch.setattr(stub,'c',payload)
    return q


def test_financial_payload_has_no_market_price_literals_or_synthetic_fallback(monkeypatch):
    raw=Path(payload.__file__).read_bytes()
    assert b'2.30' not in raw and b'2.25' not in raw
    monkeypatch.setattr(payload,'_MARKET_QUOTE',None)
    with pytest.raises(ValueError,match='ACTUAL_MARKET_INPUT_REQUIRED'):payload.quote()
    with pytest.raises(ValueError,match='HOSTED_VERSIONED'):payload.hosted()


def test_registered_context_is_once_only_immutable_and_source_bound(market):
    q=deepcopy(market);q['raw_open']='99'
    assert payload.quote()==market
    with pytest.raises(ValueError,match='ONE_EXACT'):payload.bind_market_quote(q,expected_sha256=payload.digest(q))


@pytest.mark.parametrize('key,value',[('observed_market_data',False),('authority','SYNTHETIC_COMPONENT_FIXTURE_NOT_MARKET_DATA'),
    ('session','2019-11-20'),('raw_sha256','0'*64),('raw_open','NaN'),('raw_open','0')])
def test_market_registration_falsifiers(monkeypatch,key,value):
    monkeypatch.setattr(payload,'hosted',lambda:None);monkeypatch.setattr(payload,'_MARKET_QUOTE',None)
    q=fake_quote();q[key]=value
    with pytest.raises(ValueError):payload.bind_market_quote(q,expected_sha256=payload.digest(q))


def test_component_primitives_use_registered_prices_and_independent_legal_cash(market):
    book,ledger,result=stub.apply()
    assert book.cash==float(Fraction(2000)+20*Fraction(market['raw_open'])*Fraction('0.999'))
    proof=accounting.right_flow(ledger.events,market)
    assert proof['units']=='20' and proof['legal_merger_cash_exact']=='1000'
    assert proof['gross_right_open_value_exact']=='75' and proof['right_sale_fee_exact']=='3/40'
    scale,ref=payload.reference_scale(20,stub.terms(),60.)
    assert scale==float(Fraction(60)/(50+60+Fraction(market['raw_open'])))
    assert ref['right_market_input_sha256']==payload.digest(market)


@pytest.mark.parametrize('kind',['missing-right','missing-pair','wrong-date','wrong-quote','fractional'])
def test_financial_component_refuses_missing_rights_future_quote_or_fraction(market,kind):
    term=asdict(stub.terms())
    if kind=='fractional':
        book=stub.Book();book.episodes={0:stub.Episode(current_shares=.5)}
        before=deepcopy(book.__dict__)
        with pytest.raises(ValueError):stub.apply(book=book)
        assert book.__dict__==before;return
    _,ledger,_=stub.apply()
    if kind=='missing-right':term.pop('right_units_per_source')
    elif kind=='wrong-date':term['session']='2019-11-20'
    elif kind=='wrong-quote':term['right_quote']['raw_close']='99'
    else:
        with pytest.raises(ValueError):accounting.right_flow(ledger.events[:-1],market)
        return
    with pytest.raises(ValueError):payload.validate_terms(term)


@pytest.fixture
def boundary(monkeypatch):
    old_sources={n:'a'*64 for n in source.component.EXPECTED}|{
        'sentinel/economic_manifest.py':'d'*64,'unchanged.py':'1'*64}
    new_sources={**old_sources,**{n:'b'*64 for n in source.FINANCIAL_CHANGED}}
    state=dict(strategy_identity=dict(wealth_core_source_sha256='a'*64,controller_id='EXACT'),cash='100',pending=[])
    run=dict(policy='P',input_sha256='c'*64,state=state,state_sha256=gate.digest(state))
    run['checkpoint_sha256']=gate.digest(run)
    old=dict(base=dict(sources=old_sources,policy='P',capital='50000'),run=run,
        repairs=[dict(filename=str(i),sha256=str(i)) for i in range(9)],
        journals={n:dict(bytes=0,prefix_sha256='0'*64) for n in ('watch','daily','monthly','formation')},
        source_cursor='2019-11-19',completed=475,chain='e'*64,economics={'nav':'100'},stats={},retries={})
    old['sha256']=gate.digest(old)
    spec=dict(base=old['base'],repairs=old['repairs'],journals=old['journals'],
        selected_file=dict(bytes=1,sha256='f'*64),reused_hosted_old_source_proofs={},independent_review_sha256='d'*64)
    for k,v in [('PARENT',old['sha256']),('INNER',run['checkpoint_sha256']),('STATE',run['state_sha256']),
                ('INPUT',run['input_sha256'])]:monkeypatch.setattr(gate,k,v)
    monkeypatch.setattr(gate,'specification',lambda:spec)
    source_map=dict(predecessor_financial_sources=old_sources,successor_financial_sources=new_sources)
    identity=dict(wealth_core_source_sha256='b'*64,controller_id='EXACT')
    base={**old['base'],'sources':new_sources}
    return old,source_map,identity,base


def test_exact_source_receipt_and_financial_state_mutation_falsifier(boundary):
    old,mapping,identity,base=boundary;raw=gate.receipt(old,mapping,identity)
    assert gate.verify_receipt(raw,old,base,mapping,identity)
    changed=deepcopy(old);changed['run']['state']['cash']='101'
    with pytest.raises(ValueError,match='ALL_OWN475'):gate.verify_receipt(raw,changed,base,mapping,identity)


@pytest.mark.parametrize('kind',['wrong-parent','extra-source','controller','capital','old-input'])
def test_source_gate_does_not_convert_other_financial_or_model_identity(boundary,kind):
    old,mapping,identity,base=deepcopy(boundary)
    raw=gate.receipt(old,mapping,identity)
    if kind=='wrong-parent':old['sha256']='0'*64
    elif kind=='extra-source':base['sources']['extra.py']='e'*64
    elif kind=='controller':identity['controller_id']='CHANGED';raw=gate.receipt(old,mapping,identity)
    elif kind=='capital':base['capital']='1'
    else:old['repairs'][0]['sha256']='0'*64
    with pytest.raises(ValueError):gate.verify_receipt(raw,old,base,mapping,identity)


def test_actual_parent_content_guard_removal_accepts_bad_financial_state(boundary,monkeypatch):
    old,mapping,identity,base=boundary;raw=gate.receipt(old,mapping,identity)
    changed=deepcopy(old);changed['run']['state']['cash']='101'
    with pytest.raises(ValueError):gate.verify_receipt(raw,changed,base,mapping,identity)
    fn=next(n for n in ast.parse(Path(gate.__file__).read_bytes()).body
            if isinstance(n,ast.FunctionDef) and n.name=='parent_identity')
    guards=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
            and isinstance(n.value.func,ast.Name) and n.value.func.id=='need']
    assert len(guards)==1;fn.body.remove(guards[0]);scope=dict(vars(gate))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<source-guard-removed>','exec'),scope)
    monkeypatch.setattr(gate,'parent_identity',scope['parent_identity'])
    assert gate.verify_receipt(raw,changed,base,mapping,identity)


@pytest.mark.parametrize('sid',[codec.SID,codec.BMY])
def test_full_pending_future_buy_refuses_for_both_conversion_identities(sid):
    state=SimpleNamespace(wealth_core={'episodes':{}},pending=[{'security_id':sid,'operation':'OPEN_SLOT_POSITION'}],
                          median5={'selected':[]})
    with pytest.raises(ValueError,match='PENDING_REFUSES'):codec.pending_before(state)


def test_zero_source_startup_cannot_advance():
    pause=SourcePause({}, {}, {},Path('disposable.json.gz'))
    with pytest.raises(ValueError,match='CANNOT_ADVANCE'):pause.advance(None,None)
    assert pause.advance_attempts==1


def test_renderer_new_module_is_financial_while_install_sites_remain_exact():
    raw=Path(source.__file__).read_text()
    assert 'out[PAYLOAD]=payload' in raw and 'component.render(files,expected_sources' in raw
    assert source.CHANGED==frozenset(source.component.EXPECTED)|{source.PAYLOAD}|source.METADATA
    ast.parse(Path(payload.__file__).read_bytes())


def test_financial_renderer_refuses_mutated_qualified_component_source(monkeypatch):
    pins=dict(source.COMPONENT_PINS);pins['p01_celg_component.py']='0'*64
    monkeypatch.setattr(source,'COMPONENT_PINS',pins)
    with pytest.raises(ValueError,match='EXACT_INDEPENDENTLY_QUALIFIED_COMPONENT_SOURCE_BYTES'):
        source.render({}, {})


def public_receipt():
    return dict(schema='research.p01-celg-own475-financial-bridge-receipt/1',arm='P01',stage=export.STAGE,
        run_id='123',head='1'*40,request_sha256='2'*64,protocol_sha256='3'*64,
        strict_parent_outer_sha256=gate.PARENT,status='NOT_STARTED',production_contacted=False)


def test_actual_marker_encrypted_roundtrip(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    request=tmp_path/'request.json';request.write_text(json.dumps({'protocol_sha256':'2'*64}))
    proof=export.qualify_export(tmp_path/'marker',request)
    assert proof['source_adapter_sha256']==job.sha256_file(Path(export.__file__))
    assert proof['synthetic_marker_only'] and not proof['market_or_financial_state_processed']


@pytest.mark.parametrize('mode',['qualify','economic','review'])
def test_actual_inspector_requires_exact_full_RO_input_mounts_mode_and_fences(monkeypatch,mode):
    monkeypatch.setattr(job.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.os,'getgid',lambda:1001,raising=False)
    role='qualify' if mode=='qualify' else 'review' if mode=='review' else 'worker'
    name=f'capital-system-p01-celg-bridge-{role}-123-1'
    mounts=['/variant','/frozen','/driver','/out','/old','/celg-input','/celg-input-descriptor.json']
    if mode!='qualify':mounts.append('/evidence')
    value=dict(Name='/'+name,Image=job.inspector_source.EXECUTION_IMAGE,Id='1'*64,
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Config=dict(Cmd=job.entrypoint(mode),WorkingDir='/variant',User='1001:1001',Env=[],
            Labels={'research.study':'full-system-search-20261029','research.role':'review' if mode=='review' else 'worker'}),
        Mounts=[dict(Destination=n,Type='bind',RW=n=='/out') for n in mounts])
    monkeypatch.setattr(job.inspector_source.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps([value]).encode()))
    assert job.inspect(name,'1'*64)==value
    value['HostConfig']['MemorySwap']=0
    with pytest.raises(ValueError):job.inspect(name,'1'*64)
    value['HostConfig']['MemorySwap']=8*1024**3
    next(v for v in value['Mounts'] if v['Destination']=='/celg-input')['RW']=True
    with pytest.raises(ValueError):job.inspect(name,'1'*64)
    next(v for v in value['Mounts'] if v['Destination']=='/celg-input')['RW']=False
    value['Config']['Cmd']=job.entrypoint('review' if mode!='review' else 'economic')
    with pytest.raises(ValueError):job.inspect(name,'1'*64)


def test_unknown_finance_keeps_already_stopped_qualification_without_snapshot(tmp_path,monkeypatch):
    r=public_receipt();r['qualification_exported']=True
    r['qualification_encrypted_output']=dict(name='qualification.crseal',bytes=10,sha256='1'*64,
                                            manifest_sha256='2'*64,compression='TAR_GZIP_V1')
    monkeypatch.setattr(export,'sealed',lambda *a,**k:pytest.fail('UNKNOWN mutable snapshot attempted'))
    export.finish(r,tmp_path,tmp_path/'receipt.json',b'k'*32,tmp_path/'request',known=False)
    assert r['qualification_exported'] and not r['encrypted_output_exported']


def test_separate_qualification_export_inventory_and_GCM(tmp_path,monkeypatch):
    from seal import decrypt
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    root=tmp_path/'proof';root.mkdir();(root/'qualification').mkdir()
    for n in ('spec.json','request.json','source-bindings.json','source-map.json'):(root/n).write_text('{}')
    for n in ('celg-clock-input.json','source-successor.json','zero-session-boundaries.json','bridge-preflight.json',
              'actual-two-session-component.json.gz','actual-right-accounting-and-report.json',
              'qualification-summary.json','worker-inspect.json','worker.log'):
        (root/'qualification'/n).write_text('SYNTHETIC_MARKER_ONLY')
    (root/'qualification/qualification-summary.json').write_text(json.dumps(dict(
        financial_authority=False,financial_predecessor_authorized=False)))
    request=tmp_path/'request.json';request.write_text(json.dumps({'protocol_sha256':'2'*64}))
    r=public_receipt();r['qualification_worker']=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None)
    export.preserve_qualification(r,root,tmp_path/'public.json',b'k'*32,request)
    asset=r['qualification_encrypted_output'];plain=tmp_path/'proof.tar.gz'
    decrypt(tmp_path/asset['name'],plain,b'k'*32,asset['sha256'])
    with tarfile.open(plain,'r:gz') as archive:
        manifest=json.load(archive.extractfile('manifest.json'))
        assert manifest['stage']==export.QUALIFICATION_STAGE and manifest['arm']=='P01'
        assert len(manifest['members'])==13
    (root/'book').mkdir();(root/'book/daily.jsonl').write_text('SYNTHETIC_FINANCIAL_ROW')
    with pytest.raises(ValueError,match='NO_DISPOSABLE_FINANCIAL_BOOK'):
        export.preserve_qualification(r,root,tmp_path/'public.json',b'k'*32,request)


def test_public_receipt_rejects_financial_payload(tmp_path):
    r=public_receipt();r['cash']='PRIVATE'
    with pytest.raises(ValueError):export.write_receipt(tmp_path/'receipt.json',r)


def test_metadata_request_binds_only_admitted_parent_and_uploaded_actual_input():
    request=job.expected_request()
    assert len(request['sources'])==439 and request['original_inputs']==9
    assert request['maximum_financial_transitions']==51 and request['expected_completed']==526
    assert request['source_then_input_zero_session_boundaries'] and not request['qualification_state_adoption']
    assert request['quote_release_asset_id']==700454247
    assert not set(request['sources'])&{'p01_celg_multileg_facts.py','p01_celg_multileg_quote.json.gz'}


def test_workflow_capacity_precedes_staging_and_budget_has_shutdown_headroom():
    workflow=(Path(__file__).resolve().parents[3]/'.github/workflows/p01_celg_bridge_financial.yml').read_text()
    assert workflow.index('Prepare dedicated ephemeral research capacity')<workflow.index('Authenticate frozen inputs')
    assert 'timeout-minutes: 180' in workflow and 'timeout-minutes: 160' in workflow
    assert 'retention-days: 7' in workflow and 'cancel-in-progress: false' in workflow


@pytest.mark.parametrize('index',[0,1])
@pytest.mark.parametrize('role',['held','future-buy'])
def test_native_proxy_scope_requires_actual_prior_CP_restore_before_refusal(tmp_path,monkeypatch,index,role):
    scope=codec.SCOPES[index];sid=scope['security_id'];restores=[]
    state=SimpleNamespace(wealth_core={'episodes':{'0':{'security_id':sid}} if role=='held' else {}},
        pending=[{'security_id':sid,'operation':'OPEN_SLOT_POSITION'}] if role=='future-buy' else [],
        median5={'selected':[]})
    run=SimpleNamespace(state=state,policy='P',input_sha256='a'*64)
    cp=dict(run={'stub_full_state':'SAME'},source_cursor=scope['prior_session'],completed=1)
    cp['sha256']=codec.digest(cp)
    Term=make_dataclass('NativeScopeTerm',[(k,object) for k in scope['native_term']],frozen=True)
    published=SimpleNamespace(session=scope['session'],terminal_events=(Term(**scope['native_term']),))
    folder=tmp_path/'pre-event';folder.mkdir();(folder/(scope['session']+'-'+cp['sha256']+'.json.gz')).write_bytes(b'STUB')
    module=ModuleType('research.pooled_vacancy_funding.journal');module.read_checkpoint=lambda p:deepcopy(cp)
    monkeypatch.setitem(sys.modules,'research.pooled_vacancy_funding.journal',module)
    package=ModuleType('research.pooled_vacancy_funding');package.journal=module
    monkeypatch.setitem(sys.modules,'research.pooled_vacancy_funding',package)
    guard=codec.RoleGuard({},book=tmp_path)
    guard.runtime=SimpleNamespace(checkpoint=lambda r:deepcopy(cp['run']),
        restore=lambda *a,**k:restores.append(a[0]) or run)
    with pytest.raises(ValueError,match='CANNOT_BROADEN_TO_HELD_OR_PENDING'):guard.scope_guard(run,published,scope)
    assert restores==[cp['run']]
    cp['source_cursor']='1900-01-01';cp['sha256']=codec.digest({k:v for k,v in cp.items() if k!='sha256'})
    with pytest.raises(ValueError,match='MUST_ALREADY_EXIST'):guard.scope_guard(run,published,scope)
    assert len(restores)==1


def test_native_scope_changed_source_term_refuses_before_any_restore(tmp_path):
    scope=codec.SCOPES[0];Term=make_dataclass('NativeScopeTerm',[(k,object) for k in scope['native_term']],frozen=True)
    value=dict(scope['native_term'],cash_per_share=0.0)
    run=SimpleNamespace(state=SimpleNamespace(wealth_core={'episodes':{}},pending=[],median5={'selected':[]}))
    guard=codec.RoleGuard({},book=tmp_path)
    with pytest.raises(ValueError,match='EXACT_NATIVE_UNHELD'):
        guard.scope_guard(run,SimpleNamespace(terminal_events=(Term(**value),)),scope)


def test_source_startup_only_changes_identity_epoch_and_watch_commitment(boundary):
    old,mapping,identity,base=boundary
    event=dict(schema='pooled-source-boundary/1',predecessor=old['sha256'])
    bridge=deepcopy(old);bridge['base']={**base,'source_successor_sha256':'a'*64}
    bridge['run']['state']['strategy_identity']=identity
    bridge['run']['state_sha256']=gate.digest(bridge['run']['state'])
    bridge['run']['input_sha256']=gate.digest(dict(base=bridge['base'],repairs=bridge['repairs']))
    bridge['run']['checkpoint_sha256']=gate.digest({k:v for k,v in bridge['run'].items() if k!='checkpoint_sha256'})
    bridge['chain']=gate.digest(dict(previous=old['chain'],event=event))
    bridge['sha256']=gate.digest({k:v for k,v in bridge.items() if k!='sha256'})
    saved=deepcopy(bridge);saved['journals']['watch']['bytes']=1
    saved['sha256']=gate.digest({k:v for k,v in saved.items() if k!='sha256'})
    assert gate.source_adoption(saved,bridge,old,event)==event
    for key in ('economics','stats','retries'):
        changed=deepcopy(saved);changed[key]['unexpected']='MUTATION'
        changed['sha256']=gate.digest({k:v for k,v in changed.items() if k!='sha256'})
        with pytest.raises(ValueError,match='NO_FINANCIAL_OR_REPORTING_MUTATION'):
            gate.source_adoption(changed,bridge,old,event)


def test_registered_source_epoch_continuation_cannot_repeat_boundary_or_accept_other_CP(boundary,tmp_path,monkeypatch):
    old,mapping,identity,base=boundary;path=tmp_path/'source.json';path.write_text(json.dumps(gate.receipt(old,mapping,identity)))
    registry=gate.SourceGate(old,mapping,path,tmp_path/'current.gz')
    registry.runtime=SimpleNamespace(strategy=lambda p:(None,identity))
    newbase,binding=registry.load(path,base)
    assert binding is not None
    saved=dict(sha256='e'*64,base=newbase)
    module=ModuleType('research.pooled_vacancy_funding.journal');module.read_checkpoint=lambda p:deepcopy(saved)
    monkeypatch.setitem(sys.modules,'research.pooled_vacancy_funding.journal',module)
    registry.adopted=True;registry.allowed.add(saved['sha256'])
    assert registry.load(path,base)==(newbase,None)
    saved['sha256']='f'*64
    with pytest.raises(ValueError,match='ONLY_VERIFIED_ZERO_SESSION_SOURCE_EPOCH'):registry.load(path,base)
