"""Transport and publication guards only; no local financial execution."""
import ast
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from system_campaign_acceleration import shallow_signal
from system_campaign_parallel_discovery import compile_body
import system_campaign_volatility_discovery_gate as gate
import system_campaign_volatility_discovery_run as run
import system_campaign_volatility_discovery_job as job

@dataclass(frozen=True)
class Feature:
    security_id:str
    closes:tuple
    signal_sessions:tuple

class Signal:
    model_fields={'security_id':None,'closes':None,'signal_sessions':None}
    @classmethod
    def model_validate(cls,value):return SimpleNamespace(**value)

@pytest.mark.parametrize('horizon',[14,21,42,63,126,127])
def test_actual_old_transport_loses_required_history_and_corrected_retains_it(horizon):
    values=tuple(float(i+1) for i in range(horizon));dates=tuple(str(i) for i in range(horizon))
    feature=Feature('TEST',values,dates)
    old,used=shallow_signal(Signal,feature,None,1)
    corrected,used_new=shallow_signal(Signal,feature,None,127)
    assert used and used_new and old.signal_sessions==corrected.signal_sessions==dates
    assert len(old.closes)==1<horizon
    assert corrected.closes==values and feature.closes==values

def test_entire_qualification_module_has_only_declared_execution_configuration_change():
    original=ast.parse(Path(gate.original.__file__).read_bytes())
    updated=gate.corrected_tree('FAST')
    restored=deepcopy(updated);sites=0
    for n in ast.walk(restored):
        if isinstance(n,ast.Call) and ast.unparse(n.func)=='Execution':
            assert n.keywords[0].value.value==127;n.keywords[0].value.value=1;sites+=1
    assert sites==2 and ast.dump(restored)==ast.dump(original)
    assert sum(isinstance(n,ast.Constant) and n.value=='REFERENCE' for n in ast.walk(gate.corrected_tree('REFERENCE')))==2

def test_original_discovery_changes_only_one_retention_argument():
    original=run.original.diagnostic_tree();changed=run.diagnostic_tree();count=0
    for n in ast.walk(changed):
        if isinstance(n,ast.Call) and ast.unparse(n.func)=='Execution':
            assert n.keywords[0].value.value==127;n.keywords[0].value=ast.Constant(1);count+=1
    assert count==1 and ast.dump(original)==ast.dump(changed)

def proof():
    return dict(qualification_kind='ORIGINAL_RISK_GUARDS_PRESERVED_HELD_MISSING_INPUT_REFUSED',
        held_missing_quote_continuation=False,all_actual_held_quotes_unchanged=True,normal_source_packets_unchanged=True,
        incomplete_toy_position_cash_shares_and_slot_unchanged=True,
        expected_held_input_refusal=dict(status='EXPECTED_ORIGINAL_RISK_INPUT_REFUSAL_QUALIFIED',
            expected_refusal=run.CODE,committed_transitions=0,prior_and_publication_unchanged=True,original_hook_restored=True),
        signal_material_closes=127,actual_fast_reference_full_runtime_paths_equal=True,
        actual_fast_reference_published_sessions_equal=True,financial_source_or_risk_rule_changed=False)

@pytest.mark.parametrize('field',['signal_material_closes','actual_fast_reference_full_runtime_paths_equal',
    'actual_fast_reference_published_sessions_equal','financial_source_or_risk_rule_changed'])
def test_actual_new_admission_refuses_missing_or_false_runtime_equivalence(field):
    value=proof();job.check_qualification(value,'P10')
    value[field]=1 if field=='signal_material_closes' else not value[field]
    with pytest.raises(ValueError,match='FULL_RUNTIME_EQUIVALENCE'):job.check_qualification(value,'P10')

def test_actual_equivalence_guard_removal_accepts_the_falsifier():
    fn,=[n for n in ast.parse(Path(job.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='check_qualification']
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr) and any(isinstance(c,ast.Constant)
        and c.value=='V_RETENTION_ACTUAL_HOSTED_FULL_RUNTIME_EQUIVALENCE_REQUIRED' for c in ast.walk(n)))]
    bad=proof();bad['actual_fast_reference_full_runtime_paths_equal']=False
    compile_body(fn,vars(job))(bad,'P10')

def test_original391_sources_and_only_two_unstarted_arms():
    value=job.expected_request()
    assert value['arms']==['P10','P11'] and not value['risk_guards_bypassed']
    assert not value['financial_source_or_risk_rule_changed']
    assert len(value['sources'])==397

def test_exact_offline_commands_and_other_arm_rejection(monkeypatch,tmp_path):
    monkeypatch.setattr(job.original.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.original.os,'getgid',lambda:1001,raising=False)
    for arm in job.ARMS:
        for mode in ('qualify','discovery'):
            command=job.worker_command('name',arm,mode,tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old')
            assert command[command.index('-B'):]==job.entrypoint(arm,mode)
            assert 'none'==command[command.index('--network')+1]
            assert '8g'==command[command.index('--memory')+1]
            assert any('target=/old,readonly' in s for s in command)
    with pytest.raises(ValueError):job.entrypoint('P09','discovery')
