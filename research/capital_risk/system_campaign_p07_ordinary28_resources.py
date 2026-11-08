"""All245 historical assets and literal972 seed; hosted copying only."""
import json,tempfile
from pathlib import Path,PurePosixPath
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import exact
import system_campaign_dependencies as dependencies
import system_campaign_p07_ordinary28_data as data
HERE=Path(__file__).parent
FACT='P07-ordinary28-real1426-retained972-resource-fact.json'
FACT_SHA='fa6384cc7abb5f9580e7490fc2c49f36047b57f8e22379eceb1426702719430a'
PREFIX='ordinary-successors/'+data.ROOT
RECEIPT=PREFIX+'/resource-preservation.json'
CANARY=PREFIX+'/resource-copy-canary.json'
QUALIFIED=PREFIX+'/origin/original-controller-qualification.json'
RAW=PREFIX+'/origin/entire-original-proof.jsonl'
pin=dependencies.pin

def spec():
 from system_campaign_financial_partial import root_spec
 return root_spec('P07',data.ROOT)

def fact():
 raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'ORDINARY28_RESOURCES_EXACT_AUTHENTIC1426_FACT')
 v=json.loads(raw);target=spec()
 need(v['root_admission_sha256']==data.ROOT and v['parent_transport']=={k:x for k,x in target.items() if k not in ('root_admission','root_admission_sha256')}
  and v['requirements']==len(v['resources'])==245 and v['logical_bytes']==430989588
  and (v['raw_proof']['rows'],v['committed_proof']['rows'])==(987,972) and len(v['excluded_tail_sessions'])==15
  and len(v['original216_destinations'])==216 and len(v['actual_full27_read_trace']['reads'])==103
  and len(v['current_owned_book_reads'])==28 and len(v['historical_archive_resolutions'])==11
  and v['financial_authority']is v['financial_profile_ready']is v['local_canonical_runtime_executed']is v['actual_neutral28_known']is v['financial_book_staged']is False,
  'ORDINARY28_RESOURCES_COMPLETE27_LITERAL972_NO_HOSTED28_CLAIM')
 return v

def declarations(v):
 declared={}
 for name,item in v['resources'].items():
  for n in (name,item['source_path'],item['authenticated_member']):
   p=PurePosixPath(n)
   need(n and not p.is_absolute() and p.as_posix()==n and '..'not in p.parts and '\\'not in n and ':'not in n,
    'ORDINARY28_RESOURCES_SAFE_AUTHENTIC_NAMES')
  need(item['archive_role']in v['authenticated_manifests'] and {k:item[k] for k in ('bytes','sha256')}==v['authenticated_manifests'][item['archive_role']][item['authenticated_member']],
   'ORDINARY28_RESOURCES_EXACT_DISTINCT_ORIGINAL_MANIFEST_MEMBER')
  need(name not in ('book/checkpoint.json.gz','request.json','spec.json','uncertainty-certificate.jsonl','source-bindings.json')
   and not name.startswith(('stopped-review/','parent-preflight/','lineage/')),
   'ORDINARY28_RESOURCES_NO_CURRENT_BOOK_OR_REVIEW_ALIAS')
  archive=name.startswith('book/pre-event/')
  dependencies.Requirement(path=name,role='pre_event_archive' if archive else 'historical_asset',bytes=item['bytes'],sha256=item['sha256'])
  if not archive:declared[name]={k:item[k] for k in ('bytes','sha256')}
 need(set(v['original216_destinations'])<=set(v['resources']),'ORDINARY28_RESOURCES_ALL_ORIGINAL216_PRESERVED')
 july={f'p07-vivo-ordinary25-observation/actual-future-event-{day}.json' for day in ('2023-07-11','2023-07-28')}
 need(july<=set(v['resources']) and all(v['resources'][n]['archive_role']=='prior231' and v['resources'][n]['authenticated_member']==n for n in july),
  'ORDINARY28_RESOURCES_BOTH_AUTHENTIC_JULY_OBSERVER_RECORDS_REQUIRED')
 need({r['actual'] for r in v['historical_archive_resolutions']}=={n for n in v['resources'] if n.startswith('book/pre-event/')},'ORDINARY28_RESOURCES_ALL11_ACTUAL_EVENT_ARCHIVES')
 reads=set(v['actual_full27_read_trace']['reads']);owned=set(v['current_owned_book_reads'])
 need(owned<=reads and reads-owned<=set(v['resources']) and all(n.startswith('book/') and not n.startswith('book/pre-event/') for n in owned),
  'ORDINARY28_RESOURCES_ALL103_READS_ACCOUNTED_WITHOUT_SECOND_BOOK')
 return declared

def closure(member):
 v=fact();declared=declarations(v)
 result=dependencies.build(declared,v['historical_archive_resolutions'],lambda n:member(v['resources'][n]['source_path']))
 need(len(result['requirements'])==v['requirements'] and sum(x['bytes'] for x in result['requirements'])==v['logical_bytes'],
  'ORDINARY28_RESOURCES_COMPLETE245_AUTHENTIC_BYTES')
 return result

def owned_book_contract(member,parent):
 data.parent_contract(parent,spec());v=fact()
 for n,p in v['current_owned_book_reads'].items():need(pin(member(n))==p,'ORDINARY28_RESOURCES_GENUINE_OWNED_BOOK_READ:'+n)
 return True

def seed_contract(parent,rows,qualified):
 data.parent_contract(parent,spec());v=fact();raw=b''.join(json.dumps(r,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for r in rows)
 need(dict(rows=len(rows),**pin(raw))==v['committed_proof'] and len(rows)==972
  and rows[-1]==v['last_committed_proof'] and rows[-1]['session']==parent['source_cursor']
  and rows[-1]['next_state_sha256']==parent['run']['state_sha256'] and rows[-1]['input_sha256']==parent['run']['input_sha256'],
  'ORDINARY28_RESOURCES_LITERAL972_NO_SEPTEMBER_TAIL_SEEDED')
 q=json.loads(qualified)
 need(pin(qualified)=={k:v['resources'][QUALIFIED][k] for k in ('bytes','sha256')} and q['passed']is True
  and q['exact_controller_sources']==v['controller_sources'] and len(v['controller_sources'])==6
  and all(parent['base']['sources'][n]==p for n,p in v['controller_sources'].items()),
  'ORDINARY28_RESOURCES_ORIGINAL_CONTROLLER_QUALIFICATION_AND_SIX_SOURCES')
 return True

def raw_contract(member,rows):
 v=fact();raw=member('uncertainty-certificate.jsonl');lines=raw.splitlines(keepends=True)
 need(dict(rows=len(lines),**pin(raw))==v['raw_proof'] and len(rows)==972
  and [json.loads(x)['session'] for x in lines[972:]]==v['excluded_tail_sessions']
  and all(d>v['parent_transport']['selected_session'] for d in v['excluded_tail_sessions']),
  'ORDINARY28_RESOURCES_ENTIRE987_PRESERVED_ONLY972_COMMITTED')
 return True

def verify(member,destination):
 v=fact();manifest=closure(member)
 dependencies.verify(manifest,declarations(v),v['historical_archive_resolutions'],lambda n:member(v['resources'][n]['source_path']),destination)
 return manifest

def preserve(old,out,parent,rows,qualified):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);member=lambda n:(old/n).read_bytes()
 seed_contract(parent,rows,qualified);raw_contract(member,rows);owned_book_contract(member,parent);v=fact();manifest=closure(member)
 dependencies.copy_checked(manifest,lambda n:member(v['resources'][n]['source_path']),lambda n,b:exact(out/n,b))
 need(verify(member,lambda n:(out/n).read_bytes())==manifest,'ORDINARY28_RESOURCES_ACTUAL_SHARED_COPIER_AND_VERIFIER')
 exact(out/RECEIPT,data.encoded(manifest));return manifest

def canary(old,out):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);member=lambda n:(old/n).read_bytes();v=fact();manifest=closure(member)
 with tempfile.TemporaryDirectory(prefix='p07-ordinary28-source-copy-',dir=out) as owned:
  root=Path(owned)
  dependencies.copy_checked(manifest,lambda n:member(v['resources'][n]['source_path']),lambda n,b:exact(root/n,b))
  need(verify(member,lambda n:(root/n).read_bytes())==manifest,'ORDINARY28_RESOURCES_PRIVATE_CANARY_COMPLETE245')
 need(not Path(owned).exists(),'ORDINARY28_RESOURCES_PRIVATE_CANARY_REMOVAL_OBSERVED')
 result=dict(passed=True,requirements=v['requirements'],logical_bytes=v['logical_bytes'],complete_shared_copier_and_verifier=True,copy_removal_observed=True,financial_sessions_advanced=0,actual_neutral28_known=False)
 exact(out/CANARY,data.encoded(result));return result

def source_names():return (Path(__file__).name,FACT,*data.source_names())
