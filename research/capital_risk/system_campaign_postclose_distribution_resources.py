"""Authenticated saved P07 resources; original hosted copy and verification."""
import json
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_bounded_sensor_origin_v2 import exact
import system_campaign_dependencies as dependencies
import system_campaign_p06_WWE12_resources as original
import system_campaign_p07_saved_proofs as saved
HERE=Path(__file__).parent
PLAN='P07-BWA-saved-resources.json'
PLAN_SHA='8410aeeb5ecf54d83bec31f3bb9b9f978ac1c7319df01fd592f90ab270e92524'
PREFIX='distribution-successors/'+saved.ROOT+'/provenance'
RECEIPT=PREFIX+'/resource-preservation.json'

def validate_plan(value,spec):
 meta=saved.metadata(spec)
 need(value['schema']=='research.P07-postclose-saved-resource-plan/1'
  and value['financial_authority'] is value['financial_book_aliases_created'] is False
  and value['root_admission_sha256']==spec['root_admission_sha256']
  and value['parent_outer_sha256']==spec['outer_sha256'] and value['parent_selected_file']==spec['selected_file']
  and value['parent_descriptors']==spec['repairs'] and value['parent_cursor']==spec['selected_session'],
  'POSTCLOSE_RESOURCES_EXACT_ENTIRE_GENUINE_PARENT25')
 need(value['raw_proof']==meta['raw_proof'] and value['raw_proof_rows']==930 and value['committed_rows']==929
  and value['raw_proof_source']=='uncertainty-certificate.jsonl'
  and value['raw_proof_destination']==PREFIX+'/original-full930-uncertainty-certificate.jsonl'
  and value['historical_ABMD_permission_resolution']==meta['historical_event_resolution'],
  'POSTCLOSE_RESOURCES_LITERAL_RAW930_SEED929_AND_SEPARATE_ORIGINAL_PERMISSION')
 archives=value['historical_archive_resolutions']
 need(len(archives)==7 and meta['historical_event_resolution'] in archives
  and len({v['actual'] for v in archives})==7
  and all(v['actual'].removeprefix('book/pre-event/')[:10]<=spec['selected_session'] for v in archives)
  and value['requirements']==len(value['resources'])+len(archives)==165
  and value['logical_bytes']==287155235,'POSTCLOSE_RESOURCES_ALL165_AND_NO_UNACCEPTED_JULY_ARCHIVE')
 for n,pin in value['resources'].items():dependencies.Requirement(path=n,role='historical_asset',**pin)
 for n in value['DATA_read_trace_members']:
  need(n in value['resources'] or n.startswith(('book/','lineage/')) or n==value['raw_proof_source'],
   'POSTCLOSE_RESOURCES_EVERY_COMPLETE_PREVIOUS_READER_DEPENDENCY:'+n)
 return value

def plan(spec):
 raw=(HERE/PLAN).read_bytes();need(sha(raw)==PLAN_SHA,'POSTCLOSE_RESOURCES_EXACT_AUTHENTICATED_RESOURCE_PLAN')
 return validate_plan(json.loads(raw),spec)

def closure(member,spec,resolutions):
 value=plan(spec)
 need(list(resolutions)==[value['historical_ABMD_permission_resolution']],
  'POSTCLOSE_RESOURCES_ONLY_ORIGINAL_ABMD_PERMISSION_NO_ADDED_AUTHORITY')
 result=dependencies.build(value['resources'],value['historical_archive_resolutions'],member)
 need(len(result['requirements'])==value['requirements']
  and sum(v['bytes'] for v in result['requirements'])==value['logical_bytes'],
  'POSTCLOSE_RESOURCES_COMPLETE_PINNED_HISTORICAL_CLOSURE')
 return result

def preserve(root,out,parent,spec,*,rows,resolutions):
 from full_system_core import hosted
 hosted();saved.parent_contract(parent,spec);root,out=Path(root),Path(out)
 member=lambda n:(root/n).read_bytes();value=plan(spec);manifest=closure(member,spec,resolutions)
 dependencies.copy_checked(manifest,member,lambda n,b:exact(out/n,b))
 dependencies.verify(manifest,value['resources'],value['historical_archive_resolutions'],member,lambda n:(out/n).read_bytes())
 raw=member(value['raw_proof_source']);saved.literal_prefix(raw,rows,spec);exact(out/value['raw_proof_destination'],raw)
 exact(out/RECEIPT,saved.encoded(manifest));return manifest

def verify_preserved(source,destination,spec,*,rows,resolutions):
 value=plan(spec);manifest=closure(source,spec,resolutions)
 dependencies.verify(manifest,value['resources'],value['historical_archive_resolutions'],source,destination)
 raw=source(value['raw_proof_source']);saved.literal_prefix(raw,rows,spec)
 need(destination(value['raw_proof_destination'])==raw and json.loads(destination(RECEIPT))==manifest,
  'POSTCLOSE_RESOURCES_WHOLE_RAW_PROOF_AND_EXACT_PRESERVATION_RECEIPT')
 return True

def bound_canary(spec):
 fn=original.canary
 need(fn.__closure__ is None,'POSTCLOSE_RESOURCES_ORIGINAL_CANARY_WITHOUT_HIDDEN_CLOSURE')
 def closed_inventory(member,resolutions):
  value=plan(spec)
  return dict(passed=True,plan_sha256=PLAN_SHA,resources=value['resources'],financial_authority=False,
   financial_book_aliases_created=False,financial_sessions_reexecuted=0,dependency_closure=closure(member,spec,resolutions))
 scope=dict(fn.__globals__,data=SimpleNamespace(parent_contract=saved.parent_contract,need=need),
  closed_inventory=closed_inventory,plan=lambda:plan(spec))
 bound=FunctionType(fn.__code__,scope,fn.__name__,fn.__defaults__);bound.__kwdefaults__=fn.__kwdefaults__
 need(bound.__code__ is fn.__code__,'POSTCLOSE_RESOURCES_IDENTICAL_COMPLETE_ORIGINAL_OWNED_COPY_CANARY')
 return bound

def canary(root,out,parent,spec,*,resolutions):
 from full_system_core import hosted
 hosted();return bound_canary(spec)(root,out,parent,spec,resolutions=resolutions)
