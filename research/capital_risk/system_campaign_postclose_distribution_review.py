"""Independent DATA reconstruction from complete captured rows and actual parent."""
import csv,gzip,json
from copy import deepcopy
from system_campaign_facts import sha,digest
from full_system_benchmark import need

def review(value,witness,parent,axis_raw,*,normalizer_sha256,distribution_source_sha256):
 from system_campaign_financial_partial import root_spec
 spec=root_spec('P07',value['parent_root_admission_sha256'])
 need(parent['sha256']==spec['outer_sha256']==digest({k:v for k,v in parent.items() if k!='sha256'})
  and parent['run']['checkpoint_sha256']==digest({k:v for k,v in parent['run'].items() if k!='checkpoint_sha256'})
  and parent['run']['state_sha256']==spec['state_sha256']==digest(parent['run']['state'])
  and parent['run']['input_sha256']==spec['input_sha256']==digest(dict(base=parent['base'],repairs=parent['repairs']))
  and parent['base']==spec['base'] and parent['repairs']==spec['repairs'] and len(parent['repairs'])==25
  and (parent['completed'],parent['source_cursor'])==(1383,'2023-06-30'),'POSTCLOSE_DATA_REAL_ENTIRE_ADMITTED_PARENT')
 payload=value['source_payload'];parent_id=value['parent_security_id'];child_id=value['child_security_id']
 positions={sid:[dict(slot_id=e['slot_id'],ticker=e['ticker'],quantity=e['current_shares'],entry_date=e['entry_date'])
  for _,e in sorted(parent['run']['state']['wealth_core']['episodes'].items(),key=lambda x:int(x[0])) if e['security_id']==sid]
  for sid in (parent_id,child_id)}
 need(positions==value['parent_positions'] and positions[child_id]==[] and len(positions[parent_id])==1
  and positions[parent_id][0]['quantity']==62,'POSTCLOSE_DATA_POSITIONS_FROM_REAL_SAVED_PARENT_ONLY')
 entries=[v for v in payload['observations'] if v['query']['arm']=='P07']
 groups=[v for v in payload['native_groups'] if v['query']['arm']=='P07']
 need(len(entries)==3 and len(groups)==1,'POSTCLOSE_DATA_COMPLETE_INDEPENDENT_SOURCE_AXIS')
 group,=groups
 need(len(group['raw_rows'])==len(group['original_typed_distributions'])==2 and group['original_typed_terminals']==[]
  and {v['row']['action'] for v in group['raw_rows']}=={'spinoff','spinoffdividend'},'POSTCLOSE_DATA_ALL_NATIVE_PREIMAGES_NO_HASH_FILTER')
 native_by_id={n['source_row_id']:n for n in group['original_typed_distributions']}
 queries=[];native_items=[]
 for n in group['original_typed_distributions']:
  matching=[v for v in group['raw_rows'] if sha(json.dumps(v['row'],sort_keys=True).encode())==n['source_row_id']]
  need(len(matching)==1,'POSTCLOSE_DATA_ONE_RAW_PREIMAGE_PER_ORIGINAL_PARSER_ID')
  item,=matching;row=item['row']
  expected=dict(session=row['effective_session'],parent_ticker=row['ticker'],parent_security_id=row['security_id'],
   child_ticker=None,child_security_id=None,source_row_id=sha(json.dumps(row,sort_keys=True).encode()),value_evidence=row['vendor_value'],
   child_shares_per_parent=None,child_price=None,cash_in_lieu_price=None,policy='REQUIRE_REVIEWED_CHILD_OWNERSHIP')
  need(n==expected and digest(row)==item['sha256'] and row['effective_session']==row['known_by']=='2023-07-05'
   and row['security_id']==parent_id and row['ticker']=='BWA','POSTCLOSE_DATA_UNCHANGED_ORIGINAL_PARSER_AND_RAW_VALUES')
  queries.append(dict(schema='research.exact-native-distribution-query/1',session=n['session'],parent_security_id=parent_id,parent_ticker='BWA',
   source_row_id=n['source_row_id'],native_term_sha256=digest(n),raw_source_row_sha256=digest(row),maximum_records=1,financial_use_authorized=False))
  native_items.append(dict(raw_source_row=deepcopy(row),raw_source_row_sha256=digest(row),native_distribution=deepcopy(n),native_distribution_sha256=digest(n)))
 declared=[];rows=[]
 for entry in entries:
  need(entry['status']=='FOUND' and len(entry['rows'])==1 and entry['event_date_ownership']=='UNKNOWN_NOT_CAPTURED'
   and entry['financial_authority'] is False,'POSTCLOSE_DATA_SOURCE_FOUND_IS_NOT_EVENT_OWNERSHIP')
  item,=entry['rows'];row=item['source_row'];held=positions[row['security_id']]
  need(digest(row)==item['source_row_sha256'],'POSTCLOSE_DATA_COMPLETE_ORIGINAL_OBSERVATION_DIGEST')
  identity={k:row[k] for k in ('session','security_id','ticker','issuer_id','listing_first_session','security_type_eligible')}
  identity['source_observation_sha256']=digest(row)
  declared.append(dict(session=row['session'],security_id=row['security_id'],ticker=row['ticker'],
   source_observation_sha256=digest(row),parent_positions=deepcopy(held)))
  rows.append(dict(source_row=deepcopy(row),identity_witness=identity,parent_positions=deepcopy(held)))
 need({(v['source_row']['session'],v['source_row']['security_id']) for v in rows}=={
  ('2023-07-03',parent_id),('2023-07-05',parent_id),('2023-07-05',child_id)},'POSTCLOSE_DATA_EXACT_THREE_DISTINCT_FULL_SOURCE_ROWS')
 child,=[v['source_row'] for v in rows if v['source_row']['security_id']==child_id]
 event,=[v['source_row'] for v in rows if (v['source_row']['session'],v['source_row']['security_id'])==('2023-07-05',parent_id)]
 need(child['issuer_id']=='SEC_CIK:1968915' and child['ff12']=='UNKNOWN:'+child_id
  and child['raw_open']=='29.890000000000001' and child['raw_close']=='36.75'
  and event['raw_open']=='44.369999999999997' and event['dividend_per_share']=='6.0099999999999998',
  'POSTCLOSE_DATA_FROZEN_CHILD_IDENTITY_UNKNOWN_SECTOR_AND_PRICE_DOMAINS_RETAINED')
 scope=dict(schema='research.distribution-only-source-scope/1',parent_outer_sha256=spec['outer_sha256'],parent_cursor=spec['selected_session'],
  terms=[],additional_rows=declared,native_distribution_queries=queries,expected_native_distribution_count=2)
 expected=dict(schema='research.own-parent-frozen-source-witnesses/7',arm='P07',parent_outer_sha256=spec['outer_sha256'],parent_cursor=spec['selected_session'],
  archive_sha256=spec['base']['archive_sha256'],bundle_sha256=spec['base']['bundle_sha256'],scope=scope,scope_sha256=digest(scope),
  producer_sha256=normalizer_sha256,distribution_producer_sha256=distribution_source_sha256,parser_sha256=payload['original_parser_sha256'],
  terms=[],additional_rows=rows,native_distributions=native_items,financial_sessions_advanced=0,
  financial_authority=False,input_adopted=False,provider_metadata_upgraded=False,production_contacted=False)
 need(witness==expected,'POSTCLOSE_DATA_ENTIRE_INDEPENDENTLY_RECONSTRUCTED_SOURCE_WITNESS')
 days=[v['session'] for v in csv.DictReader(gzip.decompress(axis_raw).decode().splitlines())]
 need(sha(axis_raw)==value['frozen_axis']['gzip_sha256']=='cc5c05fc2392dcb41ac0de142329e49d590b937b53c4fadc49b50f857ed7c34a'
  and days==sorted(set(days)) and days[days.index('2023-06-30'):days.index('2023-06-30')+4]==value['frozen_axis']['sessions']
  ==['2023-06-30','2023-07-03','2023-07-05','2023-07-06'],'POSTCLOSE_DATA_ACTUAL_FROZEN_AXIS_NEXT_SESSION')
 return dict(schema='research.independent-postclose-distribution-source-DATA-review/1',passed=True,
  source_payload_sha256=sha((json.dumps(payload,sort_keys=True,indent=2)+'\n').encode()),normalized_payload_digest=digest(witness),
  native_records=2,full_source_rows=3,admitted_parent_sha256=parent['sha256'],admitted_parent_sessions=1383,admitted_parent_inputs=25,
  admitted_parent_shares=62,admitted_positions_verified=True,full_raw_and_typed_preimages_verified=True,
  original_price_and_metadata_fields_unchanged=True,frozen_next_session_verified=True,
  event_date_ownership_verified=False,actual_record_date_ownership_verified=False,historical_availability='UNVERIFIED',
  financial_authority=False,canonical_runtime_executed=False,financial_sessions_advanced=0)
