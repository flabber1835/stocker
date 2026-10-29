"""Synthetic pinned-member extraction boundary; no artifact/network execution."""
import ast,re
from pathlib import Path
import pytest


def function():
    raw=Path(__file__).parents[1]/'system_campaign_diagnostic_job.py'
    node=next(n for n in ast.parse(raw.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='selected_members')
    def need(ok,code):
        if not ok:raise ValueError(code)
    namespace={'re':re,'need':need}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-diagnostic-member-guard>','exec'),namespace)
    return namespace['selected_members'],node,namespace


def test_exact_pinned_checkpoint_and_hash_guard_removal_falsifier():
    check,node,namespace=function();name='book/pre-event/2017-07-18-'+'a'*64+'.json.gz'
    spec={'selected_members':{name:{'bytes':123,'sha256':'b'*64}}}
    assert check(spec,spec['selected_members'])==spec['selected_members']
    wrong={name:{'bytes':124,'sha256':'c'*64}}
    with pytest.raises(ValueError,match='PINNED_PRE_EVENT'):check(spec,wrong)
    guard=next(n for n in node.body if isinstance(n,ast.If))
    node.body.remove(guard)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<removed-member-binding-guard>','exec'),namespace)
    assert namespace['selected_members'](spec,wrong)==spec['selected_members']


@pytest.mark.parametrize('name',('../book/checkpoint.json.gz','/book/predecessor-checkpoints/x.json.gz',
    'book/pre-event/2027-07-18.json.gz','book/formation.jsonl','../source-bindings.json'))
def test_arbitrary_or_future_members_are_refused(name):
    check,_,_=function()
    with pytest.raises(ValueError,match='EXACT_PRE_EVENT'):
        check({'selected_members':{name:{'bytes':1,'sha256':'b'*64}}})
