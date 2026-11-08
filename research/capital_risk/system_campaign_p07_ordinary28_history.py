"""Whole genuine27 history, one original cash batch, and actual neutral28."""
import gzip,json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_pxd_pause import adoption
import system_campaign_full_history_successor as original
import system_campaign_p07_KDNY_history as previous
import system_campaign_p07_ordinary28_api as api_module
import system_campaign_p07_ordinary28_resources as resources
data=api_module.data
PREFIX=resources.PREFIX
PARENT=PREFIX+'/origin/parent-checkpoint.json.gz'
DIRECTORY=api_module.DIRECTORY
NEUTRAL=DIRECTORY+'/checkpoint.json.gz'
PROOF=DIRECTORY+'/proof.json'
OVERLAY=api_module.OVERLAY
CATALOG=PREFIX+'/source-catalog.json'
QUALIFICATION=api_module.QUALIFICATION
DAY='2023-09-01'
QUALIFICATION_FLAGS=('only_terminal_field_changed','complete_terms_and_canonical_notional_verified','original_incomplete_guard_retained','wrong_predecessor_and_consumed_date_refused','wrong_native_and_delivery_witness_refused')

def spec():return resources.spec()

def full_parent(root,parent):
 data.parent_contract(parent,spec());value=previous.full(root,parent)
 need(value['passed']is True and value['full_inputs']==27,'ORDINARY28_HISTORY_ENTIRE_ORIGINAL27_VISITOR')
 return value

def archived_parent(member):
 raw=member(PARENT);target=spec()
 need(resources.pin(raw)==target['selected_file'],'ORDINARY28_HISTORY_GENUINE1426_GZIP_NOT_A_PROJECTED_BOOK')
 cp=strict_json(raw);data.parent_contract(cp,target);return cp

def packet_qualification(v):
 need(v['passed']is True and type(v['packet_checks'])is int and v['packet_checks']==24
  and type(v['financial_sessions_advanced'])is int and v['financial_sessions_advanced']==0
  and all(v[k]is True for k in QUALIFICATION_FLAGS),'ORDINARY28_HISTORY_ALL_ORIGINAL24_PACKET_AND_NEGATIVE_GUARDS')
 return True

def material_name(parent):return api_module.original.hydration_name(parent)

def document(parent,member):
 data.parent_contract(parent,spec());catalog=data.catalog()
 need(member(CATALOG)==data.encoded(catalog),'ORDINARY28_HISTORY_EXACT_FINITE_TWELVE_TERM_SOURCE_CATALOG')
 raw=member(material_name(parent));material=json.loads(raw)
 need(material['schema']==api_module.original.REFERENCE and material['arm']=='P07'
  and material['catalog']==data.CATALOG and material['catalog_sha256']==sha(data.encoded(catalog))
  and material['original_validator_sha256']==sha(Path(data.__file__).read_bytes())
  and material['selector_sha256']==sha(Path(api_module.__file__).read_bytes())
  and material['parent_outer_sha256']==parent['sha256'] and material['terms']==data.terms()
  and material['financial_source_changed']is material['provider_metadata_upgraded']is False,
  'ORDINARY28_HISTORY_WHOLE_ORIGINAL_MATERIAL_AND_ALL_SOURCE_TERM_BINDINGS')
 packet_qualification(json.loads(member(QUALIFICATION)))
 api=api_module.api(parent,spec(),validate_history=full)
 result=api.document(parent,material,sha(raw))
 need(member(OVERLAY)==data.encoded(result) and result['add']==[t['added'] for t in data.terms()]
  and len(result['source_evidence'])<=128,'ORDINARY28_HISTORY_WHOLE_ORIGINAL_DOCUMENT_AND_EVIDENCE_CAP')
 return result

def history(root,current,*,member,previous_history=full_parent):
 return original.verify(root,current,spec(),member=member,previous_history=previous_history,document=document,
  input_hash=lambda base,repairs:digest(dict(base=base,repairs=repairs)),zero_adoption=adoption,earliest=DAY,
  parent_path=PARENT,neutral_path=NEUTRAL,proof_path=PROOF)

def full(root,current):
 root=Path(root);return history(root,current,member=lambda n:(root/n).read_bytes())

def boundary(parent,neutral,member,rows):
 data.parent_contract(parent,spec());need(archived_parent(member)==parent,'ORDINARY28_HISTORY_REAL27_PARENT_BEFORE_NEUTRAL28')
 doc=document(parent,member);event=adoption(neutral,parent,sha(data.encoded(doc)),DAY)
 raw=member(NEUTRAL);proof=json.loads(member(PROOF))
 need(strict_json(raw)==neutral and len(neutral['repairs'])==28 and neutral['repairs'][:-1]==parent['repairs']
  and neutral['run']['state']==parent['run']['state']
  and proof==dict(event=event,actual_checkpoint_gzip_sha256=sha(raw),original_outer_sha256=parent['sha256'],financial_state_unchanged=True,financial_sessions_advanced=0),
  'ORDINARY28_HISTORY_ACTUAL_CANONICAL_NEUTRAL28_ENTIRE_STATE_UNCHANGED')
 need(gzip.decompress(member(DIRECTORY+'-correlation-inputs.jsonl.gz'))==b''.join(rows),
  'ORDINARY28_HISTORY_ENTIRE_RETAINED_CORRELATION_NO_NEW_OBSERVATION')
 watch=member('book/watch.jsonl');before,after=parent['journals']['watch'],neutral['journals']['watch']
 need(sha(watch[:before['bytes']])==before['prefix_sha256'] and sha(watch[:after['bytes']])==after['prefix_sha256']
  and [json.loads(v) for v in watch[before['bytes']:after['bytes']].splitlines()]==[event],
  'ORDINARY28_HISTORY_ONLY_ONE_CANONICAL_WATCH_APPEND')
 return dict(passed=True,parent_outer_sha256=parent['sha256'],neutral_outer_sha256=neutral['sha256'],neutral_gzip_sha256=sha(raw),parent_inputs=27,current_inputs=28,financial_sessions_advanced=0,event=event)

def source_names():return (Path(__file__).name,'system_campaign_p07_KDNY_history.py',*api_module.source_names(),*resources.source_names())
