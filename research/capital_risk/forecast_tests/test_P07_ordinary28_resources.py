"""Complete resource identities and closure refusal; no local book staging."""
import sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('ORDINARY28_RESOURCES_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_ordinary28_resources as p

def test_actual_full27_closure_has_all_history_and_independently_authenticated_sources():
 v=p.fact();declared=p.declarations(v)
 assert (v['requirements'],v['logical_bytes'])==(245,430989588)
 assert len(declared)+len(v['historical_archive_resolutions'])==245
 assert len(v['original216_destinations'])==216 and len(v['actual_full27_read_trace']['reads'])==103
 assert len(v['current_owned_book_reads'])==28 and not set(v['current_owned_book_reads'])&set(v['resources'])
 assert v['resources'][p.PREFIX+'/origin/prior-hosted-monthly-reproduction.json']['archive_role']=='readonly243'

@pytest.mark.parametrize('change',['original216','native_archive','member_hash','role','book_alias','read_trace'])
def test_omitted_changed_or_misclassified_history_is_refused(change):
 v=deepcopy(p.fact())
 if change=='original216':v['resources'].pop(v['original216_destinations'][0])
 elif change=='native_archive':v['historical_archive_resolutions'].pop()
 elif change=='member_hash':next(iter(v['resources'].values()))['sha256']='0'*64
 elif change=='role':next(iter(v['resources'].values()))['archive_role']='MISSING_OR_WRONG_CAPTURE'
 elif change=='book_alias':v['resources']['book/checkpoint.json.gz']=deepcopy(next(iter(v['resources'].values())))
 else:v['actual_full27_read_trace']['reads']['UNKNOWN_UNCOPIED_HISTORICAL_ASSET.json']=dict(bytes=1,sha256='0'*64)
 with pytest.raises(ValueError):p.declarations(v)

@pytest.mark.parametrize('day',['2023-07-11','2023-07-28'])
def test_both_previously_missing_july_records_are_mandatory(day):
 v=deepcopy(p.fact());v['resources'].pop('p07-vivo-ordinary25-observation/actual-future-event-'+day+'.json')
 with pytest.raises(ValueError,match='BOTH_AUTHENTIC_JULY'):p.declarations(v)

def test_july_guard_removal_really_accepts_the_previously_failed_missing_resource(monkeypatch):
 v=deepcopy(p.fact());v['resources'].pop('p07-vivo-ordinary25-observation/actual-future-event-2023-07-11.json')
 with pytest.raises(ValueError,match='BOTH_AUTHENTIC_JULY'):p.declarations(v)
 old=p.need;monkeypatch.setattr(p,'need',lambda ok,label:None if label=='ORDINARY28_RESOURCES_BOTH_AUTHENTIC_JULY_OBSERVER_RECORDS_REQUIRED' else old(ok,label))
 assert p.declarations(v)

def test_raw987_is_separate_from_literal972_committed_seed():
 v=p.fact();assert (v['raw_proof']['rows'],v['committed_proof']['rows'])==(987,972)
 assert len(v['excluded_tail_sessions'])==15 and min(v['excluded_tail_sessions'])>'2023-08-31'
 assert v['last_committed_proof']['session']=='2023-08-31'
 assert v['financial_authority']is v['actual_neutral28_known']is v['financial_profile_ready']is False

def test_local_copy_entries_remain_closed():
 with pytest.raises(ValueError):p.preserve(None,None,None,None,None)
 with pytest.raises(ValueError):p.canary(None,None)

def test_financial_import_fences():
 for n in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(x==n or x.startswith(n+'.') for x in sys.modules)
  with pytest.raises(ImportError):Fence().find_spec(n)
