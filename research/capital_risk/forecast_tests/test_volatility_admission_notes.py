"""Exact host-only observation successor and public-value omission falsifier."""
import ast,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from system_campaign_parallel_discovery import compile_body
import system_campaign_volatility_admission_recovery as change


def environment(monkeypatch,tmp_path):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path))
    monkeypatch.setattr(change,'memory_bytes',lambda:{'MemAvailable':12*1024**3})


def test_only_host_observation_statements_change_original_control_flow():
    before=change.previous.orchestration_tree();after=change.tree()
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,n):
            if isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='note':return None
            return self.generic_visit(n)
        def visit_ExceptHandler(self,n):
            if n.name=='admission_error':n.name=None
            return self.generic_visit(n)
    assert ast.dump(before)==ast.dump(ast.fix_missing_locations(Remove().visit(after)))
    value=change.expected_request()
    assert len(value['sources'])==418 and value['arms']==['P11']
    assert value['other_P10_job_unchanged'] and value['initial_min_disk_bytes']==12*1024**3


def test_atomic_note_preserves_phase_and_excludes_exception_value(tmp_path,monkeypatch):
    environment(monkeypatch,tmp_path);p=tmp_path/'phase.json'
    change.note(p,'BEFORE_STRICT_PARENT_FETCH')
    change.note(p,'FAILURE',ValueError('PRIVATE_FINANCIAL_PAYLOAD_12345'))
    raw=p.read_bytes();value=json.loads(raw)
    assert b'PRIVATE_FINANCIAL_PAYLOAD' not in raw and value['invariant_code'] is None
    assert value['previous_stage']=='BEFORE_STRICT_PARENT_FETCH' and value['exception_class']=='ValueError'
    assert not p.with_suffix('.pending').exists()
    with pytest.raises(ValueError,match='PHASE_ALLOWLIST'):change.note(p,'PRIVATE_STAGE')


def test_static_capacity_invariant_is_explicit_without_weakening_gate(tmp_path,monkeypatch):
    environment(monkeypatch,tmp_path);p=tmp_path/'phase.json'
    code='REFUSED_FULL_SYSTEM_PARALLEL_INITIAL_DISK_RESERVE'
    change.note(p,'FAILURE',ValueError(code))
    assert json.loads(p.read_bytes())['invariant_code']==code


def test_actual_public_exception_omission_guard_removal_falsifier(tmp_path,monkeypatch):
    environment(monkeypatch,tmp_path)
    fn,=[n for n in ast.parse(Path(change.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='note']
    value,=[n for n in ast.walk(fn) if isinstance(n,ast.keyword) and n.arg=='invariant_code']
    assert isinstance(value.value,ast.IfExp)
    value.value=value.value.body
    mutant=compile_body(fn,vars(change));p=tmp_path/'removed.json'
    mutant(p,'FAILURE',ValueError('PRIVATE_FINANCIAL_PAYLOAD_12345'))
    assert b'PRIVATE_FINANCIAL_PAYLOAD_12345' in p.read_bytes()
