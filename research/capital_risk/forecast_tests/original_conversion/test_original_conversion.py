"""Portable source-only CONVERSION/primary-composition tests; no replay or state fixture."""
import ast
from copy import deepcopy
from dataclasses import asdict
from datetime import date
from fractions import Fraction
import gzip,hashlib,json,math,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
P=Path(__file__).resolve().parent
C=P.parents[1]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas')):raise ImportError('CONVERSION_DATA_ONLY:'+fullname)
@pytest.fixture(scope='module',autouse=True)
def fence_canonical_imports():
    fence=Fence();sys.meta_path.insert(0,fence)
    try:yield
    finally:sys.meta_path.remove(fence)

def read(p):return p.read_bytes()
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(v):return sha(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def need(v,label):
    if not v:raise ValueError(label)
SOURCE=read(C/'system_campaign_financial_future.py');TREE=ast.parse(SOURCE)
FUNCTIONS={n.name:n for n in TREE.body if isinstance(n,ast.FunctionDef)}
def namespace():
    ns=dict(Path=Path,__file__=str(C/'system_campaign_financial_future.py'),deepcopy=deepcopy,SimpleNamespace=SimpleNamespace,
            sha=sha,digest=digest,need=need,json=json,math=math,Fraction=Fraction,asdict=asdict)
    first=min(n.lineno for n in TREE.body if isinstance(n,ast.ClassDef))
    assigns=[n for n in TREE.body if isinstance(n,ast.Assign)and n.lineno<first]
    exec(compile(ast.Module(body=deepcopy(assigns),type_ignores=[]),'<literal-selector-source-metadata>','exec'),ns)
    ns['HERE']=C
    names=('catalog_terms','compose','original_delivery_selection','ordinary_term_dates','ordinary_identity','ordinary_delivery_identity','inherited_delivery_addition','remaining_ordinary_terms','merge_selected_terms','selected')
    exec(compile(ast.Module(body=[deepcopy(FUNCTIONS[n])for n in names],type_ignores=[]),'<source-only-conversion-selectors>','exec'),ns)
    ns['original_ordinary_selection']=lambda arm,cursor:None
    return ns

def removed(ns,name,label):
    fn=deepcopy(FUNCTIONS[name])
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,n):
            if isinstance(n.value,ast.Call)and isinstance(n.value.func,ast.Name)and n.value.func.id=='need'and any(isinstance(a,ast.Constant)and a.value==label for a in n.value.args):self.count+=1;return ast.Pass()
            return self.generic_visit(n)
    x=Remove();fn=x.visit(fn);assert x.count==1
    new=dict(ns);exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-conversion-input-guard>','exec'),new);return new[name]

@pytest.fixture(scope='module')
def data():
    raw=read(C/'system-campaign-parsley-terminal-facts.json');catalog=json.loads(raw)
    source=read(C/'system_campaign_parsley_facts.py');tree=ast.parse(source)
    cl=next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='ParsleyFacts')
    cl=deepcopy(cl);cl.body=[n for n in cl.body if isinstance(n,ast.FunctionDef)and n.name=='__init__']
    ns=dict(Path=Path,__file__=str(C/'system_campaign_parsley_facts.py'),json=json,need=need,sha=sha)
    exec(compile(ast.Module(body=[cl],type_ignores=[]),'<unchanged-original-Parsley-input-constructor>','exec'),ns)
    rows=json.loads(read(P/'pe-pxd-source-rows.json'))['rows'];parent,child=[v['source_row']for v in rows]
    return dict(catalog=catalog,term=catalog['terms'][0],parent=parent,child=child,ParsleyFacts=ns['ParsleyFacts'])

@pytest.fixture
def selected(data,monkeypatch):
    ns=namespace();import importlib
    class Literal2021:
        def __init__(self,path):
            raw=read(path);self.catalog=json.loads(raw);self.catalog_sha=sha(raw);self.compiler_sha=sha(read(C/'system_campaign_2021_completions_facts.py'))
    real=importlib.import_module
    def import_data(name):
        if name=='system_campaign_parsley_facts':return SimpleNamespace(ParsleyFacts=data['ParsleyFacts'],__file__=str(C/'system_campaign_parsley_facts.py'))
        if name=='system_campaign_2021_completions_facts':return SimpleNamespace(CompletionFacts=Literal2021,__file__=str(C/'system_campaign_2021_completions_facts.py'))
        raise AssertionError('Unexpected source module '+name)
    monkeypatch.setattr(importlib,'import_module',import_data)
    return ns

def test_primary_eight_and_PE_delivery_merge_without_altering_literals(selected,data):
    n=selected;codec,catalog,primary=n['selected']('P05',cursor='2020-12-31')
    dcodec,dcatalog,delivery=n['original_delivery_selection']('P05','2020-12-31')
    assert catalog=='system-campaign-2021-completions-terminal-facts.json'and len(primary)==8
    assert [v['ticker']for v in primary]==['WPX','BEAT1','MIK','VAR','NAV','WORK','HOME','TRIL1']
    assert [v['ticker']for v in delivery]==['PE']and delivery[0]['added']==data['term']['added']
    joined=n['merge_selected_terms'](primary,delivery);assert len(joined)==9 and len({t['security_id']for t in joined})==9
    assert joined[:8]==primary and joined[-1]['added']['cash_per_share']is None

def test_original_catalog_constructor_reused(selected,data):
    codec,_,terms=selected['original_delivery_selection']('P05','2020-12-31')
    assert isinstance(codec,data['ParsleyFacts'])and terms[0]['original_ordinary_source']['catalog_sha256']==sha(read(C/'system-campaign-parsley-terminal-facts.json'))
    assert terms[0]['original_ordinary_source']['validator_sha256']==sha(read(C/'system_campaign_parsley_facts.py'))

def test_declared_primary_guard_removal(selected):
    n=selected;n['FUTURE_LITERAL_PHASES']={};n['PLANS']['P05']=('system_campaign_2021_completions_facts','CompletionFacts','system-campaign-2021-completions-terminal-facts.json',('WPX','BEAT1','MIK','VAR','NAV','WORK','HOME','TRIL1'))
    label='FUTURE_COMPOSED_DELIVERY_REQUIRES_DECLARED_PRIMARY'
    with pytest.raises(ValueError,match=label):n['selected']('P05',cursor='2020-12-31')
    assert len(removed(n,'selected',label)('P05',cursor='2020-12-31')[2])==8

def test_source_catalog_pin_guard_removal(selected):
    n=selected;plan=list(n['ORIGINAL_DELIVERY_PHASES']['P05','2020-12-31'][0]);plan[-1]='0'*64;n['ORIGINAL_DELIVERY_PHASES']['P05','2020-12-31']=(tuple(plan),)
    label='FUTURE_ORIGINAL_DELIVERY_CATALOG_BYTES'
    with pytest.raises(ValueError,match=label):n['original_delivery_selection']('P05','2020-12-31')
    assert removed(n,'original_delivery_selection',label)('P05','2020-12-31')[2][0]['ticker']=='PE'

def test_consumed_native_refused_before_filtering(selected):
    n=selected;n['ORIGINAL_DELIVERY_PHASES']['P05','2021-01-12']=n['ORIGINAL_DELIVERY_PHASES']['P05','2020-12-31']
    with pytest.raises(ValueError,match='NO_CONSUMED_PENDING_NATIVE'):n['original_delivery_selection']('P05','2021-01-12')

def test_exact_full_row_only_fills_existing_CIL_proxy(selected,data):
    n=selected;t=deepcopy(data['term']);before=deepcopy(t)
    added=n['inherited_delivery_addition'](t,data['child'])
    assert t==before and added==dict(t['added'],cash_in_lieu_price_per_delivered_share=133.68000000000001)
    assert added['cash_per_share']is None and added['kind']=='CONVERSION'and Fraction(str(added['exchange_ratio']))==Fraction(313,2500)
    dated=n['ordinary_term_dates'](t,['2021-01-08','2021-01-11','2021-01-12','2021-01-13'])
    assert dated['ordinary_identity_session']=='2021-01-11'and dated['last_trading_session']=='2021-01-12'
    assert n['ordinary_identity'](dated,data['parent'])['source_observation_sha256']=='f7d7f88e1962914149faf636a71261b6e05afe22bd2eef5fd75b84a37f580bc0'

@pytest.mark.parametrize('field',['session','security_id','ticker','issuer_id','raw_open'])
def test_full_child_row_forgery_guard_removal(selected,data,field):
    n=selected;r=deepcopy(data['child']);r[field]='WRONG'if field!='raw_open'else'134'
    label='FUTURE_ORIGINAL_DELIVERY_EXACT_FROZEN_IDENTITY_AND_PROXY'
    with pytest.raises(ValueError,match=label):n['ordinary_delivery_identity'](data['term'],r)
    assert removed(n,'ordinary_delivery_identity',label)(data['term'],r)

def test_prior_mixed_kind_behavior_remains_supported(selected,data):
    n=selected;t=deepcopy(data['term']);t['added']['kind']='CASH_PLUS_STOCK';t['added']['cash_per_share']=2.5
    result=n['inherited_delivery_addition'](t,data['child']);assert result['cash_per_share']==2.5

@pytest.mark.parametrize('kind',['CASH_MERGER','SPINOFF'])
def test_non_delivery_proxy_refused(selected,data,kind):
    t=deepcopy(data['term']);t['added']['kind']=kind
    with pytest.raises(ValueError,match='EXACT_POSITIVE_RAW_OPEN'):selected['inherited_delivery_addition'](t,data['child'])

def inherited_fixture(n,data,tmp_path):
    t=deepcopy(data['term']);t['original_ordinary_source']={};addition=n['inherited_delivery_addition'](t,data['child'])
    d=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='a'*64,suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256'])],add=[addition])
    raw=json.dumps(d).encode();h=sha(raw);path=tmp_path/'book/repairs';path.mkdir(parents=True);(path/(h+'.json')).write_bytes(raw)
    cp=dict(source_cursor='2020-12-31',repairs=[dict(filename=h+'.json',sha256=h,predecessor_checkpoint_sha256='a'*64)])
    n['inherited_delivery_row']=lambda term:deepcopy(data['child'])
    return cp,t,path,d

def test_forward_conversion_already_adopted_is_preserved_exactly(selected,data,tmp_path):
    cp,t,path,d=inherited_fixture(selected,data,tmp_path);remaining,held=selected['remaining_ordinary_terms'](cp,[t],tmp_path)
    assert remaining==[]and len(held)==1 and held[0]['inherited_addition']==d['add'][0]and held[0]['inherited_date_and_reference_preserved']

@pytest.mark.parametrize('field',['cash_per_share','exchange_ratio','session'])
def test_inherited_economic_collision_guard_removal(selected,data,tmp_path,field):
    n=selected;cp,t,path,doc=inherited_fixture(n,data,tmp_path)
    doc['add'][0][field]=.01 if field=='cash_per_share'else.2 if field=='exchange_ratio'else'2020-12-30'
    raw=json.dumps(doc).encode();h=sha(raw);(path/(h+'.json')).write_bytes(raw);cp['repairs'][0].update(filename=h+'.json',sha256=h)
    label='FUTURE_INHERITED_ORDINARY_ONE_EQUIVALENT_FORWARD_EVENT'
    with pytest.raises(ValueError,match=label):n['remaining_ordinary_terms'](cp,[t],tmp_path)
    assert len(removed(n,'remaining_ordinary_terms',label)(cp,[t],tmp_path)[1])==1

@pytest.mark.parametrize('module',['numpy','pandas','stock_strategy_shared','sentinel','research.pooled_input_support'])
def test_import_fence(module):
    with pytest.raises(ImportError,match='DATA_ONLY'):Fence().find_spec(module)

def test_unchanged_packet_qualification_and_delegating_observer_asts():
    # Function pins replace a bulky old-module fixture; these functions remain
    # the existing canonical packet qualification and delegating observer.
    pins={'document': '4d4c6723263a546ff8520784dfa128500c38282307439b69e1e20d291ec255c0', 'qualify': '508677c5937195baab1bccb94a9144a468addb586a32ce617219b52222719a70', 'ActualEvents': 'f9f55b1c12791ca118d18a628940527144644072dfab059333ed9aa6b40f591c'}
    nodes={n.name:n for n in TREE.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    assert {name:sha(ast.dump(nodes[name],include_attributes=False).encode())for name in pins}==pins
    assert sha(read(C/'system-campaign-parsley-terminal-facts.json'))=='1983dd966359020fff66eccf6d6d3c22de12190c11f5a3019cafcbf80af0478d'
    assert sha(read(C/'system_campaign_parsley_facts.py'))=='06226522eb8bbaff769fc14c0d3a1fe701ac9735f23659f73c071aa2e69ab171'


def test_source_witness_collection_includes_original_conversion_proxy(selected,data):
    n=selected;t=deepcopy(data['term']);t['original_ordinary_source']={};t['ordinary_identity_session']='2021-01-11'
    fn=deepcopy(FUNCTIONS['hydrate']);start=next(i for i,x in enumerate(fn.body)if isinstance(x,ast.Assign)and any(isinstance(a,ast.Name)and a.id=='wanted'for a in x.targets));end=next(i for i,x in enumerate(fn.body[start:],start)if isinstance(x,ast.Assign)and any(isinstance(a,ast.Name)and a.id=='seen'for a in x.targets))
    fragment=deepcopy(fn.body[start:end])
    def collect(body):
        f=ast.FunctionDef(name='collect',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg='terms'),ast.arg(arg='actions')],kwonlyargs=[],kw_defaults=[],defaults=[]),body=body+[ast.Return(value=ast.Tuple(elts=[ast.Name(id='wanted',ctx=ast.Load()),ast.Name(id='ordinary_rows',ctx=ast.Load()),ast.Name(id='delivery_rows',ctx=ast.Load())],ctx=ast.Load()))],decorator_list=[],returns=None,type_comment=None)
        ns=dict(n,asdict=lambda value:'SYNTHETIC_NATIVE',digest=lambda value:t['native_term_sha256']if value=='SYNTHETIC_NATIVE'else digest(value))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[f],type_ignores=[])),'<source-witness-loop-only>','exec'),ns)
        native=SimpleNamespace(security_id=t['security_id'],completeness=lambda count:(False,'INCOMPLETE'))
        return ns['collect']([t],SimpleNamespace(terminal={t['native_session']:[native],t['added']['session']:[]}))
    wanted,ordinary,delivery=collect(deepcopy(fragment))
    assert set(wanted)=={('2021-01-11',t['security_id']),('2021-01-13',t['added']['delivered_security_id'])}and len(ordinary)==len(delivery)==1
    class BreakConversion(ast.NodeTransformer):
        count=0
        def visit_Tuple(self,x):
            if [getattr(v,'value',None)for v in x.elts]==['CASH_PLUS_STOCK','CONVERSION']:
                self.count+=1;x.elts=x.elts[:1]
            return self.generic_visit(x)
    change=BreakConversion();bad=[change.visit(deepcopy(x))for x in fragment];assert change.count==1
    assert collect(bad)[2]=={}
