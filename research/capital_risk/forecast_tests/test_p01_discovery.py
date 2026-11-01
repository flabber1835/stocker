"""Metadata, real guard falsifiers and stub-only checkpoint scheduling."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_p01_discovery_parent as parent
import system_campaign_p01_discovery_replay as replay
import system_campaign_p01_discovery_inputs as inputs

HERE=Path(parent.__file__).parent

def spec():return json.loads((HERE/parent.SPEC).read_bytes())

def test_exact_p01_own419_and_not_reported_tail():
    value=spec();assert parent.scope(value)==value
    ref=parent.reference(value)
    assert ref['arm']=='P01' and ref['selected_outer_sha256']==value['outer_sha256']
    assert ref['complete_parent_transport_copied_into_new_output'] is False

@pytest.mark.parametrize('field,value',[
    ('arm','P02'),('selected_session','2019-09-27'),('measured_closes',438),
    ('outer_sha256','0'*64),('state_sha256','1'*64),('input_sha256','2'*64),
    ('source_binding_sha256','3'*64),('run_id',41275584524)])
def test_wrong_arm_cursor_or_exact_identity_refuses(field,value):
    current=spec();current[field]=value
    with pytest.raises(ValueError,match='P01_DISCOVERY_EXACT_PUBLIC_PARENT'):parent.scope(current)

def test_request_never_adopts_p02_state_or_parameters():
    from system_campaign_p01_discovery_job import expected_request
    request=expected_request()
    assert request['owner_candidate_priority']=='P01'
    assert request['expected_remaining_sessions']==2156-419
    assert request['financial_authority'] is False and request['account_performance_computed'] is False
    assert request['new_origin'] is False and request['new_overlay'] is False
    assert request['checkpoint_cadence']=='MONTH_END_AND_NORMAL_SIGNAL_STOP'
    index=json.loads((HERE/'system-campaign-p01-known-facts.json').read_bytes())
    assert index['scope']=='REFERENCE_ONLY_NO_AUTOMATIC_ADOPTION'
    assert index['p02_state_or_input_descriptor_adopted'] is False

def test_changed_original_replay_source_refuses():
    raw=Path(replay.original.__file__).read_bytes()
    replay.replay_tree(raw)
    with pytest.raises(ValueError,match='P01_EXACT_QUALIFIED_DISCOVERY_REPLAY_SOURCE'):
        replay.replay_tree(raw+b'\n')

def test_actual_source_guard_removal_admits_changed_source():
    fn,=[n for n in ast.parse(Path(replay.__file__).read_bytes()).body
          if isinstance(n,ast.FunctionDef) and n.name=='replay_tree']
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr)
        and any(isinstance(x,ast.Constant) and x.value=='P01_EXACT_QUALIFIED_DISCOVERY_REPLAY_SOURCE' for x in ast.walk(n)))]
    namespace=dict(vars(replay));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-actual-discovery-source-guard>','exec'),namespace)
    namespace['replay_tree'](Path(replay.original.__file__).read_bytes()+b'\n')

def simulate(stop_after=None):
    """Execute only the source-bound loop with explicit in-memory stubs."""
    tree=replay.replay_tree(Path(replay.original.__file__).read_bytes());fn=tree.body[0]
    loop,=[n for n in ast.walk(fn) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='expected']
    days=['2019-09-03','2019-09-30','2019-10-01','2019-10-31','2019-11-01']
    state=SimpleNamespace(state_hash='initial',data_version=0,last_decision={},last_processed_session='2019-08-30')
    run=SimpleNamespace(state=state,input_sha256='input');observed=[];records=[];calls=[];stops=[]
    scope=dict(wanted=days,checkpoint_days=set({d[:7]:d for d in days}.values())-{days[-1]},
        stop=stops,packets=iter(SimpleNamespace(day=d) for d in days),repaired=lambda x:x,
        need=lambda x,c:None if x else (_ for _ in ()).throw(ValueError(c)),
        buffer=SimpleNamespace(append=lambda x:None,current=None,prepare=lambda s,v,formation:None),
        run=run,context=SimpleNamespace(chain='event'),chain='parent',observed=observed,
        TAINT='DISCOVERY_ONLY_NOT_FINANCIAL_AUTHORITY',digest=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest(),
        stream=SimpleNamespace(append=lambda name,row:records.append(row)))
    def advance(prior,published):
        i=prior.state.data_version+1
        if stop_after==i:stops.append(15)
        return SimpleNamespace(state=SimpleNamespace(state_hash=str(i),data_version=i,last_decision={},
            last_processed_session=days[i-1]),input_sha256='input')
    scope['runtime']=SimpleNamespace(advance=advance)
    scope['checkpoint']=lambda:calls.append((scope['run'].state.last_processed_session,len(scope['observed'])))
    final=ast.parse('checkpoint()').body[0]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[loop,final],type_ignores=[])),
        '<only-stubbed-discovery-loop-and-final-checkpoint>','exec'),scope)
    return scope,records,calls

def test_every_transition_recorded_with_month_end_and_final_checkpoint():
    scope,records,calls=simulate()
    assert len(records)==len(scope['observed'])==5
    assert [r['session'] for r in records]==scope['wanted']
    assert calls==[('2019-09-30',2),('2019-10-31',4),('2019-11-01',5)]
    assert records[-1]['state_sha256']==scope['run'].state.state_hash
    assert all(r['account_performance_computed'] is False for r in records)

def test_signal_stop_saves_actual_last_completed_diagnostic_state():
    scope,records,calls=simulate(stop_after=3)
    assert len(records)==3 and scope['observed']==scope['wanted'][:3]
    assert calls==[('2019-09-30',2),('2019-10-01',3)]
    assert records[-1]['state_sha256']==scope['run'].state.state_hash

def test_no_individual_transition_or_recording_site_removed():
    new=replay.replay_tree(Path(replay.original.__file__).read_bytes())
    old=ast.parse(Path(replay.original.__file__).read_bytes())
    oldfn,=[n for n in old.body if isinstance(n,ast.FunctionDef) and n.name=='replay']
    for name in ('runtime.advance','stream.append','discovery_checkpoint','stream.commitment','context.commitment'):
        calls=lambda t:sum(isinstance(n,ast.Call) and ast.unparse(n.func)==name for n in ast.walk(t))
        assert calls(new)==calls(oldfn)

@pytest.mark.parametrize('bad',[False,True])
def test_exact_own_private_hydration_guard(tmp_path,monkeypatch,bad):
    old,out=tmp_path/'old',tmp_path/'out';old.mkdir();out.mkdir()
    (old/'hydrated-factual-catalog.json').write_bytes(b'fnf')
    (old/'hydrated-distribution-catalog.json').write_bytes(b'distribution')
    class Context:
        def __init__(self,path):self.path=path
        def hydrate(self,target):target.write_bytes(b'changed' if bad else b'fnf' if 'fnf' in target.name else b'distribution')
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(inputs,'hosted',lambda:None)
    monkeypatch.setattr(inputs,'FactualInputs',Context);monkeypatch.setattr(inputs,'DistributionFacts',Context)
    monkeypatch.setattr(inputs,'preserve_input_documents',lambda *a:None)
    if bad:
        with pytest.raises(ValueError,match='P01_EXACT_OWN_PRIOR_PRIVATE_INPUT_BYTES'):
            with inputs.retained_inputs(old,dict(repairs=[]),out):pass
    else:
        with inputs.retained_inputs(old,dict(repairs=[]),out):pass

def test_actual_hydration_guard_removal_admits_changed_private_bytes(tmp_path,monkeypatch):
    original=inputs.need
    monkeypatch.setattr(inputs,'need',lambda value,code:None
        if code=='P01_EXACT_OWN_PRIOR_PRIVATE_INPUT_BYTES' else original(value,code))
    old,out=tmp_path/'old',tmp_path/'out';old.mkdir();out.mkdir()
    (old/'hydrated-factual-catalog.json').write_bytes(b'original')
    (old/'hydrated-distribution-catalog.json').write_bytes(b'original')
    class Context:
        def __init__(self,path):pass
        def hydrate(self,target):target.write_bytes(b'changed')
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(inputs,'hosted',lambda:None)
    monkeypatch.setattr(inputs,'FactualInputs',Context);monkeypatch.setattr(inputs,'DistributionFacts',Context)
    monkeypatch.setattr(inputs,'preserve_input_documents',lambda *a:None)
    with inputs.retained_inputs(old,dict(repairs=[]),out):pass
