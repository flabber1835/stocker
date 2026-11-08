"""Complete authentic full26 resource closure and literal949 committed seed."""
import json,tempfile
from pathlib import Path,PurePosixPath
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import exact
import system_campaign_dependencies as dependencies
import system_campaign_p07_KDNY_history as history
source=history.source
HERE=Path(__file__).parent
FACT='P07-KDNY-real1403-retained949-resource-fact.json'
FACT_SHA='fc23241ac5c62f0c4ac6bf3c1b3326b1535d61869f6a5f1c61525d70531065e8'
RECEIPT=history.PREFIX+'/resource-preservation.json'
CANARY=history.PREFIX+'/resource-copy-canary.json'


def pin(raw):return dict(bytes=len(raw),sha256=sha(raw))


def fact():
 raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'KDNY_RESOURCES_EXACT_AUTHENTICATED_REAL1403_FACT')
 v=json.loads(raw);spec=history.spec()
 target={k:x for k,x in spec.items() if k not in ('root_admission','root_admission_sha256')}
 need(v['schema']=='research.P07-KDNY-real1403-retained949-resource-fact/1'
  and v['root_admission_sha256']==source.ROOT and v['parent_transport']==target and v['parent_selected_file']==spec['selected_file']
  and v['requirements']==len(v['resources'])==216 and v['logical_bytes']==366268272
  and v['raw_proof']['rows']==956 and v['committed_proof']['rows']==949 and len(v['excluded_tail_sessions'])==7
  and len(v['actual_resource_trace']['reads'])==94 and len(v['controller_sources'])==6
  and v['positive_branch_review_sha256']==spec['root_admission']['branch_uncertainty_proof']['hosted_canonical_transition_oracle_sha256']
  and v['financial_authority'] is v['financial_profile_ready'] is v['local_canonical_runtime_executed'] is v['actual_neutral27_known'] is False
  and v['selected_checkpoint_replaced'] is v['financial_book_aliases_created'] is False,
  'KDNY_RESOURCES_COMPLETE_ADMITTED26_RAW956_SEED949_AND_UNPERFORMED_HOSTED_BOUNDARY')
 return v


def declarations(v):
 declared={};sources=set()
 for destination,item in v['resources'].items():
  for name in (destination,item['source_path'],item['authenticated_member']):
   p=PurePosixPath(name)
   need(name and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name,
    'KDNY_RESOURCE_SAFE_ORIGINAL_SOURCE_AND_DESTINATION')
  need(destination not in ('book/checkpoint.json.gz','uncertainty-certificate.jsonl','source-bindings.json','request.json','spec.json')
   and not destination.startswith(('stopped-review/','parent-preflight/'))
   and (not destination.startswith('book/') or destination.startswith(('book/repairs/','book/pre-event/'))),
   'KDNY_RESOURCE_NO_CURRENT_CONTROL_REVIEW_JOURNAL_OR_CHECKPOINT_COLLISION')
  manifest=v['actual_financial_manifest'] if item['archive_role']=='original_financial' else v['actual_readonly_manifest']
  need({k:item[k] for k in ('bytes','sha256')}==manifest[item['authenticated_member']],
   'KDNY_RESOURCE_EXACT_AUTHENTICATED_SOURCE_MEMBER:'+destination)
  if item['archive_role']=='original_financial':sources.add(item['authenticated_member'])
  archive=destination.startswith('book/pre-event/')
  dependencies.Requirement(path=destination,role='pre_event_archive' if archive else 'historical_asset',bytes=item['bytes'],sha256=item['sha256'])
  if not archive:declared[destination]={k:item[k] for k in ('bytes','sha256')}
 archives=v.get('historical_archive_resolutions',[])
 need({x['actual'] for x in archives}=={n for n in v['resources'] if n.startswith('book/pre-event/')},
  'KDNY_RESOURCE_ALL_ORIGINAL_PRODUCER_ARCHIVE_RESOLUTIONS')
 need(set(v['actual_resource_trace']['reads'])<=sources,'KDNY_RESOURCE_ALL94_ACTUAL_FULL26_READER_DEPENDENCIES')
 return declared


def closure(member):
 v=fact();declared=declarations(v)
 def mapped(name):return member(v['resources'][name]['source_path'])
 manifest=dependencies.build(declared,v.get('historical_archive_resolutions',[]),mapped)
 need(len(manifest['requirements'])==v['requirements'] and sum(x['bytes'] for x in manifest['requirements'])==v['logical_bytes'],
  'KDNY_RESOURCES_COMPLETE216_AUTHENTIC_BYTES')
 return manifest


def seed_contract(parent,rows,qualified):
 v=fact();source.parent_contract(parent,history.spec());raw=b''.join(json.dumps(r,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for r in rows)
 need(pin(raw)=={k:v['committed_proof'][k] for k in ('bytes','sha256')} and len(rows)==949
  and rows[-1]==v['last_committed_proof'] and rows[-1]['session']==parent['source_cursor']
  and rows[-1]['next_state_sha256']==parent['run']['state_sha256']
  and rows[-1]['input_sha256']==parent['run']['input_sha256'],
  'KDNY_RESOURCES_ENTIRE_LITERAL949_COMMITTED_PREFIX_AND_NO_AUGUST_TAIL')
 q=json.loads(qualified)
 need(pin(qualified)=={k:v['resources']['branch-controller-qualification.json'][k] for k in ('bytes','sha256')}
  and q['passed'] is True and q['exact_controller_sources']==v['controller_sources'],
  'KDNY_RESOURCES_IDENTICAL_ORIGINAL_CONTROLLER_QUALIFICATION')
 return True


def raw_contract(member,rows):
 v=fact();raw=member('uncertainty-certificate.jsonl');lines=raw.splitlines(keepends=True)
 need(dict(rows=len(lines),**pin(raw))==v['raw_proof'] and len(rows)==949
  and [json.loads(r)['session'] for r in lines[949:]]==v['excluded_tail_sessions']
  and all(day>v['parent_transport']['selected_session'] for day in v['excluded_tail_sessions']),
  'KDNY_RESOURCES_ALL956_PRESERVED_ONLY949_COMMITTED')
 return True


def verify(member,destination):
 v=fact();manifest=closure(member);declared=declarations(v)
 dependencies.verify(manifest,declared,v.get('historical_archive_resolutions',[]),lambda n:member(v['resources'][n]['source_path']),destination)
 return manifest


def preserve(old,out,parent,rows,qualified):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);seed_contract(parent,rows,qualified);member=lambda n:(old/n).read_bytes();raw_contract(member,rows)
 v=fact();manifest=closure(member)
 dependencies.copy_checked(manifest,lambda n:member(v['resources'][n]['source_path']),lambda n,b:exact(out/n,b))
 need(verify(member,lambda n:(out/n).read_bytes())==manifest,'KDNY_RESOURCES_REAL_COPY_COMPLETE_SAME_CLOSURE')
 exact(out/RECEIPT,source.encoded(manifest));return manifest


def canary(old,out):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);v=fact();member=lambda n:(old/n).read_bytes();manifest=closure(member)
 with tempfile.TemporaryDirectory(prefix='p07-kdny-copy-canary-',dir=out) as owned:
  root=Path(owned)
  dependencies.copy_checked(manifest,lambda n:member(v['resources'][n]['source_path']),lambda n,b:exact(root/n,b))
  need(verify(member,lambda n:(root/n).read_bytes())==manifest,'KDNY_RESOURCES_CANARY_SAME_COMPLETE_COPIER_AND_VERIFIER')
 need(not Path(owned).exists(),'KDNY_RESOURCES_CANARY_PRIVATE_COPY_REMOVAL_OBSERVED')
 q=dict(passed=True,requirements=216,logical_bytes=366268272,complete_shared_copier_and_verifier=True,
  copy_removal_observed=True,financial_sessions_advanced=0,actual_neutral27_known=False)
 exact(out/CANARY,source.encoded(q));return q
