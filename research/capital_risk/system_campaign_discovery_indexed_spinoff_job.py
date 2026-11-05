"""One bounded offline VM per exact P03/P05 indexed diagnostic successor."""
import argparse
import ast
from copy import deepcopy
import json
import os
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from probe import check_context
from system_campaign_parallel_discovery import compile_body
from ephemeral_runner_capacity import validate_prepared_receipt
from system_campaign_discovery_indexed_spinoff_parent import (HERE,SPEC,PRIOR,PRIOR_SHA,ARMS,
 retained_sources,exact,specification,admit)
from system_campaign_discovery_indexed_spinoff_run import REQUEST
import system_campaign_discovery_suffix_job as original
import system_campaign_discovery_spinoff_job as previous

CAPACITY='ephemeral_runner_capacity.py'
CAPACITY_SHA='c7e90aa846dae28823d4be6b2ce9fa3092ab48e8346dcf21adb8d8fd7c6e3379'
NEW=(SPEC,'system_campaign_discovery_indexed_spinoff_parent.py','system_campaign_discovery_indexed_spinoff_replay.py',
 'system_campaign_discovery_indexed_spinoff_run.py','system_campaign_discovery_indexed_spinoff_job.py',
 'system_campaign_discovery_indexed_spinoff_probe.py',CAPACITY)
SOURCES=tuple(dict.fromkeys((*json.loads((HERE/PRIOR).read_bytes())['sources'],PRIOR,*NEW)))

def expected_request():
 retained_sources();old=previous.expected_request()
 need(len(old['sources'])==431 and sha256_file(HERE/CAPACITY)==CAPACITY_SHA,'INDEXED_SPIN_QUALIFIED431_AND_EXACT_CAPACITY_HELPER')
 specs={arm:specification(arm) for arm in ARMS};value=deepcopy(old)
 value.update(schema='research.exact-indexed-diagnostic-spinoff-suffix-request/1',arms=list(ARMS),prior431_request_sha256=PRIOR_SHA,
  predecessor_files={SPEC:sha256_file(HERE/SPEC)},diagnostic_predecessors={arm:dict(artifact_id=s['artifact_id'],
   checkpoint_sha256=s['diagnostic_checkpoint_sha256'],transitions=s['transitions'],source_cursor=s['selected_session']) for arm,s in specs.items()},
  indexed_anchor_proof_successor=True,old_writer_bytes_unchanged=True,committed_indexed_and_historical_seeds_only=True,
  seed_counts={arm:s['combined_committed_seed_count'] for arm,s in specs.items()},
  seed_sha256={arm:s['combined_committed_seed_sha256'] for arm,s in specs.items()},
  all_old_index_proof_files_and_tails_preserved=True,all_old_lineage_epochs_preserved_flat_once=True,
  unvalued_claim_registry_reconstructed_and_checkpoint_committed=True,parent_exit_never_erases_unvalued_claim=True,
  actual_first_affected_original_refusal_and_next_transition_postconditions_required=True,
  capacity_preparation_required=True,capacity_before_encrypted_staging=True,capacity_source_file=CAPACITY,
  capacity_source_sha256=CAPACITY_SHA,capacity_step_timeout_minutes=5,staging_timeout_minutes=8,
  orchestration_timeout_minutes=335,job_timeout_minutes=360,
  sources={n:sha256_file(HERE/n) for n in SOURCES})
 return value

def entrypoint(arm):
 need(arm in ARMS,'INDEXED_SPIN_ONLY_EXACT_SELECTED_ENTRYPOINT')
 return ['-B','-u','/driver/system_campaign_discovery_indexed_spinoff_run.py','--arm',arm,
  '--spec','/out/spec.json','--request','/driver/'+REQUEST]

def method(name,namespace):
 fn,=[deepcopy(n) for n in ast.parse(exact(original)).body if isinstance(n,ast.FunctionDef) and n.name==name]
 if name=='inspect':
  sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value==r'capital-system-diagnostic-suffix-p(?:03|05|06|07)-worker-[0-9]+-1']
  need(len(sites)==1,'INDEXED_SPIN_ONE_WORKER_INSPECTION_NAMESPACE_SITE')
  sites[0].value=r'capital-system-diagnostic-indexed-spin-p(?:03|05)-worker-[0-9]+-1'
  arms=[n for n in ast.walk(fn) if isinstance(n,ast.Subscript) and ast.unparse(n)=="name.split('-')[4]"]
  need(len(arms)==1,'INDEXED_SPIN_ONE_EXACT_INSPECTION_ARM_COMPONENT');arms[0].slice=ast.Constant(5)
 elif name=='main':
  sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='capital-system-diagnostic-suffix-']
  need(len(sites)==1,'INDEXED_SPIN_ONE_WORKER_LAUNCH_NAMESPACE_SITE');sites[0].value='capital-system-diagnostic-indexed-spin-'
 return compile_body(fn,dict(vars(original),**namespace))

def inspect(name,identity=None):return method('inspect',dict(entrypoint=entrypoint))(name,identity)
def worker_command(name,arm,source,frozen,out,old,previous):
 return method('worker_command',dict(entrypoint=entrypoint))(name,arm,source,frozen,out,old,previous)

def main(args):
 check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','INDEXED_SPIN_NO_BLIND_RERUN')
 need(args.capacity.resolve()==(args.output.parent/'ephemeral-runner-capacity.json').resolve(),
  'INDEXED_SPIN_EXACT_PRESTAGING_CAPACITY_RECEIPT_PATH')
 validate_prepared_receipt(json.loads(args.capacity.read_bytes()),head=os.environ['GITHUB_SHA'],
  run_id=os.environ['GITHUB_RUN_ID'],source_sha256=CAPACITY_SHA)
 return method('main',dict(SELECTED_ARMS=ARMS,expected_request=expected_request,specification=specification,
  admit_diagnostic=admit,worker_command=worker_command,inspect=inspect))(args)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--arm',choices=ARMS,required=True)
 for name in ('request','staging','capacity','output'):p.add_argument('--'+name,type=Path,required=True)
 main(p.parse_args())
