"""Synthetic immutable-input checks; no historical strategy/account advancement."""
from dataclasses import asdict,dataclass
import hashlib,importlib.util,json,sys,threading
from pathlib import Path
import pytest

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('campaign_accel_pure',HERE/'system_campaign_acceleration.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_hash_is_reused_only_for_same_object_and_thread_and_restored():
    class State:
        def __init__(self,value):self.value=value;self.calls=0
        @property
        def state_hash(self):self.calls+=1;return hashlib.sha256(json.dumps(self.value).encode()).hexdigest()
    a,b=State({'nested':[1,2]}),State({'nested':[3]});original=State.__dict__['state_hash'];scope=m.ReadHashScope(State)
    expected=a.state_hash;scope.begin(a);assert a.state_hash==a.state_hash==expected and scope.hits==2
    before=b.calls;assert b.state_hash!=expected and b.calls==before+1
    observed=[];t=threading.Thread(target=lambda:observed.append(a.state_hash));t.start();t.join()
    assert observed==[expected] and scope.hits==2
    with pytest.raises(ValueError,match='OVERLAPPING'):scope.begin(a)
    scope.end();assert State.__dict__['state_hash'] is original and scope.checks==1
    before=a.calls;assert a.state_hash==expected and a.calls==before+1

def test_nested_prior_mutation_refuses_and_guard_removal_falsifier():
    class State:
        def __init__(self):self.nested={'x':[1]}
        @property
        def state_hash(self):return hashlib.sha256(json.dumps(self.nested).encode()).hexdigest()
    original=State.__dict__['state_hash'];a=State();scope=m.ReadHashScope(State);scope.begin(a);a.nested['x'].append(2)
    with pytest.raises(ValueError,match='NESTED_PRIOR_MUTATION'):scope.end()
    assert State.__dict__['state_hash'] is original
    source=(HERE/'system_campaign_acceleration.py').read_text();guard="        need(actual==expected,'NESTED_PRIOR_MUTATION')"
    assert source.count(guard)==1;namespace={'__name__':'removed_transaction_guard'}
    exec(compile(source.replace(guard,'        pass',1),'removed-transaction-guard','exec'),namespace)
    a=State();broken=namespace['ReadHashScope'](State);broken.begin(a);a.nested['x'].append(2);broken.end()
    assert State.__dict__['state_hash'] is original

def test_signal_shallow_copy_preserves_final_close_and_all_fields_or_falls_back():
    @dataclass
    class Bar:
        closes:object
        certified_signals:object
        eligible:bool
    class Signal:
        model_fields={'closes':None,'certified_signals':None,'eligible':None}
        @classmethod
        def model_validate(cls,value):return {**value,'closes':tuple(value['closes'])}
    calls=[]
    def old(cls,bar):
        calls.append(1);value=asdict(bar);value['closes']=value['closes'][-1:];return cls.model_validate(value)
    bar=Bar([float(i) for i in range(127)],(.1,.2,.3,.4),True);expected=old(Signal,bar);calls.clear()
    actual,fast=m.shallow_signal(Signal,bar,old);assert fast and actual==expected and not calls
    bar.certified_signals=[.1,.2,.3,.4];actual,fast=m.shallow_signal(Signal,bar,old);assert not fast and calls
    assert bar.closes==[float(i) for i in range(127)]
