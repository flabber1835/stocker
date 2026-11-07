"""One original observer, exact historical metadata, actual future role guards."""
import json
from copy import deepcopy
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
import system_campaign_financial_future as original
import system_campaign_source_exit_api as api_module
import system_campaign_source_exit_history as history
import system_campaign_source_exit_input as source
import system_campaign_p06_WWE12_observer as previous
import system_campaign_p06_WWE12_models as previous_models
import system_campaign_source_exit_profiles as profiles
DIRECTORY='source-exit-successor-observation'
ORIGIN='observer-origin.json'

def historical(parent,spec,member):
 from system_campaign_financial_partial import root_spec
 if profiles.profile(spec)['parent_inputs']>12:
  history.parent_contract(parent,spec);oldspec=root_spec('P06',profiles.LEGACY_ROOT);names=profiles.paths(oldspec)
  prior=history.archived_parent(oldspec,member);record=historical(prior,oldspec,member)
  api=history.input_api(prior,oldspec,previous_models.full);neutral=history.strict_json(member(names['NEUTRAL']))
  material=json.loads(member(api.hydration_name(prior)))
  scopes=json.loads(member(api.SOURCE_SCOPES))
  prior_origin=json.loads(member(names['OBSERVATION']+'/'+ORIGIN))
  need(prior_origin==origin(prior,neutral,record,scopes+record['scopes'])
   and parent['repairs']==neutral['repairs'] and parent['source_cursor']>prior['source_cursor'],
   'SOURCE_EXIT_OBSERVER_EXACT_COMPLETE_PREVIOUS_SOURCE_HISTORY')
  for name in (api.OVERLAY,api.hydration_name(prior),api.SOURCE_SCOPES):
   need(member(names['OBSERVATION']+'/'+name)==member(name),'SOURCE_EXIT_OBSERVER_UNCHANGED_PREVIOUS_SOURCE_PAYLOAD:'+name)
  terms=record['terms']+[deepcopy(t['added']) for t in material['terms'] if prior['source_cursor']<t['added']['session']<=parent['source_cursor']]
  retained=scopes+record['scopes']
  need(len(retained)==profiles.profile(spec)['retained_scope_count'] and len(terms)==4
   and all(t['session']<parent['source_cursor'] for t in terms),'SOURCE_EXIT_OBSERVER_ALL_PREVIOUS_SOURCE_TERMS_STRICTLY_HISTORICAL')
  return dict(schema='research.source-exit-original-observer-history/2',parent_sha256=parent['sha256'],
   previous_parent_sha256=prior['sha256'],original_origin=prior_origin,terms=terms,scopes=retained,historical_financial_sessions_reexecuted=0)
 history.parent_contract(parent,spec);oldspec=root_spec('P06',previous.data.ROOT)
 raw=member(previous_models.PARENT)
 need(dict(bytes=len(raw),sha256=sha(raw))==oldspec['selected_file'],'SOURCE_EXIT_OBSERVER_GENUINE_PARENT11_ARCHIVE')
 parent11=strict_json(raw);previous.data.parent_contract(parent11,oldspec)
 need(parent11['repairs']==parent['repairs'][:-1] and parent11['source_cursor']<parent['source_cursor'],
  'SOURCE_EXIT_OBSERVER_HISTORICAL_PARENT11_RETAINED_IN_ENTIRE_PARENT12')
 historical_checkpoint,_,payloads,scopes=previous.historical_contract(parent11,oldspec,member)
 old_origin=json.loads(member(previous.DIRECTORY+'/'+previous.ORIGIN));terms=old_origin['old_cash_terms']
 need(old_origin==previous.origin(parent11,historical_checkpoint,payloads,terms,scopes),'SOURCE_EXIT_OBSERVER_UNCHANGED_ORIGINAL_HISTORICAL_ORIGIN')
 for n,b in payloads.items():need(member(previous.DIRECTORY+'/'+n)==b,'SOURCE_EXIT_OBSERVER_EXACT_ORIGINAL_HISTORICAL_PAYLOAD:'+n)
 added=[deepcopy(t['added']) for t in terms]+json.loads(payloads[previous.prior_models.OVERLAY])['add']
 need(len(added)==3 and len(scopes)==1 and len({(t['session'],t['security_id']) for t in added})==3
  and all(t['session']<parent['source_cursor'] for t in added) and all(s['session']<parent['source_cursor'] for s in scopes),
  'SOURCE_EXIT_OBSERVER_ALL_THREE_RETAINED_TERMS_AND_SCOPE_STRICTLY_HISTORICAL')
 return dict(schema='research.source-exit-original-observer-history/1',parent12_sha256=parent['sha256'],
  historical_parent11_sha256=parent11['sha256'],historical_parent10_sha256=historical_checkpoint['sha256'],
  original_origin=old_origin,terms=added,scopes=scopes,historical_financial_sessions_reexecuted=0)

def merge_history(event,record,parent,*,spec=None):
 if spec is None:
  from system_campaign_financial_partial import root_spec
  spec=root_spec('P06',profiles.LEGACY_ROOT)
 term=profiles.source(spec).catalog()['term'];scopes=deepcopy(event.scopes)
 need(record.get('parent_sha256',record.get('parent12_sha256'))==parent['sha256'] and len(scopes)==1 and scopes[0]['security_id']==term['security_id']
  and scopes[0]['session']==term['added']['session'] and scopes[0]['require_never_held'] is True
  and scopes[0]['terminal_sha256']==digest(term['added']),'SOURCE_EXIT_OBSERVER_ONLY_ORIGINAL_NEW_TBIO_SCOPE')
 for t in record['terms']:
  key=t['session'],t['security_id']
  need(t['session']<parent['source_cursor'] and t['kind']=='CASH_MERGER' and (key not in event.terms or event.terms[key]==t),
   'SOURCE_EXIT_OBSERVER_NO_CONFLICT_OR_AUTHORITY_UPGRADE_IN_HISTORICAL_TERMS')
  event.terms[key]=deepcopy(t)
 for s in record['scopes']:
  key=s['session'],s['security_id']
  need(s['session']<parent['source_cursor'] and s['require_never_held'] is True and s not in event.scopes
   and key in event.terms and digest(event.terms[key])==s['terminal_sha256'],'SOURCE_EXIT_OBSERVER_EXACT_HISTORICAL_BBIG_SCOPE_AND_TERM')
  event.scopes.append(deepcopy(s))
 need(event.scopes[:len(scopes)]==scopes and len(record['scopes'])==profiles.profile(spec)['retained_scope_count']
  and len(event.scopes)==1+len(record['scopes']),'SOURCE_EXIT_OBSERVER_NEW_SCOPE_UNCHANGED_AND_ORIGINAL_OLD_SCOPE_RETAINED')
 return event

def initializer(api):
 fn=original.ActualEvents.__init__;need(sha(Path(original.__file__).read_bytes())==api_module.FUTURE_SHA and fn.__closure__ is None,
  'SOURCE_EXIT_OBSERVER_WHOLE_ORIGINAL_SOURCE_AND_INITIALIZER')
 scope=dict(fn.__globals__,OVERLAY=api.OVERLAY,hydration_name=api.hydration_name,source_scopes=api.source_scopes,SOURCE_SCOPES=api.SOURCE_SCOPES)
 bound=FunctionType(fn.__code__,scope,fn.__name__,fn.__defaults__);bound.__kwdefaults__=fn.__kwdefaults__
 need(bound.__code__ is fn.__code__,'SOURCE_EXIT_OBSERVER_IDENTICAL_COMPLETE_ORIGINAL_INITIALIZER_CODE')
 return bound

def origin(parent,current,record,scopes):
 return dict(schema='research.source-exit-successor-original-observer/1',financial_parent_sha256=parent['sha256'],
  neutral_sha256=current['sha256'],historical_metadata=record,active_and_retained_scopes=scopes,
  original_methods_unchanged=True,historical_financial_sessions_reexecuted=0,held_settlement_authorized=False)

def observer(root,out,current,parent,spec,api):
 from full_system_core import hosted
 hosted();root,out=Path(root),Path(out);record=historical(parent,spec,lambda n:(root/n).read_bytes())
 need(current['base']==parent['base'] and current['repairs'][:-1]==parent['repairs'] and current['run']['state']==parent['run']['state'],
  'SOURCE_EXIT_OBSERVER_ACTUAL_NEUTRAL_WITHOUT_FINANCIAL_STATE_CHANGE')
 folder=out/profiles.paths(spec)['OBSERVATION']
 for n in (api.OVERLAY,api.hydration_name(parent),api.SOURCE_SCOPES):exact(folder/n,(out/n).read_bytes())
 event=original.ActualEvents.__new__(original.ActualEvents);initializer(api)(event,folder,spec['arm'],cp=parent);merge_history(event,record,parent,spec=spec)
 need(all(getattr(event,n).__func__ is getattr(original.ActualEvents,n) for n in ('advance','terminal','source_values')),
  'SOURCE_EXIT_OBSERVER_ALL_ORIGINAL_ADAPTER_KERNEL_CALLER_FRAME_METHODS')
 exact(folder/ORIGIN,(json.dumps(origin(parent,current,record,event.scopes),sort_keys=True,indent=2,allow_nan=False)+'\n').encode())
 return event

def excluded_refusal(record,status,current):
 need(record['passed'] is record['financial_source_changed'] is False and isinstance(record['error'],str) and bool(record['error'])
  and record['session']>current['source_cursor'] and status['status']=='REFUSED' and status['failed_session']==record['session']
  and current['source_cursor']<=status['session']<status['failed_session']
  and type(status['completed_sessions']) is int and status['completed_sessions']>=current['completed'],
  'SOURCE_EXIT_OBSERVER_ONLY_GENUINE_DIAGNOSTIC_REFUSAL_AFTER_SAVED_PREFIX')
 return dict(session=record['session'],record_sha256=digest(record),status_sha256=digest(status),financial_sessions_admitted=0,excluded_from_saved_prefix=True)

def accounting_snapshot(snapshot,events):
 # Match the mature independent reader: a compact accounting snapshot selects
 # its exact historical prefix from the authenticated checkpoint ledger.
 ledger=snapshot['ledger'];count=ledger.get('event_count')
 need(set(ledger)=={'event_count','receivables'} and type(count)is int
  and 0<=count<=len(events),'SOURCE_EXIT_OBSERVER_EXACT_COMPACT_LEDGER_PREFIX')
 result=deepcopy(snapshot);result['ledger'].pop('event_count')
 result['ledger']['events']=deepcopy(events[:count])
 return result


def source_record(record,term,scope,before,opened,events,*,source_was_selected):
 # The complete original reviewer checks the actual no-op, entire call set,
 # historical absence, original source delegation and unchanged source phase.
 result=previous.prior.source_record(record,term,scope,accounting_snapshot(before,events),
  accounting_snapshot(opened,events),events,source_was_selected=source_was_selected)
 return dict(result,ticker=term['ticker'])

def review(parent,current,evidence,out,*,spec,old,neutral,api):
 from full_system_core import hosted
 hosted()
 from system_campaign_uncertainty_review import committed_rows
 from system_campaign_retained_forward_cash import verify_records
 evidence,out,old=Path(evidence),Path(out),Path(old);folder=evidence/profiles.paths(spec)['OBSERVATION']
 record=historical(parent,spec,lambda n:(old/n).read_bytes())
 material=json.loads((evidence/api.hydration_name(parent)).read_bytes());overlay=(evidence/api.OVERLAY).read_bytes()
 scopes=api.source_scopes(parent,material,sha(overlay),sha((evidence/api.hydration_name(parent)).read_bytes()))
 allscopes=scopes+record['scopes']
 need(json.loads((folder/ORIGIN).read_bytes())==origin(parent,neutral,record,allscopes)
  and all((folder/n).read_bytes()==(evidence/n).read_bytes() for n in (api.OVERLAY,api.hydration_name(parent),api.SOURCE_SCOPES)),
  'SOURCE_EXIT_OBSERVER_COMPLETE_ACTIVE_ORIGIN_AND_UNCHANGED_SOURCE_PAYLOADS')
 logs={p.stem.removeprefix('actual-future-event-'):json.loads(p.read_bytes()) for p in folder.glob('actual-future-event-20*.json')}
 need(all(parent['source_cursor']<day for day in logs),'SOURCE_EXIT_OBSERVER_NO_REEXECUTED_HISTORICAL_EVENT_RECORDS')
 observed={d:r for d,r in logs.items() if d<=current['source_cursor']}
 active=[t for t in material['terms'] if parent['source_cursor']<t['added']['session']<=current['source_cursor']]
 need(set(observed)=={t['added']['session'] for t in active},'SOURCE_EXIT_OBSERVER_ENTIRE_COMMITTED_EVENT_AXIS')
 rows=committed_rows(evidence/'book',current,'daily');events=current['run']['state']['ledger']['events']
 cert=[json.loads(v) for v in (evidence/'uncertainty-certificate.jsonl').read_bytes().splitlines() if json.loads(v)['session']<=current['source_cursor']]
 source=[];cash=[];source_ids={s['security_id'] for s in scopes}
 cash_terms=[t for t in active if t['security_id'] not in source_ids]
 need(all(t['added']['kind']=='CASH_MERGER' for t in cash_terms),'SOURCE_EXIT_OBSERVER_ALL_ADDITIONAL_COMMITTED_TERMS_HAVE_QUALIFIED_REVIEW')
 # Refuse an overlapping source/cash day unless a separately reviewed complete
 # multi-call reviewer is supplied; never narrow a full record to make it pass.
 source_days={s['session'] for s in scopes if s['session']<=current['source_cursor']}
 need(not source_days&{t['added']['session'] for t in cash_terms},'SOURCE_EXIT_OBSERVER_COMPLETE_SOURCE_AND_CASH_RECORDS_REVIEWED_SEPARATELY')
 if cash_terms:cash=verify_records(rows,events,{d:r for d,r in observed.items() if d not in source_days},cash_terms,current['source_cursor'])
 for scope in scopes:
  day=scope['session']
  if day>current['source_cursor']:continue
  term,=[t for t in active if t['security_id']==scope['security_id'] and t['added']['session']==day]
  i,=[i for i,r in enumerate(rows) if r['session']==day];need(i>0,'SOURCE_EXIT_OBSERVER_ACTUAL_ADJACENT_FINANCIAL_ACCOUNTING')
  proof,=[r for r in cert if r['session']==day];selected=scope['security_id'] in [r['security_id'] for r in proof['material']['rows']]
  source.append(source_record(observed[day],term,scope,rows[i-1]['evidence']['research_entry_audit']['closing_accounting'],
   rows[i]['evidence']['research_entry_audit']['opening_accounting'],events,source_was_selected=selected))
 refused=[];path=folder/'actual-future-event-refusal.json'
 if path.exists():refused.append(excluded_refusal(json.loads(path.read_bytes()),json.loads((evidence/'book/status.json').read_bytes()),current))
 result=dict(passed=True,source_events=source,cash_events=cash,all_committed_dates_and_calls_accounted=True,
  historical_TRQ_MYOV_BBIG_unchanged=True,original_observer_methods_unchanged=True,historical_financial_sessions_reexecuted=0,
  excluded_future_record_days=sorted(set(logs)-set(observed)),excluded_future_refusals=refused)
 exact(out/'source-exit-successor-observation-review.json',(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())
 return result
