"""Complete actual parent history plus one genuine ordinary source append."""
import gzip,json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_pxd_pause import adoption
import system_campaign_source_exit_api as api_module
import system_campaign_source_exit_input as source
import system_campaign_full_history_successor as successor
PARENT=successor.PARENT
DIRECTORY='ordinary-successor-adoption'
NEUTRAL=DIRECTORY+'/checkpoint.json.gz'
PROOF=DIRECTORY+'/proof.json'
PROVENANCE='ordinary-successor-origin'
OLD_PROOF=PROVENANCE+'/original-full442-uncertainty-certificate.jsonl'
OVERLAY=api_module.OVERLAY

def parent_contract(parent,spec):
 from system_campaign_retained_seed_successor import metadata
 metadata(spec);successor.current_commitments(parent,spec,lambda base,repairs:digest(dict(base=base,repairs=repairs)))
 need(parent['sha256']==spec['outer_sha256'] and parent['repairs']==spec['repairs'] and parent['journals']==spec['journals']
  and parent['completed']==spec['measured_closes'] and parent['source_cursor']==spec['selected_session'],'SOURCE_EXIT_HISTORY_ENTIRE_GENUINE_FINANCIAL_PARENT')
 return True

def input_api(parent,spec,visitor):return api_module.api(parent,spec,visitor=visitor)

def document(parent,spec,member,*,visitor):
 parent_contract(parent,spec);api=input_api(parent,spec,visitor);catalog=source.catalog();codec,_,terms=source.selected(spec['arm'],cursor=parent['source_cursor'])
 raw=member(api.hydration_name(parent));material=json.loads(raw)
 need(material['schema']==api_module.original.REFERENCE and material['arm']==spec['arm'] and material['parent_outer_sha256']==parent['sha256']
  and material['catalog']==source.CATALOG and material['catalog_sha256']==codec.catalog_sha
  and material['original_validator_sha256']==codec.compiler_sha and material['selector_sha256']==api_module.FUTURE_SHA
  and material['financial_source_changed'] is material['provider_metadata_upgraded'] is False,
  'SOURCE_EXIT_HISTORY_ENTIRE_ORIGINAL_HYDRATED_MATERIAL_CONTEXT')
 selected=[t for t in material['terms'] if t['security_id']==catalog['term']['security_id']]
 need(selected==terms and all(t['added']['session']>parent['source_cursor'] for t in material['terms']),
  'SOURCE_EXIT_HISTORY_EXACT_SOURCE_BOUND_TERM_AND_ALL_FORWARD_ADDITIONS')
 return api.document(parent,material,sha(raw))

def earliest(doc):
 return min(r['session'] for field in ('suppress','add') for r in doc[field])

def archived_parent(spec,member):
 raw=member(PARENT)
 need(dict(bytes=len(raw),sha256=sha(raw))==spec['selected_file'],'SOURCE_EXIT_HISTORY_ACTUAL_SELECTED_PARENT_GZIP')
 parent=strict_json(raw);parent_contract(parent,spec);return parent

def history(root,current,spec,*,member,previous_history,input_hash):
 # The complete old visitor always receives the genuine old parent, never a
 # truncated copy of current. Actual neutral13 bytes are required for a child.
 def doc(parent,read):return document(parent,spec,read,visitor=previous_history)
 day=earliest(doc(archived_parent(spec,member),member)) if current['sha256']!=spec['outer_sha256'] else source.catalog()['term']['added']['session']
 return successor.verify(root,current,spec,member=member,previous_history=previous_history,document=doc,input_hash=input_hash,
  zero_adoption=adoption,earliest=day,parent_path=PARENT,neutral_path=NEUTRAL,proof_path=PROOF)

def full(root,current):
 from full_system_core import hosted
 hosted()
 from research.pooled_vacancy_funding import backtest
 from system_campaign_financial_partial import root_spec
 import system_campaign_p06_WWE12_models as previous
 root=Path(root);return history(root,current,root_spec('P06'),member=lambda n:(root/n).read_bytes(),previous_history=previous.full,input_hash=backtest.input_hash)

def packet_qualification(member,terms):
 q=json.loads(member(api_module.QUALIFICATION));checks=sum(len({t['native_session'],t['added']['session']}) for t in terms)
 need(q['passed'] is True and type(q['packet_checks']) is int and q['packet_checks']==checks>0
  and all(q[k] is True for k in ('only_terminal_field_changed','complete_terms_and_canonical_notional_verified','original_incomplete_guard_retained',
   'wrong_predecessor_and_consumed_date_refused','wrong_native_and_delivery_witness_refused'))
  and type(q['financial_sessions_advanced']) is int and q['financial_sessions_advanced']==0,'SOURCE_EXIT_HISTORY_COMPLETE_ORIGINAL_PACKET_QUALIFICATION')
 return q

def boundary_relation(parent,neutral,spec,member,rows,*,previous_history):
 parent_contract(parent,spec);need(archived_parent(spec,member)==parent,'SOURCE_EXIT_HISTORY_UNSUBSTITUTED_SELECTED_PARENT')
 doc=document(parent,spec,member,visitor=previous_history);overlay=member(OVERLAY)
 need(json.loads(overlay)==doc,'SOURCE_EXIT_HISTORY_COMPLETE_ORIGINAL_OVERLAY_RECONSTRUCTION')
 day=earliest(doc);event=adoption(neutral,parent,sha(overlay),day);neutral_raw=member(NEUTRAL)
 need(strict_json(neutral_raw)==neutral and neutral['run']['state']==parent['run']['state']
  and len(neutral['repairs'])==len(parent['repairs'])+1 and neutral['repairs'][:-1]==parent['repairs'],
  'SOURCE_EXIT_HISTORY_REAL_ZERO_SESSION_NEUTRAL_ARCHIVE_WITH_ALL_PRIOR_INPUTS')
 proof=json.loads(member(PROOF))
 need(proof==dict(event=event,actual_checkpoint_gzip_sha256=sha(neutral_raw),original_outer_sha256=parent['sha256'],financial_state_unchanged=True,financial_sessions_advanced=0)
  and gzip.decompress(member(DIRECTORY+'-correlation-inputs.jsonl.gz'))==b''.join(rows),'SOURCE_EXIT_HISTORY_EXACT_ZERO_SESSION_PROOF_AND_UNCHANGED_CORRELATION')
 watch=member('book/watch.jsonl');a,b=parent['journals']['watch'],neutral['journals']['watch']
 need(sha(watch[:a['bytes']])==a['prefix_sha256'] and sha(watch[:b['bytes']])==b['prefix_sha256']
  and [json.loads(v) for v in watch[a['bytes']:b['bytes']].splitlines()]==[event],'SOURCE_EXIT_HISTORY_ONLY_GENUINE_CANONICAL_INPUT_SUCCESSOR_WATCH_APPEND')
 api=input_api(parent,spec,previous_history);material=json.loads(member(api.hydration_name(parent)))
 packet_qualification(member,material['terms'])
 return dict(passed=True,parent_sha256=parent['sha256'],neutral_sha256=neutral['sha256'],neutral_gzip_sha256=sha(neutral_raw),
  original_root_admission_sha256=spec['root_admission_sha256'],original_inputs=len(parent['repairs']),current_inputs=len(neutral['repairs']),
  input_successor=event,earliest_affected_session=day,financial_sessions_advanced=0,source_exit_does_not_authorize_portfolio_settlement=True)
