"""Pinned genuine-parent resources and the whole original hosted copy canary."""
import json
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_bounded_sensor_origin_v2 import exact
import system_campaign_dependencies as dependencies
import system_campaign_source_exit_history as history
import system_campaign_retained_seed_successor as seeds
import system_campaign_p06_WWE12_resources as original
import system_campaign_source_exit_profiles as profiles
HERE=Path(__file__).parent
PLAN='system-campaign-source-exit-successor-resources.json'
PLAN_SHA='cd94bcaf5a27da1438722c111cd2a868d93523bfcec64149fa4dd4c31cf833d1'
RECEIPT=history.PROVENANCE+'/resource-preservation.json'

def validate_plan(value,spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);seed=seeds.metadata(spec)
 need(value['schema']=='research.source-exit-successor-resource-plan/1' and value['financial_authority'] is value['financial_book_aliases_created'] is False
  and value['root_admission_sha256']==spec['root_admission_sha256'] and value['parent_outer_sha256']==spec['outer_sha256']
  and value['parent_selected_file']==spec['selected_file'] and value['parent_descriptors']==spec['repairs']
  and value['raw_proof']==seed['raw_proof'] and value['raw_proof_rows']==seed['raw_rows']
  and value['event_resolutions']==[seed['historical_event_resolution']],
  'SOURCE_EXIT_RESOURCES_EXACT_ENTIRE_PARENT_AND_ORIGINAL_PROOF_ARCHIVE_CONTEXT')
 need(len(value['resources'])==value['requirements']-1 and value['requirements']>=104 and value['raw_proof_destination']==profiles.paths(spec)['OLD_PROOF'],
  'SOURCE_EXIT_RESOURCES_COMPLETE_FINITE_TRACE_NOT_CURRENT_BOOK_ALIASES')
 for n,pin in value['resources'].items():dependencies.Requirement(path=n,role='historical_asset',**pin)
 return value

def plan(spec):
 name=profiles.profile(spec)['resource_plan'];raw=(HERE/name).read_bytes()
 if name==PLAN:need(len(PLAN_SHA)==64 and sha(raw)==PLAN_SHA,'SOURCE_EXIT_RESOURCES_EXACT_AUTHENTICATED_TRACE_PLAN')
 else:need(sha(raw)==profiles.profile(spec)['resource_plan_sha256'],'SOURCE_EXIT_RESOURCES_EXACT_PROFILE_RESOURCE_PLAN')
 return validate_plan(json.loads(raw),spec)

def closure(member,spec,resolutions):
 value=plan(spec);need(list(resolutions)==value['event_resolutions'],'SOURCE_EXIT_RESOURCES_ORIGINAL_EVENT_RESOLUTION_AT_USE')
 result=dependencies.build(value['resources'],resolutions,member)
 need(len(result['requirements'])==value['requirements'] and sum(r['bytes'] for r in result['requirements'])==value['logical_bytes'],
  'SOURCE_EXIT_RESOURCES_ENTIRE104_REQUIREMENT_CLOSURE')
 return result

def preserve(root,out,parent,spec,*,rows,resolutions):
 from full_system_core import hosted
 hosted();history.parent_contract(parent,spec);root,out=Path(root),Path(out);read=lambda n:(root/n).read_bytes()
 value=plan(spec);manifest=closure(read,spec,resolutions)
 dependencies.copy_checked(manifest,read,lambda n,b:exact(out/n,b))
 dependencies.verify(manifest,value['resources'],resolutions,read,lambda n:(out/n).read_bytes())
 names=profiles.paths(spec);raw=read('uncertainty-certificate.jsonl');seeds.literal_prefix(raw,rows,spec);exact(out/names['OLD_PROOF'],raw)
 exact(out/names['PROVENANCE']+'/resource-preservation.json',(json.dumps(manifest,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())
 return manifest

def verify_preserved(source,destination,spec,*,rows,resolutions):
 value=plan(spec);manifest=closure(source,spec,resolutions)
 dependencies.verify(manifest,value['resources'],resolutions,source,destination)
 raw=source('uncertainty-certificate.jsonl');seeds.literal_prefix(raw,rows,spec)
 names=profiles.paths(spec)
 need(destination(names['OLD_PROOF'])==raw and json.loads(destination(names['PROVENANCE']+'/resource-preservation.json'))==manifest,'SOURCE_EXIT_RESOURCES_WHOLE442_PROOF_AND_ORIGINAL_CLOSURE_PRESERVED')
 return True

def bound_canary(spec):
 fn=original.canary
 need(fn.__closure__ is None,'SOURCE_EXIT_RESOURCES_WHOLE_ORIGINAL_CANARY_WITH_EXPLICIT_CLOSURE')
 def closed_inventory(member,resolutions):
  value=plan(spec)
  return dict(passed=True,plan_sha256=sha((HERE/profiles.profile(spec)['resource_plan']).read_bytes()),resources=value['resources'],financial_authority=False,
   financial_book_aliases_created=False,financial_sessions_reexecuted=0,dependency_closure=closure(member,spec,resolutions))
 scope=dict(fn.__globals__,data=SimpleNamespace(parent_contract=history.parent_contract,need=need),
  closed_inventory=closed_inventory,plan=lambda:plan(spec))
 bound=FunctionType(fn.__code__,scope,fn.__name__,fn.__defaults__);bound.__kwdefaults__=fn.__kwdefaults__
 need(bound.__code__ is fn.__code__,'SOURCE_EXIT_RESOURCES_IDENTICAL_COMPLETE_OWNED_COPY_CANARY_CODE')
 return bound

def canary(root,out,parent,spec,*,resolutions):
 from full_system_core import hosted
 hosted();return bound_canary(spec)(root,out,parent,spec,resolutions=resolutions)
