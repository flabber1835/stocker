"""Fresh-origin scope and real synthetic export checks; never run a financial engine."""
import ast,base64,json
from copy import deepcopy
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_fresh_origin as f
from system_campaign_space import DEFAULT


def request(tmp_path):
    path=tmp_path/'fresh.json';path.write_text(json.dumps(f.expected_request()))
    return path


def test_actual_fresh_request_selects_exact_p00_and_empty_own_origin():
    value=f.expected_request()
    assert value['arm']=='P00' and value['index']==0 and value['parameters']==DEFAULT
    assert value['fresh_origin'] is True and value['inherited_financial_rows']==0
    assert value['prior_checkpoint_imported'] is value['historical_result_reused'] is False
    assert (value['feature_warmup_sessions'],value['formation_sessions'],value['measured_closes'])==(425,126,2156)
    assert (value['measurement_start'],value['measurement_end'])==('2018-01-02','2026-07-31')
    assert len(value['sources'])==400 and value['full_financial_and_independent_data_admission_required'] is True


@pytest.mark.parametrize('field,value',[
 ('arm','P01'),('index',1),('fresh_origin',False),('inherited_financial_rows',1),
 ('prior_checkpoint_imported',True),('historical_result_reused',True),('measurement_start','2019-01-02'),
 ('formation_sessions',0),('measured_closes',2000),('workflow_sha256','0'*64),
 ('original_candidate_request_sha256','0'*64),('production_contacted',True),('current_paper_equivalence_claimed',True),
])
def test_changed_origin_basis_or_authority_refuses_before_financial_start(tmp_path,field,value):
    path=request(tmp_path);body=json.loads(path.read_bytes());body[field]=value;path.write_text(json.dumps(body))
    with pytest.raises(ValueError):f.probe(path)


def test_changed_source_or_parameters_refuses(tmp_path):
    path=request(tmp_path);body=json.loads(path.read_bytes());body['parameters']['stop']=.8;path.write_text(json.dumps(body))
    with pytest.raises(ValueError):f.probe(path)
    body=f.expected_request();body['sources']['system_campaign_candidate.py']='0'*64;path.write_text(json.dumps(body))
    with pytest.raises(ValueError):f.probe(path)


def test_exact_request_guard_removal_falsifier(tmp_path):
    path=request(tmp_path);body=json.loads(path.read_bytes());body['inherited_financial_rows']=2156;path.write_text(json.dumps(body))
    with pytest.raises(ValueError):f.probe(path)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='probe')
    fn.body.pop(1);namespace=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-fresh-origin-guard>','exec'),namespace)
    assert namespace['probe'](path)['status']=='EXACT_FRESH_P00_ORIGIN_SCOPE_PASSED'


def prepare_fixture(tmp_path,monkeypatch):
    import ephemeral_runner_capacity as capacity
    path=request(tmp_path);receipt=tmp_path/'capacity.json';receipt.write_text('{}');output=tmp_path/'artifacts/admission.json'
    monkeypatch.setattr(f,'check_context',lambda env:None)
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1');monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path));monkeypatch.setenv(f.SECRET,base64.b64encode(b'k'*32).decode())
    calls=[];monkeypatch.setattr(capacity,'validate_prepared_receipt',lambda value,**kwargs:calls.append(kwargs))
    return path,receipt,output,calls


def test_actual_aes_gcm_roundtrip_precedes_fresh_public_admission_without_financial_runtime(tmp_path,monkeypatch):
    path,receipt,output,calls=prepare_fixture(tmp_path,monkeypatch)
    proof=f.prepare(path,receipt,output)
    assert proof['actual_synthetic_export_passed'] and proof['capacity_prepared']
    assert proof['inherited_financial_rows']==0 and proof['previous_book_selected'] is False
    assert proof['financial_runtime_executed'] is proof['performance_admitted'] is proof['production_contacted'] is False
    assert proof['old_p00_performance_is_not_completion_authority'] is True
    assert calls==[dict(head='a'*40,run_id='123',source_sha256=f.expected_request()['sources']['ephemeral_runner_capacity.py'])]
    assert json.loads(output.read_bytes())==proof and b'kkkkkkkk' not in output.read_bytes()


@pytest.mark.parametrize('change',['key','attempt','export'])
def test_prepare_failure_never_writes_financial_admission(tmp_path,monkeypatch,change):
    path,receipt,output,calls=prepare_fixture(tmp_path,monkeypatch)
    if change=='key':monkeypatch.setenv(f.SECRET,'')
    elif change=='attempt':monkeypatch.setenv('GITHUB_RUN_ATTEMPT','2')
    else:monkeypatch.setattr(f.shared,'export_probe',lambda *args:dict(status='FAILED'))
    with pytest.raises(ValueError):f.prepare(path,receipt,output)
    assert not output.exists()


def test_workflow_runs_only_generic_fresh_p00_with_probe_export_and_capacity_before_finance():
    workflow=yaml.load((f.HERE.parent.parent/f.WORKFLOW).read_bytes(),Loader=yaml.BaseLoader);job=workflow['jobs']['candidate']
    assert job['strategy']['matrix']==dict(include=[dict(index='0',arm='P00')])
    assert job['strategy']['max-parallel']=='1'
    assert job['concurrency']==dict(group='system-optimization-002-financial-${{ matrix.arm }}',**{'cancel-in-progress':'false'})
    assert workflow['on']['push']['paths']==['research/capital_risk/'+f.REQUEST]
    steps=job['steps'];names=[s.get('name','checkout') for s in steps]
    assert names.index('Prepare dedicated ephemeral research capacity')<names.index('Probe exact fresh P00 parameters source and empty origin')
    assert names.index('Admit fresh origin and prove encrypted export before financial start')<names.index('Authenticate existing frozen inputs and offline runtime')
    assert 'system_campaign_candidate_job.py' in next(s['run'] for s in steps if s.get('name','').startswith('Run original generic'))
    checkout=steps[0];assert '.github/workflows' in checkout['with']['sparse-checkout']


def test_original_generic_origin_keeps_exclusive_new_root_and_no_parent_mount():
    import full_system_trials_job as original
    source=Path(f.candidate.__file__).read_text(encoding='utf-8')
    assert "root=temp/'campaign-candidate';root.mkdir(mode=0o700)" in source
    assert "source=temp/'campaign-variant'" in source and 'transport_admit' not in source and 'root_spec' not in source
    tree=ast.parse(Path(original.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='command')
    literals=[n.value for n in ast.walk(fn) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
    assert not any('/old' in text for text in literals)
    assert any('target=/frozen,readonly' in text for text in literals)
    assert any('target=/out' in text for text in literals)
