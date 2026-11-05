"""Read-only refusal instrumentation delegates the original risk call unchanged."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib,json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f


@dataclass
class Bar:
    security_id:str
    session:str
    close:float


def observer(tmp_path,original):
    result=f.ActualEvents.__new__(f.ActualEvents);result.out=tmp_path;result.risk_original=original
    return result


def test_success_preserves_original_argument_identities_and_exact_return(tmp_path):
    episode={'security_id':'synthetic','ticker':'TEST'};bars=[Bar('synthetic','2022-02-23',1.)];cfg={'horizon':10};marker=object();calls=[]
    def original(ep,*,bars,session,cfg):
        calls.append((ep,bars,session,cfg));return marker
    probe=observer(tmp_path,original);before=deepcopy((episode,bars,cfg))
    assert probe.risk_refusal(episode,bars=bars,session='2022-02-23',cfg=cfg)is marker
    assert len(calls)==1 and calls[0][0]is episode and calls[0][1]is bars and calls[0][3]is cfg
    assert (episode,bars,cfg)==before and not (tmp_path/'risk-refusal.json').exists()


def test_refusal_records_actual_window_configuration_and_same_exception(tmp_path):
    problem=ValueError('REFUSED_VOLATILITY_CAUSAL_AXIS');calls=[]
    def original(ep,*,bars,session,cfg):calls.append(1);raise problem
    ep={'security_id':'actual-id','ticker':'ACTUAL'};bars=[Bar('actual-id','2022-02-22',5.)];cfg={'horizon':10}
    with pytest.raises(ValueError)as caught:observer(tmp_path,original).risk_refusal(ep,bars=bars,session='2022-02-23',cfg=cfg)
    assert caught.value is problem and calls==[1]
    value=json.loads((tmp_path/'risk-refusal.json').read_bytes())
    assert value['episode']==ep and value['bars']==[dict(security_id='actual-id',session='2022-02-22',close=5.)]
    assert value['configuration']==cfg and value['session']=='2022-02-23'
    assert value['function_source_sha256']==hashlib.sha256(Path(original.__code__.co_filename).read_bytes()).hexdigest()
    assert value['financial_authority']is value['decision_overridden']is value['financial_source_changed']is False


def test_diagnostic_write_failure_never_masks_the_original_refusal(tmp_path,monkeypatch):
    problem=ValueError('original refusal')
    def original(*args,**kwargs):raise problem
    def fail(*args):raise OSError('synthetic observer write failure')
    monkeypatch.setattr(f,'save',fail)
    with pytest.raises(ValueError)as caught:observer(tmp_path,original).risk_refusal({},bars=[],session='2022-02-23',cfg={})
    assert caught.value is problem


def test_typed_configuration_fields_are_retained_without_model_serialization():
    from pydantic import BaseModel
    class Config(BaseModel):
        horizon:int=10
        def model_dump(self,*args,**kwargs):raise AssertionError('no serialization API')
    assert f.risk_diagnostic_value(Config())==dict(horizon=10)


@pytest.mark.parametrize('fails',[False,True])
def test_p11_context_restores_the_exact_original_risk_function(tmp_path,monkeypatch,fails):
    def original(*args,**kwargs):return False
    def advance(*args):pass
    def terminal(*args,**kwargs):pass
    def step(*args):pass
    runtime=SimpleNamespace(advance=advance);capital=SimpleNamespace(volatility_stop=original)
    terminal_module=SimpleNamespace(apply_terminal=terminal);adapter=SimpleNamespace(step_session=step)
    pooled=ModuleType('research.pooled_vacancy_funding');pooled.runtime=runtime
    wealth=ModuleType('stock_strategy_shared.wealth_core');wealth.capital_risk=capital;wealth.terminal=terminal_module;wealth.adapter=adapter
    monkeypatch.setitem(sys.modules,pooled.__name__,pooled);monkeypatch.setitem(sys.modules,wealth.__name__,wealth)
    monkeypatch.setattr(f,'hosted',lambda:None)
    probe=f.ActualEvents.__new__(f.ActualEvents);probe.out=tmp_path;probe.arm='P11';probe.saved=[];probe.scopes=[]
    try:
        with probe:
            assert capital.volatility_stop.__func__ is f.ActualEvents.risk_refusal
            assert probe.risk_original is original
            if fails:raise RuntimeError('synthetic financial refusal')
    except RuntimeError:assert fails
    assert capital.volatility_stop is original and runtime.advance is advance and terminal_module.apply_terminal is terminal
