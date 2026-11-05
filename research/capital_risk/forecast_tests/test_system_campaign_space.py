"""No prices or portfolio transitions: identities, inactive dimensions and material."""
from dataclasses import dataclass,asdict
from copy import deepcopy
import pytest
from system_campaign_space import DEFAULT,canonical,initial,universe,digest
from system_campaign_acceleration import shallow_signal

def test_initial_batch_is_unique_and_covers_named_families():
    first=initial();assert first==initial() and len(first)==12 and len({r['id'] for r in first})==12
    assert {r['parameters']['family'] for r in first}=={'CORE','C','V'} and first[0]['parameters']==DEFAULT
    pool=universe();assert len(pool)==len({r['id'] for r in pool})==4096

def test_inactive_parameters_do_not_create_fake_economic_settings():
    p={**DEFAULT,'c_trigger':.10,'c_target':.08,'v_horizon':42,'v_multiplier':3.,'v_minimum':.20,'v_maximum':.40}
    assert canonical(p)==DEFAULT
    with pytest.raises(ValueError):canonical({**DEFAULT,'family':'C','c_trigger':.08,'c_target':.10})
    with pytest.raises(ValueError):canonical({**DEFAULT,'slots':True})

def test_faithful_risk_material_preserves_configured_volatility_horizon():
    @dataclass
    class Bar:
        closes:object
        signal_sessions:object
    class Signal:
        model_fields={'closes':None,'signal_sessions':None}
        @classmethod
        def model_validate(cls,value):return {**value,'closes':tuple(value['closes'])}
    for horizon in (10,21,42):
        bar=Bar(list(range(127)),tuple(range(horizon)))
        def original(cls,value):
            d=asdict(value);d['closes']=d['closes'][-horizon:];return cls.model_validate(d)
        value,fast=shallow_signal(Signal,bar,original,keep=horizon)
        assert fast and value==original(Signal,bar) and len(value['closes'])==horizon
        wrong,_=shallow_signal(Signal,bar,original,keep=1);assert wrong!=value
