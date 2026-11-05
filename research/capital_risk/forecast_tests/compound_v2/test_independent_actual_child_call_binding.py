"""Independent synthetic call-frame proof of unchanged proposed Observer.spin."""
import ast
from copy import deepcopy
from dataclasses import asdict
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).parent
SOURCE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import test_distribution_v2 as input_tests
import test_closed_distribution_v2 as closed_tests
m,s=input_tests.m,input_tests.s

def namespace():
    raw=(SOURCE/'system_campaign_financial_compound_runtime_v2.py').read_bytes();tree=ast.parse(raw)
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Observer')
    ns=dict(__name__='independent_observer_call_test',Path=Path,inspect=inspect,deepcopy=deepcopy,asdict=asdict,
        need=m.need,actual_role=m.actual_role,spin_postcondition=s.spin_postcondition)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<exact-proposed-observer-class>','exec'),ns)
    return ns,node

class Snapshot:
    def __init__(self,value):self.value=deepcopy(value)
    def to_dict(self):return deepcopy(self.value)

def fixture():
    ns,node=namespace();b,before,after,lb,la,audit,cost=closed_tests.child_fixture()
    for value in (before,after):value['episodes']['7'].update(slot_id=7,ticker='PPLI',entry_date='2021-04-13')
    state,ledger=Snapshot(before),Snapshot(lb);calls=[]
    observer=ns['Observer'](Path('.'),dict(binding=b));observer.current=dict(order=[],spin=None)
    spin=input_tests.Spin(**b['spin']);distributions=(spin,)
    bars=tuple(input_tests.vendor(v) for v in b['original_rows'].values());config=SimpleNamespace(transaction_cost_bps=cost)
    def delegated(actual_state,actual_distributions,*,bars,ledger,config):
        calls.append((actual_state,actual_distributions,bars,ledger,config))
        actual_state.value=deepcopy(after);ledger.value=deepcopy(la)
        return audit
    observer.spin_original=delegated
    def kernel(obs,current_state,current_distributions,opening_bars,current_ledger,cfg):
        pending=[]
        return obs.spin(current_state,current_distributions,bars=opening_bars,ledger=current_ledger,config=cfg)
    observer.kernel_code=kernel.__code__
    return ns,node,observer,state,distributions,bars,ledger,config,kernel,calls,audit

def test_exact_caller_delegates_once_and_validates_real_child_postconditions():
    ns,node,observer,state,dist,bars,ledger,cfg,kernel,calls,audit=fixture()
    result=kernel(observer,state,dist,bars,ledger,cfg)
    assert result is audit and len(calls)==1 and calls[0]==(state,dist,bars,ledger,cfg)
    assert observer.current['order']==['SPINOFF']
    assert observer.current['spin']==m.consideration(observer.binding,13,10)

def test_direct_non_kernel_call_refuses_before_original_is_called():
    ns,node,observer,state,dist,bars,ledger,cfg,kernel,calls,audit=fixture()
    before=state.to_dict(),ledger.to_dict()
    with pytest.raises(ValueError,match='ACTUAL_KERNEL_CHILD_CALL_ONLY'):
        observer.spin(state,dist,bars=bars,ledger=ledger,config=cfg)
    assert calls==[] and (state.to_dict(),ledger.to_dict())==before

def test_caller_guard_removal_falsifier():
    ns,node,observer,state,dist,bars,ledger,cfg,kernel,calls,audit=fixture()
    fn=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='spin')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='COMPOUND_V2_ACTUAL_KERNEL_CHILD_CALL_ONLY' for v in n.value.args))
    fn.body.remove(guard);exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<caller-guard-removed>','exec'),ns)
    pending=[]
    assert ns['spin'](observer,state,dist,bars=bars,ledger=ledger,config=cfg) is audit
    assert observer.current['order']==['SPINOFF'] and len(calls)==1

@pytest.mark.parametrize('change',['quantity','child_order','receipt','cash'])
def test_actual_parent_role_and_post_call_cash_falsifiers(change):
    ns,node,observer,state,dist,bars,ledger,cfg,kernel,calls,audit=fixture()
    if change=='quantity':state.value['episodes']['7']['current_shares']=14
    elif change=='child_order':
        # A forbidden child reservation is part of the exact original role guard.
        state.value['slots']['7']['reserved_for']=observer.binding['spin']['child_security_id']
    else:
        original=observer.spin_original
        def corrupt(*args,**kwargs):
            result=original(*args,**kwargs)
            if change=='receipt':kwargs['ledger'].value['events'][-2]['shares_delta']=22
            else:args[0].value['cash']+=1
            return result
        observer.spin_original=corrupt
    with pytest.raises(ValueError):kernel(observer,state,dist,bars,ledger,cfg)
    assert observer.current['order']==[]
