"""Portable input-only AST tests. No canonical financial module is imported."""
import ast
from copy import deepcopy
from dataclasses import asdict,dataclass
from datetime import date
import hashlib,json,math
from pathlib import Path
from types import SimpleNamespace
import zipfile
import pytest

BASE=Path(__file__).resolve().parents[2]
FIXTURES=Path(__file__).parent/'fixtures'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
digest=lambda v:sha(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def need(v,c):
    if not v:raise ValueError(c)

class StripImports(ast.NodeTransformer):
    def visit_Import(self,node):return None
    def visit_ImportFrom(self,node):return None

def extract(name,*,file='system_campaign_financial_future.py',strip=False):
    node=deepcopy(next(n for n in ast.parse((BASE/file).read_bytes()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))and n.name==name))
    return StripImports().visit(node)if strip else node

def run(nodes,ns):exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<source-bound-pure-input-AST>','exec'),ns)

def setup():
    fixture=json.loads((FIXTURES/'source263-original-inputs.json').read_bytes());scope=fixture['scope']
    raw=(BASE/'system_campaign_distribution_facts.py').read_bytes()
    assert sha(raw)=='c83a3ed96b2334333fde7f8f2d05ef9e4c2b98d7a52c4be5e437a6b954aa88bb'
    cls=extract('DistributionFacts',file='system_campaign_distribution_facts.py');cls.body=[next(n for n in cls.body if isinstance(n,ast.FunctionDef)and n.name=='__init__')]
    old=dict(Path=Path,json=json,need=need,sha=sha,__file__=str(BASE/'system_campaign_distribution_facts.py'))
    run([cls],old);module=SimpleNamespace(__file__=str(BASE/'system_campaign_distribution_facts.py'),DistributionFacts=old['DistributionFacts'])
    plan_node=next(n for n in ast.parse((BASE/'system_campaign_financial_future.py').read_bytes()).body if isinstance(n,ast.Assign)and isinstance(n.targets[0],ast.Name)and n.targets[0].id=='ORIGINAL_CONTRACT_DELIVERY_PHASES')
    plans=ast.literal_eval(plan_node.value)
    def root_spec(arm,pin):
        assert arm=='P05'and pin=='b1b4db73909f584bf7704cf33158eacc9ce1f8a8cbe212785d8f9b3404e6dede'
        return dict(outer_sha256=scope['parent_outer_sha256'],selected_session=scope['parent_cursor'])
    ns=dict(Path=Path,json=json,deepcopy=deepcopy,need=need,sha=sha,digest=digest,SimpleNamespace=SimpleNamespace,math=math,date=date,
        HERE=BASE,ORIGINAL_CONTRACT_DELIVERY_PHASES=deepcopy(plans),WITNESS_SCOPE_REGISTRY={digest(scope):deepcopy(scope)},
        importlib=SimpleNamespace(import_module=lambda name:module),root_spec=root_spec)
    names=('registered_scope','catalog_terms','merge_selected_terms','ordinary_delivery_identity','ordinary_identity','ordinary_term_dates',
        'completion_session','contractual_delivery_addition','contractual_delivery_selection')
    run([extract(n,strip=True)for n in names],ns)
    for n in ast.parse((BASE/'system_campaign_financial_future.py').read_bytes()).body:
        if isinstance(n,ast.Assign)and isinstance(n.targets[0],ast.Name)and n.targets[0].id in('PRIOR_STOCK','PREOPEN_STOCK','RESEARCH_MIXED','RESEARCH_SOURCE_EXIT','RESEARCH_TENDER','RESEARCH_CASH','NEXT_COMPLETION','SOURCE_CLOSE'):
            ns[n.targets[0].id]=ast.literal_eval(n.value)
    cp=dict(sha256=scope['parent_outer_sha256'],source_cursor=scope['parent_cursor'],run=dict(state=dict(wealth_core=dict(episodes={}),pending=[])))
    return SimpleNamespace(ns=ns,cp=cp,fixture=fixture,module=module,plan=ns['ORIGINAL_CONTRACT_DELIVERY_PHASES']['P05','2021-03-31'])

def term(s):
    terms,sources=s.ns['contractual_delivery_selection'](s.cp,'P05');assert len(terms)==len(sources)==1
    value=terms[0];value['identity_witness']=deepcopy(s.fixture['terms'][0]['identity_witness'])
    value['delivered_identity_witness']=deepcopy(s.fixture['additional_rows'][0]['identity_witness'])
    return value,deepcopy(s.fixture['additional_rows'][0]['source_row'])

def test_exact_original_constructor_selection_and_literal_zero_survive_positive_quote():
    s=setup();t,row=term(s);before=deepcopy(t['added']);assert float(row['raw_open'])>0
    assert s.ns['contractual_delivery_addition'](t,row)==before
    assert before['cash_in_lieu_price_per_delivered_share']==0.0 and str(before['exchange_ratio'])=='0.8381'and before['cash_per_share']is None
    assert t['proxy']['convention']=='CONTRACTUAL_ZERO_FRACTIONAL_CONSIDERATION'

@pytest.mark.parametrize('bad',['raw_proxy','ratio','cash','policy','source','native','root','payload'])
def test_literal_contract_rejects_value_policy_or_source_changes(bad):
    s=setup();t,row=term(s)
    if bad=='raw_proxy':t['added']['cash_in_lieu_price_per_delivered_share']=float(row['raw_open'])
    elif bad=='ratio':t['added']['exchange_ratio']=0.84
    elif bad=='cash':t['added']['cash_per_share']=0.
    elif bad=='policy':t['proxy']['convention']='RETAINED_RAW_OPEN_RESEARCH_PROXY'
    elif bad=='source':t['original_contract_source']['term_sha256']='0'*64
    elif bad=='native':t['native_term_sha256']='0'*64
    elif bad=='root':t['parent_outer_sha256']='0'*64
    else:t['source_capture']['payload_sha256']='0'*64
    with pytest.raises(ValueError):s.ns['contractual_delivery_addition'](t,row)

@pytest.mark.parametrize('bad',['row','issuer','listing','identity'])
def test_frozen_child_row_and_identity_are_mandatory(bad):
    s=setup();t,row=term(s)
    if bad=='row':row['raw_open']='999'
    elif bad=='issuer':row['issuer_id']='UPGRADED'
    elif bad=='listing':row['listing_first_session']='2001-01-01'
    else:t['delivered_identity_witness']['issuer_id']='UPGRADED'
    with pytest.raises(ValueError):s.ns['contractual_delivery_addition'](t,row)

@pytest.mark.parametrize('bad',['parent','held','child','pending','missing_proof','consumed'])
def test_selection_refuses_wrong_actual_role_and_unclosed_source(bad):
    s=setup()
    if bad=='parent':s.cp['sha256']='0'*64
    elif bad in('held','child'):
        sid='1056418588994492299'if bad=='held'else'653423826172679659'
        s.cp['run']['state']['wealth_core']['episodes']['1']=dict(slot_id=1,ticker='APHA'if bad=='held'else'TLRY',security_id=sid,current_shares=1,entry_date='2021-03-01')
    elif bad=='pending':s.cp['run']['state']['pending'].append(dict(security_id='653423826172679659'))
    elif bad=='missing_proof':s.plan['source_capture']['independent_qualification_sha256']=None
    else:
        s.cp['source_cursor']='2021-04-30';s.ns['ORIGINAL_CONTRACT_DELIVERY_PHASES']['P05','2021-04-30']=s.plan
    with pytest.raises(ValueError):s.ns['contractual_delivery_selection'](s.cp,'P05')

def test_unselected_phase_has_no_contract_route():
    s=setup();assert s.ns['contractual_delivery_selection'](s.cp,'P06')==([],[])

def test_original_raw_proxy_phase_guard_is_unchanged_and_still_refuses_APHA():
    s=setup();fn=extract('original_phase_delivery_selection',strip=True)
    assert sha(ast.dump(extract('original_phase_delivery_selection'),include_attributes=False).encode())==s.fixture['raw_proxy_phase_function_AST_sha256']
    s.ns.update(ORIGINAL_DELIVERY_PHASES={('P05','2021-03-31'):[('system_campaign_distribution_facts','DistributionFacts','system-campaign-distribution-facts.json',s.plan['catalog_sha256'])]},
        ORIGINAL_DELIVERY_SUBSETS={('P05','2021-03-31','system-campaign-distribution-facts.json'):('APHA',)})
    run([fn],s.ns)
    with pytest.raises(ValueError,match='UNCONSUMED_PROXY_DELIVERIES_ONLY'):s.ns['original_phase_delivery_selection']('P05','2021-03-31')

def removed(s,name,label):
    fn=extract(name,strip=True);call,=[n for n in ast.walk(fn)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='need'and isinstance(n.args[-1],ast.Constant)and n.args[-1].value==label]
    call.args[0]=ast.Constant(True);ns=dict(s.ns);run([fn],ns);return ns[name]

def test_closed_source_guard_removal_admits_missing_qualification():
    s=setup();s.plan['source_capture']['independent_qualification_sha256']=None
    with pytest.raises(ValueError):s.ns['contractual_delivery_selection'](s.cp,'P05')
    assert removed(s,'contractual_delivery_selection','FUTURE_CONTRACT_REQUIRES_CLOSED_SOURCE_DATA_AND_QUALIFICATION')(s.cp,'P05')[0][0]['source_capture']['independent_qualification_sha256']is None

def test_parent_guard_removal_admits_wrong_parent_identity():
    s=setup();s.cp['sha256']='0'*64
    with pytest.raises(ValueError):s.ns['contractual_delivery_selection'](s.cp,'P05')
    assert removed(s,'contractual_delivery_selection','FUTURE_CONTRACT_EXACT_OWN_SOURCE_AND_ADMITTED_PARENT')(s.cp,'P05')[0][0]['parent_outer_sha256']=='0'*64

def test_role_guard_removal_admits_hidden_child_position():
    s=setup();s.cp['run']['state']['wealth_core']['episodes']['1']=dict(slot_id=1,ticker='TLRY',security_id='653423826172679659',current_shares=1,entry_date='2021-03-01')
    with pytest.raises(ValueError):s.ns['contractual_delivery_selection'](s.cp,'P05')
    assert len(removed(s,'contractual_delivery_selection','FUTURE_CONTRACT_EXACT_NATIVE_DELIVERY_AND_ACTUAL_PARENT_CHILD_ROLES')(s.cp,'P05')[0])==1

def test_literal_zero_guard_removal_admits_corrupt_input_dictionary():
    s=setup();t,row=term(s);t['added']['cash_in_lieu_price_per_delivered_share']=float(row['raw_open'])
    with pytest.raises(ValueError):s.ns['contractual_delivery_addition'](t,row)
    assert removed(s,'contractual_delivery_addition','FUTURE_CONTRACT_EXACT_SOURCE_LITERAL_ZERO_NOT_RESEARCH_PROXY')(t,row)['cash_in_lieu_price_per_delivered_share']==0.

def test_child_identity_guard_removal_admits_upgraded_metadata():
    s=setup();t,row=term(s);t['delivered_identity_witness']['issuer_id']='UPGRADED'
    with pytest.raises(ValueError):s.ns['contractual_delivery_addition'](t,row)
    assert removed(s,'contractual_delivery_addition','FUTURE_CONTRACT_EXACT_FROZEN_DELIVERED_IDENTITY')(t,row)['cash_in_lieu_price_per_delivered_share']==0.

@dataclass
class Native:
    session:str;security_id:str;kind:str;cash_per_share:object;delivered_security_id:object;delivered_ticker:object
    delivered_issuer_id:object;exchange_ratio:object;cash_in_lieu_price_per_delivered_share:object;entitlement_aggregation:str;reference:str
    def completeness(self,age):return(False,'incomplete')

def test_actual_hydrate_AST_composes_all5_preserves_APHA_zero_and_AZPN_raw_proxy(tmp_path):
    s=setup();ns=s.ns
    primary=json.loads((BASE/'system-campaign-following-completions-terminal-facts.json').read_bytes())
    terms=[deepcopy(t)for t in primary['terms']if t['ticker']in('CATM','AZPN1','REGI','PLAN')]
    codec=SimpleNamespace(catalog=primary,catalog_sha=sha((BASE/'system-campaign-following-completions-terminal-facts.json').read_bytes()),compiler_sha=sha((BASE/'system_campaign_following_completions_facts.py').read_bytes()))
    native={}
    for t in s.fixture['terms']:
        n=Native(**t['native_term']);native.setdefault(n.session,[]).append(n)
    allrows=[deepcopy(v['source_row'])for v in s.fixture['terms']+s.fixture['additional_rows']]
    dates=sorted({'2021-03-31',*(t['native_session']for t in primary['terms']),*(t['added']['session']for t in primary['terms']),
        *(t['identity_witness']['session']for t in primary['terms'])})
    class Archive:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    def require_witness(row,w):need(digest(row)==w['source_observation_sha256']and all(row[k]==v for k,v in w.items()if k!='source_observation_sha256'),'EXACT_DECLARED_WITNESS')
    ns.update(hosted=lambda:None,inputs=SimpleNamespace(load_actions=lambda p:SimpleNamespace(terminal=native),_archive_rows=lambda z,name:[r for r in allrows if r['session'].startswith(name[13:17])]),
        selected=lambda arm,cursor:(codec,'system-campaign-following-completions-terminal-facts.json',deepcopy(terms)),
        original_ordinary_selection=lambda *a:None,original_delivery_selection=lambda *a:None,supplemental_selection=lambda *a:([],[]),
        SINGLE_PHASES={},FOLLOWING_PHASES={},suppressions=lambda cp,terms:[],axis=lambda:dates,asdict=asdict,
        zipfile=SimpleNamespace(ZipFile=lambda p:Archive()),require_witness=require_witness,CIL='RESEARCH_PROXY',
        REFERENCE='synthetic-input-only-reference',__file__=str(BASE/'system_campaign_financial_future.py'))
    run([extract('hydrate',strip=True)],ns)
    material,delivered,actions=ns['hydrate'](s.cp,'P05',source_root=tmp_path)
    assert[t['ticker']for t in material['terms']]==['CATM','AZPN1','REGI','PLAN','APHA']
    apha,=[t for t in material['terms']if t['ticker']=='APHA'];azpn,=[t for t in material['terms']if t['ticker']=='AZPN1']
    assert apha['added']['cash_in_lieu_price_per_delivered_share']==0. and str(apha['added']['exchange_ratio'])=='0.8381'
    assert apha['identity_witness']['security_type_eligible']=='0'and apha['identity_witness']['issuer_id'].startswith('SEC_UNKNOWN:')
    assert azpn['added']['cash_in_lieu_price_per_delivered_share']==float(delivered[azpn['security_id']]['raw_open'])>0
    assert material['native_and_delivery_witnesses_verified']==7 and material['cil_convention']=='PER_TERM_DECLARED_ORIGINAL_CONTRACT_OR_RESEARCH_PROXY'

def test_no_canonical_financial_imports_present_in_test_module():
    tree=ast.parse(Path(__file__).read_bytes())
    assert not any((n.module or'').startswith(('research.pooled_','stock_strategy_shared','sentinel'))for n in ast.walk(tree)if isinstance(n,ast.ImportFrom))
