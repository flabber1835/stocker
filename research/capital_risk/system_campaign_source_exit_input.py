"""Source-batch-bound existing research exit policy; no financial book/runtime."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import system_campaign_financial_future as original
from system_campaign_facts import sha,digest
from full_system_benchmark import need
HERE=Path(__file__).parent
CATALOG='P06-TBIO-source-exit-input-catalog.json'

def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def validate(value,*,root_lookup):
 need(value['schema']=='research.source-batch-bound-unheld-source-exit-catalog/1'
  and value['financial_authority'] is value['input_adopted'] is value['financial_profile_ready'] is False,
  'SOURCE_EXIT_CATALOG_DATA_ONLY_NOT_FINANCIAL_PROFILE')
 term=value['term'];spec=root_lookup(term['arm'],term['parent_root_admission_sha256'])
 need(term['parent_cursor']==spec['selected_session'] and term['parent_outer_sha256']==spec['outer_sha256']
  and value['parent_input_sha256']==spec['input_sha256'] and value['parent_descriptors']==spec['repairs']
  and value['parent_completed']==spec['measured_closes'] and term['parent_positions']==[]
  and value['parent_actual_state_sha256']==spec['state_sha256'] and value['parent_actual_never_held_scope_verified'] is True,
  'SOURCE_EXIT_CATALOG_EXACT_ENTIRE_ADMITTED_PARENT_CONTEXT')
 source=value['source_payload'];capture=value['authenticated_capture']
 need(sha(encoded(source))==value['source_payload_sha256'] and sha(encoded(capture))==value['authenticated_capture_sha256']
  and source['schema']=='research.source-evidence-batch/1' and source['financial_authority'] is source['input_adopted'] is False
  and source['financial_sessions_advanced']==0 and capture['source_rows_verified'] is capture['worker_fences_verified'] is True
  and capture['financial_authority'] is capture['input_adopted'] is False and capture['financial_sessions_advanced']==0,
  'SOURCE_EXIT_CATALOG_AUTHENTICATED_COMPLETE_SOURCE_ONLY_PREIMAGES')
 context=source['admitted_context'][term['arm']]
 need(context['root_admission_sha256']==spec['root_admission_sha256'] and context['outer_sha256']==spec['outer_sha256']
  and context['through']==spec['selected_session'] and context['completed']==spec['measured_closes']
  and context['input_sha256']==spec['input_sha256'] and source['context_is_not_event_date_ownership'] is True,
  'SOURCE_EXIT_CATALOG_SOURCE_CONTEXT_IS_NOT_EVENT_DATE_OWNERSHIP')
 prior=value['prior_row'];event=value['event_row'];sid=term['security_id'];day=term['native_session']
 for row in (prior,event):
  found=[r for q in source['observations'] for r in q['rows'] if r['source_row']==row]
  need(len(found)==1 and found[0]['source_row_sha256']==digest(row) and row['security_id']==sid
   and row['ticker']==term['ticker'] and row['issuer_id']==prior['issuer_id'],
   'SOURCE_EXIT_CATALOG_ENTIRE_UNCHANGED_DISTINCT_SOURCE_OBSERVATION')
 need(prior['session']==term['identity_witness']['session']<event['session']==day
  and digest(prior)==term['identity_witness']['source_observation_sha256']
  and all(prior[k]==term['identity_witness'][k] for k in ('session','security_id','ticker','issuer_id','listing_first_session','security_type_eligible'))
  and value['next_frozen_session_after_prior']==day and value['next_frozen_session_after_event']==value['first_queried_missing_session'],
  'SOURCE_EXIT_CATALOG_EXACT_PRIOR_EVENT_AND_FROZEN_AXIS')
 missing=[q for q in source['observations'] if q['query']['session']==value['first_queried_missing_session']]
 need(len(missing)==1 and missing[0]['status']=='NOT_FOUND' and missing[0]['rows']==[],
  'SOURCE_EXIT_CATALOG_MISSING_QUOTE_REMAINS_EXPLICIT')
 group,=source['native_groups'];native,=group['original_typed_terminals']
 need(group['query']['session']==day and group['query']['security_id']==sid and group['status']=='FOUND'
  and len(group['raw_rows'])==2 and {r['row']['action'] for r in group['raw_rows']}=={'delisted','regulatorydelisting'}
  and all(digest(r['row'])==r['sha256'] and r['row']['security_id']==sid and r['row']['effective_session']==day for r in group['raw_rows'])
  and native==term['native'] and digest(native)==term['native_term_sha256'] and native['cash_per_share'] is None,
  'SOURCE_EXIT_CATALOG_COMPLETE_NATIVE_GROUP_AND_INCOMPLETE_TERMINAL')
 original.research_source_exit_term(term);original.source_exit_quote(term,prior)
 need(term['research_assumption']['retained_raw_close']==str(float(prior['raw_close']))
  and value['event_quote_is_proxy'] is value['statutory_cash_claimed'] is value['otc_security_extinction_claimed'] is False
  and value['event_date_roles_verified'] is False,'SOURCE_EXIT_CATALOG_PRIOR_PROXY_ONLY_NO_NEW_ECONOMIC_OR_ROLE_AUTHORITY')
 return deepcopy(value)

def catalog():
 from system_campaign_financial_partial import root_spec
 return validate(json.loads((HERE/CATALOG).read_bytes()),root_lookup=root_spec)

def selected(arm,*,cursor):
 value=catalog();term=value['term']
 need(arm==term['arm'] and cursor==term['parent_cursor'],'SOURCE_EXIT_CATALOG_ONLY_EXACT_UNCONSUMED_ARM_CURSOR')
 codec=SimpleNamespace(catalog=value,catalog_sha=sha((HERE/CATALOG).read_bytes()),compiler_sha=sha(Path(__file__).read_bytes()),
  parent_outer_sha256=term['parent_outer_sha256'],parent_positions=[],validator_description='Existing research source exit at exact prior retained raw close; no settlement or held treatment. Full original no-op and source-delegation guards required.')
 return codec,CATALOG,[deepcopy(term)]
