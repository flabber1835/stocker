"""Actual source-batch preimages and existing source-only model, DATA only."""
import json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE_EXIT_INPUT_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_input as p
from system_campaign_financial_partial import root_spec

@pytest.fixture(scope='module')
def actual():return json.loads((C/p.CATALOG).read_bytes())

def test_actual_source_exit_uses_prior_proxy_and_preserves_native_quote(actual):
 value=p.validate(actual,root_lookup=root_spec)
 assert value['term']['added']['cash_per_share']==3.99 and value['event_row']['raw_close']=='3.23'
 assert value['financial_profile_ready'] is value['financial_authority'] is False
 assert len(value['parent_descriptors'])==12 and value['parent_completed']==1677
 codec,_,terms=p.selected('P06',cursor='2024-08-30');assert terms==[value['term']]
 assert codec.parent_outer_sha256==root_spec('P06',actual['term']['parent_root_admission_sha256'])['outer_sha256']

@pytest.mark.parametrize('change',['authority','profile','adopt','root','input','descriptors','parent_role','event_row','prior_row','native','missing','event_roles','cash_claim','extinction','amount'])
def test_unsafe_or_unbound_term_is_refused(actual,change):
 v=deepcopy(actual)
 if change=='authority':v['financial_authority']=True
 elif change=='profile':v['financial_profile_ready']=True
 elif change=='adopt':v['input_adopted']=True
 elif change=='root':v['term']['parent_outer_sha256']='f'*64
 elif change=='input':v['parent_input_sha256']='f'*64
 elif change=='descriptors':v['parent_descriptors']=v['parent_descriptors'][:-1]
 elif change=='parent_role':v['parent_actual_never_held_scope_verified']=False
 elif change=='event_row':v['event_row']['raw_close']='9.1'
 elif change=='prior_row':v['prior_row']['raw_close']='9.1'
 elif change=='native':v['term']['native']['cash_per_share']=5.7
 elif change=='missing':v['first_queried_missing_session']='2024-10-01'
 elif change=='event_roles':v['event_date_roles_verified']=True
 elif change=='cash_claim':v['statutory_cash_claimed']=True
 elif change=='extinction':v['otc_security_extinction_claimed']=True
 else:v['term']['added']['cash_per_share']=3.23
 with pytest.raises(ValueError):p.validate(v,root_lookup=root_spec)

def test_native_observation_preimage_guard_removal_falsifier(actual,monkeypatch):
 v=deepcopy(actual);v['event_row']['raw_close']='9.1'
 with pytest.raises(ValueError,match='UNCHANGED_DISTINCT'):p.validate(v,root_lookup=root_spec)
 original=p.need;monkeypatch.setattr(p,'need',lambda value,label:None if label=='SOURCE_EXIT_CATALOG_ENTIRE_UNCHANGED_DISTINCT_SOURCE_OBSERVATION' else original(value,label))
 assert p.validate(v,root_lookup=root_spec)['event_row']['raw_close']=='9.1'

def test_actual_parent_scope_is_read_only_and_rejects_any_ownership(actual):
 import gzip
 R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial356-P06-source-snapshot/capture-P06-13581395529-001/verified-output')
 cp=json.loads(gzip.decompress((R/'book/checkpoint.json.gz').read_bytes()));state=cp['run']['state'];before=p.digest(state)
 scope=dict(security_id=actual['term']['security_id'],source_ticker='TBIO',require_never_held=True)
 p.original.require_source_scope(state['wealth_core'],state['pending'],state['ledger'],scope);assert p.digest(state)==before
 state['pending'].append(dict(EXPLICIT_NONCANONICAL_INTENT_DTO=True,security_id=scope['security_id']))
 with pytest.raises(ValueError):p.original.require_source_scope(state['wealth_core'],state['pending'],state['ledger'],scope)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
