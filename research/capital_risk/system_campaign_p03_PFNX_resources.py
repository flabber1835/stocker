"""Entire151 historical assets and committed217 seed; hosted copying only."""
import json
from pathlib import Path,PurePosixPath
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha,digest
import system_campaign_p03_STML_resources as original
import system_campaign_p03_PFNX_source as source
HERE=Path(__file__).parent
FACT='P03-PFNX-real671-retained217-resource-fact.json'
FACT_SHA='7a3c04c67717c3cf449eb46fe4a612f46e7b7661410ab151533f0b535481e525'
ORIGINAL_SHA='783f575249cf2cf1803d7d2f17f9ac97ba8e08ddfe28624f8c142ee700d989b9'
PREFIX='bounded-successors/'+source.ROOT
QUALIFIED=PREFIX+'/origin/original-controller-qualification.json'
RAW=PREFIX+'/origin/entire-original-proof.jsonl'
RECEIPT=PREFIX+'/resource-preservation.json'
CANARY=PREFIX+'/resource-copy-canary.json'
pin=original.pin

def spec():
 from system_campaign_financial_partial import root_spec
 return root_spec('P03',source.ROOT)

def fact():
 raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'PFNX_RESOURCES_EXACT_AUTHENTIC671_FACT')
 value=json.loads(raw);target=spec()
 need(value['root_admission_sha256']==source.ROOT and value['parent_transport']=={k:x for k,x in target.items() if k not in ('root_admission','root_admission_sha256')}
  and value['requirements']==len(value['resources'])==151 and value['logical_bytes']==85321622
  and (value['raw_proof']['rows'],value['committed_proof']['rows'])==(237,217) and len(value['excluded_tail_sessions'])==20
  and len(value['original127_destinations'])==127 and len(value['historical_archive_resolutions'])==4
  and len(value['actual_full21_DATA_trace']['reads'])==158 and len(value['current_owned_book_reads'])==22
  and value['actual_full21_DATA_trace']['passed']is value['actual_full21_DATA_trace']['whole_independently_admitted_full21_DATA_reader']is True
  and value['actual_full21_DATA_trace']['independent_reader_sha256']==target['root_admission']['independent_branch_reader_sha256']
  and value['financial_authority']is value['financial_profile_ready']is value['local_canonical_runtime_executed']is value['financial_book_staged']is value['actual_neutral22_known']is value['selected_checkpoint_replaced']is False,
  'PFNX_RESOURCES_COMPLETE_FULL21_AND_LITERAL217_WITHOUT_HOSTED_BOUNDARY_CLAIM')
 return value

def declarations(value):
 sources=set();old=set(value['original127_destinations'])
 for dest,item in value['resources'].items():
  for name in (dest,item['source_path'],item['authenticated_member']):
   path=PurePosixPath(name)
   need(name and not path.is_absolute() and path.as_posix()==name and '..'not in path.parts and '\\'not in name and ':'not in name,
    'PFNX_RESOURCES_SAFE_ORIGINAL_MEMBER_AND_DESTINATION')
  need(item['source_path']==item['authenticated_member'] and {k:item[k] for k in ('bytes','sha256')}==value['actual_manifest'][item['authenticated_member']],
   'PFNX_RESOURCES_EXACT_ORIGINAL_MANIFEST_MEMBER')
  need(dest not in ('book/checkpoint.json.gz','branch-controller-qualification.json','uncertainty-certificate.jsonl','request.json','spec.json','source-bindings.json')
   and not dest.startswith(('stopped-review/','parent-preflight/'))
   and (not dest.startswith('book/') or dest.startswith('book/pre-event/')
    or dest=='book/predecessor-checkpoints/50529edab057a7f1a835f3ebb6e947efc5b4f10b64ca941d12f212cd709d1f8a.json.gz' and dest in old)
   and (not dest.endswith('actual-future-event-refusal.json') or '/origin/diagnostics/'in dest),
   'PFNX_RESOURCES_NO_ACTIVE_BOOK_CONTROL_OR_REFUSAL_WRITER_COLLISION')
  need(type(item['bytes'])is int and (item['bytes']>0 or dest in old and item['bytes']==0 and item['sha256']==sha(b'')),
   'PFNX_RESOURCES_ONLY_ORIGINAL_HISTORICAL_EMPTY_ASSET')
  need(item['source_path']not in sources,'PFNX_RESOURCES_ONE_ORIGINAL_SOURCE_PER_DESTINATION');sources.add(item['source_path'])
 owned=set(value['current_owned_book_reads']);reads=set(value['actual_full21_DATA_trace']['reads'])
 need(old<=set(value['resources']) and owned<=reads and reads-owned<=sources
  and all(n=='book/watch.jsonl' or n=='book/checkpoint.json.gz' or n.startswith('book/repairs/') for n in owned),
  'PFNX_RESOURCES_ALL127_OLD_ASSETS_AND158_READS_WITHOUT_SECOND_BOOK')
 need({v['actual'] for v in value['historical_archive_resolutions']}=={n for n in value['resources'] if n.startswith('book/pre-event/')},
  'PFNX_RESOURCES_ALL_FOUR_GENUINE_PRE_EVENT_ARCHIVES')
 return sources

def original_api():
 need(sha(Path(original.__file__).read_bytes())==ORIGINAL_SHA,'PFNX_RESOURCES_WHOLE_ORIGINAL_STML_RESOURCE_IMPLEMENTATION')
 value=fact();declarations(value)
 adapted=dict(resources={item['source_path']:dict(destination=dest,bytes=item['bytes'],sha256=item['sha256']) for dest,item in value['resources'].items()},
  actual_resource_trace=dict(resource_reads=sorted(set(value['actual_full21_DATA_trace']['reads'])-set(value['current_owned_book_reads']))))
 need(len(adapted['resources'])==151,'PFNX_RESOURCES_COMPLETE_DISTINCT151_INPUTS')
 scope=dict(vars(original),fact=lambda:adapted,source=source,RECEIPT=RECEIPT,CANARY=CANARY)
 for name in ('closure','verify','preserve','canary'):
  fn=getattr(original,name);need(fn.__closure__ is None,'PFNX_RESOURCES_WHOLE_CLOSED_ORIGINAL_FUNCTION:'+name)
  scope[name]=FunctionType(fn.__code__,scope,fn.__name__,fn.__defaults__)
 return SimpleNamespace(**{n:scope[n] for n in ('closure','verify','preserve','canary')})

def closure(member):
 value=original_api().closure(member)
 need(len(value['resources'])==151 and sum(x['bytes'] for x in value['resources'].values())==85321622,'PFNX_RESOURCES_COMPLETE151_CLOSURE')
 return value

def verify(member,destination):return original_api().verify(member,destination)

def parent_contract(parent,target):
 from system_campaign_full_history_successor import current_commitments
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(target);current_commitments(parent,target,lambda b,r:digest(dict(base=b,repairs=r)))
 need(target==spec() and parent['repairs']==target['repairs'] and parent['journals']==target['journals']
  and (parent['completed'],parent['source_cursor'],len(parent['repairs']))==(671,'2020-08-31',21),
  'PFNX_RESOURCES_GENUINE_COMPLETE671_FULL21_ADMITTED_PARENT')
 return True

def seed_contract(parent,rows,qualified):
 value=fact();parent_contract(parent,spec());raw=b''.join(json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for row in rows)
 need(dict(rows=len(rows),**pin(raw))==value['committed_proof'] and len(rows)==217 and rows[-1]==value['last_committed_proof']
  and rows[-1]['session']==parent['source_cursor'] and rows[-1]['next_state_sha256']==parent['run']['state_sha256']
  and rows[-1]['input_sha256']==parent['run']['input_sha256'],'PFNX_RESOURCES_EXACT_LITERAL217_COMMITTED_SEED_AND_CURRENT_STATE')
 q=json.loads(qualified)
 need(pin(qualified)=={k:value['resources'][QUALIFIED][k] for k in ('bytes','sha256')} and q['passed']is True
  and q['exact_controller_sources']==value['controller_sources'] and len(value['controller_sources'])==6
  and all(parent['base']['sources'][n]==h for n,h in value['controller_sources'].items()),
  'PFNX_RESOURCES_ORIGINAL_POSITIVE_QUALIFICATION_AND_SIX_CONTROLLERS')
 return value['committed_proof']

def raw_contract(member,rows):
 value=fact();raw=member('uncertainty-certificate.jsonl');lines=raw.splitlines(keepends=True);tail=[json.loads(v) for v in lines[217:]]
 need(dict(rows=len(lines),**pin(raw))==value['raw_proof'] and len(rows)==217
  and [json.loads(v) for v in lines[:217]]==rows and len(tail)==20
  and [v['session'] for v in tail]==value['excluded_tail_sessions'] and all(v['session']>value['last_committed_proof']['session'] for v in tail),
  'PFNX_RESOURCES_PRESERVE_ALL237_RAW_AND_EXCLUDE20_DIAGNOSTICS_FROM217')
 return True

def preserve(old,out,parent,rows,qualified):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);seed_contract(parent,rows,qualified);raw_contract(lambda n:(old/n).read_bytes(),rows)
 return original_api().preserve(old,out)

def canary(old,out):
 from full_system_core import hosted
 hosted();return original_api().canary(Path(old),Path(out))

def source_names():return (Path(__file__).name,FACT,Path(original.__file__).name,*source.source_names())
