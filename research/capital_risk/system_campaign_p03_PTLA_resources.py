"""Authentic full20 assets and literal174 seed; no local financial authority."""
import json
from pathlib import Path,PurePosixPath
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import exact
import system_campaign_p03_STML_resources as original
HERE=Path(__file__).parent
ROOT='fa1f39c050cbb125bcd6ab7b03189d7004c2e1149f3d893a35be78c07b89b36c'
FACT='P03-PTLA-real628-retained174-resource-fact.json'
FACT_SHA='eaf2d4da9195ee8f8430e61e28aeb422496aae258e528dd91768272a4c7a70f4'
PREFIX='ordinary-successors/'+ROOT
RECEIPT=PREFIX+'/resource-preservation.json'
CANARY=PREFIX+'/resource-copy-canary.json'
QUALIFIED=PREFIX+'/origin/original-controller-qualification.json'
ORIGINAL_SHA='783f575249cf2cf1803d7d2f17f9ac97ba8e08ddfe28624f8c142ee700d989b9'
pin=original.pin
encoded=lambda v:(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()


def spec():
 from system_campaign_financial_partial import root_spec
 return root_spec('P03',ROOT)


def fact():
 raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'PTLA_RESOURCES_AUTHENTIC_CURRENT628_FACT')
 v=json.loads(raw);target=spec()
 need(v['root_admission_sha256']==ROOT and v['parent_transport']=={k:x for k,x in target.items() if k not in ('root_admission','root_admission_sha256')}
  and v['requirements']==len(v['resources'])==127 and v['logical_bytes']==61315516
  and v['raw_proof']['rows']==v['committed_proof']['rows']==174 and v['excluded_tail_sessions']==[]
  and len(v['controller_sources'])==6 and len(v['actual_resource_trace']['reads'])==27
  and len(v['original105_destinations'])==105 and len(v['historical_archive_resolutions'])==4
  and v['financial_authority'] is v['local_canonical_runtime_executed'] is v['financial_profile_ready'] is v['actual_neutral21_known'] is False
  and v['selected_checkpoint_replaced'] is v['financial_book_aliases_created'] is False,
  'PTLA_RESOURCES_FULL20_LITERAL174_AND_UNPERFORMED_HOSTED_BOUNDARY')
 return v


def declarations(v):
 declared={};sources=set()
 for destination,item in v['resources'].items():
  for name in (destination,item['source_path'],item['authenticated_member']):
   p=PurePosixPath(name)
   need(name and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name,
    'PTLA_RESOURCES_SAFE_SOURCE_AND_DESTINATION')
  need(item['source_path']==item['authenticated_member'] and {k:item[k] for k in ('bytes','sha256')}==v['actual_manifest'][item['authenticated_member']],
   'PTLA_RESOURCES_EXACT_AUTHENTICATED_SOURCE_MEMBER')
  need(destination not in ('book/checkpoint.json.gz','uncertainty-certificate.jsonl','branch-controller-qualification.json','request.json','spec.json','source-bindings.json')
   and not destination.startswith(('stopped-review/','parent-preflight/'))
   and (not destination.startswith('book/') or destination.startswith('book/pre-event/')
    or destination=='book/predecessor-checkpoints/50529edab057a7f1a835f3ebb6e947efc5b4f10b64ca941d12f212cd709d1f8a.json.gz'
     and destination in v['original105_destinations'] and item['source_path']==destination)
   and (not destination.endswith('actual-future-event-refusal.json') or destination.startswith(PREFIX+'/origin/diagnostics/')),
   'PTLA_RESOURCES_NO_ACTIVE_BOOK_CONTROL_REVIEW_OR_DIAGNOSTIC_COLLISION')
  archive=destination.startswith('book/pre-event/')
  need(type(item['bytes'])is int and (item['bytes']>0 or destination in v['original105_destinations'] and item['bytes']==0 and item['sha256']==sha(b'')),
   'PTLA_RESOURCES_ONLY_AUTHENTIC_HISTORICAL_EMPTY_ASSET')
  if not archive:declared[destination]={k:item[k] for k in ('bytes','sha256')}
  sources.add(item['source_path'])
 need(set(v['actual_resource_trace']['reads'])|set(v['original105_destinations'])<=sources,
  'PTLA_RESOURCES_ALL27_NEW_READS_AND_ALL105_OLD_ASSETS_REQUIRED')
 need({r['actual'] for r in v['historical_archive_resolutions']}=={n for n in v['resources'] if n.startswith('book/pre-event/')},
  'PTLA_RESOURCES_ALL_ORIGINAL_PRE_EVENT_RESOLUTIONS')
 return declared


def original_api():
 need(sha(Path(original.__file__).read_bytes())==ORIGINAL_SHA,'PTLA_RESOURCES_WHOLE_ORIGINAL_STML_RESOURCE_FUNCTIONS')
 v=fact();declarations(v)
 adapted=dict(resources={e['source_path']:dict(destination=n,bytes=e['bytes'],sha256=e['sha256']) for n,e in v['resources'].items()},
  actual_resource_trace=dict(resource_reads=v['actual_resource_trace']['reads']))
 need(len(adapted['resources'])==127,'PTLA_RESOURCES_UNIQUE_ORIGINAL_SOURCE_MEMBERS')
 scope=dict(vars(original),fact=lambda:adapted,source=SimpleNamespace(ROOT=ROOT,encoded=encoded),RECEIPT=RECEIPT,CANARY=CANARY)
 for name in ('closure','verify','preserve','canary'):
  fn=getattr(original,name);need(fn.__closure__ is None,'PTLA_RESOURCES_COMPLETE_CLOSED_ORIGINAL_FUNCTION:'+name)
  scope[name]=FunctionType(fn.__code__,scope,fn.__name__,fn.__defaults__)
 return SimpleNamespace(**{n:scope[n] for n in ('closure','verify','preserve','canary')})


def closure(member):
 result=original_api().closure(member)
 need(len(result['resources'])==127 and sum(p['bytes'] for p in result['resources'].values())==61315516,
  'PTLA_RESOURCES_WHOLE127_CLOSURE')
 return result


def parent_contract(parent,target):
 from system_campaign_full_history_successor import current_commitments
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(target);current_commitments(parent,target,lambda base,repairs:digest(dict(base=base,repairs=repairs)))
 need(target==spec() and parent['sha256']==target['outer_sha256'] and parent['repairs']==target['repairs']
  and parent['journals']==target['journals'] and (parent['completed'],parent['source_cursor'],len(parent['repairs']))==(628,'2020-06-30',20),
  'PTLA_RESOURCES_EXACT_GENUINE628_FULL20_ADMITTED_PARENT')


def seed_contract(parent,rows,qualified):
 v=fact();parent_contract(parent,spec())
 raw=b''.join(json.dumps(r,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for r in rows)
 need(dict(rows=len(rows),**pin(raw))==v['committed_proof'] and len(rows)==174
  and rows[-1]==v['last_committed_proof'] and rows[-1]['session']==parent['source_cursor']
  and rows[-1]['next_state_sha256']==parent['run']['state_sha256'] and rows[-1]['input_sha256']==parent['run']['input_sha256'],
  'PTLA_RESOURCES_LITERAL174_SEED_AND_ACTUAL_PARENT_STATE')
 q=json.loads(qualified)
 need(pin(qualified)=={k:v['resources'][QUALIFIED][k] for k in ('bytes','sha256')}
  and q['passed'] is True and q['exact_controller_sources']==v['controller_sources']
  and all(parent['base']['sources'][n]==h for n,h in v['controller_sources'].items()),
  'PTLA_RESOURCES_EXACT_ORIGINAL_QUALIFICATION_AND_SIX_SOURCES')
 return True


def raw_contract(member,rows):
 v=fact();raw=member('uncertainty-certificate.jsonl');lines=raw.splitlines(keepends=True)
 need(dict(rows=len(lines),**pin(raw))==v['raw_proof'] and len(rows)==174
  and [json.loads(r) for r in lines]==rows,'PTLA_RESOURCES_ENTIRE_RAW174_EQUALS_COMMITTED_SEED')
 return True


def verify(member,destination):
 return original_api().verify(member,destination)


def preserve(old,out,parent,rows,qualified):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);seed_contract(parent,rows,qualified)
 member=lambda n:(old/n).read_bytes();raw_contract(member,rows)
 return original_api().preserve(old,out)


def canary(old,out):
 from full_system_core import hosted
 hosted();return original_api().canary(Path(old),Path(out))
