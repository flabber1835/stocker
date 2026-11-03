"""Only host/request orchestration; no local financial or cleanup execution."""
import ast
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import system_campaign_volatility_capacity_job as job
from system_campaign_parallel_discovery import compile_body


def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_WORKSPACE',str(tmp_path))
    monkeypatch.setenv('GITHUB_RUN_ID','123')
    monkeypatch.setenv('GITHUB_SHA','1'*40)
    value = dict(schema=job.capacity.SCHEMA,authority=job.capacity.AUTHORITY,
        run_id='123',head='1'*40,ref=job.capacity.REF,source_sha256=job.CAPACITY_SHA,
        target=job.capacity.TARGET,phase='PREPARED',
        phase_history=['VALIDATING','REMOVAL_ATTEMPTED','PREPARED'],
        removal_attempted=True,target_removed=True,free_before_bytes=8112300032,
        free_after_bytes=12*1024**3,error_code=None,production_contacted=False,
        financial_or_market_payload_included=False)
    path = tmp_path/job.RECEIPT
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(value))
    return path,value


def test_new_request_retains_all427_and_selects_only_p11_native10():
    value = job.expected_request()
    old = json.loads((HERE/job.PRIOR).read_bytes())
    assert hashlib.sha256((HERE/job.PRIOR).read_bytes()).hexdigest() == job.PRIOR_SHA
    assert len(value['sources']) == 431 and len(old['sources']) == 427
    assert all(value['sources'][name] == digest for name,digest in old['sources'].items())
    assert value['arms'] == ['P11'] and value['concurrent_candidate_limit'] == 1
    assert value['native_signal_closes'] == {'P11':10}
    assert value['retained_reference_predecessors'] == {'P11':old['retained_reference_predecessors']['P11']}
    assert value['native_signal_factory_sha256'] == {'P11':old['native_signal_factory_sha256']['P11']}
    assert value['retained_reference_predecessors']['P11']['artifact_id'] == 13107654814
    assert value['qualify_wait_seconds'] == 1800 and value['discovery_wait_seconds'] == 14400
    assert value['initial_min_disk_bytes'] == 12*1024**3
    assert value['completed_reference_recomputed'] is False
    assert value['p10_qualification_or_discovery_reexecuted'] is False
    assert value['shared_versioned_anchor_proofs_sha256'] == job.native.ANCHOR_SHA
    assert value['prior_p11_refusal']['parent_or_worker_started'] is False
    changes = {key for key in old if old[key] != value[key]}
    assert changes == {'schema','arms','concurrent_candidate_limit','sources',
        'retained_reference_predecessors','native_signal_closes','native_signal_factory_sha256'}


def test_native_main_ast_is_exact_unmodified_source_and_namespace_only_request_changes(monkeypatch):
    source = ast.parse((HERE/'system_campaign_volatility_native_job.py').read_bytes())
    original, = [node for node in source.body if isinstance(node,ast.FunctionDef) and node.name == 'main']
    assert ast.dump(job.native_main_tree()) == ast.dump(original)
    observed = []
    monkeypatch.setenv('GITHUB_WORKSPACE','fixture')
    monkeypatch.setattr(job,'validate_capacity_receipt',lambda path:observed.append(('receipt',path)))
    def compile_stub(tree,scope):
        assert ast.dump(tree) == ast.dump(original)
        assert set(scope) == set(vars(job.native))
        assert [key for key in scope if scope[key] is not vars(job.native)[key]] == ['expected_request']
        assert scope['expected_request'] is job.expected_request
        for name in ('worker_command','inspect','admit_previous','check_qualification','note','orchestration_tree'):
            assert scope[name] is getattr(job.native,name)
        return lambda args:observed.append(('native',args.arm))
    monkeypatch.setattr(job,'compile_body',compile_stub)
    job.main(SimpleNamespace(arm='P11'))
    assert [item[0] for item in observed] == ['receipt','native']


def test_wrong_native_source_hash_refuses_before_compilation(monkeypatch):
    monkeypatch.setattr(job,'NATIVE_JOB_SHA','0'*64)
    with pytest.raises(ValueError,match='EXACT_NATIVE_MAIN_SOURCE'):
        job.native_main_tree()


@pytest.mark.parametrize('arm',['P10','P03','P11 '])
def test_outer_selection_guard_prevents_capacity_or_native_calls(monkeypatch,arm):
    def forbidden(*args):
        pytest.fail('wrong arm reached capacity or native orchestration')
    monkeypatch.setattr(job,'validate_capacity_receipt',forbidden)
    monkeypatch.setattr(job,'compile_body',forbidden)
    with pytest.raises(ValueError,match='ONLY_UNSTARTED_P11_SELECTED'):
        job.main(SimpleNamespace(arm=arm))


def test_p11_selection_guard_removal_falsifier(monkeypatch):
    tree = ast.parse(Path(job.__file__).read_bytes())
    fn, = [node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name == 'main']
    assert ast.unparse(fn.body[0]).startswith("need(args.arm == 'P11'")
    fn.body.pop(0)
    admitted = []
    namespace = dict(vars(job),validate_capacity_receipt=lambda path:None,
        native_main_tree=lambda:None,compile_body=lambda *args:lambda args:admitted.append(args.arm))
    monkeypatch.setenv('GITHUB_WORKSPACE','fixture')
    compile_body(fn,namespace)(SimpleNamespace(arm='P10'))
    assert admitted == ['P10']


def test_actual_prepared_receipt_identity_and_capacity_are_required(tmp_path,monkeypatch):
    path,value = prepared(tmp_path,monkeypatch)
    assert job.validate_capacity_receipt(path) == value
    assert not list(path.parent.glob('*.partial'))


@pytest.mark.parametrize('key,bad',[
    ('head','2'*40),('run_id','124'),('ref','refs/heads/main'),('source_sha256','0'*64),
    ('target','/usr/local'),('phase','REFUSED'),('target_removed',None),
    ('removal_attempted',False),('free_after_bytes',12*1024**3-1),
    ('free_after_bytes',True),('error_code','UNKNOWN_REMOVAL_OUTCOME'),
    ('financial_or_market_payload_included',True),('production_contacted',True)])
def test_refused_unknown_insufficient_or_unbound_receipt_cannot_pass(tmp_path,monkeypatch,key,bad):
    path,value = prepared(tmp_path,monkeypatch)
    value[key] = bad
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='CAPACITY_'):
        job.validate_capacity_receipt(path)


def test_receipt_must_be_exact_output_and_current_qualified_helper(tmp_path,monkeypatch):
    path,value = prepared(tmp_path,monkeypatch)
    other = path.with_name('different.json')
    other.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='FIXED_PUBLIC_RECEIPT_PATH'):
        job.validate_capacity_receipt(other)
    monkeypatch.setattr(job,'sha256_file',lambda path:'0'*64)
    with pytest.raises(ValueError,match='QUALIFIED_HOST_PREPARATION_SOURCE'):
        job.validate_capacity_receipt(path)


def test_helper_source_guard_removal_falsifier(tmp_path,monkeypatch):
    path,value = prepared(tmp_path,monkeypatch)
    tree = ast.parse(Path(job.__file__).read_bytes())
    fn, = [node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name == 'validate_capacity_receipt']
    sites = [i for i,node in enumerate(fn.body) if isinstance(node,ast.Expr)
        and isinstance(node.value,ast.Call) and ast.unparse(node.value.func) == 'need'
        and node.value.args[-1].value == 'V_CAPACITY_EXACT_QUALIFIED_HOST_PREPARATION_SOURCE']
    assert len(sites) == 1
    fn.body.pop(sites[0])
    assert compile_body(fn,dict(vars(job),sha256_file=lambda path:'0'*64))(path) == value


def test_unchanged_native_body_keeps_marker_before_fetch_and_stop_resource_guards():
    text = ast.unparse(job.native.orchestration_tree())
    assert text.index('qualify_export(') < text.index('old = admit(')
    assert text.index('qualify_export(') < text.index('admit_previous(arm, temp, key)')
    assert text.index('check_qualification(proof, args.arm)') < text.index("receipt.update(status='DISCOVERY_LAUNCH_ATTEMPTED'")
    assert "shutil.disk_usage(temp).free >= request['initial_min_disk_bytes']" in text
    assert "shutil.disk_usage(temp).free >= 10 * 1024 ** 3" in text
    assert "memory_bytes()['MemAvailable'] >= 10 * 1024 ** 3" in text
    assert 'known = False' in text and 'UNKNOWN_NO_SNAPSHOT' in text


def test_native_entrypoint_and_readonly_previous_worker_arguments_are_reused(tmp_path,monkeypatch):
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path))
    monkeypatch.setattr(job.native.parallel.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.native.parallel.os,'getgid',lambda:1001,raising=False)
    for mode in ('qualify','discovery'):
        command = job.native.worker_command('fixture','P11',mode,tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old')
        assert command[command.index('-B'):] == job.native.entrypoint('P11',mode)
        assert command[command.index('-B')+2] == '/driver/system_campaign_volatility_native_run.py'
        assert command[command.index('--network')+1] == 'none'
        assert command[command.index('--memory')+1] == command[command.index('--memory-swap')+1] == '8g'
        assert command[command.index('--cpus')+1] == '2'
        assert sum('target=/previous,readonly' in item for item in command) == (mode == 'qualify')


def test_capacity_probe_requires_host_receipt_before_any_ast_or_staging(monkeypatch,tmp_path):
    import system_campaign_volatility_capacity_probe as probe
    request = tmp_path/'request.json'
    request.write_text('{}')
    monkeypatch.setattr(job,'expected_request',lambda:{})
    monkeypatch.setenv('GITHUB_ACTIONS','true')
    monkeypatch.setattr(job,'native_main_tree',lambda:pytest.fail('AST reached before receipt'))
    with pytest.raises(ValueError,match='HOSTED_PREPARED_RECEIPT_REQUIRED'):
        probe.main(SimpleNamespace(request=request,capacity_receipt=None))


def test_workflow_selects_only_new_request_and_p11_with_preparation_before_staging():
    text = (HERE.parents[1]/'.github/workflows/capital-system-volatility-capacity-discovery.yml').read_text()
    assert "paths: ['research/capital_risk/"+job.REQUEST+"']" in text
    assert '--arm P11 --request' in text and 'matrix.arm' not in text and '--arm P10' not in text
    assert 'cancel-in-progress: false' in text and 'timeout-minutes: 360' in text
    assert text.index('ephemeral_runner_capacity.py --output') < text.index('Install locked transfer dependencies')
    assert text.index('system_campaign_volatility_capacity_probe.py') < text.index('research/capital_risk/stage.py')
    assert text.index('research/capital_risk/stage.py') < text.index('system_campaign_volatility_capacity_job.py')
    assert 'if: always()' in text and job.RECEIPT in text
    assert 'continue-on-error' not in text
    assert 'compression-level: 0' in text and 'retention-days: 7' in text
