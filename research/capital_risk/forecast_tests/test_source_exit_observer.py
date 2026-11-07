"""Genuine historical metadata and explicit noncanonical observer DTO checks."""
import gzip,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE_EXIT_OBSERVER_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_observer as p
from system_campaign_financial_partial import root_spec

@pytest.fixture(scope='module')
def actual():
 R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial356-P06-source-snapshot/capture-P06-13581395529-001')
 if not R.exists():pytest.skip('authenticated FIN356 DATA artifact required')
 root=Path('\\\\?\\'+str((R/'verified-output').resolve()));mf=json.loads((R/'authenticated-manifest.json').read_bytes())['members']
 def member(n):
  raw=(root/n).read_bytes();assert dict(bytes=len(raw),sha256=p.sha(raw))==mf[n];return raw
 parent=json.loads(gzip.decompress(member('book/checkpoint.json.gz')));spec=root_spec('P06')
 return parent,spec,p.historical(parent,spec,member)

def observer_DTO():
 term=p.source.catalog()['term'];added=term['added']
 scope=dict(EXPLICIT_NONCANONICAL_SCOPE_DTO=True,security_id=term['security_id'],session=added['session'],require_never_held=True,terminal_sha256=p.digest(added))
 return SimpleNamespace(EXPLICIT_NONCANONICAL_OBSERVER_DTO=True,terms={(added['session'],added['security_id']):deepcopy(added)},scopes=[scope])

def test_actual_history_has_all_original_cash_terms_and_BBIG_scope(actual):
 parent,spec,record=actual
 assert record['parent12_sha256']==parent['sha256'] and len(record['terms'])==3 and len(record['scopes'])==1
 assert all(t['session']<parent['source_cursor'] for t in record['terms'])
 assert record['original_origin']['WWE_conversion_delegated_to_original_terminal'] is True
 assert record['historical_financial_sessions_reexecuted']==0

def test_metadata_merge_retains_original_terms_and_both_scopes(actual):
 parent,spec,record=actual;event=observer_DTO();new=deepcopy(event.scopes)
 p.merge_history(event,record,parent)
 assert len(event.terms)==4 and len(event.scopes)==2 and event.scopes[:1]==new
 assert all(event.terms[t['session'],t['security_id']]==t for t in record['terms'])

@pytest.mark.parametrize('change',['new_held','new_date','new_price','parent','old_date','old_permission','conflict'])
def test_scope_upgrade_or_historical_replay_refused(actual,change):
 parent,spec,record=actual;record=deepcopy(record);event=observer_DTO()
 if change=='new_held':event.scopes[0]['require_never_held']=False
 elif change=='new_date':event.scopes[0]['session']='2024-09-30'
 elif change=='new_price':event.scopes[0]['terminal_sha256']='f'*64
 elif change=='parent':record['parent12_sha256']='f'*64
 elif change=='old_date':record['terms'][0]['session']='2024-09-27'
 elif change=='old_permission':record['scopes'][0]['require_never_held']=False
 else:
  term=deepcopy(record['terms'][0]);term['cash_per_share']=1.;event.terms[term['session'],term['security_id']]=term
 with pytest.raises(ValueError):p.merge_history(event,record,parent)

def test_neverheld_metadata_guard_removal_falsifier(actual,monkeypatch):
 parent,spec,record=actual;event=observer_DTO();event.scopes[0]['require_never_held']=False
 with pytest.raises(ValueError):p.merge_history(event,record,parent)
 original=p.need;monkeypatch.setattr(p,'need',lambda value,label:None if label=='SOURCE_EXIT_OBSERVER_ONLY_ORIGINAL_NEW_TBIO_SCOPE' else original(value,label))
 assert p.merge_history(event,record,parent) is event

def test_initializer_is_whole_original_code_and_uses_distinct_names():
 api=SimpleNamespace(OVERLAY='EXPLICIT_NONCANONICAL_OVERLAY_DTO',hydration_name=lambda cp:'EXPLICIT_NONCANONICAL_HYDRATION_DTO',source_scopes=lambda *a:[],SOURCE_SCOPES='source-exit-successor-scopes.json')
 init=p.initializer(api)
 assert init.__code__ is p.original.ActualEvents.__init__.__code__
 assert init.__globals__['SOURCE_SCOPES']==api.SOURCE_SCOPES and init.__globals__['source_scopes'] is api.source_scopes
 for name in ('advance','terminal','source_values'):assert getattr(p.original.ActualEvents,name).__module__=='system_campaign_financial_future'

def test_local_observer_refuses_before_creation(tmp_path,monkeypatch):
 monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);out=tmp_path/'must-not-exist'
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):p.observer(tmp_path,out,{}, {},root_spec('P06'),None)
 assert not out.exists()

def refusal_actual():
 R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial356-P06-source-snapshot/capture-P06-13581395529-001/verified-output')
 if not R.exists():pytest.skip('authenticated FIN356 DATA artifact required')
 return json.loads((R/'p06-WWE-retained-historical-observation/actual-future-event-refusal.json').read_bytes()),json.loads((R/'book/status.json').read_bytes())

def test_genuine_later_refusal_remains_excluded_from_saved_prefix(actual):
 parent,spec,record=actual;refusal,status=refusal_actual();before=p.digest((parent,refusal,status))
 result=p.excluded_refusal(refusal,status,parent)
 assert result['session']=='2024-09-27' and result['financial_sessions_admitted']==0 and result['excluded_from_saved_prefix'] is True
 assert p.digest((parent,refusal,status))==before

@pytest.mark.parametrize('change',['committed','passed','financial_source','wrong_status','wrong_failed_session'])
def test_refusal_cannot_be_relabelled_or_suppress_committed_evidence(actual,change):
 parent,spec,record=actual;refusal,status=refusal_actual();cursor=dict(EXPLICIT_NONCANONICAL_CURSOR_DTO=True,source_cursor=parent['source_cursor'],completed=parent['completed'])
 if change=='committed':cursor['source_cursor']=refusal['session']
 elif change=='passed':refusal['passed']=True
 elif change=='financial_source':refusal['financial_source_changed']=True
 elif change=='wrong_status':status['status']='COMPLETE'
 else:status['failed_session']='2024-09-30'
 with pytest.raises(ValueError):p.excluded_refusal(refusal,status,cursor)

def test_committed_refusal_guard_removal_falsifier(actual,monkeypatch):
 parent,spec,record=actual;refusal,status=refusal_actual();cursor=dict(EXPLICIT_NONCANONICAL_CURSOR_DTO=True,source_cursor=refusal['session'],completed=parent['completed'])
 with pytest.raises(ValueError):p.excluded_refusal(refusal,status,cursor)
 original=p.need;monkeypatch.setattr(p,'need',lambda value,label:None if label=='SOURCE_EXIT_OBSERVER_ONLY_GENUINE_DIAGNOSTIC_REFUSAL_AFTER_SAVED_PREFIX' else original(value,label))
 assert p.excluded_refusal(refusal,status,cursor)['financial_sessions_admitted']==0

def test_local_review_refuses_before_reading_or_writing(tmp_path,monkeypatch):
 monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);out=tmp_path/'must-not-exist'
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):p.review({}, {},tmp_path,out,spec=root_spec('P06'),old=tmp_path,neutral={},api=None)
 assert not out.exists()

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
