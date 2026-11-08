"""Producer contract stubs only; no financial runtime is imported or advanced."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys

import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_unit_run as run
from p01_iac_unit_export import QUALIFICATION_FILES,qualification


def branch_value():
    return dict(zero=dict(input_checkpoint={'sha256':'a'*64},input_document_sha256='b'*64,
        successor_input_sha256='c'*64),preflight={},components=[{'session':d,'opaque':{'preserve':True}} for d in run.FIRST],
        roles=[{'session':d,'opaque_full_state_check':True} for d in run.FIRST],final={'opaque':{'preserve':True}},report={},
        codec_applications=[],codec_refusals=[],origin={},contract={},action_checks=[],native_checks=[],source_checks=[],
        unit_checks=[],pre_events=[],reused={},component=dict(normalizer_qualified=True,
        unit_target_independence_qualified=True,source_scope_falsifiers_qualified=True))


def stub_branch(monkeypatch,*,mutate=False):
    def branch(old,out,rows,mode,**kwargs):
        out.mkdir(parents=True)
        for name in ('zero-session-boundaries.json','iac-unit-input.json','iac-unit-preflight.json'):
            (out/name).write_bytes(b'{}\n')
        value=branch_value()
        if mode=='REFERENCE':
            (kwargs['proof_dir']/'unit-normalization-component.json.gz').write_bytes(gzip.compress(b'{}',mtime=0))
        elif mutate:value['components'][-1]['opaque']['new_field_must_not_be_excluded']=True
        return value
    monkeypatch.setattr(run,'branch',branch);monkeypatch.setattr(run,'source_rows',lambda:([],{}))


def test_q14_member_contract_count_and_private_full_role_records(tmp_path,monkeypatch):
    stub_branch(monkeypatch);run.qualify(tmp_path/'old',tmp_path)
    proof=tmp_path/'proof';assert {p.name for p in proof.iterdir()}==set(QUALIFICATION_FILES)
    summary=json.loads((proof/'qualification-summary.json').read_bytes())
    assert type(summary['actual_role_and_full_state_checks']) is int and summary['actual_role_and_full_state_checks']==2
    assert summary['actual_role_and_full_state_records']==branch_value()['roles']
    qualification(summary)
    component=json.loads(gzip.decompress((proof/'actual-two-session-component.json.gz').read_bytes()))
    assert component['reference_components']==component['actual_components']
    assert len(component)==12 and component['financial_authority'] is False


def test_no_reference_fast_full_field_exclusion_can_create_qualified_summary(tmp_path,monkeypatch):
    stub_branch(monkeypatch,mutate=True)
    with pytest.raises(ValueError,match='WHOLE_REFERENCE_FAST'):run.qualify(tmp_path/'old',tmp_path)
    assert not (tmp_path/'proof/qualification-summary.json').exists()


def test_last_attempt_binds_only_real_latest_records_without_failure_inference():
    applied=[dict(session='2020-07-01',raw_source='synthetic'),dict(session='2020-07-02',raw_source='synthetic2')]
    prepared=[dict(session='2020-07-01',prepared=True)]
    marker=run.last_attempt(applied,[],prepared,[])
    assert marker==dict(schema='research.p01-iac-unit-last-observed-attempt/1',session='2020-07-02',
        financial_authority=False,codec_application_sha256=run.digest(applied[-1]),codec_refusal_sha256=None,
        prepared_window_sha256=None,guard_refusal_sha256=None)
    assert run.last_attempt([],[],[],[]) is None
    assert 'failure_cause' not in marker and 'committed' not in marker


def test_qualifier_component_uses_actual_first_day_clock_before_fresh_fast():
    import ast
    tree=ast.parse(Path(run.__file__).read_bytes())
    branch=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='branch')
    calls=[n for n in ast.walk(branch) if isinstance(n,ast.Call)]
    component=next(n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='qualify_components')
    actual=next(n for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=='main')
    assert actual.lineno<component.lineno
    assert any(k.arg=='post_event_state' and ast.unparse(k.value)=='first.state' for k in component.keywords)
    qualify=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualify')
    modes=[n.args[3].value for n in ast.walk(qualify) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
        and n.func.id=='branch']
    assert modes==['REFERENCE','FAST']
