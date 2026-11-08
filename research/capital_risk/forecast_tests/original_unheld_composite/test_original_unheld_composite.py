"""Input-only generic composite qualification; financial imports are fenced."""
import ast
from copy import deepcopy
from dataclasses import asdict,dataclass,make_dataclass
import gzip,hashlib,importlib.util,json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
Q=Path(__file__).parent
import os
C=Path(os.environ.get('QUALIFIED_COMPOSITE_SOURCE_DIR',str(Q.parents[1])))
O=C
FACTS=Path(os.environ.get('QUALIFIED_COMPOSITE_ORIGINAL_DIR',str(C)))
sys.path.insert(0,str(FACTS))
sys.path.insert(0,str(C))
class Fence:
    def find_spec(self,name,path=None,target=None):
        if name.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('COMPOSITE_INPUT_ONLY:'+name)
sys.meta_path.insert(0,Fence())
spec=importlib.util.spec_from_file_location('portable_generic_composite',C/'system_campaign_financial_future.py');f=importlib.util.module_from_spec(spec);sys.modules[spec.name]=f;spec.loader.exec_module(f)
class SourceFiles:
    def __truediv__(self,name):return C/name if name in('system_campaign_financial_resume.py','system_campaign_financial_future.py',f.OWN_CASH_CATALOG)else FACTS/name
f.HERE=SourceFiles()
def fixture():
    raw=(Q/'fixtures/original-composite-input-only.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='f326aa5c871ebba308719ffcd2da39e397c31fe3e3b18497b3fc54836a8241e2'
    return json.loads(raw)
@pytest.fixture(scope='module')
def parent():return deepcopy(fixture()['synthetic_scope_parent'])
def term():return deepcopy(fixture()['qualified_record'])
def scope(parent):return f.source_scopes(parent,dict(arm='P05',parent_outer_sha256=parent['sha256'],terms=[term()]),'a'*64,'b'*64)[0]

def test_original_constructor_is_qualified_without_donor_book_or_runtime():
    from pydantic import BaseModel,ConfigDict,Field,PrivateAttr
    from typing import Literal
    source=(FACTS/'p01_iac_namespace_continue.py').read_bytes();assert f.sha(source)=='1dd6857cb374532bd33faeaadd53bdd4ae600e68c16a5534408fa498d8cb8cf5'
    cls,=[n for n in ast.parse(source).body if isinstance(n,ast.ClassDef)and n.name=='UnheldCashInput']
    ns=dict(__name__=__name__,BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,PrivateAttr=PrivateAttr,Literal=Literal,MDP='1072510367992802359')
    exec(compile(ast.Module(body=[cls],type_ignores=[]),'<test-only-original-input-constructor>','exec'),ns);ns['UnheldCashInput'].model_rebuild(_types_namespace=ns)
    raw=(FACTS/'p01_iac_namespace_continue_cash_input.json').read_bytes();assert f.sha(raw)=='4978eebd26d840a0d1678ba96fdae302e844f08f932d6eaa0b2ed675470b869c'
    model=ns['UnheldCashInput'].model_validate(json.loads(raw));assert model.aggregate_cash_per_old_share=='59.17'and model.held_multileg_supported is False
    assert model.root_admission_sha256!='bb544ebebf83b35219a33ddb30141404c9df6243f5736eee1a069a8420ba96d5'
def test_current_own_source_selector_and_33_generation(parent):
    codec,_,terms=f.own_cash_selection('P05','2021-11-30');t,=terms
    assert t==term()and len(codec.catalog['terms'])==33 and codec.catalog_sha=='9b2e32b0dddd53919f846b4b275ccd04afb59ab257b2652e5b63892971012fd9'
    assert t['identity_witness']['session']==parent['source_cursor']<'2021-12-01'and t['source_parent_selected']is True
    f.research_original_unheld_composite_term(t)
def test_original32_bytes_and_generation_compatibility():
    codec,_,terms=f.own_cash_selection('P11','2026-04-30')
    assert len(codec.catalog['terms'])==32 and codec.catalog_sha=='3640674e7049db653200c8c888e70fe9f645b6dfba7110b49295a0645f318304'
    assert f.sha((json.dumps(codec.catalog,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())=='3640674e7049db653200c8c888e70fe9f645b6dfba7110b49295a0645f318304'
def test_all12_actual_input_bytes_remain_unchanged(parent):
    entries=fixture()['actual_original12_raw_inputs'];assert len(entries)==len(parent['repairs'])==12
    assert [e['descriptor']for e in entries]==parent['repairs']
    assert all(f.sha(e['raw_utf8'].encode())==e['descriptor']['sha256']for e in entries)

def test_original_runtime_exec_is_only_pure_scope_and_pinned_constant():
    fn=next(n for n in ast.parse((O/'system_campaign_financial_future.py').read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name=='original_unheld_composite_model')
    exec_call,=[n for n in ast.walk(fn)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='exec']
    assert any(isinstance(n,ast.List)and len(n.elts)==1 and isinstance(n.elts[0],ast.Name)and n.elts[0].id=='scope'for n in ast.walk(exec_call))
    assert not any(isinstance(n,ast.ClassDef)for n in ast.walk(fn))
@pytest.mark.parametrize('kind',['leg_amount','leg_order','ratio_marker','original_schema','input_hash','compiler_hash','native_hash','date','identity_day','parent_date','held','preopen','PIT','settlement','source_selected','allocation','delivered'])
def test_legal_clock_source_and_authority_changes_refuse(kind):
    t=term()
    if kind=='leg_amount':t['research_assumption']['aggregate_cash_per_original_share']='42.18'
    elif kind=='leg_order':t['research_assumption']['ordered_legs'].reverse()
    elif kind=='ratio_marker':t['added']['cash_per_share']=118.34
    elif kind=='original_schema':t['retained_original_composite_input']['schema']='foreign/1'
    elif kind=='input_hash':t['retained_original_composite_input']['input_sha256']='0'*64
    elif kind=='compiler_hash':t['retained_original_composite_input']['compiler_sha256']='0'*64
    elif kind=='native_hash':t['native_term_sha256']='0'*64
    elif kind=='date':t['added']['session']='2021-12-02'
    elif kind=='identity_day':t['identity_witness']['session']='2021-11-29'
    elif kind=='parent_date':t['parent_cursor']='2021-11-29'
    elif kind=='held':t['research_assumption']['held_multileg_supported']=True
    elif kind=='preopen':t['research_assumption']['preopen_availability_claimed']=True
    elif kind=='PIT':t['research_assumption']['strict_archival_PIT_claimed']=True
    elif kind=='settlement':t['research_assumption']['actual_settlement_claimed']=True
    elif kind=='source_selected':t['source_parent_selected']=False
    elif kind=='allocation':t['portfolio_completion_authorized']=True
    else:t['added']['delivered_security_id']='made-up-child'
    with pytest.raises((ValueError,KeyError)):f.research_original_unheld_composite_term(t)
def test_source_scope_exact_original_and_current_parent_binding(parent):
    s=scope(parent);assert s['schema']=='research.original-unheld-composite-source-scope/1'and s['require_never_held']is True
    assert s['parent_root_admission_sha256']=='bb544ebebf83b35219a33ddb30141404c9df6243f5736eee1a069a8420ba96d5'
    state=parent['run']['state'];f.require_source_scope(state['wealth_core'],state['pending'],state['ledger'],s)
@pytest.mark.parametrize('kind',['source','child','intent','reserved','ticker_reserved','claim','history','due_bill','prior_terminal'])
def test_actual_and_related_source_ownership_never_bypasses_scope(parent,kind):
    s=scope(parent);state=deepcopy(parent['run']['state']);w=state['wealth_core'];l=state['ledger'];sid=s['security_id']
    if kind=='source':w['episodes']['999']=dict(security_id=sid,ticker='MDP',current_shares=1)
    elif kind=='child':w['episodes']['999']=dict(security_id='CHILD',ticker='OTHER',source_lots=[dict(parent_security_id=sid)])
    elif kind=='intent':state['pending'].append(dict(security_id=sid))
    elif kind=='reserved':next(iter(w['slots'].values()))['reserved_for']=sid
    elif kind=='ticker_reserved':next(iter(w['slots'].values()))['reserved_ticker']='MDP'
    elif kind=='claim':l['receivables'].append(dict(security_id=sid))
    elif kind=='history':l['events'].append(dict(security_id=sid))
    elif kind=='due_bill':l['events'].append(dict(security_id='CHILD',detail=dict(parent_security_id=sid)))
    else:w['terminal_pending_terms'][sid]={}
    with pytest.raises(ValueError):f.require_source_scope(w,state['pending'],l,s)
def test_unrelated_pending_dataclass_is_fully_preserved_and_accepted(parent):
    @dataclass(frozen=True)
    class Pending:security_id:str;other:str
    state=deepcopy(parent['run']['state']);pending=[Pending('UNRELATED','unchanged')];before=deepcopy(pending)
    f.require_source_scope(state['wealth_core'],pending,state['ledger'],scope(parent));assert pending==before
def test_old_UFS_quote_validators_and_callback_class_are_byte_exact():
    after=(C/'system_campaign_financial_future.py').read_text();saved=fixture()
    for name,expected in saved['unchanged_function_source_sha256'].items():
        node=next(n for n in ast.parse(after).body if isinstance(n,ast.FunctionDef)and n.name==name)
        segment=ast.get_source_segment(after,node)
        if name=='research_cash_term':
            prefix="def research_cash_term(term):\n    if term['research_assumption'].get('schema') == 'research.daily-normalized-usd-cash-assumption/1':\n        return research_normalized_usd_cash_term(term)\n"
            assert segment.startswith(prefix)
            segment='def research_cash_term(term):\n'+segment[len(prefix):]
        assert hashlib.sha256(segment.encode()).hexdigest()==expected
    node=next(n for n in ast.parse(after).body if isinstance(n,ast.ClassDef)and n.name=='ActualEvents')
    assert hashlib.sha256(ast.get_source_segment(after,node).encode()).hexdigest()==saved['unchanged_actual_events_source_sha256']

def test_request_source_closure_adds_only_two_original_files():
    assert f.original_composite_source_names()==['p01_iac_namespace_continue.py','p01_iac_namespace_continue_cash_input.json']
    assert len(set(f.original_composite_source_names()))==2

def material(parent):
    codec,_,terms=f.own_cash_selection('P05','2021-11-30')
    return dict(arm='P05',parent_outer_sha256=parent['sha256'],terms=terms,catalog_sha256=codec.catalog_sha,original_validator_sha256=codec.compiler_sha,selector_sha256=f.sha((O/'system_campaign_financial_future.py').read_bytes()),original_validator_description=codec.validator_description)

def test_actual_request_metadata_binds_both_original_sources_441(monkeypatch):
    class RequestFiles:
        parent=FACTS.parent
        def __truediv__(self,name):
            return O/name if name in('system_campaign_financial_resume.py','system_campaign_financial_future.py',f.OWN_CASH_CATALOG)else FACTS/name
    monkeypatch.setitem(sys.modules,'system_campaign_financial_future',f)
    spec=importlib.util.spec_from_file_location('private_mdp_request',O/'system_campaign_financial_resume.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    monkeypatch.setattr(m,'HERE',RequestFiles());monkeypatch.setattr(m,'SELECTED_ARMS',('P05',));monkeypatch.setattr(m,'EXECUTION_MODE','OWN_ADMITTED_FINANCIAL_CONTINUATION')
    req=m.expected_request();assert len(req['sources'])>=441
    assert req['sources']['p01_iac_namespace_continue_cash_input.json']=='4978eebd26d840a0d1678ba96fdae302e844f08f932d6eaa0b2ed675470b869c'
    assert req['sources']['p01_iac_namespace_continue.py']=='1dd6857cb374532bd33faeaadd53bdd4ae600e68c16a5534408fa498d8cb8cf5'
    assert req['sources']['system_campaign_financial_future.py']==f.sha((O/'system_campaign_financial_future.py').read_bytes())

def test_original_nonempty_repair_document_and_loaded_identity(parent):
    from pydantic import BaseModel,ConfigDict,Field,PrivateAttr,model_validator
    from typing import Literal
    fixture_raw=(FACTS/'forecast_tests/standard_distribution/fixtures/pure-original-nonempty-input-codec.json').read_bytes();assert f.sha(fixture_raw)=='fb5b4da4b84afcc9985000723efcee5b4ab2e9884e8bebbca4f0c670d487533e'
    fixture=json.loads(fixture_raw)
    class Strict(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)
    class Evidence(Strict):
        reference:str;description:str;sha256:str|None=None
    class Suppression(Strict):
        session:str;security_id:str;term_sha256:str
    class Added(BaseModel):
        model_config=ConfigDict(extra='allow',strict=True)
        session:str;security_id:str
    ns=dict(__name__=__name__,_Strict=Strict,Literal=Literal,Field=Field,PrivateAttr=PrivateAttr,model_validator=model_validator,Digest=str,SourceEvidence=Evidence,Suppression=Suppression,AddedTerm=Added,json=json,hashlib=hashlib)
    for name in('_digest','Repair','_loaded'):
        item=fixture['functions'][name];assert f.sha(item['source'].encode())==item['source_sha256'];node=ast.parse(item['source']).body[0]
        assert f.sha(ast.dump(node,include_attributes=False).encode())==item['ast_sha256'];exec(compile(ast.Module(body=[node],type_ignores=[]),'<original-pure-input-codec>','exec'),ns)
    cls=ns['Repair'];cls.model_rebuild(_types_namespace=ns)
    doc=f.document(parent,material(parent),'d'*64);obj=cls.model_validate(doc)
    assert obj.earliest_affected_session=='2021-12-01'and len(obj.suppress)==len(obj.add)==1
    assert {v.sha256 for v in obj.source_evidence}>={'4978eebd26d840a0d1678ba96fdae302e844f08f932d6eaa0b2ed675470b869c','1dd6857cb374532bd33faeaadd53bdd4ae600e68c16a5534408fa498d8cb8cf5'}
    obj._file_sha256='e'*64;obj._resume_session='2021-11-30';obj._document_sha256=ns['_digest'](obj.model_dump(mode='json',by_alias=True));ns['_loaded'](obj)
    with pytest.raises(ValueError,match='empty terminal repair'):cls.model_validate(dict(doc,suppress=[],add=[]))
    obj.add[0].session='2021-12-02'
    with pytest.raises(ValueError,match='unchanged source-bound'):ns['_loaded'](obj)

def test_actual_constructor_restart_reconstructs_same_bound_scope(parent,tmp_path):
    m=material(parent);doc=f.document(parent,m,'d'*64)
    (tmp_path/f.OVERLAY).write_text(json.dumps(doc))
    p=tmp_path/f.hydration_name(parent);p.write_text(json.dumps(m))
    scopes=f.source_scopes(parent,m,f.sha((tmp_path/f.OVERLAY).read_bytes()),f.sha(p.read_bytes()))
    (tmp_path/f.SOURCE_SCOPES).write_text(json.dumps(scopes))
    first=f.ActualEvents(tmp_path,'P05',cp=parent);second=f.ActualEvents(tmp_path,'P05',cp=parent)
    assert first.scopes==second.scopes==scopes and len(first.terms)==1
    for observer in(first,second):
        state=parent['run']['state'];f.require_source_scope(state['wealth_core'],state['pending'],state['ledger'],observer.scopes[0])

def synthetic_observer(parent):
    obs=object.__new__(f.ActualEvents);t=term();sid=t['security_id']
    obs.terms={(t['added']['session'],sid):deepcopy(t['added'])};obs.scopes=[scope(parent)]
    obs.current=dict(session='2021-12-01',source_prior_absent=True,cash=[],source=[],stock=[],risk=[],order=[])
    data=deepcopy(parent['run']['state'])
    class Wealth:
        def to_dict(self):return deepcopy(data['wealth_core'])
    class Ledger:
        def to_dict(self):return deepcopy(data['ledger'])
    obs.terminal_original=lambda state,terms,**kw:dict(applied=False,reason='NOT_HELD')
    Term=make_dataclass('Term',[(name,object)for name in t['added']],frozen=True)
    typed=Term(**t['added']);wealth=Wealth();ledger=Ledger()
    def step(state,ledger,pending,terms,session):return obs.terminal(state,terms,ledger=ledger,phase='OPEN')
    obs.step_code=step.__code__
    return obs,typed,wealth,ledger,data,step

def test_unchanged_actual_observer_terminal_wrapper_uses_actual_caller_frame(parent):
    obs,t,w,l,data,step=synthetic_observer(parent);before=deepcopy(data)
    result=step(w,l,[],t,'2021-12-01')
    assert result==dict(applied=False,reason='NOT_HELD')and data==before
    assert obs.current['cash']==[dict(session='2021-12-01',security_id=t.security_id,actual_context_call=True,postcondition=dict(actual_held=False,quantity=0,nominal_cash=0.),source_only_noop=True)]
    assert obs.current['order']==['CASH:'+t.security_id]
def test_actual_observer_foreign_terminal_caller_still_refuses(parent):
    obs,t,w,l,_,_=synthetic_observer(parent)
    with pytest.raises(ValueError,match='ACTUAL_ADAPTER_CALL_REQUIRED'):obs.terminal(w,t,ledger=l,phase='OPEN')
def test_actual_observer_nonzero_financial_change_still_refuses(parent):
    obs,t,w,l,data,step=synthetic_observer(parent)
    def corrupt(state,terms,**kwargs):
        data['ledger']['events'].append(dict(security_id=t.security_id,cash_delta=1));return dict(applied=False,reason='NOT_HELD')
    obs.terminal_original=corrupt
    with pytest.raises(ValueError):step(w,l,[],t,'2021-12-01')

def test_unchanged_actual_observer_source_wrapper_delegates_once_on_actual_kernel_frame(parent):
    obs,t,_,_,data,_=synthetic_observer(parent);calls=[]
    prior=SimpleNamespace(wealth_core=data['wealth_core'],pending=[],ledger=data['ledger'],median5=data['median5'])
    published=SimpleNamespace(session='2021-12-01')
    def original(*,prior,published):calls.append((prior,published));return {t.security_id:59.17}
    obs.source_original=original
    def kernel(env,published):return obs.source_values(prior=env,published=published)
    obs.kernel_code=kernel.__code__
    assert kernel(prior,published)=={t.security_id:59.17}and calls==[(prior,published)]
    assert len(obs.current['source'])==1 and obs.current['source'][0]['actual_context_call']is True

def synthetic_adoption():
    source=(FACTS/'system_campaign_pxd_pause.py').read_bytes();tree=ast.parse(source)
    constant,=[n for n in tree.body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='UNCHANGED'for t in n.targets)]
    fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='adoption']
    ns=dict(need=f.need,digest=f.digest,UNCHANGED=ast.literal_eval(constant.value));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<unchanged-original-pure-zero-adoption>','exec'),ns)
    repairs=[dict(filename=str(i)+'.json',sha256=str(i),resume_session='2021-01-01',predecessor_checkpoint_sha256='a'*64)for i in range(12)]
    before=dict(base={},source_cursor='2021-11-30',completed=986,economics={},stats={},spy_base={},retries={},repairs=repairs,journals=dict(watch=dict(bytes=0),daily=dict(bytes=0)),chain='a'*64)
    state=dict(synthetic_input_only=True);run=dict(state=state,state_sha256=f.digest(state),input_sha256=f.digest(dict(base={},repairs=repairs)));run['checkpoint_sha256']=f.digest(run);before['run']=run;before['sha256']=f.digest(before)
    after=deepcopy(before);overlay='b'*64;desc=dict(filename=overlay+'.json',sha256=overlay,resume_session=before['source_cursor'],predecessor_checkpoint_sha256=run['checkpoint_sha256']);after['repairs'].append(desc)
    after['run']['input_sha256']=f.digest(dict(base=after['base'],repairs=after['repairs']));after['run']['checkpoint_sha256']=f.digest({k:v for k,v in after['run'].items()if k!='checkpoint_sha256'})
    event=dict(schema='research.pooled-action-successor/1',predecessor_checkpoint_sha256=run['checkpoint_sha256'],unchanged_through='2021-11-30',earliest_affected_session='2021-12-01',state_sha256=run['state_sha256'],overlay=desc,predecessor_input_sha256=run['input_sha256'],successor_input_sha256=after['run']['input_sha256'])
    after['chain']=f.digest(dict(previous=before['chain'],event=event));after['journals']['watch']['bytes']=1;after['sha256']=f.digest({k:v for k,v in after.items()if k!='sha256'})
    return ns['adoption'],before,after,overlay,event
def test_original_zero_adoption_accepts_only_one_neutral_12_to13_input_boundary():
    adoption,before,after,overlay,event=synthetic_adoption()
    assert adoption(after,before,overlay,'2021-12-01')==event and len(after['repairs'])==13
@pytest.mark.parametrize('kind',['finance','state','old_input','input_hash'])
def test_original_zero_adoption_refuses_finance_or_inherited_input_change(kind):
    adoption,before,after,overlay,_=synthetic_adoption()
    if kind=='finance':after['completed']+=1
    elif kind=='state':after['run']['state']['synthetic_input_only']=False
    elif kind=='old_input':after['repairs'][0]['sha256']='0'*64
    else:after['run']['input_sha256']='0'*64
    with pytest.raises(ValueError):adoption(after,before,overlay,'2021-12-01')

def test_original_legal_byte_guard_is_essential_for_unmodified_individual_cash_legs(tmp_path,monkeypatch):
    t=term();reference=t['retained_original_composite_input'];original=json.loads((f.HERE/reference['input_file']).read_bytes())
    original['gray_cash_per_old_share']='15.99';original['dotdash_cash_per_distributed_share']='43.18'
    wrong=tmp_path/'wrong-original-input.json';wrong.write_text(json.dumps(original))
    here=f.HERE
    class WrongFiles:
        def __truediv__(self,name):return wrong if name==reference['input_file']else here/name
    monkeypatch.setattr(f,'HERE',WrongFiles())
    with pytest.raises(ValueError,match='UNCHANGED_ORIGINAL_LEGAL_AND_COMPILER_BYTES'):f.research_original_unheld_composite_term(t)
    need=f.need;monkeypatch.setattr(f,'need',lambda value,label:None if label=='COMPOSITE_SOURCE_UNCHANGED_ORIGINAL_LEGAL_AND_COMPILER_BYTES'else need(value,label))
    # The exact sum alone must never substitute for the immutable legal legs.
    f.research_original_unheld_composite_term(t)
@pytest.mark.parametrize('label,kind',[
 ('COMPOSITE_SOURCE_ALL_ORDERED_LEGS_AND_EXACT_DECIMAL_SUM','sum'),
 ('COMPOSITE_SOURCE_EXACT_NATIVE_DAY_CURRENT_PARENT_IDENTITY_AND_ORIGINAL_CLOCK','clock'),
 ('COMPOSITE_SOURCE_EXPLICIT_SELECTED_UNHELD_ONLY_AUTHORITY','authority'),
 ('COMPOSITE_SCOPE_NO_RELATED_CHILD_INTENT_RESERVATION_OR_DUE_BILL','child')])
def test_meaningful_new_guard_removals(parent,monkeypatch,label,kind):
    t=term();s=scope(parent);state=deepcopy(parent['run']['state'])
    if kind=='sum':t['research_assumption']['aggregate_cash_per_original_share']='42.18'
    elif kind=='clock':t['added']['session']='2021-12-02'
    elif kind=='authority':t['portfolio_completion_authorized']=True
    else:state['wealth_core']['episodes']['999']=dict(security_id='CHILD',ticker='OTHER',source_lots=[dict(parent_security_id=s['security_id'])])
    action=(lambda:f.research_original_unheld_composite_term(t))if kind!='child'else(lambda:f.require_source_scope(state['wealth_core'],state['pending'],state['ledger'],s))
    with pytest.raises(ValueError):action()
    need=f.need;monkeypatch.setattr(f,'need',lambda value,code:None if code==label else need(value,code));action()
@pytest.mark.parametrize('name',['research.pooled_vacancy_funding','stock_strategy_shared','sentinel','numpy','pandas'])
def test_no_financial_imports(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
