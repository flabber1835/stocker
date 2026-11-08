"""Authentic batch357 observations and full legal range for the second P03 event."""
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import json
from system_campaign_facts import sha,digest
from full_system_benchmark import need
from system_campaign_bounded_sensor_input import Event,SCHEMA,parse
import system_campaign_bounded_sensor_hydration as original_hydration
from system_campaign_bounded_sensor_binding import INHERITED

HERE=Path(__file__).parent
CATALOG='P03-STML-source357-input-catalog.json'
ROOT='3ee60adb5326914846a052e26310d62045dd39b838a923378c9a84b6f230e7d4'
SID='235472954303009097'
DAY='2020-06-10'
FILES=frozenset(('system_campaign_p03_STML_source.py','system_campaign_second_bounded_codec.py',
 'system_campaign_second_bounded_factory.py','system_campaign_bounded_sensor_input.py',
 'system_campaign_bounded_sensor_binding.py','system_campaign_bounded_sensor_hydration.py',
 'system_campaign_bounded_sensor_event_review.py','system_campaign_bounded_sensor_suffix_v2.py',
 'system_campaign_full_history_successor.py'))|INHERITED.keys()

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def verify_semantics(value,root=HERE):
 pins=value['input_semantics_sources'];root=Path(root)
 need(set(pins)==FILES and all(pins[n]==pin for n,pin in INHERITED.items()),'STML_EXACT_COMPLETE_INHERITED_INTERPRETATION_SET')
 need(all(sha((root/n).read_bytes())==pin for n,pin in pins.items()),'STML_ALL_ACTUAL_INTERPRETATION_SOURCE_BYTES')
 return True

def validate(value,*,root_lookup):
 need(value['schema']=='research.P03-second-bounded-source-batch-catalog/1'
  and value['financial_authority'] is value['input_adopted'] is value['financial_profile_ready'] is False,
  'STML_CATALOG_SOURCE_ONLY_NOT_FINANCIAL_AUTHORITY')
 spec=root_lookup('P03',ROOT)
 need(value['parent_root_admission_sha256']==ROOT and value['parent_outer_sha256']==spec['outer_sha256']
  and value['parent_inner_sha256']==spec['inner_sha256'] and value['parent_input_sha256']==spec['input_sha256']
  and value['parent_state_sha256']==spec['state_sha256'] and value['parent_descriptors']==spec['repairs']
  and (value['parent_completed'],value['parent_cursor'],len(spec['repairs']))==(606,'2020-05-29',19),
  'STML_ENTIRE_ACTUAL606_FULL19_ADMITTED_PREDECESSOR')
 event=Event.model_validate(value['event']).model_dump()
 need(event['ticker']=='STML' and event['security_id']==SID and event['native_session']==event['effective_session']==DAY
  and event['prior_session']=='2020-06-09' and event['upfront_cash_per_share']=='11.50'
  and event['right_lower_per_share']=='0' and event['right_upper_per_share']=='1.00',
  'STML_EXACT_COMPLETE_LEGAL_RANGE_NO_POINT_SELECTION')
 source=value['source_payload'];capture=value['authenticated_capture']
 need(sha(encoded(source))==value['source_payload_sha256'] and sha(encoded(capture))==value['authenticated_capture_sha256']
  and source['schema']=='research.source-evidence-batch/1'
  and source['financial_authority'] is source['input_adopted'] is source['production_contacted'] is False
  and source['financial_sessions_advanced']==0 and source['context_is_not_event_date_ownership'] is True
  and source['archive_sha256']==spec['base']['archive_sha256'] and source['bundle_sha256']==spec['base']['bundle_sha256']
  and capture['source_rows_verified'] is capture['worker_fences_verified'] is True
  and capture['financial_authority'] is capture['input_adopted'] is False and capture['financial_sessions_advanced']==0
  and (capture['artifact'],capture['run'],capture['head'],capture['zip_bytes'],capture['members'],capture['logical_bytes'])
   ==(13580637335,'42388826916','5be1be10d66c703af04adb8efce2ca8e43fbf599',48413,4,114117)
  and capture['zip_sha256']=='342b8110eac0159379d076e2c001585284f0d563adff5ec9250c42bb33740594',
  'STML_COMPLETE_ORIGINAL_BATCH357_PAYLOAD_AND_AUTHENTICATED_CAPTURE')
 manifest=value['authenticated_manifest']
 need(manifest['run_id']=='42388826916' and manifest['head']==capture['head']
  and manifest['request_sha256']==source['request_sha256'] and manifest['stage']=='campaign-factual-suffix'
  and set(manifest['members'])=={'request.json','source-evidence.json','worker-inspect.json','worker.log'}
  and sum(p['bytes'] for p in manifest['members'].values())==114117
  and manifest['members']['source-evidence.json']==dict(bytes=len(encoded(source)),sha256=sha(encoded(source))),
  'STML_ORIGINAL_COMPLETE_AUTHENTICATED_MANIFEST_PAYLOAD_COMMITMENT')
 need(source['admitted_context']['P03']==dict(root_admission_sha256=ROOT,outer_sha256=spec['outer_sha256'],
  completed=606,through='2020-05-29',input_sha256=spec['input_sha256'])
  and value['event_date_ownership_verified'] is False,'STML_SOURCE_CONTEXT_NEVER_FUTURE_OWNERSHIP')
 observations=[v for v in source['observations'] if v['query']['arm']=='P03']
 groups=[v for v in source['native_groups'] if v['query']['arm']=='P03']
 need(len(observations)==2 and len(groups)==1,'STML_COMPLETE_OWN_TWO_QUOTES_AND_NATIVE_GROUP')
 rows=[]
 for q in observations:
  need(q['status']=='FOUND' and len(q['rows'])==1 and q['event_date_ownership']=='UNKNOWN_NOT_CAPTURED'
   and q['financial_authority'] is False and q['query']['security_id']==SID and q['query']['ticker']=='STML',
   'STML_ACTUAL_DISTINCT_SOURCE_QUOTES_WITH_UNKNOWN_FUTURE_ROLES')
  item,=q['rows'];row=item['source_row']
  need(item['source_row_sha256']==digest(row) and row['session']==q['query']['session'] and row['security_id']==SID
   and row['ticker']=='STML' and row['issuer_id']=='SEC_CIK:1264587' and row['listing_first_session']=='2013-01-29'
   and row['security_type_eligible']==row['tradeable']=='1','STML_ENTIRE_ORIGINAL_SOURCE_ROWS_AND_METADATA')
  rows.append(row)
 need({r['session'] for r in rows}=={'2020-06-09',DAY},'STML_EXACT_TWO_FROZEN_SOURCE_DATES')
 group,=groups;native,=group['original_typed_terminals']
 need(group['status']=='FOUND' and group['query']['security_id']==SID and group['query']['session']==DAY
  and group['original_typed_distributions']==[] and len(group['raw_rows'])==2
  and {r['row']['action'] for r in group['raw_rows']}=={'acquisitionby','delisted'}
  and all(digest(r['row'])==r['sha256'] and r['row']['security_id']==SID and r['row']['effective_session']==DAY for r in group['raw_rows'])
  and native==value['native'] and digest(native)==event['native_term_sha256']
  and native['security_id']==SID and native['session']==DAY and native['kind']=='CASH_MERGER'
  and native['cash_per_share'] is None and native['reference']=='actions/acquisitionby deal_value_musd=621.2',
  'STML_COMPLETE_NATIVE_PREIMAGES_AND_UNCHANGED_INCOMPLETE_TERM')
 market=value['market_source'];expected={r['session']:r for r in rows}
 need(market==dict(session=DAY,security_id=SID,source_quote_present=True,split_ratio=expected[DAY]['split_ratio'],
  source_observation_sha256=digest(expected[DAY]),event_contract_sha256=digest(event),
  raw_prior_row=expected['2020-06-09'],raw_event_row=expected[DAY])
  and sha(encoded(market))==value['market_source_sha256'],'STML_FULL_ORIGINAL_EVENT_MARKET_SOURCE_NO_QUOTE_SUBSTITUTION')
 primary=value['primary_facts']
 need(sha(encoded(primary))==value['primary_facts_sha256'] and primary['security_id']==SID and primary['ticker']=='STML'
  and primary['mandatory_cash_per_common_share']=='11.50' and primary['maximum_contingent_cash_per_CVR']=='1.00'
  and primary['CVRs_per_share']=='1' and primary['CVR_transferability']=='NON_TRANSFERABLE'
  and primary['preopen_completion_confirmed'] is True and primary['legal_completion_date']==DAY
  and primary['primary_source']=='https://www.sec.gov/Archives/edgar/data/1264587/000110465920071766/tm2021445d5_8k.htm'
  and primary['timing_source']=='https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2020-101'
  and primary['future_CVR_outcome_used'] is primary['financial_authority'] is False,
  'STML_EXISTING_PRIMARY_LEGAL_TERMS_SEPARATE_FROM_VENDOR_QUOTES')
 verify_semantics(value);return deepcopy(value)

def catalog():
 from system_campaign_financial_partial import root_spec
 return validate(json.loads((HERE/CATALOG).read_bytes()),root_lookup=root_spec)

def parent_contract(parent,spec):
 from system_campaign_full_history_successor import current_commitments
 from system_campaign_financial_partial import validate_root_spec
 import system_campaign_financial_future as future
 validate_root_spec(spec);value=catalog();current_commitments(parent,spec,lambda base,repairs:digest(dict(base=base,repairs=repairs)))
 need(spec['root_admission_sha256']==ROOT and parent['sha256']==value['parent_outer_sha256']
  and parent['run']['state_sha256']==value['parent_state_sha256'] and parent['repairs']==value['parent_descriptors']
  and parent['journals']==spec['journals'] and (parent['completed'],parent['source_cursor'])==(606,'2020-05-29'),
  'STML_GENUINE_FULL19_PARENT_AND_ALL_JOURNAL_COMMITMENTS')
 state=parent['run']['state'];future.require_source_scope(state['wealth_core'],state['pending'],state['ledger'],dict(security_id=SID))
 return True

def evidence(value):
 items=[('catalog',sha(encoded(value)),'Complete batch357-bound second contingent-event catalog.'),
  ('batch357-payload',value['source_payload_sha256'],'Complete original authenticated source batch, without schema relabelling.'),
  ('batch357-capture',value['authenticated_capture_sha256'],'Exact original source capture with zero financial authority.'),
  ('primary-facts',value['primary_facts_sha256'],'Mandatory upfront cash and full nominal contingent-right range.'),
  ('event-market-source',value['market_source_sha256'],'Both complete frozen raw observations and unchanged original metadata.'),
  ('event-contract',digest(value['event']),'Exact original typed event and all reachable canonical decisions required.'),
  ('interpretation-sources',digest(value['input_semantics_sources']),'All original and second-event interpretation source commitments.')]
 return [dict(reference='research.bounded-contingent-successor/'+n,sha256=h,description=d) for n,h,d in items]

def document(parent,*,value=None):
 from system_campaign_financial_partial import root_spec
 value=catalog() if value is None else validate(value,root_lookup=root_spec)
 parent_contract(parent,root_spec('P03',ROOT))
 return dict(schema=SCHEMA,predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'],
  event=deepcopy(value['event']),source_evidence=evidence(value))

def parse_document(path,parent,*,value=None):
 value=catalog() if value is None else value;expected=document(parent,value=value)
 need(Path(path).read_bytes()==encoded(expected),'STML_EXACT_COMPLETE_TYPED_DOCUMENT_BYTES')
 return parse(path,resume_session=parent['source_cursor'],predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'],
  expected_event=value['event'],expected_evidence=expected['source_evidence'])

def hydrate(value,out):
 fn=original_hydration.hydrate
 bound=FunctionType(fn.__code__,dict(fn.__globals__,validate=validate,verify_semantics=verify_semantics),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__
 return bound(value,out)
