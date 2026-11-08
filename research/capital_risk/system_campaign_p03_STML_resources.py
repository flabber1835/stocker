"""Actual606 history, literal152 seed and all105 referenced immutable assets."""
import json,tempfile
from pathlib import Path,PurePosixPath
from system_campaign_facts import sha
from full_system_benchmark import need
from system_campaign_bounded_sensor_origin_v2 import exact
import system_campaign_p03_STML_source as source
HERE=Path(__file__).parent
FACT='P03-STML-real606-retained152-resource-fact.json'
FACT_SHA='3a910a54b1051fe43a63866353aac13ac478cb3acc5ad13e7ba524622f938574'
PREFIX='bounded-successors/'+source.ROOT+'/origin'
RECEIPT=PREFIX+'/resource-preservation.json'
CANARY=PREFIX+'/dependency-canary.json'

def pin(raw):return dict(bytes=len(raw),sha256=sha(raw))

def fact():
 raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'STML_RESOURCES_EXACT_AUTHENTIC_FIN352_FACT')
 v=json.loads(raw)
 need(v['root_admission_sha256']==source.ROOT and v['financial_authority'] is v['canonical_runtime_executed'] is v['actual_neutral20_known'] is False
  and (len(v['actual_manifest']),len(v['resources']),len(v['actual_resource_trace']['resource_reads']))==(242,105,67)
  and (v['raw_proof']['rows'],v['committed_proof']['rows'])==(159,152),'STML_RESOURCES_COMPLETE159_RETAIN152_EXCLUDE7')
 return v

def closure(read):
 v=fact();items={}
 for name,e in v['resources'].items():
  dest=e['destination'];p=PurePosixPath(dest)
  need(not p.is_absolute() and p.as_posix()==dest and '..' not in p.parts and '\\' not in dest and ':' not in dest
   and not dest.startswith(('stopped-review/','parent-preflight/','retained-proof-admission/'))
   and dest not in ('book/checkpoint.json.gz','branch-controller-qualification.json','uncertainty-certificate.jsonl','spec.json','request.json'),
   'STML_RESOURCES_NO_CURRENT_CONTROL_OR_OLD_REVIEW_OUTPUT_COLLISION')
  expected={k:e[k] for k in ('bytes','sha256')};need(pin(read(name))==expected,'STML_RESOURCE_AUTHENTIC_BYTES:'+name)
  need(dest not in items,'STML_RESOURCES_DISTINCT_DESTINATIONS');items[dest]=dict(source=name,**expected)
 need(set(v['actual_resource_trace']['resource_reads'])<=set(v['resources']),'STML_RESOURCES_ALL_ACTUAL_READS_PRESERVED')
 return dict(schema='research.P03-STML-resource-preservation/1',root_admission_sha256=source.ROOT,resources=items,
  financial_checkpoint_replaced=False,financial_sessions_advanced=0)

def verify(old_read,new_read):
 value=closure(old_read)
 for n,e in value['resources'].items():need(pin(new_read(n))=={k:e[k] for k in ('bytes','sha256')},'STML_RESOURCE_PRESERVED:'+n)
 return value

def preserve(old,out):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out);value=closure(lambda n:(old/n).read_bytes())
 for n,e in value['resources'].items():exact(out/n,(old/e['source']).read_bytes())
 verify(lambda n:(old/n).read_bytes(),lambda n:(out/n).read_bytes());exact(out/RECEIPT,source.encoded(value));return value

def canary(old,out):
 from full_system_core import hosted
 hosted();old,out=Path(old),Path(out)
 with tempfile.TemporaryDirectory(prefix='stml-dependency-copy-',dir=out) as owned:
  dest=Path(owned);value=preserve(old,dest)
 need(not Path(owned).exists(),'STML_RESOURCE_CANARY_OWNED_COPY_REMOVAL_OBSERVED')
 result=dict(passed=True,closure=value,actual_copy_verified=True,owned_copy_removed=True,financial_sessions_advanced=0)
 exact(out/CANARY,source.encoded(result));return result

def seed_contract(parent,rows,qualified):
 from system_campaign_financial_partial import root_spec
 v=fact();source.parent_contract(parent,root_spec('P03',source.ROOT))
 raw=b''.join(json.dumps(r,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for r in rows)
 need(dict(rows=len(rows),**pin(raw))==v['committed_proof'] and rows[-1]==v['last_committed_proof']
  and rows[-1]['session']==parent['source_cursor'] and rows[-1]['next_state_sha256']==parent['run']['state_sha256']
  and pin(qualified)==v['prior_qualification'],'STML_RESOURCES_WHOLE_EXACT152_SEED_AND_ORIGINAL_QUALIFICATION')
 return v['committed_proof']
