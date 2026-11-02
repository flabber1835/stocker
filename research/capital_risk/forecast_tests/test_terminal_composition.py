"""Synthetic own-boundary factual composition; no historical execution."""
import ast,copy
from pathlib import Path
import pytest
from system_campaign_terminal_run import merge_future_documents


def documents():
    base=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='a'*64,
        source_evidence=[],suppress=[],add=[])
    prior=copy.deepcopy(base);prior['add']=[dict(session='2020-01-02',security_id='OLD')]
    new=copy.deepcopy(base);new['add']=[dict(session='2020-01-03',security_id='NEW')]
    return new,prior


def test_merge_preserves_both_component_documents_and_reference_identity():
    new,prior=documents();saved=copy.deepcopy((new,prior));result=merge_future_documents(new,prior)
    assert result['add']==prior['add']+new['add'] and (new,prior)==saved
    result['add'][0]['security_id']='MUTATED'
    assert (new,prior)==saved


def test_wrong_own_boundary_and_duplicate_fact_are_refused():
    new,prior=documents();prior['predecessor_checkpoint_sha256']='b'*64
    with pytest.raises(ValueError,match='SAME_OWN_PREDECESSOR'):merge_future_documents(new,prior)
    prior['predecessor_checkpoint_sha256']='a'*64;new['add']=copy.deepcopy(prior['add'])
    with pytest.raises(ValueError,match='NO_DUPLICATE_FACTS'):merge_future_documents(new,prior)


def test_actual_boundary_guard_removal_falsifier():
    new,prior=documents();prior['predecessor_checkpoint_sha256']='b'*64
    tree=ast.parse(Path(merge_future_documents.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='merge_future_documents')
    node.body.pop(0);scope=dict(merge_future_documents.__globals__)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<removed-composition-boundary>','exec'),scope)
    assert scope['merge_future_documents'](new,prior)['predecessor_checkpoint_sha256']=='a'*64
