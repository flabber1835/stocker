"""Explicitly noncanonical joint-class DTOs verify new outer event boundaries."""
import ast,json,sys
from copy import deepcopy
from dataclasses import dataclass,make_dataclass,replace
from pathlib import Path
from types import SimpleNamespace
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P07_ABMD_CERTIFICATE_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(1,'C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
import system_campaign_p07_abmd_certificate as data
from system_campaign_uncertainty_math import Interval

@dataclass
class Published:
    session:str
    terminal_events:tuple
    bars:tuple=()

class SyntheticJoint:
    def __init__(self,*,seed):
        self.seed=seed;self.pending={};self.calls=[];self.math='NONCANONICAL_RETAINED_MATH'
        self.original_values=lambda **kwargs:{'SYNTHETIC_OTHER':1.}
    def append(self,*args):pass
    def relevant(self,*args):return {'legacy_zognix_guard':True}
    def values(self,**kwargs):self.calls.append('legacy_values');return {'legacy_value':True}
    def recover(self,**kwargs):self.calls.append('legacy_recover');self.pending['legacy_kept']=True;return {'synthetic':True}
    def advance(self,run,published):self.calls.append('legacy_advance');return run

@pytest.fixture
def actual():
    path=Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk/P07-own1238-ABMD-bounded-catalog-v2.json')
    c=json.loads(path.read_bytes());event=c['event'];source=c['market_source'];native=c['native']
    Native=make_dataclass('NoncanonicalNativeDTO',[(name,object) for name in native])
    Native.completeness=lambda self,mode:(False,'SYNTHETIC_INCOMPLETE')
    native=Native(**native)
    codec=SimpleNamespace(event=event,objects=[SimpleNamespace(event=SimpleNamespace(model_dump=lambda:deepcopy(event)))])
    witness=lambda *args,**kw:None
    def factory(**kw):
        return data.extend_joint(SyntheticJoint,kw.get('event',event),kw.get('source',source),kw.get('codec',codec),
            kw.get('native',native),witness=witness,interval_class=Interval)
    prior=SimpleNamespace(wealth_core={'episodes':{}},pending=[],median5={'selected':[data.SID]},last_processed_session=data.NATIVE,
        feed={'series':{data.SID:{'signal_basis_anchor':[data.NATIVE,float(source['raw_prior_row']['raw_close']),float(source['raw_prior_row']['signal_close'])]}}})
    pub=Published(data.DAY,(replace(native,session=data.DAY),))
    return SimpleNamespace(event=event,source=source,native=native,codec=codec,factory=factory,prior=prior,published=pub)

def test_new_outer_event_preserves_joint_append_old_recovery_and_old_advance(actual):
    cls=actual.factory();certificate=cls(seed=[{'session':'2022-11-30','synthetic':True}])
    assert cls.__mro__[1] is SyntheticJoint and cls.append is SyntheticJoint.append
    result=certificate.values(prior=actual.prior,published=actual.published)
    assert result=={'SYNTHETIC_OTHER':1.,data.SID:380.} and certificate.event_bounds.pair()==[380.,415.]
    before=certificate.math;assert certificate.recover(state={'last_session':data.DAY})=={'synthetic':True}
    assert certificate.pending['legacy_kept'] is True and certificate.pending['bounded_event_basis']['selected'] is True
    assert certificate.math==before
    run=SimpleNamespace(state=actual.prior);assert certificate.advance(run,actual.published) is run
    assert certificate.calls==['legacy_recover','legacy_advance']
    assert certificate.relevant(actual.prior,SimpleNamespace(day=data.DAY))['legacy_zognix_guard'] is True

def test_other_dates_delegate_to_original_joint(actual):
    certificate=actual.factory()(seed=[{'session':'2022-11-30','synthetic':True}])
    result=certificate.values(prior=actual.prior,published=replace(actual.published,session='2022-12-23'))
    assert result=={'legacy_value':True} and certificate.calls==['legacy_values']

def test_unselected_event_has_no_interval_or_portfolio_cash(actual):
    actual.prior.median5['selected']=[]
    certificate=actual.factory()(seed=[{'session':'2022-11-30','synthetic':True}])
    assert certificate.values(prior=actual.prior,published=actual.published)=={'SYNTHETIC_OTHER':1.}
    assert certificate.event_bounds is None and certificate.bounded_basis['selected'] is False

@pytest.mark.parametrize('change',['cash','upper','day','source_quote','split','native','empty_objects','owned','ordered','anchor','event_bar'])
def test_foreign_legal_source_codec_or_actual_event_preimage_refuses(actual,change):
    event=deepcopy(actual.event);source=deepcopy(actual.source);native=actual.native;codec=actual.codec
    if change=='cash':event['upfront_cash_per_share']='379.00'
    elif change=='upper':event['right_upper_per_share']='36.00'
    elif change=='day':event['effective_session']='2022-12-21'
    elif change=='source_quote':source['source_quote_present']=True
    elif change=='split':source['split_ratio']='2'
    elif change=='native':native=replace(native,reference='FOREIGN')
    elif change=='empty_objects':codec.objects=[]
    elif change=='owned':actual.prior.wealth_core['episodes']['1']={'security_id':data.SID}
    elif change=='ordered':actual.prior.pending=[{'security_id':data.SID}]
    elif change=='anchor':actual.prior.feed['series'][data.SID]['signal_basis_anchor'][1:]=[100.,100.]
    else:actual.published=replace(actual.published,bars=(SimpleNamespace(session=data.DAY,security_id=data.SID,split_ratio=1.),))
    with pytest.raises(ValueError):
        certificate=actual.factory(event=event,source=source,native=native,codec=codec)(seed=[{'session':'2022-11-30','synthetic':True}])
        certificate.values(prior=actual.prior,published=actual.published)

def test_missing_old_committed_seed_refuses(actual):
    with pytest.raises(ValueError,match='COMMITTED_SEED_REQUIRED'):actual.factory()(seed=[])

def test_both_pre_and_post_advance_unowned_guards_remain(actual,monkeypatch):
    cls=actual.factory();certificate=cls(seed=[{'session':'2022-11-30','synthetic':True}])
    run=SimpleNamespace(state=actual.prior)
    actual.prior.wealth_core['episodes']['1']={'security_id':data.SID}
    with pytest.raises(ValueError,match='MUST_NOT_BE_OWNED'):certificate.advance(run,actual.published)
    actual.prior.wealth_core['episodes']={}
    after=deepcopy(actual.prior);after.wealth_core['episodes']['1']={'security_id':data.SID}
    monkeypatch.setattr(SyntheticJoint,'advance',lambda self,run,published:SimpleNamespace(state=after))
    with pytest.raises(ValueError,match='MUST_NOT_BE_OWNED'):certificate.advance(run,actual.published)

def test_removing_actual_anchor_guard_accepts_wrong_source_and_is_detected(actual):
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='extend_joint')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,n):
            if isinstance(n.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value=='P07_ABMD_EXACT_ACTUAL_PRIOR_RAW_SIGNAL_ANCHOR' for v in n.value.args):self.hits+=1;return None
            return self.generic_visit(n)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-anchor-guard-synthetic-only>','exec'),scope)
    actual.prior.feed['series'][data.SID]['signal_basis_anchor'][1:]=[100.,100.]
    with pytest.raises(ValueError):actual.factory()(seed=[{'session':'2022-11-30','synthetic':True}]).values(prior=actual.prior,published=actual.published)
    cls=scope['extend_joint'](SyntheticJoint,actual.event,actual.source,actual.codec,actual.native,witness=lambda:None,interval_class=Interval)
    assert cls(seed=[{'session':'2022-11-30','synthetic':True}]).values(prior=actual.prior,published=actual.published)[data.SID]==380.

def test_runtime_factory_refuses_before_financial_imports(monkeypatch):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):data.certificate_class({},None,None,None,mixed=None,inherited_root=None)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
