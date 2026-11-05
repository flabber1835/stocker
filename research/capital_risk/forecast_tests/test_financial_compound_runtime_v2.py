"""Portable synthetic v2 runtime guards; no canonical financial imports/calls."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict,dataclass,replace
from fractions import Fraction
import importlib.abc
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in ('stock_strategy_shared','sentinel','numpy','pandas') or fullname.startswith('research.pooled_'):
            raise AssertionError('FORBIDDEN_CANONICAL_IMPORT:'+fullname)

fence=Fence();sys.meta_path.insert(0,fence)
try:
    import system_campaign_financial_compound_runtime_v2 as m
    import system_campaign_financial_compound_dispatch as dispatch
finally:sys.meta_path.remove(fence)

@pytest.fixture(autouse=True)
def imported():
    guard=Fence();sys.meta_path.insert(0,guard)
    yield
    sys.meta_path.remove(guard)

def mutant(name,code,*,method=None):
    nodes=ast.parse(Path(m.__file__).read_bytes()).body
    node=next(v for v in nodes if isinstance(v,ast.ClassDef if method else ast.FunctionDef) and v.name==name)
    if method:node=next(v for v in node.body if isinstance(v,ast.FunctionDef) and v.name==method)
    class Remove(ast.NodeTransformer):
        def __init__(self):self.count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value==code for v in node.value.args):
                self.count+=1;return None
            return self.generic_visit(node)
    remove=Remove();node=remove.visit(node);assert remove.count==1
    namespace=dict(vars(m));exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-runtime-v2-guard>','exec'),namespace)
    return namespace[method or name]

def prefix():
    return b''.join((json.dumps(dict(session=f'2020-{1+i//28:02}-{1+i%28:02}',index=i),sort_keys=True)+'\n').encode() for i in range(336))+b''.join(
        (json.dumps(dict(session=f'2021-{1+i//28:02}-{1+i%28:02}',index=i+336),sort_keys=True)+'\n').encode() for i in range(48))

def test_exact384_committed_raw_prefix_retains_all_bytes_excludes_tail():
    raw=prefix();assert m.committed_prefix(raw+b'{"session":"2021-05-03"}\n','2021-04-30')==raw

@pytest.mark.parametrize('kind',['missing','extra','order','newline','interior_tail'])
def test_prefix_count_order_and_boundary_falsifiers(kind):
    lines=prefix().splitlines(keepends=True)
    if kind=='missing':lines.pop()
    elif kind=='extra':lines.append(lines[-1])
    elif kind=='order':lines[0],lines[1]=lines[1],lines[0]
    elif kind=='newline':lines[-1]=lines[-1].rstrip(b'\n')
    else:lines.insert(0,b'{"session":"2021-05-01"}\n')
    with pytest.raises(ValueError):m.committed_prefix(b''.join(lines),'2021-04-30')

def test_prefix_guard_removal_really_admits_missing_record():
    raw=b''.join(prefix().splitlines(keepends=True)[:-1])
    with pytest.raises(ValueError):m.committed_prefix(raw,'2021-04-30')
    assert mutant('committed_prefix','COMPOUND_V2_EXACT384_COMMITTED_BRANCH_PREFIX_NO_TAIL')(raw,'2021-04-30')==raw

def test_child_sale_preserves_parent_while_later_strategy_sale_is_allowed():
    binding={'spin':dict(parent_security_id='P',child_security_id='C')};before=dict(events=[dict(old=True)])
    after=dict(events=before['events']+[dict(security_id='P',event_type='SELL')]);core=dict(episodes={})
    assert m.no_proxy_cash(binding,before,after,core)==dict(parent_proxy_cash_accrued=False,parent_proxy_cash_paid=False,child_retained=False)

@pytest.mark.parametrize('kind',['accrue','paid','child','prefix'])
def test_duplicate_cash_child_and_original_ledger_falsifiers(kind):
    binding={'spin':dict(parent_security_id='P',child_security_id='C')};before=dict(events=[dict(old=True)]);after=deepcopy(before);core=dict(episodes={})
    if kind=='accrue':after['events'].append(dict(security_id='P',event_type='DIVIDEND_ACCRUED'))
    elif kind=='paid':after['events'].append(dict(security_id='P',event_type='DIVIDEND_PAID'))
    elif kind=='child':core['episodes']['1']=dict(security_id='C')
    else:after['events'][0]['old']=False
    with pytest.raises(ValueError):m.no_proxy_cash(binding,before,after,core)

def test_double_cash_guard_removal_really_admits_accrued_proxy():
    b={'spin':dict(parent_security_id='P',child_security_id='C')};before=dict(events=[]);after=dict(events=[dict(security_id='P',event_type='DIVIDEND_ACCRUED')])
    with pytest.raises(ValueError):m.no_proxy_cash(b,before,after,dict(episodes={}))
    assert mutant('no_proxy_cash','COMPOUND_V2_NO_DUPLICATE_IN_KIND_PROXY_CASH_OR_RETAINED_CHILD')(b,before,after,dict(episodes={}))['parent_proxy_cash_accrued'] is False

@dataclass(frozen=True)
class Packet:
    value:int=0

def context(tmp_path,monkeypatch):
    path=tmp_path/'activation.json';raw=b'qualified activation\n';path.write_bytes(raw)
    ctx=m.ProjectionContext.__new__(m.ProjectionContext);ctx.root=tmp_path;ctx.overlay=path;ctx.overlay_sha=m.sha(raw);ctx.raw=b'payload'
    ctx.payload=dict(original_parent=dict(source_cursor='2021-04-30',run=dict(checkpoint_sha256='a'*64)),ordinary_material={'arm':'P07'},binding={'spin':'test'})
    ctx.bound_objects=[];ctx.changed_packets=0
    obj=SimpleNamespace(source_evidence=[SimpleNamespace(reference=m.CATALOG_REF,sha256='b'*64)],sha256=ctx.overlay_sha)
    ctx.original_load=lambda *a,**k:obj;ctx.original_apply=lambda packet,obj:packet
    ctx.projection=SimpleNamespace(descriptor={'source':'exact'},apply=lambda packet,activation:replace(packet,value=packet.value+1))
    monkeypatch.setattr(m,'qualified_record',lambda arm:dict(source_proof={'closed':True}))
    monkeypatch.setattr(m,'refs',lambda raw,r:{m.CATALOG_REF:'b'*64})
    monkeypatch.setattr(m,'activation_descriptor',lambda *args:{'minimum':'2021-05-25'})
    monkeypatch.setattr(m,'qualified_loaded_view',lambda original,*args:SimpleNamespace(**vars(original),earliest_affected_session='2021-05-25'))
    return ctx,path,obj

def test_actual_parsed_qualified_view_bound_once_foreign_b19_objects_delegate(tmp_path,monkeypatch):
    ctx,path,original=context(tmp_path,monkeypatch)
    loaded=ctx.load(path,resume_session='2021-04-30',predecessor_checkpoint_sha256='a'*64)
    assert loaded is not original and loaded.earliest_affected_session=='2021-05-25'
    assert ctx.apply(Packet(),loaded)==Packet(1)
    assert ctx.changed_packets==1
    foreign=SimpleNamespace(sha256='c'*64);ctx.original_load=lambda *a,**k:foreign
    assert ctx.load(path,resume_session='other',predecessor_checkpoint_sha256='x') is foreign
    packet=Packet();assert ctx.apply(packet,foreign) is packet

@pytest.mark.parametrize('kind',['cursor','predecessor','bytes','catalogsha','duplicate'])
def test_wrong_parent_or_activation_bytes_cannot_bind_loaded_view(tmp_path,monkeypatch,kind):
    ctx,path,obj=context(tmp_path,monkeypatch);cursor='2021-04-30';pred='a'*64
    if kind=='cursor':cursor='2021-05-01'
    elif kind=='predecessor':pred='c'*64
    elif kind=='bytes':path.write_bytes(b'changed\n')
    elif kind=='catalogsha':obj.source_evidence[0].sha256='c'*64
    else:obj.source_evidence*=2
    with pytest.raises(ValueError):ctx.load(path,resume_session=cursor,predecessor_checkpoint_sha256=pred)
    assert not ctx.bound_objects

def test_loaded_parent_guard_removal_really_admits_wrong_original_cursor(tmp_path,monkeypatch):
    ctx,path,obj=context(tmp_path,monkeypatch)
    with pytest.raises(ValueError):ctx.load(path,resume_session='2021-05-01',predecessor_checkpoint_sha256='a'*64)
    fn=mutant('ProjectionContext','COMPOUND_V2_LOADER_EXACT_ACTIVATION_BYTES_AND_ORIGINAL_PARENT',method='load')
    assert fn(ctx,path,resume_session='2021-05-01',predecessor_checkpoint_sha256='a'*64).earliest_affected_session=='2021-05-25'

def test_forged_copy_cannot_apply_even_with_identical_serialized_fields(tmp_path,monkeypatch):
    ctx,path,obj=context(tmp_path,monkeypatch);loaded=ctx.load(path,resume_session='2021-04-30',predecessor_checkpoint_sha256='a'*64)
    forged=SimpleNamespace(**vars(loaded))
    with pytest.raises(ValueError):ctx.apply(Packet(),forged)
    fn=mutant('ProjectionContext','COMPOUND_V2_APPLY_REQUIRES_ACTUAL_QUALIFIED_LOADED_OBJECT',method='apply')
    assert fn(ctx,Packet(),forged)==Packet(1)

def test_immutable_APHA_unwraps_actual_B19_when_v2_enters_outside():
    path=Path(m.__file__).parent/'system_campaign_financial_projection.py';raw=path.read_bytes()
    assert m.sha(raw)==m.APHA_SHA
    fn=next(v for v in ast.parse(raw).body if isinstance(v,ast.FunctionDef) and v.name=='branch_loader_owner')
    class Codec:
        def load(self,*a,**k):pass
    class OwnProjection:
        def __init__(self,load):self.original_load=load;self.active=True
        def load(self,*a,**k):pass
    class Compound:
        def load(self,*a,**k):pass
    scope={'OwnProjection':OwnProjection,'need':m.need}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<exact-immutable-APHA-unwrap>','exec'),scope)
    compound=Compound();codec=Codec();codec.original_load=compound.load;apha=OwnProjection(codec.load)
    assert scope['branch_loader_owner'](apha.load) is codec
    # Opposite composition demonstrates the wrong owner, making the ordering
    # assertion meaningful without importing the financial branch engine.
    assert scope['branch_loader_owner'](compound.load) is compound

def test_version_dispatch_exact_initial_selection_and_ambiguity(monkeypatch):
    a=SimpleNamespace(applies=lambda cp,arm:arm=='P06');b=SimpleNamespace(applies=lambda cp,arm:arm=='P07')
    monkeypatch.setattr(dispatch,'versions',lambda:(a,b))
    assert dispatch.selected({},'P06') is a and dispatch.selected({},'P07') is b
    assert dispatch.selected({},'P00') is None
    b.applies=lambda cp,arm:True
    with pytest.raises(ValueError):dispatch.selected({},'P06')

def test_version_retention_allows_distinct_phases_refuses_duplicates_and_samephase(monkeypatch,tmp_path):
    a=SimpleNamespace(CATALOG_REF='v1');b=SimpleNamespace(CATALOG_REF='v2');monkeypatch.setattr(dispatch,'versions',lambda:(a,b))
    book=tmp_path/'book/repairs';book.mkdir(parents=True)
    def row(ref,cursor):
        raw=m.encoded(dict(source_evidence=[dict(reference=ref)]));name=m.sha(raw)+'.json';(book/name).write_bytes(raw)
        return dict(filename=name,sha256=m.sha(raw),resume_session=cursor,predecessor_checkpoint_sha256='a'*64)
    first=row('v1','2020-01-01');second=row('v2','2021-01-01')
    assert dispatch.retained_versions(tmp_path,dict(repairs=[first,second]))==(a,b)
    with pytest.raises(ValueError):dispatch.retained_versions(tmp_path,dict(repairs=[first,first]))
    second['resume_session']=first['resume_session']
    with pytest.raises(ValueError):dispatch.retained_versions(tmp_path,dict(repairs=[first,second]))

def test_retained_context_enters_all_versions_before_original_branch_stack(monkeypatch):
    order=[]
    @contextmanager
    def context(name):
        order.append(name+' enter');yield;order.append(name+' exit')
    monkeypatch.setattr(dispatch,'retained_versions',lambda *a:())
    monkeypatch.setattr(dispatch,'versions',lambda:tuple(SimpleNamespace(retained_context=lambda *a,n=n:context(n)) for n in ('v1','v2')))
    with dispatch.retained_context('old',{},'out'):
        with context('B19'),context('APHA'):order.append('actual')
    assert order==['v1 enter','v2 enter','B19 enter','APHA enter','actual','APHA exit','B19 exit','v2 exit','v1 exit']

def test_hosted_source_and_financial_entrypoints_refuse_before_canonical_import():
    for fn,args in ((m.reconstruct_source,({},{})),(m.hydrate,({},'P07',Path('.'))),(m.prepare,({},Path('.'),'P07')),
                    (m.qualify,({},Path('.'),{},None,None)),(m.review,({},Path('.'),'P07'))):
        with pytest.raises(ValueError):fn(*args)

def test_hooks_resolve_actual_codec_before_initial_projection_and_keep_existing_gate():
    root=Path(m.__file__).parent;path=root/'system_campaign_financial_uncertainty.py'
    if not path.exists():path=root/'system_campaign_financial_uncertainty.py.after'
    raw=path.read_text();fn=next(v for v in ast.parse(raw).body if isinstance(v,ast.FunctionDef) and v.name=='run_retained')
    calls=[v for v in ast.walk(fn) if isinstance(v,ast.Call)]
    def one(name):
        return [v for v in calls if ast.unparse(v.func)==name]
    assert len(one('AdoptionGate'))==1 and len(one('active_codec'))==1 and len(one('compound.initial_context'))==1
    assert one('active_codec')[0].lineno<one('compound.initial_context')[0].lineno
    gate=ast.unparse(one('AdoptionGate')[0]);assert 'loaded.earliest_affected_session' in gate and 'loaded.sha256' in gate
    cert=ast.unparse(one('Certificate')[0]);assert 'seed=rows' in cert and 'codec' in cert
    withs=[v for v in ast.walk(fn) if isinstance(v,ast.With)]
    assert any(ast.unparse(v.items[0].context_expr)=='compound_scope' for v in withs)
    assert 'compound.ordinary_events(out, cp)' in ast.unparse(fn)
    module=ast.parse(Path(m.__file__).read_bytes())
    initial=next(v for v in module.body if isinstance(v,ast.FunctionDef) and v.name=='initial_context')
    assert 'AdoptionGate' not in ast.unparse(initial)

@dataclass(frozen=True)
class Spin:
    session:str='2021-05-25'
    source_row_id:str='source'
    parent_security_id:str='P'
    child_security_id:str='C'

def observing(tmp_path,monkeypatch):
    spin=Spin();binding=dict(spin=asdict(spin))
    observer=m.Observer(tmp_path,dict(binding=binding));observer.kernel_code=None
    before=SimpleNamespace(wealth_core=dict(episodes={}),ledger=dict(events=[]),pending=[])
    result=SimpleNamespace(state=SimpleNamespace(wealth_core=dict(episodes={}),ledger=dict(events=[])))
    run=SimpleNamespace(state=before)
    pub=SimpleNamespace(session=spin.session,bars=(SimpleNamespace(security_id='P',dividend_per_share=0.),),spinoff_distributions=(spin,))
    monkeypatch.setattr(m,'actual_role',lambda *a:True)
    def original(run,publication):
        observer.current['order'].append('SPINOFF');observer.current['spin']={'delegated':True};return result
    observer.advance_original=original
    return observer,run,pub,result

def test_actual_observer_delegates_return_unchanged_and_writes_only_after_postconditions(tmp_path,monkeypatch):
    obs,run,pub,result=observing(tmp_path,monkeypatch)
    assert obs.advance(run,pub) is result and obs.current is None
    proof=json.loads((tmp_path/m.ACTUAL).read_bytes())
    assert proof['passed'] and proof['order']==['SPINOFF'] and proof['proxy_cash']['parent_proxy_cash_paid'] is False
    later=SimpleNamespace(session='2021-05-26');obs.advance_original=lambda a,b:result
    assert obs.advance(run,later) is result

@pytest.mark.parametrize('kind',['proxy','native','duplicate','missing_call','duplicate_call','paid','child'])
def test_actual_publication_call_order_and_cash_falsifiers(tmp_path,monkeypatch,kind):
    obs,run,pub,result=observing(tmp_path,monkeypatch)
    if kind=='proxy':pub.bars[0].dividend_per_share=84.55
    elif kind=='native':pub.spinoff_distributions=(replace(Spin(),source_row_id='unreviewed'),)
    elif kind=='duplicate':pub.spinoff_distributions*=2
    elif kind=='missing_call':obs.advance_original=lambda *a:result
    elif kind=='duplicate_call':
        original=obs.advance_original
        def duplicate(*args):
            value=original(*args);obs.current['order'].append('SPINOFF');return value
        obs.advance_original=duplicate
    elif kind=='paid':result.state.ledger['events'].append(dict(security_id='P',event_type='DIVIDEND_PAID'))
    else:result.state.wealth_core['episodes']['9']=dict(security_id='C')
    with pytest.raises(ValueError):obs.advance(run,pub)
    assert not (tmp_path/m.ACTUAL).exists() and obs.current is None
    assert json.loads((tmp_path/'compound-event-v2-refusal.json').read_bytes())['passed'] is False

def test_actual_call_guard_removal_really_admits_missing_canonical_call(tmp_path,monkeypatch):
    obs,run,pub,result=observing(tmp_path,monkeypatch);obs.advance_original=lambda *args:result
    with pytest.raises(ValueError):obs.advance(run,pub)
    fn=mutant('Observer','COMPOUND_V2_ACTUAL_CANONICAL_CHILD_CALL_BEFORE_COMMIT',method='advance')
    assert fn(obs,run,pub) is result

def retained(tmp_path,monkeypatch):
    book=tmp_path/'book/repairs';book.mkdir(parents=True)
    raw=m.encoded(dict(source_evidence=[dict(reference=m.CATALOG_REF)]));name=m.sha(raw)+'.json';(book/name).write_bytes(raw)
    descriptor=dict(filename=name,sha256=m.sha(raw),resume_session='2021-04-30',predecessor_checkpoint_sha256='a'*64)
    own=dict(sha256='b'*64,source_cursor='2021-04-30',run=dict(checkpoint_sha256='a'*64),base={'own':True})
    binding=dict(spin=dict(session='2021-05-25'));material=dict(arm='P07',terms=[dict(added=dict(session='2022-02-23'))])
    p=dict(original_parent=own,binding=binding,base=own['base'],ordinary_material=material,retained_certificate={'sha256':m.sha(prefix())})
    payload=b'payload';(tmp_path/m.PAYLOAD).write_bytes(payload);(tmp_path/m.PREFIX).write_bytes(prefix());(tmp_path/m.CERTIFICATE).write_bytes(prefix())
    (tmp_path/m.MATERIAL).write_bytes(m.encoded(material));(tmp_path/'source-bindings.json').write_bytes(b'own')
    cp=dict(sha256='c'*64,source_cursor='2021-06-01',base=own['base'],repairs=[descriptor])
    monkeypatch.setattr(m,'verify_payload',lambda root:(p,payload));monkeypatch.setattr(m,'qualified_record',lambda arm:{'source_bindings_sha256':m.sha(b'own')})
    monkeypatch.setattr(m,'ProjectionContext',lambda root,path,**kw:SimpleNamespace(root=root,overlay=root/path,payload=p))
    return cp,p,descriptor

def test_retained_own_generation_keeps_original_activation_cursor_and384_raw_bytes(tmp_path,monkeypatch):
    cp,p,d=retained(tmp_path,monkeypatch);projection=m.retained_activation(tmp_path,cp)
    assert projection.payload is p and projection.overlay.name==d['filename']
    assert projection.payload['original_parent']['source_cursor']=='2021-04-30'

@pytest.mark.parametrize('kind',['base','cursor','predecessor','bindings','prefix','material','descriptor','duplicate'])
def test_retained_generation_binding_material_prefix_and_activation_falsifiers(tmp_path,monkeypatch,kind):
    cp,p,d=retained(tmp_path,monkeypatch)
    if kind=='base':cp['base']={'other':True}
    elif kind=='cursor':d['resume_session']='2021-05-01'
    elif kind=='predecessor':d['predecessor_checkpoint_sha256']='d'*64
    elif kind=='bindings':(tmp_path/'source-bindings.json').write_bytes(b'other')
    elif kind=='prefix':(tmp_path/m.PREFIX).write_bytes(prefix()+b'\n')
    elif kind=='material':(tmp_path/m.MATERIAL).write_bytes(b'other')
    elif kind=='descriptor':d['sha256']='d'*64
    else:cp['repairs'].append(deepcopy(d))
    with pytest.raises(ValueError):m.retained_activation(tmp_path,cp)

def test_retained_activation_guard_removal_really_admits_other_binding(tmp_path,monkeypatch):
    cp,p,d=retained(tmp_path,monkeypatch);(tmp_path/'source-bindings.json').write_bytes(b'other')
    with pytest.raises(ValueError):m.retained_activation(tmp_path,cp)
    fn=mutant('retained_activation','COMPOUND_V2_RETAINED_ORIGINAL_CURSOR_BINDING_AND_MATERIAL')
    assert fn(tmp_path,cp).payload is p

def test_retained_observation_files_select_only_committed_child_and_cash_proofs(tmp_path):
    p=dict(binding={'spin':{'session':'2021-05-25'}},ordinary_material={'terms':[{'added':{'session':'2022-02-23'}}]})
    event='actual-future-event-2022-02-23.json';(tmp_path/event).write_bytes(b'original committed ordinary proof')
    folder=tmp_path/'compound-v2-retained-ordinary-observation';folder.mkdir();(folder/event).write_bytes(b'prior retained proof')
    assert m.retained_observation_files(p,tmp_path,{'source_cursor':'2021-05-24'})==()
    assert m.retained_observation_files(p,tmp_path,{'source_cursor':'2021-05-25'})==(m.ACTUAL,)
    assert m.retained_observation_files(p,tmp_path,{'source_cursor':'2022-02-23'})==(m.ACTUAL,Path(event),Path(folder.name)/event)

def test_restart_after_ordinary_completion_preserves_both_candidate_paths_byte_exact(tmp_path,monkeypatch):
    root=tmp_path/'old';out=tmp_path/'out';root.mkdir();out.mkdir()
    p=dict(binding={'spin':{'session':'2021-05-25'}},ordinary_material={'terms':[{'added':{'session':'2022-02-23'}}]})
    event='actual-future-event-2022-02-23.json';nested=Path('compound-v2-retained-ordinary-observation')/event
    originals={m.PAYLOAD:b'closed payload',m.PREFIX:prefix(),m.MATERIAL:b'original material',m.QUALIFICATION:b'original qualifier',
               m.ORDINARY_QUALIFICATION:b'original ordinary qualifier',m.ACTUAL:b'committed child proof',event:b'committed ordinary proof',nested:b'committed retained proof'}
    for name,raw in originals.items():
        path=root/name;path.parent.mkdir(exist_ok=True,parents=True);path.write_bytes(raw)
    entered=[]
    @contextmanager
    def projection():entered.append('projection');yield
    ctx=projection();ctx.payload=p
    monkeypatch.setattr(m,'retained_activation',lambda *a:ctx)
    calls=[];monkeypatch.setattr(m,'review_actual',lambda *a:calls.append(a))
    with m.retained_context(root,{'source_cursor':'2022-03-01'},out):pass
    assert calls and entered==['projection']
    assert all((out/name).read_bytes()==raw for name,raw in originals.items())

def test_pre_event_restart_ignores_uncommitted_child_and_cash_tail_proofs(tmp_path,monkeypatch):
    root=tmp_path/'old';out=tmp_path/'out';root.mkdir();out.mkdir()
    p=dict(binding={'spin':{'session':'2021-05-25'}},ordinary_material={'terms':[{'added':{'session':'2022-02-23'}}]})
    (root/m.ACTUAL).write_bytes(b'uncommitted child tail');(root/'actual-future-event-2022-02-23.json').write_bytes(b'uncommitted ordinary tail')
    @contextmanager
    def empty():yield
    ctx=empty();ctx.payload=p;ctx.overlay=root/'repair.json'
    monkeypatch.setattr(m,'retained_activation',lambda *a:ctx);monkeypatch.setattr(m,'review_actual',lambda *a:None)
    monkeypatch.setattr(m,'Observer',lambda *a:empty())
    ordinary=empty();ordinary.out=root
    monkeypatch.setattr(m,'ordinary_events',lambda *a,**k:ordinary)
    with m.retained_context(root,{'source_cursor':'2021-05-24'},out):pass
    assert not (out/m.ACTUAL).exists() and not (out/'actual-future-event-2022-02-23.json').exists()

def test_actual_review_ignores_malformed_uncommitted_child_tail_and_requires_committed_proof(tmp_path):
    p=dict(binding={'spin':{'session':'2021-05-25'}},ordinary_material={'terms':[{'security_id':'G','added':{'session':'2022-02-23'}}]})
    (tmp_path/m.ACTUAL).write_bytes(b'truncated uncommitted observer JSON')
    assert m.review_actual(p,tmp_path,{'source_cursor':'2021-05-24'}) is None
    (tmp_path/m.ACTUAL).unlink()
    with pytest.raises(ValueError,match='POST_EVENT_REQUIRES_ACTUAL_CHILD_OBSERVER'):
        m.review_actual(p,tmp_path,{'source_cursor':'2021-05-25'})
