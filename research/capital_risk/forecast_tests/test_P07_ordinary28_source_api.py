"""Source facts and opaque API DTOs only; never import the financial engine."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('ORDINARY28_SOURCE_API_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_ordinary28_data as d
import system_campaign_p07_ordinary28_api as a

def test_exact_batch_reuses_twelve_original_cash_terms_and_three_exact_inherited_terms():
 v=d.fact();assert [x['term']['ticker'] for x in v['selected']]==['CFMS','QUOT','RADI','RETA','SYNH','ATVI','SGEN','SPLK','CBAY','ASTR','JNPR','AMED']
 assert [x['term']['ticker'] for x in v['already_inherited']]==['NEWR','IMGN','CTLT']
 assert (C/d.CATALOG).read_bytes()==d.encoded(d.catalog())
 assert len({x['term']['security_id'] for x in v['selected']+v['already_inherited']})==15
 assert all(d.retained(x,v['source_files'])==x['term'] for x in v['selected']+v['already_inherited'])

@pytest.mark.parametrize('field',['cash','day','native','identity','scope'])
def test_original_cash_identity_date_native_and_scope_cannot_be_rewritten(field):
 v=d.fact();row=deepcopy(next(x for x in v['selected'] if x['term']['ticker']=='RETA'))
 if field=='cash':row['term']['added']['cash_per_share']=172.36
 elif field=='day':row['term']['added']['session']='2023-09-25'
 elif field=='native':row['term']['native_term_sha256']='0'*64
 elif field=='identity':row['term']['identity_witness']['issuer_id']='WRONG'
 else:row['term']['require_unowned_and_unordered']=True
 with pytest.raises(ValueError,match='RETAINED_ORIGINAL_TERM_BYTES_AND_SCOPE'):d.retained(row,v['source_files'])

def test_cash_guard_removal_really_accepts_a_wrong_positive_cash_amount(monkeypatch):
 v=d.fact();row=deepcopy(next(x for x in v['selected'] if x['term']['ticker']=='RETA'));row['term']['added']['cash_per_share']=172.36
 with pytest.raises(ValueError,match='RETAINED_ORIGINAL_TERM_BYTES_AND_SCOPE'):d.retained(row,v['source_files'])
 old=d.need;monkeypatch.setattr(d,'need',lambda ok,label:None if label=='ORDINARY28_RETAINED_ORIGINAL_TERM_BYTES_AND_SCOPE' else old(ok,label))
 assert d.retained(row,v['source_files'])['added']['cash_per_share']==172.36

def test_reta_native_market_quote_is_distinct_from_legal_cash_and_next_session():
 v=d.fact();t=next(x['term'] for x in v['selected'] if x['term']['ticker']=='RETA')
 p=json.loads((C/v['source_catalog']).read_bytes())['source_evidence']
 row=next(g for g in p['observations'] if g['query']['name']=='p07-next-native')['rows'][0]['source_row']
 assert row['raw_close']=='172.36000000000001' and t['added']['cash_per_share']==172.5
 assert row['session']==t['native_session']=='2023-09-25' and t['added']['session']=='2023-09-26'
 d.completion_session(t,['2023-09-22','2023-09-25','2023-09-26'])
 with pytest.raises(ValueError,match='NEXT_FROZEN_SESSION'):d.completion_session(t,['2023-09-22','2023-09-25','2023-09-27'])

def test_retained_next_convention_is_preserved_without_claiming_preopen():
 t=next(x['term'] for x in d.fact()['selected'] if x['term']['ticker']=='AMED')
 assert t['recognition_rule']==d.NEXT and t['preopen_completion_confirmed']is False
 assert t['actual_completion_date']==t['last_trading_session']=='2025-08-14' and t['added']['session']=='2025-08-15'
 d.completion_session(t,['2025-08-13','2025-08-14','2025-08-15'])

def test_whole_original_remaining_AST_undo():
 raw=Path(a.original.__file__).read_bytes();old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='remaining_ordinary_terms');new=a.remaining_tree(raw)
 def site(fn):return next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(x,ast.Constant) and x.value=='FUTURE_INHERITED_ORDINARY_EXACT_RETAINED_TYPED_INPUT' for x in n.args))
 site(new).args[0]=deepcopy(site(old).args[0]);assert ast.dump(new)==ast.dump(old)

def metadata_DTO():
 roots=json.loads((C/'system-campaign-financial-admitted-parents.json').read_bytes());spec=roots['arms']['P07']['transport']
 return dict(EXPLICIT_NONCANONICAL_CURRENT_METADATA_DTO=True,repairs=deepcopy(spec['repairs'])),spec

def test_all_five_typed_descriptors_use_the_same_complete_unprojected_current_DTO():
 cp,spec=metadata_DTO();calls=[]
 def visit(root,current):calls.append(current);assert current is cp;return dict(passed=True,full_inputs=27)
 for row in d.fact()['nonterminal_descriptors']:assert a.known_input(Path('EXPLICIT_NONCANONICAL_ROOT'),cp,row['descriptor'],spec,visit)
 assert len(calls)==5 and all(x is cp for x in calls) and len(cp['repairs'])==27

@pytest.mark.parametrize('change',['visitor_failed','visitor_count','narrowed','unknown','extra_input'])
def test_no_unknown_or_narrowed_typed_history_is_accepted(change):
 cp,spec=metadata_DTO();entry=d.fact()['nonterminal_descriptors'][0]['descriptor'];result=dict(passed=True,full_inputs=27)
 if change=='visitor_failed':result['passed']=False
 elif change=='visitor_count':result['full_inputs']=26
 elif change=='narrowed':cp['repairs']=cp['repairs'][:24];result['full_inputs']=24
 elif change=='unknown':entry=dict(filename='0'*64+'.json',sha256='0'*64)
 else:cp['repairs']+=cp['repairs'][:2];result['full_inputs']=29
 with pytest.raises(ValueError,match='COMPLETE_CURRENT_HISTORY'):a.known_input(Path('EXPLICIT_NONCANONICAL_ROOT'),cp,entry,spec,lambda *args:result)

def test_complete_history_guard_removal_really_accepts_an_unknown_descriptor(monkeypatch):
 cp,spec=metadata_DTO();entry=dict(EXPLICIT_NONCANONICAL_UNKNOWN_DESCRIPTOR=True);visit=lambda *args:dict(passed=True,full_inputs=27)
 with pytest.raises(ValueError,match='COMPLETE_CURRENT_HISTORY'):a.known_input(Path('EXPLICIT_NONCANONICAL_ROOT'),cp,entry,spec,visit)
 old=d.need;monkeypatch.setattr(d,'need',lambda ok,label:None if label=='ORDINARY28_COMPLETE_CURRENT_HISTORY_AND_ONLY_FIVE_ORIGINAL_TYPED_INPUTS' else old(ok,label))
 assert a.known_input(Path('EXPLICIT_NONCANONICAL_ROOT'),cp,entry,spec,visit)

def opaque_API(monkeypatch):
 cp=dict(EXPLICIT_NONCANONICAL_API_PARENT_DTO=True);spec=dict(EXPLICIT_NONCANONICAL_API_SPEC_DTO=True)
 def contract(current,target):assert current is cp and target is spec
 value=d.catalog();codec=SimpleNamespace(catalog=value,catalog_sha=d.sha(d.encoded(value)),compiler_sha='EXPLICIT_NONCANONICAL_COMPILER_DTO')
 monkeypatch.setattr(d,'parent_contract',contract);monkeypatch.setattr(d,'codec',lambda current,target:codec)
 return a.api(cp,spec,validate_history=lambda *args:dict(passed=True,full_inputs=27))

def test_six_entire_original_API_functions_have_identical_code_objects(monkeypatch):
 api=opaque_API(monkeypatch)
 for name in a.FUNCTIONS:
  fn=getattr(api,name);fn=getattr(fn,'__wrapped__',fn)
  assert fn.__code__ is getattr(a.original,name).__code__
 assert len(api.selected('P07',cursor='2023-08-31')[2])==12
 with pytest.raises(ValueError,match='GENUINE1426_PARENT_CLOCK'):api.selected('P07',cursor='2023-09-22')

def test_current_selected_reta_is_not_assumed_unselected_or_owned_later():
 v=d.fact();r=v['actual_parent_roles']['877716075426179792']
 assert r['leadership_selected']is True and r['held']==[] and r['pending']==[]
 assert v['current_role_is_not_future_ownership']is True and v['event_date_ownership']=='UNKNOWN_UNTIL_ACTUAL_GUARDED_TRANSITION'
 assert v['financial_authority']is v['financial_profile_ready']is v['local_canonical_runtime_executed']is False

def test_financial_imports_are_fenced():
 for n in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(x==n or x.startswith(n+'.') for x in sys.modules)
  with pytest.raises(ImportError):Fence().find_spec(n)
