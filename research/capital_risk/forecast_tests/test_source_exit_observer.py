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
from system_campaign_financial_partial import root_spec as admitted_root
def root_spec(arm):return admitted_root(arm,p.profiles.LEGACY_ROOT) if arm=='P06' else admitted_root(arm)

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


@pytest.fixture(scope='module')
def actual_FIN366_source_interface():
 root=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial366-source-snapshot/authenticated-artifact-13587599730')
 if not root.exists():pytest.skip('authenticated FIN366 DATA artifact required')
 members=json.loads((root/'authenticated-manifest.json').read_bytes())['members']
 output=Path('\\\\?\\'+str((root/'verified-output').resolve()))
 def member(name):
  raw=(output/name).read_bytes()
  assert dict(bytes=len(raw),sha256=p.sha(raw))==members[name]
  return raw
 current=json.loads(gzip.decompress(member('book/checkpoint.json.gz')))
 assert (current['completed'],current['source_cursor'],current['sha256'])==(1821,'2025-03-31','8e9ca16b18cf79928e6e2d7320defacfdecca781447a5a8bd6fd803db02fe6c7')
 rows=[json.loads(v) for v in member('book/daily.jsonl').splitlines()]
 i,=[i for i,r in enumerate(rows) if r['session']=='2024-09-27']
 before=rows[i-1]['evidence']['research_entry_audit']['closing_accounting']
 opened=rows[i]['evidence']['research_entry_audit']['opening_accounting']
 origin=json.loads(member(p.DIRECTORY+'/'+p.ORIGIN))
 scope,=[s for s in origin['active_and_retained_scopes'] if s['session']=='2024-09-27']
 name='hydrated-source-exit-successor-catalog-3a7dbe9befba4316481b5955203302edd057e5e90b655ba2531c8ccd92f5d12a.json'
 term,=[t for t in json.loads(member(name))['terms'] if t['security_id']==scope['security_id'] and t['added']['session']==scope['session']]
 record=json.loads(member(p.DIRECTORY+'/actual-future-event-2024-09-27.json'))
 cert,=[json.loads(v) for v in member('uncertainty-certificate.jsonl').splitlines() if json.loads(v)['session']=='2024-09-27']
 selected=scope['security_id'] in [v['security_id'] for v in cert['material']['rows']]
 return record,term,scope,before,opened,current['run']['state']['ledger']['events'],selected


def test_actual_FIN366_compact_interface_regression_preserves_original_validator_and_evidence(actual_FIN366_source_interface):
 record,term,scope,before,opened,events,selected=actual_FIN366_source_interface
 unchanged=p.digest(actual_FIN366_source_interface)
 # Reproduce the exact failed interface with genuine saved evidence.
 with pytest.raises(KeyError,match='events'):
  p.previous.prior.source_record(record,term,scope,before,opened,events,source_was_selected=selected)
 result=p.source_record(record,term,scope,before,opened,events,source_was_selected=selected)
 assert result==dict(ticker='TBIO',session='2024-09-27',actual_noop=True,original_kernel_source_delegated=True,
  portfolio_completion_authorized=False,actual_settlement_claimed=False)
 assert p.digest(actual_FIN366_source_interface)==unchanged
 for snapshot in (before,opened):
  full=p.accounting_snapshot(snapshot,events)
  assert full['ledger']['events']==events[:snapshot['ledger']['event_count']]
  assert full['ledger']['receivables']==snapshot['ledger']['receivables']


@pytest.mark.parametrize('count',[True,-1,1561,None,'1455'])
def test_actual_FIN366_invalid_compact_count_refused(actual_FIN366_source_interface,count):
 *_,before,opened,events,selected=actual_FIN366_source_interface
 snapshot=deepcopy(before);snapshot['ledger']['event_count']=count
 with pytest.raises(ValueError,match='EXACT_COMPACT_LEDGER_PREFIX'):p.accounting_snapshot(snapshot,events)


def test_actual_FIN366_compact_bound_guard_removal_falsifier(actual_FIN366_source_interface,monkeypatch):
 _,_,_,before,_,events,_=actual_FIN366_source_interface
 snapshot=deepcopy(before);snapshot['ledger']['event_count']=len(events)+1
 with pytest.raises(ValueError,match='EXACT_COMPACT_LEDGER_PREFIX'):p.accounting_snapshot(snapshot,events)
 original=p.need
 monkeypatch.setattr(p,'need',lambda value,label:None if label=='SOURCE_EXIT_OBSERVER_EXACT_COMPACT_LEDGER_PREFIX' else original(value,label))
 assert len(p.accounting_snapshot(snapshot,events)['ledger']['events'])!=snapshot['ledger']['event_count']

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
