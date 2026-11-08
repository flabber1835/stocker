"""Complete Chinook source witnesses for the genuine admitted full26 P07 book."""
import json
from copy import deepcopy
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_input import Event,SCHEMA,parse
from system_campaign_bounded_sensor_binding import INHERITED
import system_campaign_chinook_facts as original

HERE=Path(__file__).parent
ROOT='8571f67e874bc4cc4677b8e8876bc116186952f4f7307d651e0131fce0017be2'
SID='47247117758471252'
NATIVE='2023-08-10'
DAY='2023-08-11'
CATALOG='P07-KDNY-full26-source-catalog.json'
CONTRACT_SHA='3d0950938cf7a065b19d363f4d4d08488099dc0e4aa27dd0f06c2b7bb489d9e8'
BATCH_HEAD='6d5ee0413f4e8fc34eb333335aec49ed9c1e6528'
BATCH_RUN='42448767108'
REQUEST_SHA='b7706e95dfcd6e725a4bdeef85ab5b74f556ac8625ad6e06203910cbfaaf8ee9'
FILES=frozenset(('system_campaign_p07_KDNY_source.py','system_campaign_p07_KDNY_preparation.py',
 'system_campaign_abmd_bounded_preparation.py','system_campaign_chinook_facts.py','system_campaign_chinook_input.py',
 'system_campaign_bounded_sensor_input.py','system_campaign_bounded_sensor_binding.py',
 'system_campaign_bounded_sensor_event_review.py','system_campaign_second_bounded_codec.py','system_campaign_second_bounded_factory.py'))|INHERITED.keys()


def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()


def event(native):
 return Event.model_validate(dict(ticker='KDNY',security_id=SID,native_session=NATIVE,effective_session=DAY,
  prior_session=NATIVE,native_term_sha256=digest(native),currency='USD',upfront_cash_per_share='40.00',
  right_lower_per_share='0',right_upper_per_share='4.00',right_kind='NONTRANSFERABLE_CONTINGENT_VALUE_RIGHT',
  ownership_scope='UNOWNED_UNORDERED_SENSOR_ONLY',treatment='EVERY_REACHABLE_CANONICAL_DECISION_MUST_MATCH',
  price_or_probability_selected=False,cash_settlement_authorized=False,historical_causality='UNVERIFIED')).model_dump()


def verify_semantics(value,root=HERE):
 pins=value['input_semantics_sources'];contract=value['primary_contract'];root=Path(root)
 need(set(pins)==FILES|contract['inherited_sources'].keys()
  and all(pins[n]==h for n,h in {**INHERITED,**contract['inherited_sources']}.items())
  and all(sha((root/n).read_bytes())==h for n,h in pins.items()),'KDNY_ALL_ORIGINAL_AND_NEW_INTERPRETATION_SOURCE_BYTES')
 return True


def source_rows(value):
 source=value['source_payload'];rows={}
 need(len(source['observations'])==3 and len(source['native_groups'])==1,'KDNY_COMPLETE_THREE_SOURCE_DATES_ONE_NATIVE_GROUP')
 for observation in source['observations']:
  q=observation['query'];items=observation['rows']
  need(q['arm']=='P07' and q['ticker']=='KDNY' and q['security_id']==SID
   and observation['financial_authority'] is False and observation['event_date_ownership']=='UNKNOWN_NOT_CAPTURED',
   'KDNY_SOURCE_QUOTES_NEVER_FUTURE_OWNERSHIP')
  need(q['session'] in ('2023-08-09',NATIVE,DAY) and q['session'] not in rows,'KDNY_DISTINCT_COMPLETE_SOURCE_DATES')
  if q['session']==DAY:
   need(observation['status']=='NOT_FOUND' and not items,'KDNY_ACTUAL_COMPLETION_QUOTE_ABSENT');rows[DAY]=None
  else:
   need(observation['status']=='FOUND' and len(items)==1,'KDNY_ACTUAL_TWO_COMPLETE_SOURCE_ROWS')
   item,=items;row=item['source_row']
   need(digest(row)==item['source_row_sha256'] and row['session']==q['session'] and row['security_id']==SID
    and row['ticker']=='KDNY' and row['issuer_id']=='SEC_CIK:1435049' and row['listing_first_session']=='2015-04-15'
    and row['security_type_eligible']==row['tradeable']=='1','KDNY_ORIGINAL_FULL_SOURCE_IDENTITY_AND_METADATA')
   rows[q['session']]=row
 need(set(rows)=={'2023-08-09',NATIVE,DAY},'KDNY_ALL_ACTUAL_REQUESTED_DATES')
 return rows


def market(value,rows):
 return dict(session=DAY,security_id=SID,source_quote_present=False,split_ratio='1',
  split_rule='CANONICAL_NO_EVENT_BAR_UNIT_SPLIT',event_contract_sha256=digest(value['event']),
  raw_identity_row=deepcopy(rows['2023-08-09']),raw_prior_row=deepcopy(rows[NATIVE]),raw_event_row=None,
  source_metadata_unchanged=True,right_market_price_observed=False)


def validate(value,*,root_lookup):
 need(value['schema']=='research.P07-KDNY-full26-bounded-source-catalog/1'
  and value['financial_authority'] is value['input_adopted'] is value['financial_profile_ready'] is value['event_date_ownership_verified'] is False,
  'KDNY_SOURCE_ONLY_NO_FUTURE_OWNERSHIP_OR_FINANCIAL_AUTHORITY')
 spec=root_lookup('P07',ROOT)
 need(value['parent_root_admission_sha256']==ROOT and value['parent_outer_sha256']==spec['outer_sha256']
  and value['parent_inner_sha256']==spec['inner_sha256'] and value['parent_input_sha256']==spec['input_sha256']
  and value['parent_state_sha256']==spec['state_sha256'] and value['parent_descriptors']==spec['repairs']
  and (value['parent_completed'],value['parent_cursor'],len(spec['repairs']))==(1403,'2023-07-31',26),
  'KDNY_GENUINE_CURRENT1403_FULL26_ADMITTED_PREDECESSOR')
 contract=value['primary_contract'];source=value['source_payload'];capture=value['authenticated_capture'];manifest=value['authenticated_manifest']
 need(sha(encoded(contract))==value['primary_contract_sha256']==CONTRACT_SHA
  and contract['security_id']==SID and contract['native_session']==NATIVE and contract['session']==DAY
  and contract['cash_consideration_range']==[40.,44.] and contract['last_trading_session']==NATIVE
  and contract['preopen_completion_confirmed'] is contract['mandatory_remaining_common_share_entitlement'] is True
  and contract['tender_participation_assumed'] is contract['later_payment_information_used'] is contract['production_contacted'] is False
  and contract['event_source_quote_present'] is contract['contingent_right_market_price_observed'] is False,
  'KDNY_ORIGINAL_PRIMARY_COMMON_ENTITLEMENT_COMPLETE_RANGE_AND_CLOCK')
 need(value['native']==contract['native'] and digest(value['native'])==contract['native_term_sha256']
  and value['event']==event(value['native']),'KDNY_EXACT_EXISTING_NATIVE_AND_TYPED_LEGAL_RANGE')
 need(sha(encoded(source))==value['source_payload_sha256'] and source['schema']=='research.source-evidence-batch/1'
  and source['request_sha256']==REQUEST_SHA and source['archive_sha256']==spec['base']['archive_sha256']
  and source['bundle_sha256']==spec['base']['bundle_sha256'] and source['admitted_context']=={'P07':dict(completed=1403,
   input_sha256=spec['input_sha256'],outer_sha256=spec['outer_sha256'],root_admission_sha256=ROOT,through='2023-07-31')}
  and source['financial_authority'] is source['input_adopted'] is source['production_contacted'] is False
  and source['financial_sessions_advanced']==0 and source['context_is_not_event_date_ownership'] is True,
  'KDNY_WHOLE_ORIGINAL_AUTHENTICATED_SOURCE_PAYLOAD_AND_ADMITTED_CONTEXT')
 need((capture['run'],capture['head'],capture['artifact'],capture['zip_bytes'],capture['zip_sha256'],capture['members'],capture['logical_bytes'])
  ==(BATCH_RUN,BATCH_HEAD,13603829822,46093,'00e75ed2a716525dbcfc05f19ca902d608ead5e3a39414cb55ff355ad9929094',4,100216)
  and capture['source_rows_verified'] is capture['worker_fences_verified'] is True
  and capture['financial_authority'] is capture['input_adopted'] is False and capture['financial_sessions_advanced']==0
  and manifest['run_id']==BATCH_RUN and manifest['head']==BATCH_HEAD and manifest['request_sha256']==REQUEST_SHA
  and set(manifest['members'])=={'request.json','source-evidence.json','worker-inspect.json','worker.log'}
  and sum(x['bytes'] for x in manifest['members'].values())==100216
  and manifest['members']['source-evidence.json']==dict(bytes=len(encoded(source)),sha256=sha(encoded(source))),
  'KDNY_EXACT_COMPLETE_ORIGINAL_CAPTURE_MANIFEST_AND_POSITIVE_WORKER_FENCES')
 rows=source_rows(value)
 for w in contract['source_witnesses']:
  row=rows[w['session']];need(digest(row)==w['source_observation_sha256']
   and all(row[k]==v for k,v in w.items() if k!='source_observation_sha256'),'KDNY_BOTH_ORIGINAL_COMPLETE_CHINOOK_SOURCE_WITNESSES')
 group,=source['native_groups'];native,=group['original_typed_terminals']
 need(group['query']==dict(arm='P07',name='p07-kdny-native-group',security_id=SID,session=NATIVE,ticker='KDNY')
  and group['status']=='FOUND' and native==value['native'] and group['original_typed_distributions']==[]
  and len(group['raw_rows'])==2 and {x['row']['action'] for x in group['raw_rows']}=={'acquisitionby','delisted'}
  and all(digest(x['row'])==x['sha256'] and x['row']['security_id']==SID and x['row']['effective_session']==NATIVE for x in group['raw_rows']),
  'KDNY_COMPLETE_ORIGINAL_NATIVE_PREIMAGES_NO_NATIVE_SCHEMA_RELABEL')
 expected=market(value,rows)
 need(value['market_source']==expected and value['market_source_sha256']==sha(encoded(expected)),
  'KDNY_COMPLETE_RAW_PRIOR_SOURCE_AND_GENUINE_ABSENCE_NO_SUBSTITUTE_QUOTE')
 private=value['original_chinook_private_event'];providers=private['provider_rows']
 need(private==dict(schema='research.chinook-sensor-private-event/1',contract=contract,actual_native=value['native'],
  source_witnesses=[rows['2023-08-09'],rows[NATIVE]],provider_rows=providers,session=DAY,security_id=SID,
  source_quote_present=False,split_ratio='1',source_metadata_unchanged=True,right_market_price_observed=False)
  and len(providers)==3 and digest(providers)==contract['provider_rows_sha256']
  and [digest(x) for x in providers]==contract['provider_row_sha256']
  and value['original_chinook_private_event_sha256']==sha(encoded(private)),
  'KDNY_ALL_THREE_ORIGINAL_TARGET_AND_INVERSE_PROVIDER_ROWS_AND_PRIVATE_EVENT')
 verify_semantics(value);return deepcopy(value)


def catalog():
 from system_campaign_financial_partial import root_spec
 return validate(json.loads((HERE/CATALOG).read_bytes()),root_lookup=root_spec)


def parent_contract(parent,spec):
 from system_campaign_financial_partial import validate_root_spec
 from system_campaign_full_history_successor import current_commitments
 import system_campaign_financial_future as future
 validate_root_spec(spec);value=catalog();current_commitments(parent,spec,lambda b,r:digest(dict(base=b,repairs=r)))
 need(spec['root_admission_sha256']==ROOT and parent['sha256']==value['parent_outer_sha256']
  and parent['repairs']==value['parent_descriptors'] and parent['journals']==spec['journals']
  and (parent['completed'],parent['source_cursor'])==(1403,'2023-07-31'),'KDNY_EXACT_GENUINE_ADMITTED_FULL26_PARENT')
 state=parent['run']['state'];future.require_source_scope(state['wealth_core'],state['pending'],state['ledger'],dict(security_id=SID))
 return True


def evidence(value):
 return [dict(reference='research.P07-KDNY-bounded-successor/'+label,sha256=pin,description=description)
  for label,pin,description in (
   ('catalog',sha(encoded(value)),'Complete current full26 parent and authenticated native, quotes, absence and primary contract.'),
   ('batch',value['source_payload_sha256'],'Entire original source-only batch; no future ownership inference.'),
   ('contract',CONTRACT_SHA,'Original mandatory common entitlement and full40..44 nominal range.'),
   ('market',value['market_source_sha256'],'Actual full August10 quote and August11 absence; unchanged source metadata.'),
   ('original-private-event',value['original_chinook_private_event_sha256'],'Complete original witnesses and all target/inverse provider rows.'),
   ('interpretation',digest(value['input_semantics_sources']),'Exact complete inherited and generic bounded-event interpretation sources.'))]


def document(parent,*,value=None):
 value=catalog() if value is None else value
 from system_campaign_financial_partial import root_spec
 validate(value,root_lookup=root_spec);parent_contract(parent,root_spec('P07',ROOT))
 return dict(schema=SCHEMA,predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'],event=deepcopy(value['event']),source_evidence=evidence(value))


def parse_document(path,parent):
 value=catalog();need(Path(path).read_bytes()==encoded(document(parent,value=value)),'KDNY_EXACT_COMPLETE_TYPED_DOCUMENT')
 return parse(path,resume_session=parent['source_cursor'],predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'],
  expected_event=value['event'],expected_evidence=evidence(value))


def hydrate(value,out,*,old=Path('/old')):
 from full_system_core import hosted
 hosted()
 from system_campaign_financial_partial import root_spec
 from system_campaign_bounded_sensor_origin_v2 import exact
 validate(value,root_lookup=root_spec);out=Path(out);folder=out.parent/'original-chinook-witnesses';folder.mkdir(parents=True,exist_ok=True)
 def save(path,v):exact(path,encoded(v))
 fn=original.hydrate;need(fn.__closure__ is None,'KDNY_COMPLETE_ORIGINAL_FACTUAL_HYDRATOR_WITHOUT_HIDDEN_CLOSURE')
 bound=FunctionType(fn.__code__,dict(fn.__globals__,save=save),fn.__name__,fn.__defaults__)
 native=bound(Path(old),folder)
 raw=(folder/original.PRIVATE).read_bytes()
 need(raw==encoded(value['original_chinook_private_event']),'KDNY_ACTUAL_WHOLE_ORIGINAL_CHINOOK_HYDRATION_UNCHANGED')
 exact(out,encoded(value['market_source']));return native,deepcopy(value['market_source'])
