"""Actual observer-function error reproduction, with no strategy execution."""
import ast
from dataclasses import dataclass
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from system_campaign_parallel_discovery import compile_body
from full_system_benchmark import save
import system_campaign_volatility_discovery_gate_v2 as corrected
import system_campaign_volatility_discovery_job_v2 as job

@dataclass(frozen=True)
class Publication:
    session:str
    close:float

def recorder(tmp_path,*,old=False,mutation=None):
    fn=ast.parse(Path(corrected.original.__file__).read_bytes()) if old else None
    if old:fn,=[n for n in fn.body if isinstance(n,ast.FunctionDef) and n.name=='qualify']
    else:fn=corrected.recorder_tree()
    imports=[n for n in fn.body if isinstance(n,ast.ImportFrom)];assert len(imports)==1
    fn.body=[n for n in fn.body if n not in imports]
    runtime=SimpleNamespace(advance=lambda run,published:SimpleNamespace(value=run.value),
                            checkpoint=lambda run:dict(state_value=run.value))
    def compiled(mode):
        def qualify(root,parent,out,**kw):
            for i in range(3):
                published=Publication(str(i),2. if mutation=='publication' and mode=='REFERENCE' else 1.)
                run=SimpleNamespace(value=i+(1 if mutation=='checkpoint' and mode=='REFERENCE' else 0))
                runtime.advance(run,published)
            save(out/'discovery-canonical-qualification.json',dict(status='QUALIFIED'))
        return qualify
    scope=dict(vars(corrected.original),runtime=runtime,hosted=lambda:None,compiled_gate=compiled,
               publication_digest=corrected.publication_digest)
    return compile_body(fn,scope)

def test_actual_retained_recorder_reproduces_dataclass_serialization_error(tmp_path):
    call=recorder(tmp_path,old=True)
    with pytest.raises(TypeError,match='Publication is not JSON serializable'):
        call(tmp_path,{},tmp_path/'old',selected_file='not-used',source_iterator=None,code='TEST')

def test_corrected_actual_recorder_stores_equal_typed_publication_and_checkpoint_paths(tmp_path):
    call=recorder(tmp_path)
    call(tmp_path,{},tmp_path/'corrected',selected_file='not-used',source_iterator=None,code='TEST')
    assert (tmp_path/'corrected/fast/actual-runtime-path.json.gz').exists()
    assert (tmp_path/'corrected/reference/actual-runtime-path.json.gz').exists()

@pytest.mark.parametrize('mutation',['publication','checkpoint'])
def test_actual_recorder_refuses_either_publication_or_runtime_inequality(tmp_path,mutation):
    call=recorder(tmp_path,mutation=mutation)
    with pytest.raises(ValueError,match='ALL_ACTUAL_PUBLISHED_AND_RUNTIME_VALUES_EQUAL'):
        call(tmp_path,{},tmp_path/mutation,selected_file='not-used',source_iterator=None,code='TEST')

def test_source_adapter_changes_exactly_one_digest_call():
    original=ast.parse(Path(corrected.original.__file__).read_bytes())
    original,=[n for n in original.body if isinstance(n,ast.FunctionDef) and n.name=='qualify']
    changed=corrected.recorder_tree();sites=[n for n in ast.walk(changed) if isinstance(n,ast.Call)
        and ast.unparse(n.func)=='publication_digest']
    assert len(sites)==1;sites[0].func=ast.Name(id='digest',ctx=ast.Load())
    assert ast.dump(original)==ast.dump(changed)

def test_all402_old_sources_and_same_two_V_forks():
    request=job.expected_request()
    assert len(request['sources'])==408 and request['arms']==['P10','P11']
    assert request['signal_material_closes']==127 and not request['risk_guards_bypassed']
    assert not request['financial_source_or_risk_rule_changed']

def test_exact_new_commands_still_have_offline_readonly_fences(tmp_path,monkeypatch):
    monkeypatch.setattr(job.original.original.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.original.original.os,'getgid',lambda:1001,raising=False)
    for mode in ['qualify','discovery']:
        cmd=job.worker_command('name','P10',mode,tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old')
        assert cmd[cmd.index('-B'):]==job.entrypoint('P10',mode)
        assert cmd[cmd.index('--network')+1]=='none'
        assert any('target=/old,readonly' in s for s in cmd)
