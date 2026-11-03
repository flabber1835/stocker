"""Pure math, source AST and synthetic episodes; no strategy runtime imports."""
import ast
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import sys
from types import SimpleNamespace,ModuleType

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import discovery_approximations as policy
import system_campaign_discovery_suffix_run as run
import system_campaign_discovery_suffix_parent as parent


@pytest.mark.parametrize('holdings,target',[
    ([(0,1),(1,1),(2,1)],1), ([(0,3),(1,7)],4),
    ([(0,.1),(1,.2),(2,3.7)],1), ([(0,1),(1,1),(2,1)],0),
    ([(n,1) for n in range(144)],79), ([(0,.0000000000001),(1,3)],1)])
def test_allocation_conserves_every_original_share_and_holder_target(holdings,target):
    rows,proof=policy.allocate_trim(holdings,target)
    assert sum(Fraction(str(r)) for _,r,_ in rows)==target
    assert all(Fraction(str(r))+Fraction(str(s))==Fraction(str(q))
               for (_,r,s),(_,q) in zip(rows,holdings,strict=True))
    assert all(0<=Fraction(str(r))<=Fraction(str(q)) for (_,r,_),(_,q) in zip(rows,holdings,strict=True))
    assert policy.allocate_trim(holdings,target)==(rows,proof)


def test_known_old_one_third_refusal_and_approved_rounding_only_on_representation():
    with pytest.raises(ValueError,match='REFUSED_TRIM_QUANTITY_REPRESENTATION'):
        policy.exact_number(Fraction(1,3))
    rows,proof=policy.allocate_trim([(0,1),(1,1),(2,1)],1)
    assert proof['rounded'] and proof['decimal_places']==12
    assert rows[0][1] > rows[1][1] == rows[2][1]
    assert not policy.allocate_trim([(0,1),(1,1)],1)[1]['rounded']
    def bad(value): raise ValueError('SYNTHETIC_OTHER_INVARIANT')
    with pytest.raises(ValueError,match='SYNTHETIC_OTHER_INVARIANT'):
        policy.allocate_trim([(0,1),(1,1),(2,1)],1,exact=bad)


def test_allocator_uses_real_exact_guard_and_no_broken_conservation_fallback():
    # A deliberately defective representation callback is still caught by the
    # independent conservation predicates, rather than accepted as rounding.
    with pytest.raises(ValueError,match='EXACT_HOLDER_CONSERVATION'):
        policy.allocate_trim([(0,1),(1,1),(2,1)],1,exact=lambda v:round(float(v),2))
    # Remove the actual conservation assertion and prove this same falsifier
    # becomes an invalid accepted allocation. Compile only the pure allocator.
    fn,=[n for n in ast.parse(Path(policy.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='allocate_trim']
    nested,=[n for n in fn.body if isinstance(n,ast.FunctionDef) and n.name=='checked']
    nested.body=[n for n in nested.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and len(n.value.args)==2 and isinstance(n.value.args[1],ast.Constant)
        and n.value.args[1].value=='DIAGNOSTIC_ALLOCATION_EXACT_HOLDER_CONSERVATION')]
    scope=dict(vars(policy));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<pure-guard-removal-falsifier>','exec'),scope)
    rows,_=scope['allocate_trim']([(0,1),(1,1),(2,1)],1,exact=lambda v:round(float(v),2))
    assert sum(Fraction(str(r)) for _,r,_ in rows)!=1


@dataclass
class Episode:
    security_id:str='SYNTHETIC'
    current_shares:float=3.
    exit_pending:bool=False
    research_stop_floor:float=10.
    research_stop_cursor:str='2020-01-02'


def missing(ep,**kwargs):raise ValueError('REFUSED_VOLATILITY_CAUSAL_AXIS')
def carry():return dict(source_stale_raw_close=12.,source_print_session='2020-01-02')
def call(original=missing,**kwargs):
    values=dict(episode=Episode(),bars=[],session='2020-01-03',cfg=None,carried=carry(),emit=lambda *a:None)
    values.update(kwargs);return policy.unknown_stop(original,**values)


def test_unknown_stop_preserves_full_episode_and_records_unknown():
    ep=Episode();before=deepcopy(ep);events=[]
    assert call(episode=ep,emit=lambda *a:events.append(a)) is False
    assert ep==before and len(events)==1 and events[0][0]['research_stop_floor']==10.


@pytest.mark.parametrize('bad',[
    None,dict(source_stale_raw_close=0.,source_print_session='2020-01-02'),
    dict(source_stale_raw_close=12.,source_print_session='2020-01-03')])
def test_unknown_stop_refuses_unproved_or_current_dated_carry(bad):
    with pytest.raises(ValueError,match='POSITIVE_DATED_PRIOR_SOURCE_MARK'):call(carried=bad)


def test_existing_bar_and_unrelated_refusal_are_never_swallowed():
    def other(ep,**kwargs):raise ValueError('SYNTHETIC_MALFORMED_WINDOW')
    with pytest.raises(ValueError,match='SYNTHETIC_MALFORMED_WINDOW'):
        call(other,bars=[SimpleNamespace(security_id='SYNTHETIC')])
    with pytest.raises(ValueError,match='EXACT_ORIGINAL_REFUSAL'):call(other)
    with pytest.raises(ValueError,match='ORIGINAL_DID_NOT_REFUSE'):call(lambda *a,**k:False)
    def mutated(ep,**kwargs):ep.research_stop_floor=0.;missing(ep)
    with pytest.raises(ValueError,match='ENTIRE_EPISODE_FLOOR_AND_CURSOR_UNCHANGED'):call(mutated)


def test_missing_provenance_guard_removal_is_detected():
    fn,=[n for n in ast.parse(Path(policy.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='unknown_stop']
    fn.body=[n for n in fn.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and len(n.value.args)==2 and isinstance(n.value.args[1],ast.Constant)
        and n.value.args[1].value=='DIAGNOSTIC_UNKNOWN_STOP_POSITIVE_DATED_PRIOR_SOURCE_MARK')]
    scope=dict(vars(policy));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<pure-stop-guard-removal-falsifier>','exec'),scope)
    assert scope['unknown_stop'](missing,Episode(),bars=[],session='2020-01-03',cfg=None,carried=None,emit=lambda *a:None) is False


def test_exact_zip_members_refuse_extra_duplicate_and_wrong_bytes(tmp_path):
    import zipfile,hashlib
    path=tmp_path/'synthetic.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr('public.json',b'SYNTHETIC_PUBLIC')
    spec=dict(zip_members={'public.json':dict(bytes=16,sha256=hashlib.sha256(b'SYNTHETIC_PUBLIC').hexdigest())},
              encrypted_output=dict(name='synthetic.crseal'))
    spec['zip_members']['public.json']['bytes']=len(b'SYNTHETIC_PUBLIC')
    with zipfile.ZipFile(path) as z:assert parent.zip_valid(z,spec)
    spec['zip_members']['public.json']['sha256']='0'*64
    with zipfile.ZipFile(path) as z:
        with pytest.raises(ValueError,match='OTHER_ZIP_ASSET_BYTES'):parent.zip_valid(z,spec)
    with zipfile.ZipFile(path,'a') as z:z.writestr('extra',b'SYNTHETIC')
    with zipfile.ZipFile(path) as z:
        with pytest.raises(ValueError,match='COMPLETE_SELECTED_ZIP_MEMBER_SET'):parent.zip_valid(z,spec)


def test_actual_planner_ast_changes_only_allocation_and_zero_lot_outcomes():
    raw=Path(policy.__file__).with_name('core_policy.py').read_bytes()
    old,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='trim_decisions']
    actual=policy.trim_tree(raw);body=ast.unparse(actual)
    assert 'diagnostic_plan(episodes, target, total)' in body
    assert 'if sold == 0:' in body and 'if remain == 0:' in body
    for guard in ['REFUSED_TRIM_UNRESOLVED_EQUITY','REFUSED_TRIM_CURRENT_RAW_MARK','REFUSED_TRIM_PRICE_DOMAIN_MISMATCH']:
        assert guard in body
    # Restore the three declared AST sites and compare the entire real planner.
    allocation,=[n for n in ast.walk(old) if isinstance(n,ast.For) and ast.unparse(n.target)=='(slot, ep)' and ast.unparse(n.iter)=='episodes']
    class Undo(ast.NodeTransformer):
        def visit_Assign(self,node):
            if ast.unparse(node)=='plans = diagnostic_plan(episodes, target, total)':return deepcopy(allocation)
            return self.generic_visit(node)
        def visit_For(self,node):
            if ast.unparse(node.target)=='(slot, ep, remain, sold)':
                node.body=node.body[1:]
                zero,=[n for n in node.body if isinstance(n,ast.If) and ast.unparse(n.test)=='remain == 0']
                zero.test=ast.parse('target == 0',mode='eval').body
            return self.generic_visit(node)
    assert ast.dump(Undo().visit(actual),include_attributes=False)==ast.dump(old,include_attributes=False)


@pytest.mark.parametrize('arm',['P09','P10','P11'])
def test_selected_real_replay_ast_native_horizon_and_carrier_only(arm):
    from system_campaign_discovery_suffix_replay import proven,original,suffix_tree
    spec=parent.specification(arm);raw=proven.exact_raw(original)
    actual=run.selected_tree(raw,spec);compile(actual,'<source-only-no-execution>','exec')
    assert f"Execution('FAST', signal_closes={spec['native_horizon']})" in ast.unparse(actual)
    class Undo(ast.NodeTransformer):
        def visit_Call(self,node):
            if ast.unparse(node.func)=='Execution':node.keywords[0].value=ast.Constant(1)
            return self.generic_visit(node)
        def visit_FunctionDef(self,node):
            if node.name=='checkpoint':node.body=[n for n in node.body if ast.unparse(n)!='value = bind_selected_checkpoint(value, context)']
            return self.generic_visit(node)
    assert ast.dump(Undo().visit(actual),include_attributes=False)==ast.dump(suffix_tree(raw),include_attributes=False)


def test_policy_cannot_claim_financial_authority_or_other_arm():
    from pydantic import ValidationError
    for extra in [dict(financial_authority=True),dict(arm='P01'),dict(account_performance_computed=True)]:
        values=dict(arm='P09',native_risk_source_sha256='a'*64,implementation_sha256='b'*64);values.update(extra)
        with pytest.raises(ValidationError):policy.DiscoveryPolicy(**values)


def test_approved_hook_host_fence_and_restoration_on_exit_and_failed_install(tmp_path,monkeypatch):
    import hashlib
    import full_system_core
    class Base:
        def __init__(self,*args,**kwargs):self.saved=[];self.current=None
        def __enter__(self):self.stream=SimpleNamespace(close=lambda:None);return self
        def __exit__(self,*args):self.restore()
        def patch(self,owner,name,value):self.saved.append((owner,name,getattr(owner,name)));setattr(owner,name,value)
        def restore(self):
            for owner,name,value in reversed(self.saved):setattr(owner,name,value)
            self.saved=[]
    source=tmp_path/'synthetic_risk.py';source.write_text('# SYNTHETIC STUB ONLY\n')
    risk=ModuleType('stock_strategy_shared.wealth_core.capital_risk')
    risk.__file__=str(source);risk.volatility_stop=missing;risk.V_PROFILE='SYNTHETIC'
    outer=ModuleType('stock_strategy_shared');inner=ModuleType('stock_strategy_shared.wealth_core');inner.capital_risk=risk
    monkeypatch.setitem(sys.modules,'stock_strategy_shared',outer);monkeypatch.setitem(sys.modules,'stock_strategy_shared.wealth_core',inner)
    selected=policy.DiscoveryPolicy(arm='P11',native_risk_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        implementation_sha256=hashlib.sha256(Path(policy.__file__).read_bytes()).hexdigest())
    def refused():raise ValueError('SYNTHETIC_NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refused)
    with pytest.raises(ValueError,match='SYNTHETIC_NOT_HOSTED'):
        with policy.context_class(Base,selected)():pass
    assert risk.volatility_stop is missing
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    with pytest.raises(RuntimeError,match='SYNTHETIC_BODY_FAILURE'):
        with policy.context_class(Base,selected)():
            assert risk.volatility_stop is not missing
            raise RuntimeError('SYNTHETIC_BODY_FAILURE')
    assert risk.volatility_stop is missing
    with pytest.raises(ValueError,match='EXACT_APPROVED_POLICY_IMPLEMENTATION'):
        with policy.context_class(Base,selected.model_copy(update={'implementation_sha256':'0'*64}))():pass
    assert risk.volatility_stop is missing
