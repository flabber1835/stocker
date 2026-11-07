"""Read-only real input DATA and explicitly noncanonical orchestration DTOs."""
import ast,gzip,json,sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import pytest

class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P05_BATCH_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_p05_batch_data as data
import system_campaign_p05_batch_api as api
import system_campaign_p05_batch_runtime as runtime

@pytest.fixture(scope='module')
def actual():
    from system_campaign_financial_partial import root_spec
    spec=root_spec('P05',data.ROOT)
    root=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial320-source-snapshot/capture-P05-13473317076-001/verified-output')
    root=Path(chr(92)*2+'?'+chr(92)+str(root.resolve()))
    raw=(root/spec['selected_checkpoint']).read_bytes()
    assert dict(bytes=len(raw),sha256=data.sha(raw))==spec['selected_file']
    parent=json.loads(gzip.decompress(raw))
    return root,parent,spec,data.catalogs(root,parent)

def test_real65_old_contracts_plus_exact_ACC_compile_under_original128_cap(actual):
    root,parent,spec,chunks=actual
    assert [len(c['terms']) for c in chunks]==[30,30,6]
    assert sum(len(c['retained_source_indices']) for c in chunks)==65
    assert sum(t['security_id']==data.acc.SID for c in chunks for t in c['terms'])==1
    counts=[]
    for c in chunks:
        material=dict(catalog_sha256=data.sha(data.encoded(c)),original_validator_sha256=data.sha(Path(data.__file__).read_bytes()),selector_sha256='1'*64,terms=c['terms'])
        doc=runtime.future.document(parent,material,'2'*64);counts.append(len(doc['source_evidence']))
        assert len(doc['source_evidence'])<=128 and doc['add']==[t['added'] for t in c['terms']]
    assert counts==[124,124,28]
    material['terms']=[t for c in chunks for t in c['terms']]
    assert len(runtime.future.document(parent,material,'2'*64)['source_evidence'])==268>128

def test_actual_source_binding_retains_all_old_predicates_with_only_two_AST_sites():
    raw=Path(data.original.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='source_binding')
    after=data.source_tree(raw)
    n=next(n for n in after.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_p05_batch_data');n.module='system_campaign_financial_future'
    literal=next(n for n in ast.walk(after) if isinstance(n,ast.Constant) and n.value=='research.independent-forward-source-DATA-validation/2')
    literal.value='research.independent-frozen-source-data-validation/1'
    assert ast.dump(after,include_attributes=False)==ast.dump(before,include_attributes=False)

def test_full_validator_AST_undo_keeps_extraction_and_every_other_guard():
    raw=Path(data.original.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate')
    after=data.validator_tree(raw)
    inserted=next(n for n in after.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='(captured, declared, checked_members)')
    after.body.remove(inserted)
    class Undo(ast.NodeTransformer):
        members=policies=0
        def visit_Name(self,node):
            if node.id=='checked_members':self.members+=1;return ast.copy_location(ast.parse("review['terms']",mode='eval').body,node)
            return node
        def visit_If(self,node):
            if ast.unparse(node.test)=='is_acc(term)':self.policies+=1;return node.orelse
            return self.generic_visit(node)
    undo=Undo();after=undo.visit(after)
    assert (undo.members,undo.policies)==(2,1)
    assert ast.dump(after,include_attributes=False)==ast.dump(before,include_attributes=False)

def test_whole_original_adoption_helper_plus_three_unique_filenames_only():
    raw=Path(runtime.uncertainty.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption')
    after=runtime.adoption_tree(raw);mapping=next(n.value for n in after.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names')
    assert [k.value for k in mapping.keys[-3:]]==[api.directory(i) for i in range(3)]
    assert [v.value for v in mapping.values[-3:]]==[api.overlay(i) for i in range(3)]
    mapping.keys=mapping.keys[:-3];mapping.values=mapping.values[:-3]
    assert ast.dump(after,include_attributes=False)==ast.dump(before,include_attributes=False)

@pytest.mark.parametrize('change',['q_projection','parent','native','capture','legal_price','extraction_date','extraction_preopen','source_only','retained_pin','ACC_date','ACC_policy'])
def test_semantic_or_provenance_changes_refuse(actual,change):
    root,parent,spec,chunks=actual;c=deepcopy(chunks[0]);t=c['terms'][1]
    if change=='q_projection':c['source_data']['qualification'].pop('independent_raw_source_proof')
    elif change=='parent':t['parent_outer_sha256']='0'*64
    elif change=='native':t['native']['cash_per_share']=1.
    elif change=='capture':t['source_capture']['artifact_id']+=1
    elif change=='legal_price':t['added']['cash_per_share']+=1.
    elif change=='extraction_date':t['primary_extraction']['completion_date']='2099-01-01'
    elif change=='extraction_preopen':t['primary_extraction']['preopen_completion_confirmed']=False
    elif change=='source_only':t['recognition_rule']='RESEARCH_NATIVE_UNHELD_CASH_SOURCE_CLOSE'
    elif change=='retained_pin':t['retained_qualified_legal_term']['term_sha256']='0'*64
    elif change=='ACC_date':c['terms'][0]['added']['session']='2022-08-09'
    else:c['terms'][0]['recognition_rule']='RESEARCH_COMPLETION_DATE_OPEN_AVAILABILITY'
    with pytest.raises((ValueError,KeyError)):data.validate(c,parent)

def test_source_and_input_guards_are_meaningful(actual,monkeypatch):
    root,parent,spec,chunks=actual;bad=deepcopy(chunks[0]);bad['terms'][1]['primary_extraction']['completion_date']='2099-01-01'
    fn=data.validator_tree(Path(data.original.__file__).read_bytes())
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='CASH_BATCH_EXACT_PRIMARY_AMOUNT_AND_DATE_EXTRACTION' for a in node.value.args):
                self.hits+=1;return None
            return self.generic_visit(node)
    remove=Remove();changed=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    with pytest.raises(ValueError):data.validate(bad,parent)
    monkeypatch.setattr(data,'validator_tree',lambda raw:changed)
    assert data.validate(bad,parent) is True

def test_whole_original_future_function_code_objects_and_no_auxiliary_policy_dropped(actual):
    root,parent,spec,chunks=actual;bound=api.api(parent,parent,chunks[0],0)
    for name in api.FUNCTIONS:assert getattr(bound,name).__code__ is getattr(runtime.future,name).__code__
    assert bound.prepare.__globals__['qualify'] is bound.qualify
    assert bound.qualify.__globals__['save'] is not runtime.future.save
    f=runtime.future
    assert f.original_ordinary_selection('P05',parent['source_cursor']) is None
    assert f.original_delivery_selection('P05',parent['source_cursor']) is None
    assert f.supplemental_selection('P05',parent['source_cursor'])==([],[])
    assert f.qualified_own_batch_selection(parent,'P05')==([],[])
    assert f.contractual_delivery_selection(parent,'P05')==([],[])
    from system_campaign_financial_compound_dispatch import selected
    assert selected(parent,'P05') is None

def test_first_original_observer_constructor_sees_all94_before_any_gate(actual,tmp_path,monkeypatch):
    import full_system_core
    import system_campaign_retained_cash_v2 as cash
    root,parent,spec,chunks=actual;plan,=cash.original.plans()
    _,_,prior=cash.original.checked_resources(root,parent,plan)
    all_prior=cash.union_terms(prior,cash.full_inventory(root,parent,plan)['terms'])
    assert len(all_prior)==28
    terms=cash.union_terms(all_prior,*[c['terms'] for c in chunks]);assert len(terms)==94
    bound=api.api(parent,parent,chunks[0],0)
    material=dict(arm='P05',terms=chunks[0]['terms'])
    doc=dict(add=[t['added'] for t in chunks[0]['terms']])
    (tmp_path/runtime.future.OVERLAY).write_bytes(data.encoded(doc))
    (tmp_path/runtime.future.hydration_name(parent)).write_bytes(data.encoded(material))
    original_constructor=runtime.future.ActualEvents.__init__
    constructor=FunctionType(original_constructor.__code__,dict(original_constructor.__globals__,source_scopes=bound.source_scopes),
        original_constructor.__name__,original_constructor.__defaults__);constructor.__kwdefaults__=deepcopy(original_constructor.__kwdefaults__)
    Original=type('NoncanonicalObserverConstructorHarness',(),dict(__init__=constructor,advance=runtime.future.ActualEvents.advance,terminal=runtime.future.ActualEvents.terminal))
    original_proxy=SimpleNamespace(selected=lambda *a:[plan],observer_class=lambda *a:Original,merge_terms=cash.original.merge_terms)
    fn=cash.context.__wrapped__
    harness=FunctionType(fn.__code__,dict(fn.__globals__,original=original_proxy,stage=lambda *a:terms),fn.__name__,fn.__defaults__)
    monkeypatch.setattr(runtime.future,'ActualEvents',Original);monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    with contextmanager(harness)(root,parent,tmp_path,spec):
        event=runtime.future.ActualEvents(tmp_path,'P05',cp=parent)
        assert len(event.terms)==94 and event.scopes==[]
        assert event.advance.__func__ is Original.advance and event.terminal.__func__ is Original.terminal
        assert ('2022-08-10',data.acc.SID) in event.terms

def test_entry_binding_restores_all_functions_even_on_abort(actual):
    import system_campaign_retained_cash_v2 as cash,system_campaign_retained_cash_materials_v2 as materials,system_campaign_pending_cash_api as pending
    root,parent,spec,chunks=actual
    module=SimpleNamespace(financial_inputs=lambda *a:None,qualified_overlay=lambda *a:None,review_adoption=lambda *a:None)
    saved=cash.stage,materials.inventory,pending.for_parent,module.financial_inputs,module.qualified_overlay,module.review_adoption
    with pytest.raises(RuntimeError):
        with runtime.entry_context(module,spec):
            assert materials.inventory is runtime.inventory
            raise RuntimeError('NONCANONICAL_ABORT')
    assert saved==(cash.stage,materials.inventory,pending.for_parent,module.financial_inputs,module.qualified_overlay,module.review_adoption)

def test_future_financial_family_is_explicitly_unqualified(actual):
    root,parent,spec,chunks=actual
    # This is input metadata only, not a new financial root or checkpoint.
    dto=dict(NONCANONICAL_FUTURE_INPUT_FAMILY_DTO=True,arm='P05',repairs=parent['repairs']+[{'NONCANONICAL':True}]*3)
    module=SimpleNamespace(EXECUTION_MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION')
    with pytest.raises(ValueError,match='INITIAL_OWN1152_ONLY'):
        with runtime.entry_context(module,dto):pass

def test_original_material_inventory_survives_binding_without_recursion(actual):
    import system_campaign_retained_cash_v2 as cash,system_campaign_retained_cash_materials_v2 as materials
    root,parent,spec,chunks=actual;plan,=cash.original.plans()
    names={p.relative_to(root).as_posix() for p in [*root.glob('hydrated-future-financial-terminal-catalog-*.json'),
        *(root/materials.DIRECTORY).glob('*/hydrated-future-financial-terminal-catalog-*.json')]}
    original=runtime.ORIGINAL_INVENTORY(parent,plan,names,lambda n:(root/n).read_bytes())
    module=SimpleNamespace(financial_inputs=lambda *a:None,qualified_overlay=lambda *a:None,review_adoption=lambda *a:None)
    with runtime.entry_context(module,spec):
        bound=materials.inventory(parent,plan,names,lambda n:(root/n).read_bytes())
    assert bound==original

def test_real_prior_canonical_watch_event_is_exact_actual_gate_proof(actual):
    root,parent,spec,chunks=actual
    proof=json.loads((root/'input-adoption/proof.json').read_bytes())
    committed=(root/'book/watch.jsonl').read_bytes()[:parent['journals']['watch']['bytes']]
    rows=[json.loads(line) for line in committed.splitlines()]
    events=[r for r in rows if r.get('schema')=='research.pooled-action-successor/1']
    assert len(events)==16 and events[-1]==proof['event']

def test_actual_compiled_evidence_cap_guard_removal_accepts_oversize_metadata(tmp_path,monkeypatch):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    catalog={'terms':[{'NONCANONICAL_INPUT_DTO':True}]}
    gate=runtime.BatchGate.__new__(runtime.BatchGate);gate.initial={'NONCANONICAL_CONTROL_DTO':True};gate.out=tmp_path;gate.catalogs=[catalog]
    current={'NONCANONICAL_CONTROL_DTO':True,'sha256':'1'*64}
    raw=data.encoded({'NONCANONICAL_INPUT_DTO':True,'source_evidence':[{'reference':'SYNTHETIC'}]*129})
    (tmp_path/api.overlay(0)).write_bytes(raw)
    (tmp_path/runtime.future.hydration_name(current)).write_bytes(data.encoded(catalog))
    (tmp_path/api.qualification(0)).write_text('{"NONCANONICAL_INPUT_DTO":true,"passed":true,"financial_sessions_advanced":0}')
    fake=SimpleNamespace(prepare=lambda *a:(tmp_path/api.overlay(0),SimpleNamespace(sha256=data.sha(raw))))
    monkeypatch.setattr(api,'api',lambda *a:fake)
    with pytest.raises(ValueError,match='ORIGINAL_EVIDENCE_CAP'):gate.prepare(current,0)
    owner=next(n for n in ast.parse(Path(runtime.__file__).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='BatchGate')
    fn=next(n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='prepare')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value=='P05_BATCH_WHOLE_ACTUAL_PREPARED_CHUNK_AND_ORIGINAL_EVIDENCE_CAP' for a in n.value.args))
    fn.body.remove(guard);scope=dict(vars(runtime));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-evidence-cap-control-metadata-only>','exec'),scope)
    assert scope['prepare'](gate,current,0)[1]==tmp_path/api.overlay(0)

def test_four_worker_function_AST_pins_stay_unchanged():
    source=Path(runtime.uncertainty.__file__).with_name('system_campaign_financial_resume.py').read_bytes()
    expected=dict(preflight='fa2f6f19d53137596c3cc96575f19e610c32bd93bdade3dc55a48c764e1ce2b2',
        economic='cb10dbe24ce57173da398097a359f5b3418c30c68618375db6e22a269e8250f9',
        review='1306cc4b8378c3c48332fbfd625fc6d36306f1211f4032bc394f609eddc5a734',
        launch='9e6c1f8b7841c58f7e4972299bc928d170c906e0b2a44d98ceb5b9872d387b94')
    assert {n.name:data.sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(source).body
        if isinstance(n,ast.FunctionDef) and n.name in expected}==expected

def test_gate_runs_three_paused_calls_then_one_original_main_with_no_final_overlay(monkeypatch):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    raw=b'EXPLICIT_NONCANONICAL_CONTROL_METADATA_RESOURCE';calls=[];written=[]
    class MetadataPath:
        def __truediv__(self,name):return self
        def read_bytes(self):return raw
    gate=runtime.BatchGate.__new__(runtime.BatchGate)
    gate.initial={'NONCANONICAL_CONTROL_DTO':True,'sha256':'1'*64};gate.out=MetadataPath();gate.rows=[b'NONCANONICAL_CORRELATION_DTO\n']
    gate.spec={'selected_file':dict(bytes=len(raw),sha256=data.sha(raw))};gate.in_adoption=gate.started=gate.completed=False
    def original(args):calls.append(('ORIGINAL_MAIN',tuple(args)));return 0
    gate.original_main=original
    def prepare(current,index):
        calls.append(('PREPARE',index));return None,MetadataPath(),SimpleNamespace(earliest_affected_session='2099-01-02')
    gate.first=prepare(gate.initial,0);gate.prepare=prepare
    def pause(before,out,args,rows,path,earliest,directory):
        calls.append(('PAUSE',directory));gate.main(args+['--repair-overlay','NONCANONICAL_INPUT_ONLY'])
        return dict(NONCANONICAL_CONTROL_DTO=True,sha256=str(int(before['sha256'][0])+1)*64)
    monkeypatch.setattr(runtime,'adopter',lambda:pause)
    monkeypatch.setattr(runtime,'exact',lambda path,blob:written.append(blob))
    def relations(value,current,member):
        assert len(value['stages'])==3 and len(value['resources'])==22 and current['NONCANONICAL_CONTROL_DTO'] is True
        calls.append(('FULL_CHAIN_CHECK',3))
    monkeypatch.setattr(runtime,'chain_relations',relations)
    assert gate.main(['--resume'])==0 and gate.completed
    originals=[v for k,v in calls if k=='ORIGINAL_MAIN']
    assert originals==[('--resume','--repair-overlay','NONCANONICAL_INPUT_ONLY')]*3+[('--resume',)]
    assert len([v for k,v in calls if k=='PAUSE'])==3
    with pytest.raises(ValueError,match='ONE_FINAL_ORIGINAL_MAIN'):gate.main(['--resume'])

@pytest.mark.parametrize('target',['prepare','main','review_chain','preserve_chain','enter'])
def test_hosted_guard_precedes_every_actual_canonical_operation(monkeypatch,target):
    import full_system_core
    def refuse():raise ValueError('LOCAL_FINANCIAL_FORBIDDEN')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    gate=runtime.BatchGate.__new__(runtime.BatchGate)
    with pytest.raises(ValueError,match='LOCAL_FINANCIAL_FORBIDDEN'):
        if target=='prepare':gate.prepare(None,0)
        elif target=='main':gate.main([])
        elif target=='review_chain':runtime.review_chain(None,None,None,None)
        elif target=='preserve_chain':runtime.preserve_chain(None,None,None)
        else:gate.__enter__()
