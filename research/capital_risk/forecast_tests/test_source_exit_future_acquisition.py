"""Complete original source compiler and authentic SGN DATA; no local finance."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('SGN_SOURCE_COMPILER_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_future_acquisition as p
from system_campaign_financial_partial import root_spec

@pytest.fixture
def actual():
 return json.loads((C/p.CATALOG).read_bytes())

def test_whole_original_compiler_AST_undo_has_one_native_pair_change():
 raw=Path(p.previous.__file__).read_bytes()
 before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate')
 after=p.validator_tree(raw)
 site,=[n for n in ast.walk(after) if isinstance(n,ast.Set)
  and all(isinstance(v,ast.Constant) for v in n.elts)
  and {v.value for v in n.elts}=={'acquisitionby','delisted'}]
 old,=[n for n in ast.walk(before) if isinstance(n,ast.Set)
  and all(isinstance(v,ast.Constant) for v in n.elts)
  and {v.value for v in n.elts}=={'delisted','regulatorydelisting'}]
 site.elts=deepcopy(old.elts)
 assert ast.dump(before)==ast.dump(after)

def test_complete_actual_catalog_and_original_selector_code(actual):
 assert p.catalog()==p.validate(actual,root_lookup=root_spec)==actual
 term=actual['term'];codec,name,terms=p.selected('P06',cursor='2026-02-27')
 assert name==p.CATALOG and terms==[term] and codec.compiler_sha==p.sha(Path(p.__file__).read_bytes())
 assert term['retained_quote']['session']=='2026-03-13' and term['native_session']=='2026-03-16'
 assert term['parent_cursor']<term['identity_witness']['session']<term['native_session']
 assert term['retained_quote']['raw_close']==0.7
 assert actual['event_row']['raw_close']=='0.54000000000000004' and term['native']['cash_per_share'] is None
 assert term['portfolio_completion_authorized'] is term['research_assumption']['actual_settlement_claimed'] is False

def test_original_provider_still_refuses_acquisition_pair_and_is_unchanged(actual):
 assert p.sha(Path(p.previous.__file__).read_bytes())==p.ORIGINAL_SHA
 with pytest.raises(ValueError,match='NATIVE_GROUP'):p.previous.validate(actual,root_lookup=root_spec)
 old=json.loads((C/'P06-TBIO-source-exit-input-catalog.json').read_bytes())
 assert p.previous.validate(old,root_lookup=root_spec)==old

@pytest.mark.parametrize('mutation',['authority','adopt','ready','parent','native_cash','event_quote','source_row','statutory','roles'])
def test_complete_original_guards_remain_active(actual,mutation):
 value=deepcopy(actual)
 if mutation=='authority':value['financial_authority']=True
 elif mutation=='adopt':value['input_adopted']=True
 elif mutation=='ready':value['financial_profile_ready']=True
 elif mutation=='parent':value['parent_completed']+=1
 elif mutation=='native_cash':value['term']['native']['cash_per_share']=2.2
 elif mutation=='event_quote':value['event_quote_is_proxy']=True
 elif mutation=='source_row':value['prior_row']['raw_close']='2.2'
 elif mutation=='statutory':value['statutory_cash_claimed']=True
 else:value['event_date_roles_verified']=True
 with pytest.raises(ValueError):p.validate(value,root_lookup=root_spec)

def test_authority_guard_removal_is_meaningful(actual,monkeypatch):
 actual['financial_authority']=True
 with pytest.raises(ValueError,match='DATA_ONLY'):p.validate(actual,root_lookup=root_spec)
 original=p.previous.need
 monkeypatch.setattr(p.previous,'need',lambda ok,label:None if label=='SOURCE_EXIT_CATALOG_DATA_ONLY_NOT_FINANCIAL_PROFILE' else original(ok,label))
 assert p.validate(actual,root_lookup=root_spec)['financial_authority'] is True

@pytest.mark.parametrize('n',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(n):
 assert not any(k==n or k.startswith(n+'.') for k in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(n)
