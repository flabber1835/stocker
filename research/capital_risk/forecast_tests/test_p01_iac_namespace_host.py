"""Source-bound new namespace host/worker contracts; no canonical APIs."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
import pytest
import yaml
HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_namespace_job as job
import p01_iac_namespace_export as export
import p01_iac_reference_evidence as evidence
import p01_iac_unit_contract as contract


def old_case(name):
    path=HERE/'forecast_tests/test_p01_iac_reference_host.py'
    assert job.sha256_file(path)=='9e88a5e463aa35c3040e0fd925e5f52e98ab40cb92b018b46b41b0c26962a809'
    spec=importlib.util.spec_from_file_location('frozen_reference_host_fixtures',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    wanted={name,'proof','populate_q15','successful_snapshot_fixture','old_fixture'}
    nodes=[n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in wanted]
    for n in nodes:n.decorator_list=[]
    class Namespace(ast.NodeTransformer):
        def visit_Constant(self,n):
            if type(n.value) is str:n.value=n.value.replace('p01-iac-reference','p01-iac-namespace').replace('p01-own628-iac-reference','p01-own628-iac-namespace').replace('p01_iac_reference_run.py','p01_iac_namespace_run.py')
            return n
    ns=dict(vars(module),job=job,export=export,evidence=evidence)
    exec(compile(ast.fix_missing_locations(Namespace().visit(ast.Module(body=nodes,type_ignores=[]))),'<pinned-fixtures-new-namespace>','exec'),ns)
    return ns[name]


@pytest.fixture
def flat(tmp_path,monkeypatch):
    folder=tmp_path/'driver';folder.mkdir()
    for name in job.SOURCES:(folder/name).write_bytes((HERE/name).read_bytes())
    (folder/'system-campaign-search-protocol.json').write_bytes((HERE/'system-campaign-search-protocol.json').read_bytes())
    seen=set()
    def patch(module):
        if id(module) in seen:return
        seen.add(id(module))
        if hasattr(module,'HERE'):monkeypatch.setattr(module,'HERE',folder)
        for key in ('previous','predecessor'):
            child=getattr(module,key,None)
            if isinstance(child,ModuleType):patch(child)
    patch(job);patch(evidence);patch(contract)
    value=job.expected_request();path=folder/job.REQUEST;path.write_bytes(job.encoded_request(value))
    return folder,path,value


def test_actual_flat_new_and_prior_whole_closures_without_workflow_lookup(flat):
    folder,path,value=flat;prior=json.loads((folder/job.PRIOR_REQUEST).read_bytes())
    assert len(prior['sources'])==509 and prior['sources']=={k:value['sources'][k] for k in prior['sources']}
    assert set(value['sources'])==set(prior['sources'])|{job.PRIOR_REQUEST}|set(job.NEW)
    assert not (folder.parents[1]/'.github/workflows').exists()
    assert job.validate_worker_request(path,mode='qualify')==value
    assert value['actual_entrypoint']=='/driver/p01_iac_namespace_run.py'
    assert value['input_document_sha256']==prior['input_document_sha256'] and value['successor_input_sha256']==prior['successor_input_sha256']
    assert value['namespace_failure_run_id']==41481585931


@pytest.mark.parametrize('kind',['newsource','oldsource','priorrequest','newmodel','rawcopy','crlf'])
def test_new_flat_identity_refuses_wrong_source_model_and_rawcopy(kind,flat,monkeypatch):
    folder,path,value=flat
    if kind=='newsource':(folder/'p01_iac_namespace_run.py').write_bytes(b'changed')
    if kind=='oldsource':(folder/'p01_iac_reference_run.py').write_bytes(b'changed')
    if kind=='priorrequest':(folder/job.PRIOR_REQUEST).write_bytes(b'{}')
    if kind=='newmodel':
        wrong=deepcopy(value);wrong['generated_nested_global_resolution_required']=False;path.write_bytes(job.encoded_request(wrong))
    if kind=='crlf':path.write_bytes(path.read_bytes().replace(b'\n',b'\r\n'))
    if kind=='rawcopy':
        copy=folder/'copy.json';copy.write_bytes(b'changed');monkeypatch.setattr(job,'_worker_copy',lambda mode:copy)
    with pytest.raises(ValueError):job.validate_worker_request(path,mode='economic' if kind=='rawcopy' else 'qualify')


def test_economic_and_review_require_same_entire_new_raw_request(flat,monkeypatch):
    folder,path,value=flat;copy=folder/'copy.json';copy.write_bytes(path.read_bytes());monkeypatch.setattr(job,'_worker_copy',lambda mode:copy)
    assert job.validate_worker_request(path,mode='economic')==job.validate_worker_request(path,mode='review')==value


def test_actual_new_request_guard_removal_falsifier(flat):
    folder,path,value=flat
    old_case('test_new_request_whole_model_predicate_removal_falsifier')((folder,value))


def test_actual_three_commands_use_new_entrypoint_eight_fenced_mounts(monkeypatch):
    old_case('test_exact_new_entrypoints_mounts_and_source_bound_inspector')(monkeypatch)


@pytest.mark.parametrize('role',['qualify','worker','review'])
def test_actual_new_inspection_entrypoint_and_ro_evidence(role,tmp_path,monkeypatch):
    old_case('test_actual_inspection_receipt_new_namespace_modes_and_ro_falsifiers')(tmp_path,monkeypatch,role)


@pytest.mark.parametrize('failure',['none','qualify_unknown','qualify_refused','finance_unknown','review_unknown'])
def test_actual_source_bound_main_marker_qcipher_fresh_finance_order(failure,tmp_path,monkeypatch):
    old_case('test_same_proven_source_bound_main_ordering_in_new_namespace')(tmp_path,monkeypatch,failure)


def test_actual_new_synthetic_marker_crypto_stage(tmp_path,monkeypatch):
    old_case('test_actual_synthetic_new_marker_crypto_and_namespace')(tmp_path,monkeypatch)


def test_actual_q15_snapshot_crypto_original_retained(tmp_path,monkeypatch):
    old_case('test_actual_frozen_q_inventory_refuses_progress_and_new_exact_snapshot_seals15')(tmp_path,monkeypatch)


def test_new_public_allowlist_scalar_values(tmp_path):
    old_case('test_new_public_export_scalar_allowlist_conformance')(tmp_path)


def test_new_export_ast_exact_except_public_namespace_literals():
    old=ast.parse((HERE/'p01_iac_reference_export.py').read_bytes());new=ast.parse(Path(export.__file__).read_bytes())
    class Reverse(ast.NodeTransformer):
        def visit_Constant(self,n):
            if type(n.value) is str:n.value=n.value.replace('p01-iac-namespace','p01-iac-reference').replace('p01-own628-iac-namespace','p01-own628-iac-reference')
            return n
    assert ast.dump(Reverse().visit(new),include_attributes=False)==ast.dump(old,include_attributes=False)
    assert export.RECEIPT_SCHEMA=='research.p01-own628-iac-namespace-receipt/1'


def test_new_workflow_exact_request_only_sourcepin_and_every_step_budget():
    path=HERE.parents[1]/'.github/workflows'/job.WORKFLOW;assert job.sha256_file(path)==job.WORKFLOW_SHA
    value=yaml.safe_load(path.read_bytes());trigger=value.get('on',value.get(True))
    assert trigger['push']['paths']==['research/capital_risk/'+job.REQUEST]
    assert value['concurrency']['cancel-in-progress'] is False
    worker=value['jobs']['iac-namespace'];steps=worker['steps']
    assert [s['timeout-minutes'] for s in steps]==[3,3,4,2,8,210,5]
    assert sum(s['timeout-minutes'] for s in steps)<=worker['timeout-minutes']-5
    wrong=deepcopy(steps);del wrong[-1]['timeout-minutes']
    with pytest.raises(KeyError):sum(s['timeout-minutes'] for s in wrong)
