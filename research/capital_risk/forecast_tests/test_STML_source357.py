"""Full authentic source preimages and strict typed event DATA, without a book."""
import json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('STML_SOURCE_TEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_STML_source as p
from system_campaign_financial_partial import root_spec

def test_whole_batch_schema_and_all_raw_rows_are_preserved():
 v=p.catalog();assert p.validate(v,root_lookup=root_spec)==v
 assert v['source_payload']['schema']=='research.source-evidence-batch/1'
 assert len(v['source_payload']['observations'])==8 and len(v['source_payload']['native_groups'])==3
 assert v['event_date_ownership_verified'] is False
 assert v['market_source']['raw_event_row']['raw_compatible_volume']=='84'
 assert v['market_source']['raw_event_row']['raw_close']=='11.83'
 assert v['event']['upfront_cash_per_share']=='11.50' and v['event']['right_upper_per_share']=='1.00'
 assert v['native']['cash_per_share'] is None

@pytest.mark.parametrize('change',['authority','bound','effective','parent','native_cash','missing_raw','market_metadata','ownership','source_schema','manifest_payload','primary','semantics'])
def test_mutation_of_any_source_authority_native_or_interpretation_is_rejected(change):
 v=p.catalog()
 if change=='authority':v['financial_authority']=True
 elif change=='bound':v['event']['right_upper_per_share']='0.50'
 elif change=='effective':v['event']['effective_session']='2020-06-11'
 elif change=='parent':v['parent_completed']=613
 elif change=='native_cash':v['native']['cash_per_share']=11.50
 elif change=='missing_raw':v['source_payload']['native_groups'][0]['raw_rows'].pop()
 elif change=='market_metadata':v['market_source']['raw_event_row']['ff12']='UPGRADED'
 elif change=='ownership':v['event_date_ownership_verified']=True
 elif change=='source_schema':v['source_payload']['schema']='research.independent-source290-DATA-validation/1'
 elif change=='manifest_payload':v['authenticated_manifest']['members']['source-evidence.json']['sha256']='0'*64
 elif change=='primary':v['primary_facts']['mandatory_cash_per_common_share']='12.50'
 else:v['input_semantics_sources']['system_campaign_second_bounded_factory.py']='0'*64
 with pytest.raises(ValueError):p.validate(v,root_lookup=root_spec)

def test_quote_rewrite_still_fails_after_an_attacker_updates_its_own_digest():
 v=p.catalog();v['market_source']['raw_event_row']['raw_open']='12.50'
 v['market_source_sha256']=p.sha(p.encoded(v['market_source']))
 with pytest.raises(ValueError,match='FULL_ORIGINAL_EVENT'):p.validate(v,root_lookup=root_spec)

def test_complete_market_preimage_guard_falsifier(monkeypatch):
 v=p.catalog();v['market_source']['raw_event_row']['raw_open']='12.50';v['market_source_sha256']=p.sha(p.encoded(v['market_source']))
 with pytest.raises(ValueError):p.validate(v,root_lookup=root_spec)
 previous=p.need;monkeypatch.setattr(p,'need',lambda yes,label:None if label=='STML_FULL_ORIGINAL_EVENT_MARKET_SOURCE_NO_QUOTE_SUBSTITUTION' else previous(yes,label))
 assert p.validate(v,root_lookup=root_spec)==v

def test_original_hydrator_refuses_locally_before_any_financial_import(tmp_path):
 with pytest.raises(ValueError):p.hydrate(p.catalog(),tmp_path/'EXPLICIT_NONCANONICAL_SOURCE_DTO.json')
 assert list(tmp_path.iterdir())==[]

def test_distinct_later_event_evidence_keeps_original_DOVA_evidence_unchanged():
 import system_campaign_bounded_sensor_runtime_v2 as old
 from system_campaign_bounded_sensor_lifecycle_data import evidence
 v=p.catalog();before=p.encoded(old.catalog());refs=p.evidence(v)
 assert 4<=len(refs)<=32 and len({r['reference'] for r in refs})==len(refs)
 assert {r['reference'] for r in refs}.isdisjoint(r['reference'] for r in evidence(old.catalog()))
 assert p.encoded(old.catalog())==before

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
