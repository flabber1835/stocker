"""Portable source/input-only qualification; canonical finance is never imported."""
import ast
from copy import deepcopy
from dataclasses import asdict,dataclass
from datetime import date,datetime
from fractions import Fraction
from functools import lru_cache
import hashlib,json,math,sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated,Literal
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel,ConfigDict,Field

BASE=Path(__file__).resolve().parents[2]
FIXTURE=Path(__file__).parent/'fixtures/source269-original-inputs.json'
FIXTURE_SHA='c67bace8eb368431556dbb78600a4f8dedba8ce13a09e0607b8cf28c7e7a9c25'
SOURCE=BASE/'system_campaign_financial_future.py'
CATALOG=BASE/'system-campaign-selected-own-cash-terminal-facts.json'
sha=lambda b:hashlib.sha256(b).hexdigest()
digest=lambda v:sha(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
enc=lambda v:(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()


class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas')):
            raise ImportError('CATALOG28_INPUT_ONLY:'+fullname)


@pytest.fixture(scope='module',autouse=True)
def fence():
    value=Fence();sys.meta_path.insert(0,value)
    try:yield
    finally:sys.meta_path.remove(value)


def need(value,label):
    if not value:raise ValueError(label)


class StripImports(ast.NodeTransformer):
    def visit_Import(self,node):return None
    def visit_ImportFrom(self,node):return None


@lru_cache(maxsize=1)
def nodes():return {n.name:n for n in ast.parse(SOURCE.read_bytes()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}


def extract(name,strip=True):
    value=deepcopy(nodes()[name]);return StripImports().visit(value)if strip else value


def run(values,env):exec(compile(ast.fix_missing_locations(ast.Module(body=values,type_ignores=[])),'<source-bound-pure-input-AST>','exec'),env)


def facts():
    raw=FIXTURE.read_bytes();assert sha(raw)==FIXTURE_SHA
    return json.loads(raw)


def selected_term():
    return deepcopy(next(t for t in json.loads(CATALOG.read_bytes())['terms']if(t['arm'],t['parent_cursor'])==('P06','2021-03-31')))


def root_name(target):
    while isinstance(target,ast.Subscript):target=target.value
    return target.id if isinstance(target,ast.Name)else None


def constructor(name,cls):
    """Use the unchanged factual constructor, without its hydrate/overlay methods."""
    raw=(BASE/(name+'.py')).read_bytes();f=facts()
    assert sha(raw)==f['source_file_pins'][name+'.py']
    tree=ast.parse(raw);env=dict(Path=Path,json=json,need=need,sha=sha,__file__=str(BASE/(name+'.py')),
        CIL='RETAINED_FROZEN_RAW_OPEN_PROXY_NOT_ACTUAL_ISSUER_SETTLEMENT')
    constants=[deepcopy(n)for n in tree.body if isinstance(n,ast.Assign)and isinstance(n.targets[0],ast.Name)
               and n.targets[0].id in('CATALOG','COMPILER','HYDRATED','CIL','EXPECTED','ALIASES','ALIAS_SHA')]
    node=deepcopy(next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name==cls))
    node.body=[next(n for n in node.body if isinstance(n,ast.FunctionDef)and n.name=='__init__')]
    run(constants+[node],env)
    return SimpleNamespace(__file__=str(BASE/(name+'.py')),**{cls:env[cls]})


def setup():
    f=facts();scope=f['source_payload']['scope'];term=selected_term()
    modules={name:constructor(name,cls)for name,cls in[
        ('system_campaign_2021_completions_facts','CompletionFacts'),
        ('system_campaign_following_completions_facts','FollowingFacts'),
        ('system_campaign_distribution_facts','DistributionFacts')]}
    env=dict(Path=Path,__file__=str(SOURCE),HERE=BASE,deepcopy=deepcopy,json=json,math=math,
        Fraction=Fraction,SimpleNamespace=SimpleNamespace,sha=sha,digest=digest,need=need,date=date,datetime=datetime,ZoneInfo=ZoneInfo,
        Annotated=Annotated,Literal=Literal,BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,
        importlib=SimpleNamespace(import_module=lambda name:modules[name]))
    metadata={'OWN_CASH_SHA','OWN_CASH_CATALOG','OWN_CASH_PHASES','CASH_GENERATION_LENGTHS','CLOSED_CASH_GENERATIONS',
        'OWN_CASH_SOURCE_CLOCKS','SUPPLEMENTAL_PHASES','ORIGINAL_CONTRACT_DELIVERY_PHASES',
        'RESEARCH_MIXED','RESEARCH_CASH','RESEARCH_TENDER','RESEARCH_SOURCE_EXIT','NEXT_COMPLETION','SOURCE_CLOSE','PREOPEN_STOCK','PRIOR_STOCK'}
    assignments=[deepcopy(n)for n in ast.parse(SOURCE.read_bytes()).body if isinstance(n,ast.Assign)and root_name(n.targets[0])in metadata]
    run(assignments,env)
    names=['ResearchMixedAssumption','ResearchExactCashMixedAssumption','ResearchAfterCloseMixedAssumption',
        'ResearchCashAssumption','ResearchTenderAssumption','ResearchSourceExitAssumption',
        'registered_scope','research_after_close_mixed_timing','research_mixed_term','research_cash_term','research_tender_term',
        'research_source_exit_term','completion_session','catalog_terms','merge_selected_terms','supplemental_selection',
        'remaining_ordinary_terms','contractual_delivery_selection','contractual_delivery_addition','ordinary_identity',
        'ordinary_delivery_identity','ordinary_term_dates','suppressions']
    run([extract(n)for n in names],env)
    def root_spec(arm,pin):
        assert arm=='P06'and pin=='f8be3c331ac12f211c630078d128278c155eb99a98afaff81bc8219e435094aa'
        return dict(outer_sha256=scope['parent_outer_sha256'],selected_session=scope['parent_cursor'])
    env.update(root_spec=root_spec,WITNESS_SCOPE_REGISTRY={digest(scope):deepcopy(scope)})
    cp=dict(sha256=scope['parent_outer_sha256'],source_cursor=scope['parent_cursor'],
        repairs=[deepcopy(d['descriptor'])for d in f['inherited_input_documents']],
        run=dict(state=dict(wealth_core=dict(episodes={'7':dict(slot_id=7,ticker='IPHI',security_id=term['security_id'],
            current_shares=23,entry_date='2020-03-30')}),pending=[])))
    return SimpleNamespace(env=env,f=f,term=term,scope=scope,cp=cp,modules=modules)


def remove_guard(s,name,label):
    node=extract(name);call,=[n for n in ast.walk(node)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='need'
        and isinstance(n.args[-1],ast.Constant)and n.args[-1].value==label]
    call.args[0]=ast.Constant(True);env=dict(s.env);run([node],env);return env[name]


def install_inputs(s,root):
    folder=root/'book/repairs';folder.mkdir(parents=True)
    for item in s.f['inherited_input_documents']:
        d=item['descriptor'];raw=item['raw_utf8'].encode();assert sha(raw)==d['sha256'];(folder/d['filename']).write_bytes(raw)


def test_catalog28_append_is_exact_and_source_data_pins_are_closed():
    s=setup();catalog=json.loads(CATALOG.read_bytes())
    assert len(catalog['terms'])==len(s.env['OWN_CASH_PHASES'])==28
    assert sha(CATALOG.read_bytes())==s.f['new_catalog_sha256']==s.env['OWN_CASH_SHA']
    assert sha(enc(dict(deepcopy(catalog),terms=catalog['terms'][:27])))==s.f['old_catalog_sha256']=='69cace876439b11fd0d9b48f8a6c8faa2ee149be9c6ffaf2e54dda034292feca'
    assert s.env['CLOSED_CASH_GENERATIONS'][s.f['old_catalog_sha256']]==27
    assert s.env['CASH_GENERATION_LENGTHS']['P06','2021-03-31']==28
    assert s.term['source_capture']['independent_data_review_sha256']==s.f['source_review_sha256']
    assert s.term['source_capture']['independent_qualification_sha256']==s.f['source_qualification_sha256']
    assert s.term['source_capture']['scope_sha256']==digest(s.scope)
    assert s.term['source_capture']['payload_sha256']==sha(enc(s.f['source_payload']))
    for n,h in s.f['source_file_pins'].items():assert sha((BASE/n).read_bytes())==h


def test_actual_postclose_model_preserves_legal_date_and_literal_consideration():
    s=setup();result=s.env['research_mixed_term'](s.term)
    assert result['actual_completion_date']==s.term['native_session']=='2021-04-20'
    assert result['added']['session']=='2021-04-21'and result['added']['cash_per_share']==66.
    assert s.term['added']['exchange_ratio']=='2.323'and result['added']['exchange_ratio']==2.323
    assert result['added']['cash_in_lieu_price_per_delivered_share']is None
    assert result['delivered_identity_witness']['issuer_id']=='SEC_CIK:1058057'
    assert result['delivered_identity_witness']['security_type_eligible']=='1'
    assert result['research_assumption']['actual_settlement_claimed']is False
    s.env['completion_session'](result,s.f['axis_sessions'])


@pytest.mark.parametrize('change',['atclose','beforeclose','wrongoffset','legalday','native','lasttrading','recognition','confirmed','zone'])
def test_postclose_timing_refuses_false_legal_or_boundary_claims(change):
    s=setup();t=s.term;a=t['research_assumption']
    if change=='atclose':a['legal_effective_local']='2021-04-20T16:00:00-04:00'
    elif change=='beforeclose':a['legal_effective_local']='2021-04-20T15:59:59-04:00'
    elif change=='wrongoffset':a['legal_effective_local']='2021-04-20T16:02:00-05:00'
    elif change=='legalday':t['actual_completion_date']='2021-04-21'
    elif change=='native':t['native_session']='2021-04-19'
    elif change=='lasttrading':t['last_trading_session']='2021-04-19'
    elif change=='recognition':a['recognition_session']=t['added']['session']='2021-04-20'
    elif change=='confirmed':a['completed_after_close_confirmed']=False
    else:a['legal_effective_timezone']='UTC'
    with pytest.raises(ValueError):s.env['research_mixed_term'](t)


@pytest.mark.parametrize('change',['missingday','insertion','unsorted','duplicate'])
def test_postclose_recognition_requires_the_actual_next_frozen_axis(change):
    s=setup();dates=deepcopy(s.f['axis_sessions'])
    if change=='missingday':dates.remove('2021-04-21')
    elif change=='insertion':s.term['added']['session']=s.term['research_assumption']['recognition_session']='2021-04-22'
    elif change=='unsorted':dates=list(reversed(dates))
    else:dates.insert(0,dates[0])
    with pytest.raises(ValueError,match='AFTERCLOSE_MIXED_EXACT_NEXT'):s.env['completion_session'](s.term,dates)


@pytest.mark.parametrize('change',['cash','ratio','reference','preopen','settlement','proxy'])
def test_mixed_consideration_and_research_disclosures_cannot_be_changed(change):
    s=setup();t=s.term
    if change=='cash':t['added']['cash_per_share']=65.
    elif change=='ratio':t['added']['exchange_ratio']='2.32'
    elif change=='reference':t['added']['reference']='UNQUALIFIED'
    elif change=='preopen':t['preopen_completion_confirmed']=True
    elif change=='settlement':t['research_assumption']['actual_settlement_claimed']=True
    else:t['proxy']['actual_settlement_rate_observed']=True
    with pytest.raises(ValueError):s.env['research_mixed_term'](t)


def test_original_mixed_v1_v2_models_and_behavior_remain_exact():
    s=setup();old_env=dict(s.env);run(ast.parse(s.f['old_research_mixed_term_source']).body,old_env)
    old_axis=dict(s.env);run(ast.parse(s.f['old_completion_session_source']).body,old_axis)
    for name,h in s.f['original_model_AST_sha256'].items():assert sha(ast.dump(nodes()[name],include_attributes=False).encode())==h
    old_terms=[t for t in json.loads(CATALOG.read_bytes())['terms']if t.get('recognition_rule')==s.env['RESEARCH_MIXED']and t['research_assumption']['schema'].endswith(('/1','/2'))]
    assert[t['ticker']for t in old_terms]==['FMSA','WLH']
    for term in old_terms:
        assert s.env['research_mixed_term'](deepcopy(term))==old_env['research_mixed_term'](deepcopy(term))
        assert s.env['completion_session'](term,s.f['axis_sessions'])==old_axis['completion_session'](term,s.f['axis_sessions'])
        for field in('actual_completion_date','last_trading_session'):
            wrong=deepcopy(term);wrong[field]='1900-01-01'
            with pytest.raises(ValueError):s.env['research_mixed_term'](wrong)
            with pytest.raises(ValueError):old_env['research_mixed_term'](wrong)


def test_original_selectors_compose_exact_twelve_and_preserve_all_six_inputs(tmp_path):
    s=setup();install_inputs(s,tmp_path)
    extra,sources=s.env['supplemental_selection']('P06','2021-03-31')
    extra,inherited=s.env['remaining_ordinary_terms'](s.cp,extra,tmp_path)
    contracts,contract_sources=s.env['contractual_delivery_selection'](s.cp,'P06')
    selected=s.env['merge_selected_terms']([s.env['research_mixed_term'](s.term)],extra)
    selected=s.env['merge_selected_terms'](selected,contracts)
    assert[t['ticker']for t in selected]==['IPHI','MIK','VAR','NAV','WORK','HOME','TRIL1','CATM','AZPN1','REGI','PLAN','APHA']
    assert not set(('WPX','BEAT1','PE','ACIA'))&{t['ticker']for t in selected}
    assert len(sources)==2 and len(contract_sources)==1 and inherited==[]
    assert len(s.cp['repairs'])==6
    for item in s.f['inherited_input_documents']:assert(tmp_path/'book/repairs'/item['descriptor']['filename']).read_bytes()==item['raw_utf8'].encode()
    assert len(s.env['suppressions'](s.cp,selected))==12


def own_binding(s):
    """Extract the unchanged selector's actual multi-source choice and binding guard."""
    loop=next(n for n in nodes()['own_cash_selection'].body if isinstance(n,ast.For)and isinstance(n.target,ast.Name)and n.target.id=='term')
    branch=next(n for n in loop.body if isinstance(n,ast.If)and "len(scope['terms'])" in ast.unparse(n.test))
    guard=next(n for n in loop.body if isinstance(n,ast.Expr)and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant)and a.value=='OWN_CASH_EXACT_CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE'for a in n.value.args))
    initial=ast.parse("phase = term['arm'], term['parent_cursor']\nsource = term['source_capture']\nparent = root_spec(term['arm'], term['parent_root_admission_sha256'])\n").body
    fn=ast.FunctionDef(name='binding',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg=n)for n in('term','scope')],
        kwonlyargs=[],kw_defaults=[],defaults=[]),body=initial+[deepcopy(branch),deepcopy(guard),ast.Return(ast.Name(id='declared',ctx=ast.Load()))],
        decorator_list=[],returns=None,type_comment=None)
    env=dict(s.env);run([fn],env);return fn,env


def test_actual_multi_scope_selects_IPHI_and_preserves_other_eleven_source_members():
    s=setup();_,env=own_binding(s);before=deepcopy(s.scope)
    selected=env['binding'](s.term,s.scope)
    assert selected==s.scope['terms'][0]and selected['ticker']=='IPHI'
    assert s.scope==before and len(s.scope['terms'])==12


@pytest.mark.parametrize('change',['clock','native','outer','rootpin','quantity','missing','duplicate_id','duplicate_native'])
def test_actual_owncash_binding_refuses_wrong_source_parent_native_or_role(change):
    s=setup();_,env=own_binding(s);t=s.term;scope=deepcopy(s.scope)
    if change=='clock':t['source_capture']['head']='0'*40
    elif change=='native':t['native_term_sha256']='0'*64
    elif change=='outer':t['parent_outer_sha256']='0'*64
    elif change=='rootpin':t['parent_root_admission_sha256']='0'*64
    elif change=='quantity':t['parent_positions'][0]['quantity']=22
    elif change=='missing':scope['terms']=scope['terms'][1:]
    elif change=='duplicate_id':scope['terms'].append(deepcopy(scope['terms'][0]))
    else:
        duplicate=deepcopy(scope['terms'][0]);duplicate['ticker']='OTHER';scope['terms'].append(duplicate)
    with pytest.raises((ValueError,AssertionError)):env['binding'](t,scope)


def test_source_binding_guard_removal_demonstrates_wrong_clock_admission():
    s=setup();fn,env=own_binding(s);s.term['source_capture']['head']='0'*40
    label='OWN_CASH_EXACT_CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE'
    with pytest.raises(ValueError,match=label):env['binding'](s.term,s.scope)
    call,=[n for n in ast.walk(fn)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='need'
        and isinstance(n.args[-1],ast.Constant)and n.args[-1].value==label]
    call.args[0]=ast.Constant(True);run([fn],env)
    assert env['binding'](s.term,s.scope)['security_id']==s.term['security_id']


def test_APHA_uses_original_zero_while_raw_proxy_route_still_refuses_it():
    s=setup();contracts,_=s.env['contractual_delivery_selection'](s.cp,'P06');t,=contracts
    row,=[v['source_row']for v in s.f['source_payload']['additional_rows']if v['identity_witness']['ticker']=='TLRY']
    t['delivered_identity_witness']={k:row[k]for k in('session','security_id','ticker','issuer_id','listing_first_session','security_type_eligible')}
    t['delivered_identity_witness']['source_observation_sha256']=digest(row)
    assert float(row['raw_open'])>0
    assert s.env['contractual_delivery_addition'](t,row)['cash_in_lieu_price_per_delivered_share']==0.
    assert str(t['added']['exchange_ratio'])=='0.8381'
    assert sha(ast.dump(nodes()['original_phase_delivery_selection'],include_attributes=False).encode())==s.f['raw_proxy_phase_function_AST_sha256']
    s.env.update(ORIGINAL_DELIVERY_PHASES={('P06','2021-03-31'):[('system_campaign_distribution_facts','DistributionFacts','system-campaign-distribution-facts.json',s.f['source_file_pins']['system-campaign-distribution-facts.json'])]},
        ORIGINAL_DELIVERY_SUBSETS={('P06','2021-03-31','system-campaign-distribution-facts.json'):('APHA',)})
    run([extract('original_phase_delivery_selection')],s.env)
    with pytest.raises(ValueError,match='UNCONSUMED_PROXY_DELIVERIES_ONLY'):s.env['original_phase_delivery_selection']('P06','2021-03-31')


@pytest.mark.parametrize('change',['parent','childheld','pending','sourcepin','inputbytes'])
def test_actual_source_and_inherited_input_falsifiers(change,tmp_path):
    s=setup();install_inputs(s,tmp_path)
    if change=='inputbytes':
        name=s.cp['repairs'][0]['filename'];(tmp_path/'book/repairs'/name).write_text('{}')
        with pytest.raises(ValueError,match='EXACT_REPAIR_BYTES'):s.env['remaining_ordinary_terms'](s.cp,[],tmp_path)
        return
    if change=='parent':s.cp['sha256']='0'*64
    elif change=='childheld':s.cp['run']['state']['wealth_core']['episodes']['1']=dict(slot_id=1,ticker='TLRY',security_id='653423826172679659',current_shares=1,entry_date='2021-03-01')
    elif change=='pending':s.cp['run']['state']['pending']=[dict(security_id='653423826172679659')]
    else:s.env['ORIGINAL_CONTRACT_DELIVERY_PHASES']['P06','2021-03-31']['source_capture']['independent_qualification_sha256']=None
    with pytest.raises(ValueError):s.env['contractual_delivery_selection'](s.cp,'P06')


def test_timing_guard_removal_demonstrates_false_admission_at_close():
    s=setup();s.term['research_assumption']['legal_effective_local']='2021-04-20T16:00:00-04:00'
    model=s.env['ResearchAfterCloseMixedAssumption'].model_validate(s.term['research_assumption'])
    label='OWN_INPUT_MIXED_CONFIRMED_POSTCLOSE_LEGAL_TIME_AND_DISTINCT_RECOGNITION'
    with pytest.raises(ValueError,match=label):s.env['research_after_close_mixed_timing'](s.term,model)
    assert remove_guard(s,'research_after_close_mixed_timing',label)(s.term,model)=='2021-04-21'


def test_axis_guard_removal_demonstrates_false_admission_without_next_day():
    s=setup();dates=[d for d in s.f['axis_sessions']if d!='2021-04-21'];label='OWN_INPUT_AFTERCLOSE_MIXED_EXACT_NEXT_FROZEN_DAILY_BOUNDARY'
    with pytest.raises(ValueError,match=label):s.env['completion_session'](s.term,dates)
    assert remove_guard(s,'completion_session',label)(s.term,dates)is None


def test_mixed_guard_removal_demonstrates_wrong_cash_admission():
    s=setup();s.term['added']['cash_per_share']=65.;label='OWN_INPUT_EXPLICIT_RESEARCH_MIXED_AMOUNT_RATIO_IDENTITY_AND_TIMING'
    with pytest.raises(ValueError,match=label):s.env['research_mixed_term'](s.term)
    assert remove_guard(s,'research_mixed_term',label)(s.term)['added']['cash_per_share']==65.


def test_supplement_source_guard_removal_demonstrates_wrong_validator_admission():
    s=setup();plans=list(s.env['SUPPLEMENTAL_PHASES']['P06','2021-03-31']);bad=list(plans[0]);bad[5]='0'*64;plans[0]=tuple(bad);s.env['SUPPLEMENTAL_PHASES']['P06','2021-03-31']=tuple(plans)
    label='FUTURE_SUPPLEMENT_EXACT_ORIGINAL_SOURCE_BYTES'
    with pytest.raises(ValueError,match=label):s.env['supplemental_selection']('P06','2021-03-31')
    assert len(remove_guard(s,'supplemental_selection',label)('P06','2021-03-31')[0])==10


def test_merge_guard_removal_demonstrates_duplicate_parent_admission():
    s=setup();label='FUTURE_ORIGINAL_ORDINARY_DISJOINT_SELECTED_TERMS'
    with pytest.raises(ValueError,match=label):s.env['merge_selected_terms']([s.term],[s.term])
    assert len(remove_guard(s,'merge_selected_terms',label)([s.term],[s.term]))==2


@dataclass
class Native:
    session:str;security_id:str;kind:str;cash_per_share:object;exchange_ratio:object;delivered_security_id:object
    delivered_ticker:object;delivered_issuer_id:object;cash_in_lieu_price_per_delivered_share:object;entitlement_aggregation:str;reference:str
    def completeness(self,age):return(False,'incomplete')


def hydrate_case(tmp_path,change=None):
    s=setup();install_inputs(s,tmp_path);ns=s.env
    primary=s.env['research_mixed_term'](s.term);scope=s.scope
    if change=='held':s.cp['run']['state']['wealth_core']['episodes']['7']['current_shares']=22
    natives={}
    for t in s.f['source_payload']['terms']:
        n=Native(**t['native_term']);natives.setdefault(n.session,[]).append(n)
    allrows=[deepcopy(v['source_row'])for v in s.f['source_payload']['terms']+s.f['source_payload']['additional_rows']]
    if change=='issuer':next(r for r in allrows if r['ticker']=='MRVL')['issuer_id']='SEC_CIK:1835632'
    class Archive:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    raw=(BASE/'system_campaign_2021_completions_facts.py').read_bytes()
    witness=deepcopy(next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)and n.name=='require_witness'))
    run([witness],ns)
    ns.update(hosted=lambda:None,inputs=SimpleNamespace(load_actions=lambda p:SimpleNamespace(terminal=natives),
        _archive_rows=lambda z,name:[r for r in allrows if r['session'].startswith(name[13:17])]),
        selected=lambda arm,cursor:(SimpleNamespace(catalog=json.loads(CATALOG.read_bytes()),catalog_sha=sha(CATALOG.read_bytes()),
            compiler_sha=sha(SOURCE.read_bytes()),parent_outer_sha256=scope['parent_outer_sha256'],parent_positions=scope['terms'][0]['parent_positions']),
            CATALOG.name,[deepcopy(primary)]),
        original_ordinary_selection=lambda *a:None,original_delivery_selection=lambda *a:None,
        SINGLE_PHASES={},FOLLOWING_PHASES={},axis=lambda:s.f['axis_sessions'],asdict=asdict,
        zipfile=SimpleNamespace(ZipFile=lambda p:Archive()),
        CIL='RETAINED_FROZEN_RAW_OPEN_PROXY_NOT_ACTUAL_ISSUER_SETTLEMENT',REFERENCE='synthetic-input-only-reference')
    run([extract('hydrate')],ns)
    return s,ns['hydrate'](s.cp,'P06',source_root=tmp_path)


def test_actual_hydrate_AST_composes_all12_and_exact16_rows(tmp_path):
    s,(material,delivered,actions)=hydrate_case(tmp_path)
    assert[t['ticker']for t in material['terms']]==['IPHI','MIK','VAR','NAV','WORK','HOME','TRIL1','CATM','AZPN1','REGI','PLAN','APHA']
    assert material['native_and_delivery_witnesses_verified']==16
    iphi,=[t for t in material['terms']if t['ticker']=='IPHI'];apha,=[t for t in material['terms']if t['ticker']=='APHA']
    assert iphi['actual_completion_date']=='2021-04-20'and iphi['added']['session']=='2021-04-21'
    assert iphi['added']['cash_per_share']==66. and iphi['added']['exchange_ratio']==2.323
    assert iphi['added']['cash_in_lieu_price_per_delivered_share']==float(delivered[iphi['security_id']]['raw_open'])
    assert iphi['added']['delivered_issuer_id']=='SEC_CIK:1058057'and iphi['delivered_identity_witness']['security_type_eligible']=='1'
    assert apha['added']['cash_in_lieu_price_per_delivered_share']==0. and str(apha['added']['exchange_ratio'])=='0.8381'
    assert material['cil_convention']=='PER_TERM_DECLARED_ORIGINAL_CONTRACT_OR_RESEARCH_PROXY'
    for item in s.f['inherited_input_documents']:assert(tmp_path/'book/repairs'/item['descriptor']['filename']).read_bytes()==item['raw_utf8'].encode()


@pytest.mark.parametrize('change',['held','issuer'])
def test_hydrate_refuses_wrong_current_held_quantity_or_upgraded_MRVL(change,tmp_path):
    with pytest.raises(ValueError):hydrate_case(tmp_path,change)


@pytest.mark.parametrize('name',['stock_strategy_shared','sentinel','research.pooled_vacancy_funding','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
