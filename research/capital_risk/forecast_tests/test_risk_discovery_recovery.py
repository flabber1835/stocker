"""Actual correction guards and orchestration; financial execution stays hosted."""
import ast
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_risk_discovery_gate as gate
import system_campaign_risk_discovery_job as job
from system_campaign_parallel_discovery import compile_body


@dataclass
class Packet:
    day:str='SYNTHETIC_DAY'
    bars:tuple=()
    terminal:tuple=()


@dataclass
class Publication:
    cash_distributions:object=None
    spinoff_distributions:tuple=()
    mutation:int=0


def refusal_case(tmp_path,mutation=None,*,old_source=False):
    source=(json.loads((job.HERE/'system-campaign-risk-prepare-order-provenance.json').read_bytes())['original_gate_source_text'].encode()
            if old_source else Path(gate.__file__).read_bytes())
    fn,=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='expected_refusal']
    # Pure stub bindings replace imports, leaving the actual function's guards.
    imports=[n for n in fn.body if isinstance(n,ast.ImportFrom)]
    assert len(imports)==3;fn.body=[n for n in fn.body if n not in imports]
    state=SimpleNamespace(wealth_core=dict(episodes={'0':dict(security_id='HELD')}),
        median5=dict(selected=['LEADER']),data_version=1)
    run=SimpleNamespace(state=state);material=dict(synthetic='PRIOR');publication=Publication()
    prepared=dict(active=False,prior=None)
    class FastExecution:
        def __enter__(self):prepared['active']=True;return self
        def __exit__(self,*args):prepared['active']=False
    class Context:
        transitions=1 if mutation=='commit' else 0
        def __init__(self,out,**kw):self.out=out
        def __enter__(self):
            (self.out/'discovery-events.jsonl').write_text(json.dumps(dict(event=dict(kind='DISCOVERY_TRANSITION_REFUSED')))+'\n')
            return self
        def __exit__(self,*args):pass
        def commitment(self):return dict(rows=1)
    def advance(*args):
        if prepared['prior'] is not run.state:raise ValueError('REFUSED_CAMPAIGN_ACCELERATION_EXACT_PREPARED_PRIOR')
        if mutation=='prior':material['changed']=True
        if mutation=='publication':args[1].mutation=1
        if mutation=='success':return run
        raise ValueError('WRONG_ERROR' if mutation=='wrong_error' else 'REFUSED_TRIM_CURRENT_RAW_MARK')
    runtime=SimpleNamespace(advance=advance,checkpoint=lambda r:deepcopy(dict(checkpoint_sha256='1'*64,state=material)))
    def prepare(*a,**k):
        prepared['prior']=a[0] if prepared['active'] else None
        return publication
    buffer=SimpleNamespace(append=lambda p:None,prepare=prepare)
    packet=Packet(bars=(SimpleNamespace(security_id='HELD'),SimpleNamespace(security_id='LEADER')))
    iterator=lambda *args:(run,buffer,iter([packet]),lambda p:p,['SYNTHETIC_DAY'])
    namespace=dict(vars(gate),runtime=runtime,TerminalTerms=lambda **kw:SimpleNamespace(**kw),
        TerminalKind=SimpleNamespace(CASH_MERGER='CASH'),Execution=lambda *a,**k:FastExecution(),DiscoveryContext=Context)
    call=compile_body(fn,namespace)
    return call,iterator,tmp_path/'probe'


def test_actual_refusal_function_accepts_only_expected_original_zero_commit(tmp_path):
    call,iterator,out=refusal_case(tmp_path)
    proof=call(tmp_path,dict(base=dict(sources={}),sha256='2'*64),out,iterator,'REFUSED_TRIM_CURRENT_RAW_MARK')
    assert proof['status']=='EXPECTED_ORIGINAL_RISK_INPUT_REFUSAL_QUALIFIED'
    assert proof['committed_transitions']==0 and proof['prior_and_publication_unchanged']


def test_actual_prior_prepare_order_bug_reproduced_by_fast_scope_stub(tmp_path):
    call,iterator,out=refusal_case(tmp_path,old_source=True)
    with pytest.raises(ValueError,match='EXACT_EXISTING_MISSING_INPUT_REFUSAL'):
        call(tmp_path,dict(base=dict(sources={}),sha256='2'*64),out,iterator,'REFUSED_TRIM_CURRENT_RAW_MARK')
    assert not (out/'proof.json').exists()


@pytest.mark.parametrize('mutation',['prior','publication','commit','success','wrong_error'])
def test_refusal_cannot_hide_state_publication_or_commit_changes(tmp_path,mutation):
    call,iterator,out=refusal_case(tmp_path,mutation)
    with pytest.raises(ValueError):
        call(tmp_path,dict(base=dict(sources={}),sha256='2'*64),out,iterator,'REFUSED_TRIM_CURRENT_RAW_MARK')
    assert not (out/'proof.json').exists()


def proof(arm):
    return dict(qualification_kind='ORIGINAL_RISK_GUARDS_PRESERVED_HELD_MISSING_INPUT_REFUSED',
        held_missing_quote_continuation=False,all_actual_held_quotes_unchanged=True,normal_source_packets_unchanged=True,
        incomplete_toy_position_cash_shares_and_slot_unchanged=True,
        expected_held_input_refusal=dict(status='EXPECTED_ORIGINAL_RISK_INPUT_REFUSAL_QUALIFIED',
            expected_refusal=job.CODES[arm],committed_transitions=0,prior_and_publication_unchanged=True,
            original_hook_restored=True))


@pytest.mark.parametrize('arm',job.ARMS)
def test_new_exact_proof_required_before_original_discovery(arm):
    value=proof(arm);job.check_qualification(value,arm)
    value['expected_held_input_refusal']['committed_transitions']=1
    with pytest.raises(ValueError,match='GUARD_REFUSAL_PROOF'):job.check_qualification(value,arm)


def test_actual_new_admission_guard_removal_falsifier():
    fn,=[n for n in ast.parse(Path(job.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='check_qualification']
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr) and any(isinstance(v,ast.Constant)
        and v.value=='RISK_RECOVERY_ACTUAL_EXISTING_GUARD_REFUSAL_PROOF' for v in ast.walk(n)))]
    value=proof('P09');value['expected_held_input_refusal']['committed_transitions']=1
    compile_body(fn,vars(job))(value,'P09')


def test_continuing_candidate_sources_and_orchestrators_remain_exact():
    request=job.expected_request();assert request['arms']==['P09','P10','P11']
    assert request['actual_discovery_replay_changed'] is False and request['risk_guards_bypassed'] is False
    assert len(request['sources'])==391 and request['other_five_jobs_unchanged']
    job.validate_prepare_order()
    assert 'risk' not in ast.unparse(job.adopted('worker_command')).lower()
    assert callable(compile_body(job.adopted('main'),vars(job.original)))


def test_risk_worker_exact_command_and_readonly_fences(monkeypatch,tmp_path):
    monkeypatch.setattr(job.original.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.original.os,'getgid',lambda:1001,raising=False)
    for arm in job.ARMS:
        for mode,role in [('qualify','qualify'),('discovery','worker')]:
            name=f'capital-system-parallel-discovery-{arm.lower()}-{role}-123-1'
            cmd=job.worker_command(name,arm,mode,tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old')
            assert cmd[cmd.index('-B'):]==job.entrypoint(arm,mode)
            assert any('target=/old,readonly' in v for v in cmd)
            value=dict(Name='/'+name,Image=job.original.EXECUTION_IMAGE,Id='1'*64,
                HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
                    PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
                Config=dict(Cmd=job.entrypoint(arm,mode),WorkingDir='/variant',User='1001:1001',Env=[],
                    Labels={'research.study':'full-system-search-20261029','research.role':'worker'}),
                Mounts=[dict(Destination=n,Type='bind',RW=n=='/out') for n in ('/variant','/frozen','/driver','/out','/old')])
            monkeypatch.setattr(job.original.inspector_source.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps([value]).encode()))
            assert job.inspect(name,'1'*64)==value
            value['Config']['Cmd']=job.original.entrypoint(arm,mode)
            with pytest.raises(ValueError,match='ENTRYPOINT'):job.inspect(name,'1'*64)


def test_normal_qualification_uses_actual_source_packets_and_no_risk_patch():
    tree=ast.parse(Path(gate.__file__).read_bytes());fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualify']
    text=ast.unparse(fn)
    assert 'packet = repaired(next(packets))' in text
    assert 'packet = replace(' not in text
    assert 'RISK_GATE_ALL_ACTUAL_SOURCE_PACKET_BYTES_UNCHANGED' in text
    assert 'runtime.advance(run, publication)' in text
    assert 'capital_risk' not in text
    raw=(Path(__file__).resolve().parents[3]/'.github/workflows/capital-system-risk-discovery.yml').read_text()
    assert 'max-parallel: 3' in raw and 'arm: [P09, P10, P11]' in raw
    assert 'system-optimization-002-risk-discovery-recovery' in raw
