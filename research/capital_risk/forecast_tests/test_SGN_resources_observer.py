"""Genuine complete ancestry, all resources and original positive review routing."""
import ast,gzip,json,sys,zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('SGN_LINEAGE_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_observer as p
import system_campaign_source_exit_resources as resources
import system_campaign_source_exit_entry as entry
import system_campaign_financial_partial as partial
from system_campaign_financial_partial import root_spec

@pytest.fixture(scope='module')
def actual():
 F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/P06-request228-source-snapshot/authenticated-artifact-13596566525')
 if not F.exists():pytest.skip('authenticated request228 DATA required')
 F=Path('\\\\?\\'+str(F.resolve()));mf=json.loads((F/'authenticated-manifest.json').read_bytes())['members']
 def member(n):
  raw=(F/'verified-output'/n).read_bytes();assert dict(bytes=len(raw),sha256=p.sha(raw))==mf[n];return raw
 current=json.loads(gzip.decompress(member('book/checkpoint.json.gz')));spec=root_spec('P06')
 prior=root_spec('P06',spec['root_admission']['parent_root_admission_sha256']);names=p.profiles.paths(prior)
 parent=json.loads(gzip.decompress(member(names['PARENT'])))
 origin=json.loads(member(names['OBSERVATION']+'/'+p.ORIGIN))
 return F,current,spec,prior,parent,origin,member

def test_old13_observer_record_is_identical_to_actual_original_hosted_metadata(actual):
 _,_,_,prior,parent,origin,member=actual
 record=p.historical(parent,prior,member)
 assert record==origin['historical_metadata']
 assert len(record['scopes'])==2 and len(record['terms'])==4

def test_new14_record_retains_each_actual_previous_origin_and_all5_terms3_scopes(actual):
 _,current,spec,prior,parent,origin,member=actual
 record=p.historical(current,spec,member)
 api=p.history.input_api(parent,prior,lambda *args:pytest.fail('metadata test must not execute financial history'))
 material=json.loads(member(api.hydration_name(parent)))
 added=[t['added'] for t in material['terms'] if parent['source_cursor']<t['added']['session']<=current['source_cursor']]
 assert len(added)==1 and record['terms']==origin['historical_metadata']['terms']+added
 assert record['original_origin']==origin and record['scopes']==origin['active_and_retained_scopes']
 assert record['parent_sha256']==current['sha256'] and record['previous_parent_sha256']==parent['sha256']
 assert len(record['scopes'])==3 and len(record['terms'])==5 and record['historical_financial_sessions_reexecuted']==0
 term=p.profiles.source(spec).catalog()['term'];added=term['added']
 event=SimpleNamespace(EXPLICIT_NONCANONICAL_OBSERVER_DTO=True,terms={(added['session'],added['security_id']):deepcopy(added)},
  scopes=[dict(session=added['session'],security_id=added['security_id'],require_never_held=True,terminal_sha256=p.digest(added))])
 p.merge_history(event,record,current,spec=spec)
 assert len(event.scopes)==4 and len(event.terms)==6 and all(s['require_never_held'] is True for s in event.scopes)

def test_all138_resources_preserve_every_original_pin_and_actual_history_read(actual):
 _,_,spec,_,_,_,member=actual;plan=resources.plan(spec)
 closure=resources.closure(member,spec,plan['event_resolutions'])
 assert len(closure['requirements'])==138 and sum(v['bytes'] for v in closure['requirements'])==288182311
 old=json.loads((C/'P06-DM-source-exit-resources.json').read_bytes())
 assert all(plan['resources'][n]==pin for n,pin in old['resources'].items())
 assert resources.bound_canary(spec).__code__ is resources.original.canary.__code__
 first=next(iter(plan['resources']))
 def corrupt(n):
  raw=member(n);return bytes([raw[0]^1])+raw[1:] if n==first else raw
 with pytest.raises(ValueError):resources.dependencies.verify(closure,plan['resources'],plan['event_resolutions'],member,corrupt)

def test_positive_original_review_does_not_select_failed_review_capsule(actual):
 F,_,spec,prior,_,_,_=actual
 assert entry.failed_review_parent(spec) is False and entry.failed_review_parent(prior) is True
 assert partial.reviewed_archive_limit(spec)==1024**3
 with zipfile.ZipFile(F/'artifact.zip') as z:
  assert partial.public_names(spec,z)==set(z.namelist())
  receipt=json.loads(z.read(spec['receipt_name']))
 assert [receipt[n]['exit_code'] for n in ('preflight','worker','reviewer')]==[0,1,0]
 # Execute the actual routing lambdas as pure metadata, outside hosted context.
 fn=next(n for n in ast.parse(Path(entry.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='context')
 calls=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0]) in ('dispatch.applies','dispatch.accounting_review')]
 scope=dict(vars(entry),saved_dispatch=dict(applies=lambda target:False,accounting_review=lambda target:(partial.review_name(target),target['review_sha256'])))
 funcs={ast.unparse(n.targets[0]):eval(compile(ast.Expression(body=n.value),'<actual-positive-original-review-routing-DATA>','eval'),scope) for n in calls}
 assert funcs['dispatch.applies'](spec) is False
 assert funcs['dispatch.accounting_review'](spec)==(partial.review_name(spec),spec['review_sha256'])
 assert funcs['dispatch.applies'](prior) is True
 assert funcs['dispatch.accounting_review'](prior)==entry.loader.accounting_review(prior)

def test_immediate_predecessor_guard_removal_on_explicit_metadata_DTO(actual,monkeypatch):
 _,current,spec,_,_,_,_=actual
 target=deepcopy(spec);target['EXPLICIT_NONCANONICAL_ADMISSION_EDGE_DTO']=True
 target['root_admission']['parent_root_admission_sha256']=p.profiles.LEGACY_ROOT
 # Isolate the edge guard from the earlier admission-hash check; no book changes.
 monkeypatch.setattr(p.history,'parent_contract',lambda *args:None)
 original_profile=p.profiles.profile
 monkeypatch.setattr(p.profiles,'profile',lambda value:original_profile(spec) if value is target else original_profile(value))
 class UnexpectedArchiveRead(Exception):pass
 def no_read(*args):raise UnexpectedArchiveRead()
 monkeypatch.setattr(p.history,'archived_parent',no_read)
 with pytest.raises(ValueError,match='IMMEDIATE_ADMITTED_INPUT_PREDECESSOR'):p.historical(current,target,lambda n:None)
 original=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='SOURCE_EXIT_OBSERVER_EXACT_IMMEDIATE_ADMITTED_INPUT_PREDECESSOR' else original(ok,label))
 with pytest.raises(UnexpectedArchiveRead):p.historical(current,target,lambda n:None)
