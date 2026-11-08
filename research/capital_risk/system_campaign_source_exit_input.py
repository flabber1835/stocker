"""Source-batch-bound existing research exit policy; no financial book/runtime."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast,json
import system_campaign_financial_future as original
from system_campaign_facts import sha,digest
from full_system_benchmark import need
HERE=Path(__file__).parent
CATALOG='P06-TBIO-source-exit-input-catalog.json'
V2='research.source-batch-bound-unheld-source-exit-catalog/2'
FUTURE_SHA='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'

def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def ancestor_context(source,spec,*,root_lookup):
 context=source['admitted_context'][spec['arm']];current=spec;seen=set()
 while current['root_admission_sha256']!=context['root_admission_sha256']:
  key=current['root_admission_sha256'];need(key not in seen,'SOURCE_EXIT_SOURCE_CONTEXT_NO_ANCESTRY_CYCLE');seen.add(key)
  ancestor=root_lookup(spec['arm'],current['root_admission']['parent_root_admission_sha256'])
  need(ancestor['arm']==spec['arm'] and ancestor['base']==spec['base']
   and current['repairs'][:len(ancestor['repairs'])]==ancestor['repairs']
   and ancestor['measured_closes']<current['measured_closes'] and ancestor['selected_session']<current['selected_session'],
   'SOURCE_EXIT_SOURCE_CONTEXT_GENUINE_SAME_ARM_ADMISSION_ANCESTRY')
  current=ancestor
 need(context==dict(root_admission_sha256=current['root_admission_sha256'],outer_sha256=current['outer_sha256'],
  through=current['selected_session'],completed=current['measured_closes'],input_sha256=current['input_sha256'])
  and source['archive_sha256']==spec['base']['archive_sha256'] and source['bundle_sha256']==spec['base']['bundle_sha256']
  and source['context_is_not_event_date_ownership'] is True,'SOURCE_EXIT_SOURCE_CONTEXT_EXACT_ORIGINAL_ANCESTOR_AND_FROZEN_INPUTS')
 return current


def boundary_validator():
 raw=Path(original.__file__).read_bytes();need(sha(raw)==FUTURE_SHA,'SOURCE_EXIT_BOUNDARY_WHOLE_ORIGINAL_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='research_source_exit_term']
 site,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n).startswith("term['parent_cursor'] < w['session'] == model.retained_quote_session")]
 need(isinstance(site.ops[0],ast.Lt),'SOURCE_EXIT_BOUNDARY_ONE_EXACT_ORIGINAL_PARENT_COMPARISON')
 site.ops[0]=ast.LtE();scope=dict(vars(original))
 exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<whole-original-source-exit-validator-parent-boundary-equality>','exec'),scope)
 return scope['research_source_exit_term']


def validate_parent(value,parent,*,root_lookup):
 from system_campaign_full_history_successor import current_commitments
 term=value['term'];spec=root_lookup(term['arm'],term['parent_root_admission_sha256'])
 current_commitments(parent,spec,lambda base,repairs:digest(dict(base=base,repairs=repairs)))
 need(value['schema']==V2 and parent['sha256']==spec['outer_sha256'] and parent['repairs']==spec['repairs']
  and parent['completed']==spec['measured_closes'] and parent['source_cursor']==term['identity_witness']['session']==spec['selected_session'],
  'SOURCE_EXIT_BOUNDARY_ACTUAL_ENTIRE_PARENT_AND_LAST_PROCESSED_SESSION')
 series=parent['run']['state']['feed']['series'][term['security_id']]
 witness=dict(security_id=series['security_id'],ticker=series['ticker'],session=series['sessions'][-1],raw_close=series['raw_closes'][-1],series_sha256=digest(series))
 need(witness==value['parent_source_witness'] and witness['session']==parent['source_cursor']
  and witness['security_id']==term['security_id'] and witness['ticker']==term['ticker']
  and witness['raw_close']==float(value['prior_row']['raw_close'])==term['retained_quote']['raw_close'],
  'SOURCE_EXIT_BOUNDARY_EXACT_COMMITTED_PARENT_RAW_QUOTE')
 state=parent['run']['state'];original.require_source_scope(state['wealth_core'],state['pending'],state['ledger'],
  dict(security_id=term['security_id'],source_ticker=term['ticker'],require_never_held=True))
 return dict(passed=True,parent_sha256=parent['sha256'],parent_state_sha256=parent['run']['state_sha256'],witness_sha256=digest(witness),
  financial_sessions_advanced=0,event_date_ownership='UNKNOWN_UNTIL_ACTUAL_GUARDED_TRANSITION')


def validate(value,*,root_lookup):
 need(value['schema'] in ('research.source-batch-bound-unheld-source-exit-catalog/1',V2)
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
 if value['schema']==V2:
  ancestor_context(source,spec,root_lookup=root_lookup)
  need(value['witness_at_parent_cursor'] is True and value['parent_source_witness']['session']==spec['selected_session']
   and value['parent_source_witness']['security_id']==term['security_id'],'SOURCE_EXIT_BOUNDARY_ONLY_EXPLICIT_PARENT_WITNESS')
 else:need(context['root_admission_sha256']==spec['root_admission_sha256'] and context['outer_sha256']==spec['outer_sha256']
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
 actions={'delisted','regulatorydelisting'}
 if value['schema']==V2:
  actions=set(value['native_action_pair'])
  need(len(value['native_action_pair'])==2 and actions in ({'delisted','regulatorydelisting'},{'acquisitionby','delisted'}),
   'SOURCE_EXIT_BOUNDARY_ONLY_COMPLETE_SUPPORTED_NATIVE_PAIR')
 need(group['query']['session']==day and group['query']['security_id']==sid and group['status']=='FOUND'
  and len(group['raw_rows'])==2 and {r['row']['action'] for r in group['raw_rows']}==actions
  and all(digest(r['row'])==r['sha256'] and r['row']['security_id']==sid and r['row']['effective_session']==day for r in group['raw_rows'])
  and native==term['native'] and digest(native)==term['native_term_sha256'] and native['cash_per_share'] is None,
  'SOURCE_EXIT_CATALOG_COMPLETE_NATIVE_GROUP_AND_INCOMPLETE_TERMINAL')
 (boundary_validator() if value['schema']==V2 else original.research_source_exit_term)(term);original.source_exit_quote(term,prior)
 if value['schema']==V2:need(term['parent_cursor']==prior['session'],'SOURCE_EXIT_BOUNDARY_IMMEDIATE_SUCCESSOR_ONLY')
 need(term['research_assumption']['retained_raw_close']==str(float(prior['raw_close']))
  and value['event_quote_is_proxy'] is value['statutory_cash_claimed'] is value['otc_security_extinction_claimed'] is False
  and value['event_date_roles_verified'] is False,'SOURCE_EXIT_CATALOG_PRIOR_PROXY_ONLY_NO_NEW_ECONOMIC_OR_ROLE_AUTHORITY')
 return deepcopy(value)

def catalog(name=CATALOG):
 from system_campaign_financial_partial import root_spec
 need(type(name)is str and Path(name).name==name and '/' not in name and '\\' not in name,'SOURCE_EXIT_CATALOG_SAFE_EXPLICIT_FILENAME')
 return validate(json.loads((HERE/name).read_bytes()),root_lookup=root_spec)

def selected(arm,*,cursor,catalog_name=CATALOG):
 value=catalog(catalog_name);term=value['term']
 need(arm==term['arm'] and cursor==term['parent_cursor'],'SOURCE_EXIT_CATALOG_ONLY_EXACT_UNCONSUMED_ARM_CURSOR')
 codec=SimpleNamespace(catalog=value,catalog_sha=sha((HERE/catalog_name).read_bytes()),compiler_sha=sha(Path(__file__).read_bytes()),
  parent_outer_sha256=term['parent_outer_sha256'],parent_positions=[],validator_description='Existing research source exit at exact prior retained raw close; no settlement or held treatment. Full original no-op and source-delegation guards required.')
 return codec,catalog_name,[deepcopy(term)]
