"""Initial-certificate code objects and noncanonical sensor metadata DTOs only."""
import ast,json,sys
from copy import deepcopy
from dataclasses import dataclass,make_dataclass,replace
from pathlib import Path
from types import SimpleNamespace
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P06_INITIAL_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
D=Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk');sys.path[:0]=[str(Path(__file__).parent),str(D)]
import system_campaign_p06_abmd_initial_certificate as data

@dataclass(frozen=True)
class Published:
    session:str
    bars:tuple
    terminal_events:tuple

@pytest.fixture
def setup(monkeypatch,tmp_path):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    c=json.loads((D/'P06-own1238-ABMD-bounded-catalog-v2.json').read_bytes());n=c['native']
    Native=make_dataclass('SyntheticNativeMetadata',[(k,object) for k in n],frozen=True)
    Native.completeness=lambda self,count:(self.cash_per_share is not None,())
    native=Native(**n);codec=SimpleNamespace(event=c['event'],objects=[SimpleNamespace(event=SimpleNamespace(model_dump=lambda:c['event']))])
    cls=data.certificate_class(c['event'],c['market_source'],codec,native,inherited_root=D)
    obj=cls(tmp_path,codec,native,{},event_source=c['market_source'])
    obj.original_values=lambda *,prior,published:{'SYNTHETIC_OTHER':101.}
    selected=[data.SID,'SYNTHETIC_OTHER']
    prior=SimpleNamespace(not_canonical_state=True,wealth_core={'episodes':{}},pending=[],
        median5=dict(selected=selected),last_processed_session='2022-12-21',
        feed={'series':{data.SID:{'signal_basis_anchor':['2022-12-21',381.02,381.02]}}})
    packet=Published('2022-12-22',(),(replace(native,session='2022-12-22'),))
    return c,cls,obj,prior,packet,tmp_path

def test_initial_has_no_seed_and_all_date_bound_original_code_objects(setup):
    import system_campaign_financial_branches as branches
    import system_campaign_uncertainty_context as base
    c,cls,obj,prior,packet,tmp=setup
    assert obj.seed==[] and obj.math is obj.pending is None and not list(tmp.iterdir())
    for name,original in [('append',branches.Certificate.append),('original_bound_recover',branches.Certificate.recover),
                          ('original_bound_witness',base.SensorCertificate.witness)]:
        fn=getattr(cls,name);assert fn.__code__ is original.__code__ and fn.__globals__['DAY']=='2022-12-22'
    assert cls.original_bound_material.__code__ is base.return_material.__code__
    assert cls.original_bound_material.__globals__['SID']==data.SID

def test_prior_seed_is_explicitly_refused_without_staging(setup):
    c,cls,obj,prior,packet,tmp=setup
    with pytest.raises(ValueError,match='INITIAL_HAS_NO_PRIOR_B19_SEED'):
        cls(tmp,obj.codec,obj.native,{},seed=[{'synthetic_fake_prior':True}])
    assert not list(tmp.iterdir())

def test_original_seed_reader_is_bound_to_first_ABMD_day_and_actual_parent_has_no_prior_seed():
    import gzip
    import system_campaign_financial_branches as branches
    reader=data.seed_reader(inherited_root=D)
    assert reader.__code__ is branches.seed.__code__ and reader.__globals__['DAY']=='2022-12-22'
    folder=Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/financial-runs-20261104-281/capture-P06-13413225228-001')
    folder=Path('\\\\?\\'+str(folder.resolve()));manifest=json.loads((folder/'authenticated-manifest.json').read_bytes())['members']
    assert 'uncertainty-certificate.jsonl' not in manifest
    raw=(folder/'verified-output/book/checkpoint.json.gz').read_bytes()
    assert data.digest is not None and dict(bytes=len(raw),sha256=__import__('hashlib').sha256(raw).hexdigest())==manifest['book/checkpoint.json.gz']
    cp=json.loads(gzip.decompress(raw))
    assert reader(folder/'verified-output',cp)==[]

def test_selected_absent_quote_uses_entire380_to415_range_without_cash_settlement(setup):
    c,cls,obj,prior,packet,tmp=setup;result=obj.values(prior=prior,published=packet)
    assert result=={'SYNTHETIC_OTHER':101.,data.SID:380.}
    assert obj.event_bounds.pair()==[380.,415.] and obj.bounded_basis['selected'] is True
    assert obj.bounded_basis['raw_anchor']=='381.02' and obj.bounded_basis['split']=='1'
    assert not list(tmp.iterdir()) and prior.wealth_core=={'episodes':{}} and prior.pending==[]

@pytest.mark.parametrize('change',['owned','ordered','anchor','complete_native','quote','missing_commitment'])
def test_actual_source_position_and_commitment_guards_refuse(setup,change):
    c,cls,obj,prior,packet,tmp=setup
    if change=='owned':prior.wealth_core['episodes']['0']={'security_id':data.SID}
    elif change=='ordered':prior.pending.append({'security_id':data.SID})
    elif change=='anchor':prior.feed['series'][data.SID]['signal_basis_anchor'][1]=1.
    elif change=='complete_native':packet=replace(packet,terminal_events=(replace(packet.terminal_events[0],cash_per_share=380.),))
    elif change=='quote':packet=replace(packet,bars=(SimpleNamespace(security_id=data.SID,session='2022-12-22',split_ratio=1.),))
    else:obj.codec.objects=[]
    with pytest.raises(ValueError):obj.values(prior=prior,published=packet)

def test_unselected_event_starts_a_real_point_proof_without_fake_seed_or_event_price(setup):
    c,cls,obj,prior,packet,tmp=setup;prior.median5['selected']=['SYNTHETIC_OTHER']
    terminals=obj.values(prior=prior,published=packet)
    assert terminals=={'SYNTHETIC_OTHER':101.} and obj.event_bounds is None and obj.bounded_basis['selected'] is False
    state=dict(not_canonical_state=True,selected=['SYNTHETIC_OTHER'],selected_closes={'SYNTHETIC_OTHER':100.},witness_nav=[1.]*41)
    obj.original_witness=lambda state,**kw:(dict(state,witness_nav=state['witness_nav']+[1.01]),dict(recent_r20=.01,recent_r40=.01))
    result,observed=obj.witness(state,session='2022-12-22',closes={'SYNTHETIC_OTHER':101.},terminal_values=terminals)
    assert obj.seed==[] and obj.math.steps==1 and obj.material['rows']==[dict(security_id='SYNTHETIC_OTHER',prior=100.,current=[101.,101.])]
    assert obj.material['factor'][0]<=1.01<=obj.material['factor'][1] and obj.event_bounds is None
    assert not list(tmp.iterdir())

def test_unselected_point_initialization_cannot_skip_actual_event_basis(setup):
    c,cls,obj,prior,packet,tmp=setup
    state=dict(selected=['SYNTHETIC_OTHER'],selected_closes={'SYNTHETIC_OTHER':100.},witness_nav=[1.]*41)
    with pytest.raises(ValueError,match='UNSELECTED_POINT_INITIALIZATION_REQUIRES_ACTUAL_EVENT_BASIS'):
        obj.witness(state,session='2022-12-22',closes={'SYNTHETIC_OTHER':101.})
    assert obj.math is None

def test_before_event_witness_and_append_delegate_without_starting_old2019_clock(setup):
    c,cls,obj,prior,packet,tmp=setup;calls=[]
    obj.original_witness=lambda *a,**k:calls.append('WITNESS') or 'SYNTHETIC_DELEGATE'
    assert obj.witness({},session='2022-12-21')=='SYNTHETIC_DELEGATE' and obj.math is None
    obj.original_append=lambda *a:calls.append('APPEND') or 'SYNTHETIC_APPEND'
    assert obj.append(object(),'daily',{'session':'2022-12-21'})=='SYNTHETIC_APPEND'
    assert calls==['WITNESS','APPEND']

def test_removing_point_basis_guard_really_accepts_missing_event_and_is_detected(setup):
    c,cls,obj,prior,packet,tmp=setup
    tree=ast.parse(Path(data.__file__).read_bytes());fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='witness')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,n):
            if isinstance(n.value,ast.Call) and any(isinstance(x,ast.Constant) and x.value=='P06_ABMD_UNSELECTED_POINT_INITIALIZATION_REQUIRES_ACTUAL_EVENT_BASIS' for x in n.value.args):self.hits+=1;return None
            return self.generic_visit(n)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    fn.name='mutated_witness'
    from system_campaign_uncertainty_math import RollingWitnessBounds
    scope=dict(vars(data),day='2022-12-22',witness=cls.original_bound_witness,RollingWitnessBounds=RollingWitnessBounds)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-point-case-guard-synthetic-only>','exec'),scope)
    state=dict(selected=['SYNTHETIC_OTHER'],selected_closes={'SYNTHETIC_OTHER':100.},witness_nav=[1.]*41)
    obj.original_witness=lambda state,**kw:(dict(state,witness_nav=state['witness_nav']+[1.01]),dict(recent_r20=.01,recent_r40=.01))
    with pytest.raises(ValueError):obj.witness(state,session='2022-12-22',closes={'SYNTHETIC_OTHER':101.})
    scope['mutated_witness'](obj,state,session='2022-12-22',closes={'SYNTHETIC_OTHER':101.})
    assert obj.math.steps==1

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
