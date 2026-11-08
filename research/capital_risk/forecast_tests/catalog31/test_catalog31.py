"""Portable source/metadata/constructor tests; no financial imports or replay."""
import ast
import builtins
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator

HERE=Path(__file__).parent
DEFAULT=HERE.parents[1]
C=Path(os.environ.get('P06_CATALOG31_SOURCE_DIR',str(DEFAULT)))
B=Path(os.environ.get('P06_CATALOG31_BASE_DIR',str(C)))
SHARED=Path(os.environ.get('P06_CATALOG31_SHARED_DIR',str(C)))
FUTURE=C/'system_campaign_financial_future.py'
CATALOG=C/'system-campaign-selected-own-cash-terminal-facts.json'
FIXTURE=HERE/'fixtures/source279-catalog31.json'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
enc=lambda value:(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
digest=lambda value:sha(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())

class Overlay:
    def __truediv__(self,name):
        for root in (C,B,SHARED):
            if(root/name).exists():return root/name
        return SHARED/name

def source(name):return Overlay()/name

def helper():
    path=source('forecast_tests/test_research_unheld_cash_source.py')
    spec=importlib.util.spec_from_file_location('catalog31_closed_p05_pure_loader',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.C=Overlay();module.FUTURE=FUTURE;module.CATALOG=CATALOG
    return module

@pytest.fixture
def data():
    fixture=json.loads(FIXTURE.read_bytes());h=helper();n=h.load()
    def root_spec(arm,pin):
        value=fixture['root_metadata'][pin];assert value['arm']==arm
        return deepcopy(value)
    n.update(root_spec=root_spec,calendar=SimpleNamespace(__file__=str(source('system_campaign_cash_calendar.py'))),
        PREOPEN='CONFIRMED_PREOPEN_COMPLETION',NEXT='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY')
    astnode=ast.parse(fixture['original_validate_term_source']).body[0]
    assert sha(ast.dump(astnode,include_attributes=False).encode())==fixture['original_validate_term_AST_sha256']
    exec(compile(ast.Module(body=[astnode],type_ignores=[]),'<unchanged-original-cash-validator>','exec'),n)
    return n,fixture,h

@pytest.fixture(autouse=True)
def fence():
    import sys
    guard=helper().Fence();sys.meta_path.insert(0,guard)
    yield
    sys.meta_path.remove(guard)

def test_all30_records_and_envelope_are_exact(data):
    n,f,h=data;catalog=json.loads(CATALOG.read_bytes())
    assert len(catalog['terms'])==31
    assert sha(enc(dict(catalog,terms=catalog['terms'][:30])))==f['previous_catalog_sha256']=='5951b1ffa420910291a756b31b0a9a324ace68f4af77c854a9cc71a71b3115a5'
    assert sha(enc(dict(catalog,terms=catalog['terms'][:29])))==f['previous_catalog29_sha256']
    assert catalog['terms'][-1]['ticker']=='XENT' and catalog['terms'][-2]['ticker']=='UFS'

def test_only_opted_in_branch_changes_and_alias_functions_stay_exact(data):
    n,f,h=data;nodes={x.name:x for x in ast.parse(FUTURE.read_bytes()).body if isinstance(x,(ast.FunctionDef,ast.ClassDef))}
    for name,pin in f['base_function_AST_sha256'].items():
        if name!='supplemental_selection':assert sha(ast.dump(nodes[name],include_attributes=False).encode())==pin,name
    changed=deepcopy(nodes['supplemental_selection'])
    class Historical(ast.NodeTransformer):
        def visit_If(self,node):
            if 'SUPPLEMENTAL_SHARED_VALIDATOR_PHASES'in ast.unparse(node.test):return node.orelse
            return self.generic_visit(node)
    historical=Historical().visit(changed)
    assert ast.dump(historical,include_attributes=False)==ast.dump(ast.parse(f['original_supplemental_selection_source']).body[0],include_attributes=False)
    assert n['SUPPLEMENTAL_SHARED_VALIDATOR_PHASES']==frozenset({('P06','2022-04-29')})
    assert n['SUPPLEMENTAL_SAME_DAY_PHASES']==frozenset({('P05','2021-10-29'),('P06','2022-04-29')})

def test_actual_xent_source_and_root_selection(data):
    n,f,h=data;codec,name,terms=n['own_cash_selection']('P06','2022-04-29');term,=terms
    source_term,=[t for t in f['source_payload']['terms']if t['native_term']['security_id']==term['security_id']]
    assert term['native']==source_term['native_term'] and term['identity_witness']==source_term['identity_witness']
    assert term['parent_positions']==source_term['parent_positions']==[]
    assert term['source_capture']['payload_sha256']==f['source_payload_sha256']==sha(enc(f['source_payload']))
    assert term['source_capture']['independent_data_review_sha256']==f['source_review_sha256']==sha(enc(f['source_review']))
    assert term['source_capture']['independent_qualification_sha256']==f['source_qualification_sha256']==sha(enc(f['source_qualification']))
    assert term['added']['cash_per_share']==28.25 and term['added']['session']=='2022-05-13'
    assert term['native_session']==term['last_trading_session']=='2022-05-12'
    assert term['parent_root_admission_sha256']=='492d237b92b995ee1fdc1f6e81049f62688df5981cd5b72f493245c695fb6fc9'
    assert f['current_roots']['P07']=='532e1e4ca1317d3631235cb0316860112a355ab1b4cf4f61704f5583245540fd'

def bind_catalog(n,h,catalog,*,remove=None,repin=False):
    raw=enc(catalog)
    target=n if remove is None else h.load(remove=remove)
    class Files:
        def __truediv__(self,name):
            return SimpleNamespace(read_bytes=lambda:raw)if name==n['OWN_CASH_CATALOG']else source(name)
    target.update(HERE=Files(),root_spec=n['root_spec'],validate_term=n['validate_term'],calendar=n['calendar'],
        PREOPEN=n['PREOPEN'],NEXT=n['NEXT'])
    if repin:target['OWN_CASH_SHA']=sha(raw)
    return target

def test_catalog_hash_guard_removal_admits_changed_new_cash(data):
    n,f,h=data;bad=json.loads(CATALOG.read_bytes());bad['terms'][-1]['added']['cash_per_share']=28.26
    with pytest.raises(ValueError,match='EXACT_REVIEWED_LITERAL_CATALOG'):bind_catalog(n,h,bad)['own_cash_selection']('P06','2022-04-29')
    mutant=bind_catalog(n,h,bad,remove='OWN_CASH_EXACT_REVIEWED_LITERAL_CATALOG')
    assert mutant['own_cash_selection']('P06','2022-04-29')[2][0]['added']['cash_per_share']==28.26

def test_closed30_generation_still_refuses_changed_older_bytes(data):
    n,f,h=data;bad=json.loads(CATALOG.read_bytes());bad['terms'][0]['unauthorized_annotation']='changed'
    with pytest.raises(ValueError,match='CLOSED_CATALOG_GENERATION_BYTES'):
        bind_catalog(n,h,bad,repin=True)['own_cash_selection']('P06','2022-04-29')

@pytest.mark.parametrize('field',['parent_outer_sha256','native_term_sha256','identity_session','source_head'])
def test_exact_new_source_and_root_binding(data,field):
    n,f,h=data;bad=json.loads(CATALOG.read_bytes());term=bad['terms'][-1]
    if field=='identity_session':term['identity_witness']['session']='2022-05-10'
    elif field=='source_head':term['source_capture']['head']='0'*40
    else:term[field]='0'*64
    with pytest.raises(ValueError,match='CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE'):
        bind_catalog(n,h,bad,repin=True)['own_cash_selection']('P06','2022-04-29')

def test_root_binding_guard_removal_is_meaningful(data):
    n,f,h=data;bad=json.loads(CATALOG.read_bytes());bad['terms'][-1]['parent_outer_sha256']='0'*64
    with pytest.raises(ValueError,match='CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE'):
        bind_catalog(n,h,bad,repin=True)['own_cash_selection']('P06','2022-04-29')
    mutant=bind_catalog(n,h,bad,remove='OWN_CASH_EXACT_CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE',repin=True)
    assert mutant['own_cash_selection']('P06','2022-04-29')[2][0]['parent_outer_sha256']=='0'*64

def test_registry50_and_prior_metadata_are_unchanged(data):
    n,f,h=data;saved=h.FUTURE;h.FUTURE=B/'system_campaign_financial_future.py'
    old=h.load();h.FUTURE=saved
    for key in ('WITNESS_SCOPE_REGISTRY','ACTIVE_WITNESS_SCOPES','WITNESS_SCOPES','ROOT_BOUND_ALIAS_SOURCE_PHASES'):
        assert n[key]==old[key]
    assert len(n['WITNESS_SCOPE_REGISTRY'])==50
    for key in ('OWN_CASH_PHASES','CASH_GENERATION_LENGTHS','OWN_CASH_SOURCE_CLOCKS','SUPPLEMENTAL_PHASES','CLOSED_CASH_GENERATIONS'):
        assert all(n[key][phase]==value for phase,value in old[key].items())

def test_parent_MIME38_and_all_seven_inputs_remain_context_only(data):
    n,f,h=data;mime,=[t for t in f['source_payload']['terms']if t['identity_witness']['ticker']=='MIME']
    assert mime['parent_positions']==[dict(slot_id=26,ticker='MIME',quantity=38,entry_date='2022-04-01')]
    assert len(f['inherited_input_commitments'])==7
    assert all(row['descriptor']['sha256']==row['sha256']for row in f['inherited_input_commitments'])
    assert n['OWN_CASH_PHASES']['P06','2022-04-29']=='XENT'

def original_module(n,f):
    # Exact original pure constructor; methods that hydrate finance are absent.
    node=ast.parse(f['original_init_source']).body[0]
    klass=ast.ClassDef(name='CashCalendar',bases=[],keywords=[],body=[node],decorator_list=[])
    env=dict(n,__file__=str(source('system_campaign_cash_calendar.py')),
        registrations=lambda:json.loads(source('system-campaign-ordinary-catalog-registry.json').read_bytes())['groups'])
    ordinary=SimpleNamespace(registrations=env['registrations'])
    def pure_import(name,*args,**kwargs):
        if name=='system_campaign_ordinary_registry':return ordinary
        return builtins.__import__(name,*args,**kwargs)
    env['__builtins__']={**vars(builtins),'__import__':pure_import}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[klass],type_ignores=[])),'<exact-original-cash-constructor>','exec'),env)
    return SimpleNamespace(__file__=str(source('system_campaign_cash_calendar.py')),CashCalendar=env['CashCalendar'])

def importers(n,f,modules=None):
    if 'validate_term'not in n:
        n.update(PREOPEN='CONFIRMED_PREOPEN_COMPLETION',NEXT='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY')
        exec(f['original_validate_term_source'],n)
    module=original_module(n,f)
    n['importlib']=SimpleNamespace(import_module=lambda name:module if modules is None else modules[name])
    return module

def test_actual_three_original_constructors_and_ten_terms(data):
    n,f,h=data;importers(n,f)
    selected=n['own_cash_selection']('P06','2022-04-29')[2]
    supplement,sources=n['supplemental_selection']('P06','2022-04-29')
    assert len(sources)==3 and len({s['validator_file']for s in sources})==1
    assert len({s['catalog_file']for s in sources})==3
    assert [t['ticker']for t in supplement]==['EPAY','CCXI1','MIME','CYBE','AVLR','FMTX','PING','Y','ZEN']
    merged=n['merge_selected_terms'](selected,supplement)
    assert len(merged)==10
    for term in supplement:
        original,=[t for t in f['original_ten_terms']if t['ticker']==term['ticker']]
        assert {k:v for k,v in term.items()if k!='original_ordinary_source'}==original
    assert [t['ticker']for t in merged if t['native_session']==t['added']['session']]==['EPAY']

def test_default_foreign_phase_keeps_unique_validator_refusal(data):
    n,f,h=data;importers(n,f);plans=deepcopy(n['SUPPLEMENTAL_PHASES']['P06','2022-04-29'])
    # Remove EPAY only, so the original strict date guard is satisfied.
    plans=(tuple([*plans[0][:-1],('CCXI1',)]),plans[1])
    n['SUPPLEMENTAL_PHASES']['P04','2022-04-29']=plans
    with pytest.raises(ValueError,match='UNIQUE_SOURCE_COMPONENTS'):n['supplemental_selection']('P04','2022-04-29')

def test_duplicate_catalog_rejected_and_removal_is_meaningful(data):
    n,f,h=data;importers(n,f);first=n['SUPPLEMENTAL_PHASES']['P06','2022-04-29'][0]
    duplicate=(tuple([*first[:-1],('EPAY',)]),tuple([*first[:-1],('CCXI1',)]))
    n['SUPPLEMENTAL_PHASES']['P06','2022-04-29']=duplicate
    with pytest.raises(ValueError,match='OPT_IN_UNIQUE_CATALOG'):n['supplemental_selection']('P06','2022-04-29')
    mutant=h.load(remove='FUTURE_SUPPLEMENT_OPT_IN_UNIQUE_CATALOG_AND_IDENTICAL_SHARED_VALIDATOR')
    mutant['SUPPLEMENTAL_PHASES']['P06','2022-04-29']=duplicate;importers(mutant,f)
    assert len(mutant['supplemental_selection']('P06','2022-04-29')[0])==2

def test_conflicting_same_validator_hash_refuses_and_removal_is_meaningful(data,tmp_path):
    n,f,h=data;first,second,*_=deepcopy(n['SUPPLEMENTAL_PHASES']['P06','2022-04-29'])
    first=tuple([*first[:-1],('CCXI1',)])
    path=tmp_path/'system_campaign_cash_calendar.py';path.write_bytes(b'foreign synthetic validator bytes')
    second=tuple(['synthetic_other_cash_module',*second[1:5],sha(path.read_bytes()),second[-1]])
    base=original_module(n,f)
    foreign=SimpleNamespace(__file__=str(path),CashCalendar=lambda catalog:SimpleNamespace(catalog=catalog))
    modules={'system_campaign_cash_calendar':base,'synthetic_other_cash_module':foreign}
    plans=(first,second);n['SUPPLEMENTAL_PHASES']['P06','2022-04-29']=plans;importers(n,f,modules)
    with pytest.raises(ValueError,match='IDENTICAL_SHARED_VALIDATOR'):n['supplemental_selection']('P06','2022-04-29')
    mutant=h.load(remove='FUTURE_SUPPLEMENT_OPT_IN_UNIQUE_CATALOG_AND_IDENTICAL_SHARED_VALIDATOR')
    mutant['SUPPLEMENTAL_PHASES']['P06','2022-04-29']=plans;importers(mutant,f,modules)
    assert len(mutant['supplemental_selection']('P06','2022-04-29')[0])==3

@pytest.mark.parametrize('mutation',['preopen','noncash','native_before_cursor'])
def test_same_day_original_safety_guards_remain(data,mutation):
    n,f,h=data;module=importers(n,f);original_terms=n['catalog_terms']
    def altered(codec,tickers):
        terms=original_terms(codec,tickers)
        for t in terms:
            if t['ticker']=='EPAY':
                if mutation=='preopen':t['preopen_completion_confirmed']=False
                elif mutation=='noncash':t['added']['kind']='CASH_PLUS_STOCK'
                else:t['native_session']='2022-04-29'
        return terms
    n['catalog_terms']=altered
    with pytest.raises(ValueError,match='SAME_DAY_PREOPEN_CASH_ONLY'):n['supplemental_selection']('P06','2022-04-29')

def test_original_same_validator_evidence_is_accepted_by_exact_original_predicates(data):
    n,f,h=data;importers(n,f)
    own=n['own_cash_selection']('P06','2022-04-29')[2];terms,sources=n['supplemental_selection']('P06','2022-04-29')
    material=dict(terms=n['merge_selected_terms'](own,terms),ordinary_components=sources,catalog_sha256=f['new_catalog_sha256'],
        original_validator_sha256=f['original_validator_sha256'],selector_sha256=sha(FUTURE.read_bytes()))
    doc=n['document'](dict(run=dict(checkpoint_sha256='c'*64),source_cursor='2022-04-29'),material,'d'*64)
    evidence=f['original_repair_evidence_predicates'];ns=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,
        model_validator=model_validator,Digest=Annotated[str,Field(pattern=r'^[0-9a-f]{64}$')],Text=Annotated[str,Field(min_length=1,max_length=16384)])
    for name in ('_Strict','SourceEvidence'):exec(evidence['classes'][name],ns)
    parsed=[ns['SourceEvidence'].model_validate(row)for row in doc['source_evidence']]
    matches=[r for r in parsed if r.reference.endswith('/system_campaign_cash_calendar.py')]
    assert len(matches)==3 and len({r.sha256 for r in matches})==1
    node=ast.parse(evidence['sparse_unique_source']).body[0]
    assert sha(ast.dump(node,include_attributes=False).encode())==evidence['sparse_unique_AST_sha256'];node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<unchanged-original-repair-identity-predicate>','exec'),ns)
    obj=SimpleNamespace(source_evidence=parsed,suppress=[SimpleNamespace(**v)for v in doc['suppress']],add=[SimpleNamespace(**v)for v in doc['add']])
    assert ns['sparse_unique'](obj)is obj and len(parsed)<=128

@pytest.mark.parametrize('forbidden',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_no_financial_imports(forbidden):
    with pytest.raises(ImportError):helper().Fence().find_spec(forbidden)
