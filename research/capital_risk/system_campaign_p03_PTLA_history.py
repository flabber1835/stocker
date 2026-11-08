"""Entire admitted full20 plus one original ordinary input and real neutral21."""
import gzip,json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_pxd_pause import adoption
import system_campaign_full_history_successor as original
import system_campaign_p03_STML_history as previous
import system_campaign_p03_PTLA_api as api_module
data,resources=api_module.data,api_module.data.resources
PREFIX=resources.PREFIX
PARENT=PREFIX+'/origin/parent-checkpoint.json.gz'
DIRECTORY=api_module.DIRECTORY
NEUTRAL=DIRECTORY+'/checkpoint.json.gz'
PROOF=DIRECTORY+'/proof.json'
OVERLAY=api_module.OVERLAY
CATALOG=PREFIX+'/source-catalog.json'
QUALIFICATION=api_module.QUALIFICATION
DAY='2020-07-01'
QUALIFICATION_FLAGS=('only_terminal_field_changed','complete_terms_and_canonical_notional_verified',
 'original_incomplete_guard_retained','wrong_predecessor_and_consumed_date_refused','wrong_native_and_delivery_witness_refused')


def spec():return resources.spec()


def full_parent(root,parent):
 resources.parent_contract(parent,spec());result=previous.full(root,parent)
 need(result['passed'] is True and result['full_inputs']==20,'PTLA_HISTORY_COMPLETE_EXISTING_STML_FULL20_VISITOR')
 return result


def archived_parent(member):
 raw=member(PARENT);target=spec()
 need(resources.pin(raw)==target['selected_file'],'PTLA_HISTORY_UNSUBSTITUTED_GENUINE628_PARENT_GZIP')
 parent=strict_json(raw);resources.parent_contract(parent,target);return parent


def packet_qualification(value):
 need(value['passed'] is True and type(value['packet_checks'])is int and value['packet_checks']==2
  and type(value['financial_sessions_advanced'])is int and value['financial_sessions_advanced']==0
  and all(value[k] is True for k in QUALIFICATION_FLAGS),'PTLA_HISTORY_ENTIRE_ACTUAL_TWO_PACKET_AND_NEGATIVE_GUARDS')
 return True


def material_name(parent):return api_module.original.hydration_name(parent)


def document(parent,member):
 resources.parent_contract(parent,spec());catalog=data.catalog()
 need(member(CATALOG)==data.encoded(catalog),'PTLA_HISTORY_EXACT_COMPLETE_SOURCE_CATALOG')
 raw=member(material_name(parent));material=json.loads(raw)
 need(material['schema']==api_module.original.REFERENCE and material['arm']=='P03'
  and material['catalog']==data.CATALOG and material['catalog_sha256']==sha(data.encoded(catalog))
  and material['original_validator_sha256']==sha(Path(data.__file__).read_bytes())
  and material['selector_sha256']==sha(Path(api_module.__file__).read_bytes())
  and material['parent_outer_sha256']==parent['sha256'] and material['terms']==data.terms()
  and material['financial_source_changed'] is material['provider_metadata_upgraded'] is False,
  'PTLA_HISTORY_ACTUAL_ORIGINAL_HYDRATION_ALL_SOURCE_AND_TERM_BINDINGS')
 packet_qualification(json.loads(member(QUALIFICATION)))
 api=api_module.api(parent,spec(),validate_history=full_parent)
 expected=api.document(parent,material,sha(raw))
 need(member(OVERLAY)==data.encoded(expected) and expected['add']==[t['added'] for t in data.terms()]
  and len(expected['source_evidence'])<=128,'PTLA_HISTORY_ENTIRE_ORIGINAL_DOCUMENT_AND_EVIDENCE_CAP')
 return expected


def history(root,current,*,member,previous_history=full_parent):
 return original.verify(root,current,spec(),member=member,previous_history=previous_history,document=document,
  input_hash=lambda base,repairs:digest(dict(base=base,repairs=repairs)),zero_adoption=adoption,
  earliest=DAY,parent_path=PARENT,neutral_path=NEUTRAL,proof_path=PROOF)


def full(root,current):
 root=Path(root);return history(root,current,member=lambda n:(root/n).read_bytes())


def boundary(parent,neutral,member,rows):
 resources.parent_contract(parent,spec());need(archived_parent(member)==parent,'PTLA_HISTORY_REAL20_PARENT_BEFORE_NEUTRAL21')
 doc=document(parent,member);event=adoption(neutral,parent,sha(data.encoded(doc)),DAY)
 raw=member(NEUTRAL);proof=json.loads(member(PROOF))
 need(strict_json(raw)==neutral and len(neutral['repairs'])==21 and neutral['repairs'][:-1]==parent['repairs']
  and neutral['run']['state']==parent['run']['state']
  and proof==dict(event=event,actual_checkpoint_gzip_sha256=sha(raw),original_outer_sha256=parent['sha256'],financial_state_unchanged=True,financial_sessions_advanced=0),
  'PTLA_HISTORY_ACTUAL_CANONICAL_NEUTRAL21_UNCHANGED_FINANCIAL_STATE')
 need(gzip.decompress(member(DIRECTORY+'-correlation-inputs.jsonl.gz'))==b''.join(rows),
  'PTLA_HISTORY_ALL_RETAINED_CORRELATION_AND_NO_NEW_OBSERVATION')
 watch=member('book/watch.jsonl');before,after=parent['journals']['watch'],neutral['journals']['watch']
 need(sha(watch[:before['bytes']])==before['prefix_sha256'] and sha(watch[:after['bytes']])==after['prefix_sha256']
  and [json.loads(v) for v in watch[before['bytes']:after['bytes']].splitlines()]==[event],
  'PTLA_HISTORY_ONLY_ONE_ACTUAL_CANONICAL_WATCH_APPEND')
 return dict(passed=True,parent_outer_sha256=parent['sha256'],neutral_outer_sha256=neutral['sha256'],neutral_gzip_sha256=sha(raw),
  parent_inputs=20,current_inputs=21,financial_sessions_advanced=0,event=event)
