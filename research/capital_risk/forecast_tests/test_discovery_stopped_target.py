"""Review-target separation and source/stub guards, never a Core replay."""
import ast
from copy import deepcopy
import importlib.abc
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_discovery_suffix_job as job
import system_campaign_discovery_suffix_parent as parent
import system_campaign_discovery_suffix_run as run


def test_request_binds_distinct_admitted404_and_unadmitted420_review_only():
    request=job.expected_request();spec=parent.specification('P10');target=parent.specification('P10',role='review_target')
    assert spec['transitions']==404 and target['transitions']==420 and target['next_session']=='2020-10-01'
    assert target['transport_only'] and not target['admitted_diagnostic_prefix']
    assert request['modes']['P10']=='review' and not request['discovery_forward_sessions_authorized']['P10']
    assert request['review_targets']['P10']==target
    assert target['input_descriptors']==spec['input_descriptors'] and target['diagnostic_input_epoch']==spec['diagnostic_input_epoch']


def test_review_only_rejects_forward_mode_before_any_private_import(tmp_path,monkeypatch):
    request=tmp_path/'request.json';request.write_text(json.dumps(job.expected_request()))
    monkeypatch.setattr(run,'hosted',lambda:None)
    class NoPrivate(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname.startswith(('research.pooled_','stock_strategy_shared')):raise AssertionError('PRIVATE_IMPORT_FORBIDDEN')
    fence=NoPrivate();sys.meta_path.insert(0,fence)
    try:
        with pytest.raises(ValueError,match='REVIEW_ONLY_SELECTION_FORBIDS_FORWARD'):
            run.main(SimpleNamespace(arm='P10',mode='discovery',request=request,spec=tmp_path/'ABSENT'))
    finally:sys.meta_path.remove(fence)


def test_actual_forward_guard_falsifier_discriminates_removed_gates():
    request=dict(modes={'P10':'review'},discovery_forward_sessions_authorized={'P10':False})
    with pytest.raises(ValueError):run.require_mode(request,'P10','discovery')
    fn,=[n for n in ast.parse(Path(run.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='require_mode']
    fn.body=[n for n in fn.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and len(n.value.args)==2 and isinstance(n.value.args[1],ast.Constant)
        and n.value.args[1].value in {'SUFFIX_REVIEW_ONLY_SELECTION_FORBIDS_FORWARD_DISCOVERY','SUFFIX_EXPLICIT_FORWARD_DISCOVERY_AUTHORITY'})]
    scope=dict(vars(run));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<role-guard-removal-pure-metadata>','exec'),scope)
    assert scope['require_mode'](request,'P10','discovery') is None


def test_unadmitted_target_cannot_be_selected_by_wrong_role(tmp_path,monkeypatch):
    meta=json.loads((parent.HERE/parent.REMAINING_SPEC).read_bytes())
    meta['review_targets']['P10']['transport_only']=False
    (tmp_path/parent.REMAINING_SPEC).write_text(json.dumps(meta));monkeypatch.setattr(parent,'HERE',tmp_path)
    with pytest.raises(ValueError,match='TARGET_NOT_ADMITTED_AS_PARENT'):parent.specification('P10',role='review_target')


def test_review_branch_exits_before_discovery_launch_and_targets_are_readonly():
    fn,=[n for n in ast.parse(Path(job.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='main']
    branch,=[n for n in ast.walk(fn) if isinstance(n,ast.If) and ast.unparse(n.test)=='evidence is not None'
             and any(isinstance(x,ast.Raise) for x in n.body)]
    text=ast.unparse(branch)
    assert "worker_command(name, arm, source, frozen, out, old, previous, evidence=evidence)" in text
    assert 'qualification(' not in text and 'raise SystemExit' in text
    assert 'finish_export(' in text
    assert 'readonly' in str(job.worker_command.__code__.co_consts)
