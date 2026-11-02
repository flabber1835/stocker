"""Only changed transport, retention and missing-reference control paths."""
import ast,gzip,json
from dataclasses import dataclass
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from full_system_benchmark import save
from system_campaign_parallel_discovery import compile_body
import system_campaign_volatility_reference_gate as gate
import system_campaign_volatility_reference_job as job
import system_campaign_volatility_reference_parent as parent


@dataclass(frozen=True)
class Publication:
    session:str
    value:float


def recorder(tmp_path,*,mutation=None,remove_guard=False,interrupt=False):
    fn=gate.reference_tree();fn.body=[n for n in fn.body if not isinstance(n,ast.ImportFrom)]
    if remove_guard:
        sites=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
               and ast.unparse(n.value.func)=='need' and len(n.value.args)>1
               and isinstance(n.value.args[1],ast.Constant)
               and n.value.args[1].value=='V_RETENTION_ALL_ACTUAL_PUBLISHED_AND_RUNTIME_VALUES_EQUAL']
        assert len(sites)==1;fn.body.pop(sites[0])
    runtime=SimpleNamespace(advance=lambda run,published:run,checkpoint=lambda run:dict(state_value=run.value))
    calls=[]
    def compiled(mode):
        calls.append(mode);assert mode=='REFERENCE','COMPLETED_FAST_MUST_NEVER_EXECUTE_AGAIN'
        def qualify(root,prior,out,**kw):
            for i in range(3):
                run=SimpleNamespace(value=i+(1 if mutation=='checkpoint' else 0))
                runtime.advance(run,Publication(str(i),2. if mutation=='publication' else 1.))
                if interrupt:raise TimeoutError('actual stub interrupt after durable canonical record')
            save(out/'discovery-canonical-qualification.json',dict(status='QUALIFIED'))
        return qualify
    records=[dict(session=str(i),publication_sha256=gate.publication_digest(Publication(str(i),1.)),
                  checkpoint=dict(state_value=i)) for i in range(3)]
    scope=dict(vars(gate.original),runtime=runtime,hosted=lambda:None,compiled_gate=compiled,
               seed_fast=lambda *a:(records,dict(status='QUALIFIED')),progress=gate.progress,
               phase=gate.phase,publication_digest=gate.publication_digest)
    return compile_body(fn,scope),calls


def test_only_reference_executes_and_every_completed_transition_is_durable(tmp_path):
    call,calls=recorder(tmp_path)
    out=tmp_path/'out';call(tmp_path,{},out,selected_file='not-used',source_iterator=None,code='TEST')
    assert calls==['REFERENCE']
    assert len(list((out/'reference-progress').glob('*.json.gz')))==3
    phases=[json.loads(r) for r in (out/'reference-progress/phases.jsonl').read_bytes().splitlines()]
    assert sum(r['stage']=='CANONICAL_REFERENCE_TRANSITION_RETAINED' for r in phases)==3
    assert json.loads((out/'discovery-canonical-qualification.json').read_bytes())['actual_fast_reference_full_runtime_paths_equal']


@pytest.mark.parametrize('mutation',['checkpoint','publication'])
def test_reused_fast_still_requires_actual_full_reference_equality(tmp_path,mutation):
    call,_=recorder(tmp_path,mutation=mutation)
    with pytest.raises(ValueError,match='ALL_ACTUAL_PUBLISHED_AND_RUNTIME_VALUES_EQUAL'):
        call(tmp_path,{},tmp_path/mutation,selected_file='not-used',source_iterator=None,code='TEST')


def test_actual_runtime_comparison_guard_removal_falsifier(tmp_path):
    call,_=recorder(tmp_path,mutation='checkpoint',remove_guard=True)
    call(tmp_path,{},tmp_path/'removed',selected_file='not-used',source_iterator=None,code='TEST')


def test_interruption_retains_new_reference_checkpoint_without_combined_pass(tmp_path):
    call,_=recorder(tmp_path,interrupt=True);out=tmp_path/'interrupted'
    with pytest.raises(TimeoutError):
        call(tmp_path,{},out,selected_file='not-used',source_iterator=None,code='TEST')
    assert json.loads(gzip.decompress((out/'reference-progress/0.json.gz').read_bytes()))['session']=='0'
    assert not (out/'discovery-canonical-qualification.json').exists()


def test_exact_old408_sources_qualified_fast_predecessors_and_bounded_waits():
    value=job.expected_request()
    assert len(value['sources'])==415 and value['arms']==['P10','P11']
    assert value['only_missing_reference_qualification_executed']
    assert value['qualify_wait_seconds']==3600 and value['discovery_wait_seconds']==14400
    tree=ast.unparse(parent.admission_tree())
    assert 'validate_fast(spec, inventory, dest)' in tree
    assert 'FACTUAL_SELECTED_BINDINGS' not in tree and 'selected_checkpoint' not in tree
    assert 'export-qualification.json' in tree
    for arm in job.ARMS:
        spec=parent.specification(arm)
        assert spec['qualification_worker']['exit_code']==137 and spec['no_diagnostic_origin_or_worker']


@pytest.mark.parametrize('mode',['qualify','discovery'])
@pytest.mark.parametrize('arm',['P10','P11'])
def test_new_worker_adds_only_readonly_fast_mount_for_qualification(tmp_path,monkeypatch,arm,mode):
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path))
    monkeypatch.setattr(job.parallel.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.parallel.os,'getgid',lambda:1001,raising=False)
    cmd=job.worker_command('name',arm,mode,tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old')
    assert cmd[cmd.index('-B'):]==job.entrypoint(arm,mode)
    assert cmd[cmd.index('--network')+1]=='none' and '--read-only' in cmd
    assert any('target=/old,readonly' in value for value in cmd)
    assert sum('target=/previous,readonly' in value for value in cmd)==(1 if mode=='qualify' else 0)


@pytest.mark.parametrize('mode,role',[('qualify','qualify'),('discovery','worker')])
@pytest.mark.parametrize('arm',['P10','P11'])
def test_actual_inspection_body_rejects_writable_evidence(monkeypatch,arm,mode,role):
    monkeypatch.setattr(job.inspector_source.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.inspector_source.os,'getgid',lambda:1001,raising=False)
    name=f'capital-system-parallel-discovery-{arm.lower()}-{role}-123-1'
    destinations=['/variant','/frozen','/driver','/out','/old']+(['/previous'] if mode=='qualify' else [])
    value=dict(Name='/'+name,Image=job.parallel.EXECUTION_IMAGE,Id='1'*64,
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Config=dict(Cmd=job.entrypoint(arm,mode),WorkingDir='/variant',User='1001:1001',Env=[],
            Labels={'research.study':'full-system-search-20261029','research.role':'worker'}),
        Mounts=[dict(Destination=n,Type='bind',RW=n=='/out') for n in destinations])
    monkeypatch.setattr(job.inspector_source.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps([value]).encode()))
    assert job.inspect(name,'1'*64)==value
    value['Mounts'][-1]['RW']=True
    with pytest.raises(ValueError,match='MOUNTS'):job.inspect(name,'1'*64)
