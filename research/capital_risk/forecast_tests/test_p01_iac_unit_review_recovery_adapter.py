"""Actual source-selected exclusive-save fault/fix; no financial execution."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_unit_review_recovery_adapter as adapter


def result():
    return dict(schema='research.p01-iac-unit-suffix-review/1',status='IAC_UNIT_ACTUAL_COMMITTED_SUFFIX_REVIEWED_PENDING_CLIENT',
        financial_predecessor_admitted=False,qualification_state_adopted=False,synthetic_test_only=True,
        unchanged_scalar='0x1.0000000000001p+0')


def source_tail(node):
    # Preserve the actual local import, save call and return from the frozen
    # complete reviewer. Its financial prefix is replaced by supplied inert data.
    imported=next(n for n in node.body if isinstance(n,ast.ImportFrom) and any(x.asname=='save' or x.name=='save' for x in n.names))
    saved=next(n for n in node.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and isinstance(n.value.func,ast.Name) and n.value.func.id=='save')
    returned=next(n for n in node.body if isinstance(n,ast.Return))
    fn=ast.FunctionDef(name='tail',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg='out'),ast.arg(arg='result')],
        vararg=None,kwonlyargs=[],kw_defaults=[],kwarg=None,defaults=[]),body=deepcopy([imported,saved,returned]),decorator_list=[])
    ns={};exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-save-callsite-only>','exec'),ns)
    return ns['tail']


def test_published_wrapper_reproduces_file_exists_after_original_actual_single_save(tmp_path,monkeypatch):
    import full_system_benchmark
    original=full_system_benchmark.save;calls=[]
    def counted(path,value):calls.append(path);return original(path,value)
    monkeypatch.setattr(full_system_benchmark,'save',counted)
    tail=source_tail(adapter.previous._node('review_loaded'))
    monkeypatch.setattr(adapter.previous,'_body',lambda name:lambda *a,**kw:tail(a[1],a[0]))
    with pytest.raises(FileExistsError):adapter.previous.review_loaded(result(),tmp_path,None)
    saved=json.loads((tmp_path/'iac-unit-financial-review.json').read_bytes())
    assert len(calls)==2 and saved['unchanged_scalar']=='0x1.0000000000001p+0' and 'fixture_review' not in saved


def test_new_actual_callsite_creates_once_with_full_metadata_and_unchanged_values(tmp_path,monkeypatch):
    import full_system_benchmark
    original=full_system_benchmark.save;calls=[]
    def counted(path,value):calls.append(path);return original(path,value)
    monkeypatch.setattr(full_system_benchmark,'save',counted)
    tail=source_tail(adapter._node('review_loaded'))
    monkeypatch.setattr(adapter,'_body',lambda name:lambda *a,**kw:tail(a[1],a[0]))
    raw=result();expected=deepcopy(raw);actual=adapter.review_loaded(raw,tmp_path,None)
    saved=json.loads((tmp_path/'iac-unit-financial-review.json').read_bytes())
    assert len(calls)==1 and actual==saved
    assert {k:v for k,v in saved.items() if k not in ('fixture_review','review_recovery')}==expected
    assert saved['fixture_review']['fixture_review_sha256']==adapter.FIXTURE_REVIEW_SHA
    assert saved['review_recovery']['financial_sessions_advanced']==0
    assert saved['review_recovery']['adapter_source_sha256']==adapter.sha(Path(adapter.__file__).read_bytes())


def test_save_import_rewrite_removal_loses_required_recovery_metadata_falsifier(tmp_path):
    old=source_tail(adapter.previous._node('review_loaded'));raw=result();old(tmp_path,raw)
    saved=json.loads((tmp_path/'iac-unit-financial-review.json').read_bytes())
    assert 'review_recovery' not in saved
    with pytest.raises(AssertionError):assert 'review_recovery' in saved


@pytest.mark.parametrize('kind',['schema','status','admitted','adopted','existing_metadata','wrong_path'])
def test_report_gate_refuses_before_new_file(kind,tmp_path):
    value=result();path=tmp_path/'iac-unit-financial-review.json'
    if kind=='schema':value['schema']='wrong'
    if kind=='status':value['status']='wrong'
    if kind=='admitted':value['financial_predecessor_admitted']=True
    if kind=='adopted':value['qualification_state_adopted']=True
    if kind=='existing_metadata':value['review_recovery']={}
    if kind=='wrong_path':path=tmp_path/'other.json'
    with pytest.raises(ValueError):adapter.save_review(path,value)
    assert not path.exists()


def test_existing_report_is_never_overwritten(tmp_path):
    path=tmp_path/'iac-unit-financial-review.json';path.write_bytes(b'original immutable report')
    with pytest.raises(FileExistsError):adapter.save_review(path,result())
    assert path.read_bytes()==b'original immutable report'


def test_exact_two_source_nodes_only_one_save_import_change_and_no_outer_save():
    assert ast.dump(adapter._node('review'),include_attributes=False)==ast.dump(adapter.previous._node('review'),include_attributes=False)
    node=adapter._node('review_loaded');imports=[]
    for item in ast.walk(node):
        if isinstance(item,ast.ImportFrom) and item.module=='p01_iac_unit_review_recovery_adapter':
            assert [(a.name,a.asname) for a in item.names]==[('save_review','save')]
            item.module='full_system_benchmark';item.names=[ast.alias(name='save',asname=None)];imports.append(item)
    assert len(imports)==1 and ast.dump(node,include_attributes=False)==ast.dump(adapter.previous._node('review_loaded'),include_attributes=False)
    tree=ast.parse(Path(adapter.__file__).read_bytes());outer=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='review_loaded')
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('save','save_review') for n in ast.walk(outer))
    assert callable(adapter._body('review')) and callable(adapter._body('review_loaded'))


def test_source_hash_mismatch_refuses_before_compiling_old_review(monkeypatch):
    monkeypatch.setattr(adapter,'FIXTURE_REVIEW_SHA','0'*64)
    monkeypatch.setattr(adapter.previous,'_node',lambda name:pytest.fail('compiled before exact source pin'))
    with pytest.raises(ValueError):adapter._node('review_loaded')
