"""Exact stopped-report metadata only; no financial payload or execution."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_namespace_review_recovery as adapter


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def toy():
    ids=[sid+'/'+role for sid in ('517224929580411308','369995575874917058')
         for role in ('HELD','CLOSE_PENDING','DOLLAR_BUY_PENDING','EXIT_FLAG_ONLY')]+['POST_EVENT_SOURCE_BUY']
    value=dict(target_cases={case:dict(before={'toy_case':case,'number':1},actual={'toy_case':case,'number':2}) for case in ids[:-1]},
        fixture_aggregate=dict(expected_case_ids=ids),post_event_new_unit_case=dict(before={'toy_post':1},after={'toy_post':2}))
    return json.loads(json.dumps(value,sort_keys=True))


def boundary(component):
    zero=dict(epoch_checkpoint=dict(run={'toy_epoch':1}),input_checkpoint=dict(run={'toy_input':1}))
    paths=[dict(session=day,prior_checkpoint={'toy_prior':day},checkpoint={'toy_after':day}) for day in ('2020-07-01','2020-07-02')]
    q=dict(reference_qualifier_checkpoint=dict(run={'toy_final':1}))
    labels=[dict(label=name,runtime_sha256=digest(value)) for name,value in [
        ('old-epoch-zero',zero['epoch_checkpoint']['run']),('old-input-zero',zero['input_checkpoint']['run']),
        *[(f'old-reference/{r["session"]}/{k}',r[k]) for r in paths for k in ('prior_checkpoint','checkpoint')],
        ('old-reference-final',q['reference_qualifier_checkpoint']['run'])]]
    labels.extend(dict(label='old-synthetic/'+str(i),state_sha256=digest(wire)) for i,wire in enumerate(adapter.producer_wires(component)))
    return zero,paths,q,labels


def predicate(node):
    start=next(i for i,n in enumerate(node.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='labels' for t in n.targets))
    end=next(i for i,n in enumerate(node.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value=='REFERENCE_REVIEW_ALL_25_SOURCE_BOUND_NEW_RESTORE_LABELS_AND_ENTIRE_HASHES' for a in n.value.args))
    body=[deepcopy(n) for n in node.body[start:end+1]
        if not (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='component' for t in n.targets))]
    fn=ast.FunctionDef(name='check',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg=n) for n in ('zero','paths','q','component','check')],
        kwonlyargs=[],kw_defaults=[],defaults=[]),body=body,decorator_list=[])
    namespace=dict(digest=digest,producer_wires=adapter.producer_wires,same=lambda a,b:json.dumps(a,sort_keys=True)==json.dumps(b,sort_keys=True),
        need=lambda ok,code:None if ok else (_ for _ in ()).throw(ValueError(code)))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-ordered-restore-predicate>','exec'),namespace)
    return namespace['check']


def old_node():return next(n for n in ast.parse(adapter._raw()).body if isinstance(n,ast.FunctionDef) and n.name=='validate_reuse')


def test_actual_published_predicate_refuses_and_new_actual_predicate_accepts_producer_order():
    component=toy();zero,paths,q,labels=boundary(component);check=dict(canonical_restores=dict(checked=labels))
    with pytest.raises(ValueError,match='ALL_25'):predicate(old_node())(zero,paths,q,component,check)
    predicate(adapter._metadata_node('validate_reuse'))(zero,paths,q,component,check)


@pytest.mark.parametrize('kind',('missing_wire','wire_order','wire_hash','wire_type','record_label','runtime_hash'))
def test_exact_order_count_labels_and_full_hashes_remain_required(kind):
    component=toy();zero,paths,q,labels=boundary(component);check=dict(canonical_restores=dict(checked=deepcopy(labels)))
    if kind=='missing_wire':component['target_cases'].pop(next(iter(component['target_cases'])))
    if kind=='wire_order':component['target_cases']=dict(reversed(list(component['target_cases'].items())))
    if kind=='wire_hash':component['target_cases'][next(iter(component['target_cases']))]['before']['number']=3
    if kind=='wire_type':component['target_cases'][next(iter(component['target_cases']))]['before']['number']=1.0
    if kind=='record_label':check['canonical_restores']['checked'][7]['label']='old-synthetic/99'
    if kind=='runtime_hash':check['canonical_restores']['checked'][0]['runtime_sha256']='0'*64
    with pytest.raises(ValueError,match='ALL_25'):predicate(adapter._metadata_node('validate_reuse'))(zero,paths,q,component,check)


def test_metadata_full_ast_reversal_only_affected_collector_and_existing_namespace_literal():
    old=old_node();new=adapter._metadata_node('validate_reuse')
    old_loop=next(n for n in old.body if isinstance(n,ast.For) and ast.unparse(n.target)=='case')
    class Reverse(ast.NodeTransformer):
        def visit_Constant(self,item):
            if item.value=='p01_iac_namespace_request.json':item.value='p01_iac_reference_request.json'
            return item
        def visit_Assign(self,item):
            if isinstance(item.value,ast.Call) and isinstance(item.value.func,ast.Name) and item.value.func.id=='producer_wires':
                return deepcopy(old_loop)
            return self.generic_visit(item)
    assert ast.dump(Reverse().visit(new),include_attributes=False)==ast.dump(old,include_attributes=False)
    original_save=next(n for n in ast.parse(adapter._raw()).body if isinstance(n,ast.FunctionDef) and n.name=='save_review')
    assert ast.dump(adapter._metadata_node('save_review'),include_attributes=False)==ast.dump(original_save,include_attributes=False)


def test_entire_review_function_asts_keep_every_other_statement():
    for name in ('review','review_loaded'):
        node=adapter._node(name)
        class Reverse(ast.NodeTransformer):
            def visit_ImportFrom(self,item):
                if item.module=='p01_iac_namespace_review_recovery':item.module='p01_iac_namespace_review'
                return item
        assert ast.dump(Reverse().visit(node),include_attributes=False)==ast.dump(adapter.previous._node(name),include_attributes=False)
    assert adapter._metadata('validate_reuse').__globals__['producer_wires'] is adapter.producer_wires


def tail(node):
    imported=next(n for n in node.body if isinstance(n,ast.ImportFrom) and any(x.asname=='save' or x.name=='save' for x in n.names))
    saved=next(n for n in node.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='save')
    returned=next(n for n in node.body if isinstance(n,ast.Return))
    fn=ast.FunctionDef(name='tail',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg='out'),ast.arg(arg='result')],kwonlyargs=[],kw_defaults=[],defaults=[]),
        body=deepcopy([imported,saved,returned]),decorator_list=[])
    namespace={};exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-report-save-tail-only>','exec'),namespace)
    return namespace['tail']


def result():return dict(schema='research.p01-iac-unit-suffix-review/1',status='IAC_UNIT_ACTUAL_COMMITTED_SUFFIX_REVIEWED_PENDING_CLIENT',
    financial_predecessor_admitted=False,qualification_state_adopted=False,synthetic_only='preserve me')


def test_actual_nested_single_save_dispatch_creates_once_and_preserves_all_values(tmp_path,monkeypatch):
    import full_system_benchmark
    original=full_system_benchmark.save;calls=[]
    def counted(path,value):calls.append(path);return original(path,value)
    monkeypatch.setattr(full_system_benchmark,'save',counted)
    monkeypatch.setattr(adapter,'validate_reuse',lambda evidence:dict(synthetic_only=True,ordered_records=25))
    raw=result();expected=deepcopy(raw);actual=tail(adapter._node('review_loaded'))(tmp_path,raw)
    saved=json.loads((tmp_path/'iac-unit-financial-review.json').read_bytes())
    assert len(calls)==1 and saved==actual
    for k,v in expected.items():assert saved[k]==v
    assert saved['reference_reuse_review']==dict(synthetic_only=True,ordered_records=25)
    assert saved['restore_label_order_review']['adapter_source_sha256']==adapter.sha(Path(adapter.__file__).read_bytes())
    assert saved['review_recovery']['correction']=='METADATA_BEFORE_ORIGINAL_SINGLE_EXCLUSIVE_CREATE'
    with pytest.raises(ValueError):adapter.save_review(tmp_path/'iac-unit-financial-review.json',raw)
    assert len(calls)==1


def test_failed_affected_predicate_prevents_any_file_create(tmp_path,monkeypatch):
    def refuse(evidence):raise ValueError('ORDERED_HASH_REFUSAL')
    monkeypatch.setattr(adapter,'validate_reuse',refuse)
    with pytest.raises(ValueError,match='ORDERED_HASH_REFUSAL'):tail(adapter._node('review_loaded'))(tmp_path,result())
    assert not (tmp_path/'iac-unit-financial-review.json').exists()


def test_whole_source_pin_failure_precedes_compilation(monkeypatch):
    monkeypatch.setattr(adapter,'REFERENCE_SHA','0'*64)
    with pytest.raises(ValueError,match='EXACT_PUBLISHED515'):adapter._node('review_loaded')


def test_real_factories_metadata_only_under_financial_import_fence():
    script=r'''
import sys,importlib.abc
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='sentinel' or fullname.startswith(('sentinel.','stock_strategy_shared','research.pooled_','research.bounded_')):
   raise AssertionError('LOCAL_FINANCIAL_IMPORT_FORBIDDEN:'+fullname)
sys.meta_path.insert(0,Fence())
import p01_iac_namespace_review_recovery as a
for name in ('review','review_loaded'):assert a._body(name).__name__==name
for name in ('validate_reuse','save_review'):assert a._metadata(name).__name__==name
assert a.producer_wires({'target_cases':{},'post_event_new_unit_case':{'before':{},'after':{}}})==[{},{}]
print('FOUR_REAL_FACTORIES_AND_ORDER_HELPER_FENCED')
'''
    done=subprocess.run([sys.executable,'-B','-c',script],cwd=HERE,text=True,capture_output=True)
    assert done.returncode==0,done.stderr
    assert done.stdout.strip()=='FOUR_REAL_FACTORIES_AND_ORDER_HELPER_FENCED'
