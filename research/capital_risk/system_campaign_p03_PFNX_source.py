"""Original PFNX sources, entire legal12..14 range and genuine671 parent."""
import base64,json
from copy import deepcopy
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_input import Event,SCHEMA,parse
from system_campaign_bounded_sensor_binding import INHERITED
HERE=Path(__file__).parent
ROOT='215aba53b3c8932ba7171b83f90d372b9add6a5c89322d8e5bdf75528c9b5cc8'
SID='326446597882092349'
PRIOR,NATIVE,DAY='2020-09-29','2020-09-30','2020-10-01'
BATCH='P03-PFNX-P07-RETA-native-source-catalog.json'
BATCH_SHA='067d6a8258967e24d1bf8d450fbc598a81320551df31d5e7ed4ffbba2a90c74c'
CATALOG='P03-PFNX-full21-source-catalog.json'
ANNUAL_SHA='b34e74c0983d1672e1e82cbd854727e2b752b235bfac217699e166238cac78cf'
PRIMARY='https://www.sec.gov/Archives/edgar/data/1478121/000119312520260581/d939421d8k.htm'
TERMS='https://www.sec.gov/Archives/edgar/data/1478121/000119312520215352/d948683dex991.htm'
FILES=frozenset(('system_campaign_p03_PFNX_source.py','system_campaign_p03_PFNX_hydration.py','system_campaign_p03_PFNX_preparation.py',
 'system_campaign_abmd_bounded_hydration.py','system_campaign_abmd_bounded_preparation.py','system_campaign_p07_KDNY_preparation.py',
 'system_campaign_second_bounded_codec.py','system_campaign_second_bounded_factory.py','system_campaign_bounded_sensor_input.py',
 'system_campaign_bounded_sensor_binding.py','system_campaign_bounded_sensor_event_review.py','system_campaign_bounded_sensor_suffix_v2.py',
 'system_campaign_full_history_successor.py'))|INHERITED.keys()

def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def batch():
 raw=(HERE/BATCH).read_bytes();need(sha(raw)==BATCH_SHA,'PFNX_WHOLE_ORIGINAL_AUTHENTICATED_BATCH')
 value=json.loads(raw);manifest=value['authenticated_manifest'];source=value['source_evidence'];capture=value['source_capture']
 need(value['financial_authority']is value['input_adopted']is source['financial_authority']is source['input_adopted']is source['production_contacted']is False
  and value['financial_sessions_advanced']==source['financial_sessions_advanced']==0 and source['context_is_not_event_date_ownership']is True
  and (capture['artifact'],capture['run'],capture['head'],capture['members'],capture['logical_bytes'])
   ==(13612957167,'42469385090','d324a9068ede96339c683c3c776589f894a86fd5',4,107093)
  and capture['source_rows_verified']is capture['worker_fences_verified']is True
  and set(manifest['members'])==set(value['authenticated_members'])=={'request.json','source-evidence.json','worker-inspect.json','worker.log'},
  'PFNX_EXACT_ORIGINAL_SOURCE_ONLY_CAPTURE_AND_ALL_FOUR_MEMBERS')
 for name,item in value['authenticated_members'].items():
  content=base64.b64decode(item['base64'],validate=True)
  need({k:item[k] for k in ('bytes','sha256')}==manifest['members'][name]==dict(bytes=len(content),sha256=sha(content)),
   'PFNX_COMPLETE_UNCHANGED_ORIGINAL_MEMBER:'+name)
  if name=='source-evidence.json':need(json.loads(content)==source,'PFNX_ORIGINAL_PAYLOAD_NOT_RELABELED')
 return value

def event(native):
 return Event.model_validate(dict(ticker='PFNX',security_id=SID,native_session=NATIVE,effective_session=DAY,prior_session=NATIVE,
  native_term_sha256=digest(native),currency='USD',upfront_cash_per_share='12.00',right_lower_per_share='0',right_upper_per_share='2.00',
  right_kind='NONTRANSFERABLE_CONTINGENT_VALUE_RIGHT',ownership_scope='UNOWNED_UNORDERED_SENSOR_ONLY',
  treatment='EVERY_REACHABLE_CANONICAL_DECISION_MUST_MATCH',price_or_probability_selected=False,cash_settlement_authorized=False,
  historical_causality='UNVERIFIED')).model_dump()

def source_rows(original):
 source=original['source_evidence'];observations=[x for x in source['observations'] if x['query']['arm']=='P03'];rows={}
 need(len(observations)==3,'PFNX_COMPLETE_THREE_ACTUAL_SOURCE_DATES')
 for observation in observations:
  query=observation['query'];day=query['session']
  need(query['security_id']==SID and day in (PRIOR,NATIVE,DAY) and day not in rows
   and observation['financial_authority']is False and observation['event_date_ownership']=='UNKNOWN_NOT_CAPTURED',
   'PFNX_SOURCE_CONTEXT_NEVER_FUTURE_OWNERSHIP')
  if day==DAY:
   need(observation['status']=='NOT_FOUND' and observation['rows']==[],'PFNX_GENUINE_OCTOBER1_QUOTE_ABSENCE');rows[day]=None
  else:
   need(observation['status']=='FOUND' and len(observation['rows'])==1,'PFNX_COMPLETE_PRIOR_AND_NATIVE_ROWS')
   item,=observation['rows'];row=item['source_row']
   need(digest(row)==item['source_row_sha256'] and row['session']==day and row['security_id']==SID and row['ticker']=='PFNX'
    and row['issuer_id']=='SEC_CIK:1478121' and row['listing_first_session']=='2014-07-24'
    and row['security_type_eligible']==row['tradeable']=='1','PFNX_FULL_ORIGINAL_IDENTITY_PRICE_AND_METADATA')
   rows[day]=row
 need(set(rows)=={PRIOR,NATIVE,DAY},'PFNX_ALL_ORIGINAL_SOURCE_DATES_PRESENT');return rows

def market(value,rows):
 return dict(session=DAY,security_id=SID,source_quote_present=False,split_ratio='1',split_rule='CANONICAL_NO_EVENT_BAR_UNIT_SPLIT',
  event_contract_sha256=digest(value['event']),raw_identity_row=deepcopy(rows[PRIOR]),raw_prior_row=deepcopy(rows[NATIVE]),raw_event_row=None,
  annual_member_sha256=ANNUAL_SHA,source_metadata_unchanged=True,right_market_price_observed=False)

def verify_semantics(value,root=HERE):
 pins=value['input_semantics_sources'];root=Path(root)
 need(set(pins)==FILES and all(pins[n]==h for n,h in INHERITED.items())
  and all(sha((root/n).read_bytes())==h for n,h in pins.items()),'PFNX_ALL_ORIGINAL_AND_THIRD_LAYER_INTERPRETATION_SOURCE_BYTES')
 return True

def validate(value,*,root_lookup):
 need(value['schema']=='research.P03-PFNX-full21-bounded-source-catalog/1'
  and value['financial_authority']is value['input_adopted']is value['financial_profile_ready']is value['event_date_ownership_verified']is False,
  'PFNX_SOURCE_COMPONENT_WITHOUT_FINANCIAL_OR_FUTURE_OWNERSHIP_AUTHORITY')
 target=root_lookup('P03',ROOT)
 need(value['parent_root_admission_sha256']==ROOT and value['parent_outer_sha256']==target['outer_sha256']
  and value['parent_inner_sha256']==target['inner_sha256'] and value['parent_input_sha256']==target['input_sha256']
  and value['parent_state_sha256']==target['state_sha256'] and value['parent_descriptors']==target['repairs']
  and (value['parent_completed'],value['parent_cursor'],len(target['repairs']))==(671,'2020-08-31',21),
  'PFNX_GENUINE_CURRENT671_FULL21_PARENT_NEVER_COLLECTION_CONTEXT')
 original=batch();source=original['source_evidence'];rows=source_rows(original)
 need(value['source_batch']==dict(file=BATCH,sha256=BATCH_SHA) and source['archive_sha256']==target['base']['archive_sha256']
  and source['bundle_sha256']==target['base']['bundle_sha256']
  and source['admitted_context']['P03']['completed']==628 and source['admitted_context']['P03']['through']=='2020-06-30',
  'PFNX_ORIGINAL628_CAPTURE_CONTEXT_PRESERVED_SEPARATELY_FROM_CURRENT671')
 groups=[x for x in source['native_groups'] if x['query']['arm']=='P03'];need(len(groups)==1,'PFNX_ONE_ACTUAL_NATIVE_GROUP')
 group,=groups;native,=group['original_typed_terminals']
 need(group['status']=='FOUND' and group['original_typed_distributions']==[] and len(group['raw_rows'])==2
  and {x['row']['action'] for x in group['raw_rows']}=={'acquisitionby','delisted'}
  and all(digest(x['row'])==x['sha256'] and x['row']['security_id']==SID and x['row']['effective_session']==NATIVE for x in group['raw_rows'])
  and value['native']==native and native['session']==NATIVE and native['security_id']==SID and native['kind']=='CASH_MERGER'
  and native['cash_per_share']is None and native['reference']=='actions/acquisitionby deal_value_musd=437.3',
  'PFNX_ENTIRE_ORIGINAL_INCOMPLETE_NATIVE_PREIMAGES_NOT_DEAL_VALUE_PER_SHARE')
 need(value['event']==event(native),'PFNX_FULL_LEGAL12_TO14_RANGE_AND_DISTINCT_NATIVE_COMPLETION_DATES')
 expected=market(value,rows)
 need(value['market_source']==expected and value['market_source_sha256']==sha(encoded(expected)),
  'PFNX_FULL_SOURCE_ROWS_GENUINE_ABSENCE_AND_NO_FABRICATED_BAR')
 primary=dict(ticker='PFNX',security_id=SID,currency='USD',mandatory_cash_per_common_share='12.00',rights_per_share='1',
  contingent_lower_per_share='0',contingent_upper_per_share='2.00',right_transferable=False,legal_completion_date=DAY,
  preopen_completion_confirmed=True,last_trading_date=NATIVE,milestone_deadline='2021-12-31',primary_source=PRIMARY,
  terms_source=TERMS,future_CVR_outcome_used=False,settlement_authorized=False,probability_selected=False,financial_authority=False)
 need(value['primary_facts']==primary and value['primary_facts_sha256']==sha(encoded(primary)),
  'PFNX_PRIMARY_COMMON_ENTITLEMENT_WHOLE_RANGE_AND_PREOPEN_CLOCK')
 audit=value['full_annual_source_DATA'];need(sha(encoded(audit))==value['full_annual_source_DATA_sha256'] and audit['passed']is True
  and audit['canonical_runtime_executed']is audit['financial_book_staged']is audit['financial_authority']is False
  and audit['financial_sessions_advanced']==0 and audit['root_admission_sha256']==ROOT
  and audit['parent_outer_sha256']==target['outer_sha256'] and audit['parent_state_sha256']==target['state_sha256']
  and audit['archive_sha256']==target['base']['archive_sha256'] and audit['annual_member']=='observations-2020.csv.gz'
  and audit['annual_member_sha256']==ANNUAL_SHA and (audit['scanned'],audit['security_rows'],audit['last_source_session'])==(1541141,189,NATIVE)
  and sorted(audit['raw_source_rows'],key=lambda x:x['session'])==[rows[PRIOR],rows[NATIVE]]
  and audit['source_catalog_sha256']==BATCH_SHA and audit['complete_original_source_members_verified']==4
  and value['parent_role']==audit['parent_role'] and value['parent_role']['held']is value['parent_role']['ordered']is False,
  'PFNX_ENTIRE_AUTHENTIC2020_MEMBER_AND_ACTUAL_PARENT_ROLE_SEPARATE_FROM_FUTURE')
 verify_semantics(value);return deepcopy(value)

def catalog():
 from system_campaign_financial_partial import root_spec
 return validate(json.loads((HERE/CATALOG).read_bytes()),root_lookup=root_spec)

def parent_contract(parent,spec):
 from system_campaign_financial_partial import validate_root_spec
 from system_campaign_full_history_successor import current_commitments
 import system_campaign_financial_future as future
 validate_root_spec(spec);value=catalog();current_commitments(parent,spec,lambda b,r:digest(dict(base=b,repairs=r)))
 need(spec['root_admission_sha256']==ROOT and parent['sha256']==value['parent_outer_sha256'] and parent['repairs']==value['parent_descriptors']
  and parent['journals']==spec['journals'] and (parent['completed'],parent['source_cursor'])==(671,'2020-08-31'),
  'PFNX_GENUINE_ENTIRE671_PARENT_AND_ALL_JOURNAL_COMMITMENTS')
 state=parent['run']['state'];future.require_source_scope(state['wealth_core'],state['pending'],state['ledger'],dict(security_id=SID))
 role=dict(held=any(v['security_id']==SID for v in state['wealth_core']['episodes'].values()),ordered=any(v['security_id']==SID for v in state['pending']),
  selected=SID in state['median5']['selected'],signal_anchor=state['feed']['series'].get(SID,{}).get('signal_basis_anchor'))
 need(role==value['parent_role'],'PFNX_ENTIRE_ACTUAL_PARENT_ROLE_NO_FUTURE_ABSENCE_INFERENCE');return True

def evidence(value):
 return [dict(reference='research.P03-PFNX-third-bounded/'+label,sha256=pin,description=description) for label,pin,description in (
  ('catalog',sha(encoded(value)),'Genuine full21 parent and complete original legal/source commitments.'),
  ('source-batch',BATCH_SHA,'All four original authenticated source-only members and628 collection context unchanged.'),
  ('primary-facts',value['primary_facts_sha256'],'Mandatory12 cash and full0..2 nontransferable contingent right, October1 preopen.'),
  ('market-source',value['market_source_sha256'],'Entire September29/30 rows, unchanged metadata and genuine October1 absence.'),
  ('annual-scan',value['full_annual_source_DATA_sha256'],'Entire frozen2020 compressed member and all1541141 rows independently scanned.'),
  ('interpretation',digest(value['input_semantics_sources']),'Original source/packet and complete successive bounded implementation sources.'))]

def document(parent,*,value=None):
 from system_campaign_financial_partial import root_spec
 value=catalog() if value is None else validate(value,root_lookup=root_spec);parent_contract(parent,root_spec('P03',ROOT))
 return dict(schema=SCHEMA,predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'],event=deepcopy(value['event']),source_evidence=evidence(value))

def parse_document(path,parent):
 value=catalog();need(Path(path).read_bytes()==encoded(document(parent,value=value)),'PFNX_EXACT_COMPLETE_TYPED_DOCUMENT_BYTES')
 return parse(path,resume_session=parent['source_cursor'],predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'],expected_event=value['event'],expected_evidence=evidence(value))

def source_names():return tuple(sorted(FILES|{BATCH,CATALOG}))
