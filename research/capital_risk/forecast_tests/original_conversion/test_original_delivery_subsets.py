"""Generic explicit delivery subset/composition DATA tests; no financial execution."""
import ast,csv,gzip,hashlib,io,json,math,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
P=Path(__file__).resolve().parent
C=P.parents[1]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas')):raise ImportError('BATCH_SOURCE_ONLY:'+fullname)
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
RAW=read(C/'system_campaign_financial_future.py');TREE=ast.parse(RAW);FN={n.name:n for n in TREE.body if isinstance(n,ast.FunctionDef)}

def ctor(name,cls):
    raw=read(C/(name+'.py'));tree=ast.parse(raw);cl=deepcopy(next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name==cls))
    cl.body=[n for n in cl.body if isinstance(n,ast.FunctionDef)and n.name=='__init__']
    ns=dict(Path=Path,__file__=str(C/(name+'.py')),json=json,need=need,sha=sha,digest=digest,deepcopy=deepcopy)
    exec(compile(ast.Module(body=[cl],type_ignores=[]),'<unchanged-original-factual-constructor>','exec'),ns)
    return ns[cls]

@pytest.fixture
def ns(monkeypatch):
    n=dict(Path=Path,__file__=str(C/'system_campaign_financial_future.py'),need=need,sha=sha,digest=digest,json=json,deepcopy=deepcopy,SimpleNamespace=SimpleNamespace,math=math)
    first=min(x.lineno for x in TREE.body if isinstance(x,ast.ClassDef));nodes=[x for x in TREE.body if isinstance(x,ast.Assign)and x.lineno<first]
    exec(compile(ast.Module(body=deepcopy(nodes),type_ignores=[]),'<literal-batch-source-configuration>','exec'),n);n['HERE']=C
    contract=next(x for x in TREE.body if isinstance(x,ast.Assign)and isinstance(x.targets[0],ast.Name)and x.targets[0].id=='ORIGINAL_CONTRACT_DELIVERY_PHASES')
    n['ORIGINAL_CONTRACT_DELIVERY_PHASES']=ast.literal_eval(contract.value)
    names=['original_phase_delivery_selection','original_delivery_selection','original_ordinary_selection','supplemental_selection','merge_selected_terms','catalog_terms','selected','suppressions','ordinary_term_dates','ordinary_identity','ordinary_delivery_identity','inherited_delivery_addition','remaining_ordinary_terms','contractual_delivery_selection']
    functions=[deepcopy(FN[x])for x in names]
    for fn in functions:
        if fn.name=='contractual_delivery_selection':
            fn.body=[x for x in fn.body if not isinstance(x,(ast.Import,ast.ImportFrom))]
    exec(compile(ast.Module(body=functions,type_ignores=[]),'<generic-original-source-functions>','exec'),n)
    constructors={'system_campaign_array_facts':'ArrayFacts','system_campaign_tableau_facts':'TableauFacts','system_campaign_distribution_facts':'DistributionFacts','system_campaign_parsley_facts':'ParsleyFacts'}
    modules={name:SimpleNamespace(**{cls:ctor(name,cls),'__file__':str(C/(name+'.py'))})for name,cls in constructors.items()}
    class Literal2021:
        def __init__(self,path):
            raw=read(path);self.catalog=json.loads(raw);self.catalog_sha=sha(raw);self.compiler_sha=sha(read(C/'system_campaign_2021_completions_facts.py'))
    modules['system_campaign_2021_completions_facts']=SimpleNamespace(CompletionFacts=Literal2021,__file__=str(C/'system_campaign_2021_completions_facts.py'))
    import importlib
    monkeypatch.setattr(importlib,'import_module',lambda name:modules[name])
    ordinary=n['original_ordinary_selection'];n['original_ordinary_selection']=lambda arm,cursor:None if arm=='P05'else ordinary(arm,cursor)
    def own(arm,cursor):
        raw=read(C/'system-campaign-selected-own-cash-terminal-facts.json');term,=[t for t in json.loads(raw)['terms']if(t['arm'],t['parent_cursor'])==(arm,cursor)]
        return SimpleNamespace(catalog={},catalog_sha=sha(raw),compiler_sha=sha(RAW)),'system-campaign-selected-own-cash-terminal-facts.json',[deepcopy(term)]
    n['own_cash_selection']=own
    return n


def strip(n,name,label):
    fn=deepcopy(FN[name])
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,x):
            if isinstance(x.value,ast.Call)and isinstance(x.value.func,ast.Name)and x.value.func.id=='need'and any(isinstance(a,ast.Constant)and a.value==label for a in x.value.args):self.count+=1;return ast.Pass()
            return self.generic_visit(x)
    change=Remove();fn=change.visit(fn);assert change.count==1;env=dict(n);exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-generic-source-guard>','exec'),env);return env[name]

def test_all_original_phase_delivery_components_aggregate(ns):
    codec,name,terms=ns['original_delivery_selection']('P03','2019-05-31')
    assert [t['ticker']for t in terms]==['LLL1','DATA','TCF1']and len(codec.ordinary_sources)==2
    assert name=='EXPLICIT_ORDERED_ORIGINAL_DELIVERY_COMPOSITION'
    assert [s['selected_tickers']for s in codec.ordinary_sources]==[['LLL1'],['DATA','TCF1']]
    assert all(t['added']['cash_per_share']is None and t['added']['cash_in_lieu_price_per_delivered_share']is None for t in terms)
    assert [t['added']['exchange_ratio']for t in terms]==[1.3,1.103,.5081]
    for source in codec.ordinary_sources:
        assert source['catalog_sha256']==sha(read(C/source['catalog_file']))and source['validator_sha256']==sha(read(C/source['validator_file']))
    assert codec.catalog_sha==digest(codec.composition)

def test_existing_PE_primary_eight_and_actual_Parsley_constructor_are_preserved(ns):
    primary=ns['selected']('P05',cursor='2020-12-31')[2];codec,name,extra=ns['original_delivery_selection']('P05','2020-12-31')
    assert type(codec).__name__=='ParsleyFacts'and [x['ticker']for x in primary]==['WPX','BEAT1','MIK','VAR','NAV','WORK','HOME','TRIL1']
    assert len(ns['merge_selected_terms'](primary,extra))==9 and extra[0]['ticker']=='PE'and extra[0]['added']['cash_per_share']is None
    assert 'selected_tickers'not in codec.ordinary_source

def test_eight_term_source_prefix_retains_unrelated_forward_input_bytes(ns,tmp_path):
    # A tiny unrelated forward-input fixture tests preservation without
    # importing or copying any financial book/state. It is not an actual seed.
    old_term=next(t for t in json.loads(read(C/'system-campaign-autumn2020-cash-terminal-facts.json'))['terms']if t['ticker']=='VRTU')
    doc=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='a'*64,
        suppress=[dict(session=old_term['native_session'],security_id=old_term['security_id'],term_sha256=old_term['native_term_sha256'])],add=[old_term['added']])
    raw=(json.dumps(doc,sort_keys=True,indent=2)+'\n').encode();digest_raw=sha(raw)
    folder=tmp_path/'book/repairs';folder.mkdir(parents=True);(folder/(digest_raw+'.json')).write_bytes(raw)
    cp=dict(source_cursor='2019-05-31',repairs=[dict(filename=digest_raw+'.json',sha256=digest_raw,predecessor_checkpoint_sha256='a'*64)])
    old={digest_raw+'.json':raw}
    h=FN['hydrate'];start=next(i for i,x in enumerate(h.body)if isinstance(x,ast.Assign)and any(isinstance(a,ast.Tuple)and [v.id for v in a.elts]==['codec','catalog','terms']for a in x.targets));end=next(i for i,x in enumerate(h.body)if isinstance(x,ast.Assign)and any(isinstance(a,ast.Name)and a.id=='actions'for a in x.targets))
    returned=ast.Tuple(elts=[ast.Name(id=x,ctx=ast.Load())for x in ('terms','ordinary_components','inherited_ordinary')],ctx=ast.Load())
    fn=ast.FunctionDef(name='prefix',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg=x)for x in ('cp','arm','source_root')],kwonlyargs=[],kw_defaults=[],defaults=[]),body=deepcopy(h.body[start:end])+[ast.Return(value=returned)],decorator_list=[],returns=None,type_comment=None)
    env=dict(ns);exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<exact-source-hydration-prefix>','exec'),env)
    terms,components,inherited=env['prefix'](cp,'P03',tmp_path)
    assert [t['ticker']for t in terms]==['KEYW','ARRY1','LLL1','DATA','TCF1','CTRL','UQM','BKS']and inherited==[]
    assert all((folder/name).read_bytes()==value for name,value in old.items())
    assert len(ns['suppressions'](cp,terms))==8
    assert sum(len({t['native_session'],t['added']['session']})for t in terms)==15
    assert [s['catalog_file']for s in components]==['system-campaign-array-terminal-facts.json','system-campaign-distribution-facts.json','system-campaign-tableau-terminal-facts.json','system-campaign-tableau-terminal-facts.json']
    assert all(x['ticker']not in ('APHA','NVS','OPLN')for x in terms)
    source_rows=json.loads(read(P/'p03-seven-source-rows.json'))['rows'];rows={(x['source_row']['session'],x['source_row']['security_id']):x['source_row']for x in source_rows}
    dates=json.loads(read(P/'p03-seven-source-rows.json'))['axis_sessions']
    original=deepcopy(terms)
    for t in terms:
        if 'identity_witness'not in t:
            t=ns['ordinary_term_dates'](t,dates);t['identity_witness']=ns['ordinary_identity'](t,rows[t['ordinary_identity_session'],t['security_id']])
        if t['added']['kind']=='CONVERSION':
            row=rows[t['proxy']['session'],t['proxy']['security_id']]
            t['delivered_identity_witness']=ns['ordinary_delivery_identity'](t,row)
            hydrated=ns['inherited_delivery_addition'](t,row)
            assert hydrated==dict(t['added'],cash_in_lieu_price_per_delivered_share=float(row['raw_open']))
            assert hydrated['cash_per_share']is None
    assert all(a['added']==b['added']for a,b in zip(terms,original))

@pytest.mark.parametrize('declared',[('APHA',),('LLL1','APHA')])
def test_contractual_zero_APHA_never_enters_proxy_fill_route(ns,declared):
    ns['ORIGINAL_DELIVERY_SUBSETS']['P03','2019-05-31','system-campaign-distribution-facts.json']=declared
    with pytest.raises(ValueError,match='UNCONSUMED_PROXY_DELIVERIES_ONLY'):ns['original_delivery_selection']('P03','2019-05-31')
    bad=strip(ns,'original_phase_delivery_selection','FUTURE_ORIGINAL_PHASE_UNCONSUMED_PROXY_DELIVERIES_ONLY')('P03','2019-05-31')[2]
    assert next(t for t in bad if t['ticker']=='APHA')['added']['cash_in_lieu_price_per_delivered_share']==0.

def test_omitted_subset_refuses_whole_distribution_catalog_with_fixed_zero(ns):
    del ns['ORIGINAL_DELIVERY_SUBSETS']['P03','2019-05-31','system-campaign-distribution-facts.json']
    with pytest.raises(ValueError,match='UNCONSUMED_PROXY_DELIVERIES_ONLY'):ns['original_delivery_selection']('P03','2019-05-31')

@pytest.mark.parametrize('subset',[('MISSING',),('DATA',),('LLL1','LLL1'),()])
def test_invalid_or_duplicate_declared_subsets_refused(ns,subset):
    ns['ORIGINAL_DELIVERY_SUBSETS']['P03','2019-05-31','system-campaign-distribution-facts.json']=subset
    with pytest.raises(ValueError,match='DELIVERY_SUBSET'):ns['original_delivery_selection']('P03','2019-05-31')

def test_catalog_pin_guard_removal(ns):
    plan=list(ns['ORIGINAL_DELIVERY_PHASES']['P03','2019-05-31']);first=list(plan[0]);first[-1]='0'*64;plan[0]=tuple(first);ns['ORIGINAL_DELIVERY_PHASES']['P03','2019-05-31']=tuple(plan)
    with pytest.raises(ValueError,match='DELIVERY_CATALOG_BYTES'):ns['original_delivery_selection']('P03','2019-05-31')
    # Two separate pins are intentional: removing the first still cannot admit it.
    with pytest.raises(ValueError,match='EXACT_CATALOG_VALIDATOR_BINDING'):strip(ns,'original_phase_delivery_selection','FUTURE_ORIGINAL_DELIVERY_CATALOG_BYTES')('P03','2019-05-31')

def test_duplicate_source_catalog_is_refused(ns):
    plans=ns['ORIGINAL_DELIVERY_PHASES']['P03','2019-05-31'];ns['ORIGINAL_DELIVERY_PHASES']['P03','2019-05-31']=plans+(plans[0],)
    with pytest.raises(ValueError,match='UNIQUE_DELIVERY_SOURCE_COMPONENTS'):ns['original_delivery_selection']('P03','2019-05-31')

@pytest.mark.parametrize('name',['numpy','pandas','stock_strategy_shared','sentinel','research.pooled_input_support'])
def test_import_fence(name):
    with pytest.raises(ImportError,match='SOURCE_ONLY'):Fence().find_spec(name)

def test_existing_fallback_and_financial_function_asts_are_preserved():
    # Compact AST pins replace an entire old-source adapter fixture.
    pins={'qualify': '508677c5937195baab1bccb94a9144a468addb586a32ce617219b52222719a70', 'document': '4d4c6723263a546ff8520784dfa128500c38282307439b69e1e20d291ec255c0', 'ActualEvents': 'f9f55b1c12791ca118d18a628940527144644072dfab059333ed9aa6b40f591c', 'selected': '553114b8851af04d5ede1a5b9cbf84014061250d79a39de1a4a0f4270b045ef0', 'remaining_ordinary_terms': '2a8c36f465544392e4f7b01837aca435bd8f1af31018924d36bcaf24c9e4334d', 'merge_selected_terms': 'bf445e83a13cde557f07a4d256cce6bae32c4219b9d4bb14a3521f2de109e4e4'}
    nodes={n.name:n for n in TREE.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    assert {n:sha(ast.dump(nodes[n],include_attributes=False).encode())for n in pins}==pins
    fallback=deepcopy(FN['original_delivery_selection']);fallback.body=[x for x in fallback.body if not isinstance(x,ast.If)]
    assert sha(ast.dump(fallback,include_attributes=False).encode())=='3454784368ea966acc856e8ff2797a7049c345b3cc37853fbe6bb25e61ffdd18'


def test_missing_declared_member_guard_removal_cannot_silently_shrink_subset(ns):
    ns['ORIGINAL_DELIVERY_SUBSETS']['P03','2019-05-31','system-campaign-distribution-facts.json']=('LLL1','MISSING')
    label='FUTURE_ORIGINAL_PHASE_EXACT_EXISTING_DELIVERY_SUBSET'
    with pytest.raises(ValueError,match=label):ns['original_delivery_selection']('P03','2019-05-31')
    result=strip(ns,'original_phase_delivery_selection',label)('P03','2019-05-31')
    assert [t['ticker']for t in result[2]]==['LLL1','DATA','TCF1']


def test_consumed_phase_native_guard_removal_refuses_retrospective_stock_input(ns):
    phase='P03','2019-06-28';ns['ORIGINAL_DELIVERY_PHASES'][phase]=ns['ORIGINAL_DELIVERY_PHASES']['P03','2019-05-31']
    for catalog in ('system-campaign-distribution-facts.json','system-campaign-tableau-terminal-facts.json'):
        ns['ORIGINAL_DELIVERY_SUBSETS'][phase+(catalog,)]=ns['ORIGINAL_DELIVERY_SUBSETS']['P03','2019-05-31',catalog]
    label='FUTURE_ORIGINAL_PHASE_UNCONSUMED_PROXY_DELIVERIES_ONLY'
    with pytest.raises(ValueError,match=label):ns['original_delivery_selection'](*phase)
    assert strip(ns,'original_phase_delivery_selection',label)(*phase)[2][0]['native_session']=='2019-06-28'


def test_validator_source_binding_guard_removal(ns,monkeypatch):
    import importlib
    original=importlib.import_module
    def module(name):
        value=original(name)
        if name!='system_campaign_tableau_facts':return value
        actual=value.TableauFacts
        class WrongCompiler(actual):
            def __init__(self,path):super().__init__(path);self.compiler_sha='0'*64
        return SimpleNamespace(TableauFacts=WrongCompiler,__file__=value.__file__)
    monkeypatch.setattr(importlib,'import_module',module)
    label='FUTURE_ORIGINAL_PHASE_EXACT_CATALOG_VALIDATOR_BINDING'
    with pytest.raises(ValueError,match=label):ns['original_delivery_selection']('P03','2019-05-31')
    result=strip(ns,'original_phase_delivery_selection',label)('P03','2019-05-31')
    assert result[0].ordinary_sources[-1]['validator_sha256']=='0'*64
