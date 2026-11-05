"""Historical real-root request falsifiers; no financial engine imports."""
import ast
from copy import deepcopy
import importlib.abc
from pathlib import Path
import sys

import pytest

C=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(C))
class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas')):
            raise AssertionError('RETAINED_ADMISSION_METADATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
import system_campaign_financial_partial as p
import system_campaign_financial_uncertainty as u
import system_campaign_financial_resume as m

OLD='9524b5ab97174248bd1171b00b6e5ac667546171f176a1d2b87ecd4f8cea23b4'
NEW='6abf375981b345fcdfebc5db1f68664a1f401783a7e13f6a3cf2e9c8bd6a2a22'
PHASE=dict(completed=986,source_cursor='2021-11-30',rows=532,new_rows=148,retained_rows=384)

def request_phase(monkeypatch,spec):
    monkeypatch.setattr(m,'EXECUTION_MODE','OWN_ADMITTED_FINANCIAL_CONTINUATION')
    monkeypatch.setattr(m,'SELECTED_ARMS',('P07',))
    # Exercise this historical epoch even after the campaign has completed.
    monkeypatch.setattr(m,'COMPLETED_ADMISSIONS',{k:v for k,v in m.COMPLETED_ADMISSIONS.items()if k!='P07'})
    monkeypatch.setattr(m,'root_spec',lambda arm:spec)

def mutated_function(name,path,namespace,*,label=None,remove_hook=False):
    node=next(n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name==name)
    if label:
        calls=[n for n in ast.walk(node)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='need'
               and len(n.args)==2 and isinstance(n.args[1],ast.Constant)and n.args[1].value==label]
        assert len(calls)==1;calls[0].args[0]=ast.Constant(True)
    if remove_hook:
        hooks=[n for n in node.body if isinstance(n,ast.If)and ast.unparse(n.test)=="financial and 'P07' in SELECTED_ARMS"]
        assert len(hooks)==1;hooks[0].body=[ast.Pass()]
    copied=dict(namespace);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<single-removed-retained-admission-or-request-guard>','exec'),copied)
    return copied[name]

def test_exact_corrected_metadata_and_frozen_point_witness():
    spec=p.root_spec('P07',NEW)
    assert u.validate_retained_admission_metadata(spec)==PHASE
    assert NEW in u.POINT_RETURN_SEEDS
    assert u.POINT_WITNESS_SHA=='177d5906b9ecd6b33512999ef8408704d5814ba5f69a4d8284fb22b62b7f5cf1'


@pytest.mark.parametrize('pin,phase',[
    ('ad8b330eaed295dac664c4ea7392e8eb38956cb78765f51a2f4e05d6515a1c95',
     dict(completed=1028,source_cursor='2022-01-31',rows=574,new_rows=42,retained_rows=532)),
    ('532e1e4ca1317d3631235cb0316860112a355ab1b4cf4f61704f5583245540fd',
     dict(completed=1047,source_cursor='2022-02-28',rows=593,new_rows=19,retained_rows=574))])
def test_admitted_roots_register_the_whole_proof_and_both_seed_paths(pin,phase):
    spec=p.root_spec('P07',pin)
    assert spec['root_admission_sha256']==pin
    assert u.validate_retained_admission_metadata(spec)==phase
    assert spec['root_admission_sha256'] in u.POINT_RETURN_SEEDS

def test_real_bad_historical_root_refuses_before_host_and_hook_removal_reproduces_bug(monkeypatch):
    request_phase(monkeypatch,p.root_spec('P07',OLD))
    with pytest.raises(ValueError,match='EXACT_OWN_ADMITTED_PARENT'):m.expected_request()
    missing_hook=mutated_function('expected_request',Path(m.__file__),vars(m),remove_hook=True)
    assert missing_hook()['admitted_checkpoints']['P07']=='55174c2fd0b8737014267eb7e77a782dc1d3ba0536c8516c42c98f9a8a497956'

def test_valid_old_pin_with_stale_proof_counts_still_refuses_and_guard_removal_is_detected(monkeypatch):
    spec=p.root_spec('P07',OLD);seeds=deepcopy(u.RETAINED_PROOF_SEEDS);seeds[OLD]=PHASE
    monkeypatch.setattr(u,'RETAINED_PROOF_SEEDS',seeds);monkeypatch.setattr(u,'POINT_RETURN_SEEDS',u.POINT_RETURN_SEEDS|{OLD})
    request_phase(monkeypatch,spec)
    with pytest.raises(ValueError,match='EXACT_CURRENT_SUFFIX_PROOF_COUNTS'):m.expected_request()
    missing_guard=mutated_function('validate_retained_admission_metadata',Path(u.__file__),vars(u),
        label='FINANCIAL_RETAINED_ADMISSION_EXACT_CURRENT_SUFFIX_PROOF_COUNTS')
    assert missing_guard(spec)==PHASE

def test_missing_corrected_point_registration_refuses_and_guard_removal_is_detected(monkeypatch):
    spec=p.root_spec('P07',NEW);monkeypatch.setattr(u,'POINT_RETURN_SEEDS',u.POINT_RETURN_SEEDS-{NEW})
    request_phase(monkeypatch,spec)
    with pytest.raises(ValueError,match='EXACT_POINT_RETURN_REGISTRATION'):m.expected_request()
    missing_guard=mutated_function('validate_retained_admission_metadata',Path(u.__file__),vars(u),
        label='FINANCIAL_RETAINED_ADMISSION_EXACT_POINT_RETURN_REGISTRATION')
    assert missing_guard(spec)==PHASE
