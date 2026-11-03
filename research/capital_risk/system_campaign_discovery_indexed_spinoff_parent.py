"""Authenticate exact indexed diagnostic parents; never financial adoption."""
import ast
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_discovery_context import TAINT,digest
from system_campaign_parallel_discovery import compile_body
from system_campaign_anchor_proofs import proof_prefix_evidence,PROOF_STATUS
import system_campaign_discovery_suffix_parent as original
from system_campaign_discovery_suffix_replay import qualified_anchor_seeds
import system_campaign_factual_admit as crypto
import system_campaign_p02_close_diagnostics as stops

HERE=Path(__file__).parent
SPEC='system-campaign-discovery-indexed-spinoff-predecessors.json'
PRIOR='system-campaign-discovery-spinoff-request-001.json'
PRIOR_SHA='a06a3e3caf274775e214ee2805a27562198bb48abccff63d35207f464f534452'
OLD_REQUEST='system-campaign-discovery-suffix-request-001.json'
OLD_REQUEST_SHA='b5721050ff042d9be4dd343607625317f13c228a0e978afd321213f66318beb6'
ARMS=('P03','P05')
SELECTED={'P03':(13112303282,883,'2021-10-29','2021-11-01','29a09d12cee9c42a81a79d779dd4bc280cdbd93aa1399ff358b4f26c184cfd9a'),
 'P05':(13111846485,1175,'2022-09-30','2022-10-03','4ee01b2d263ee23728d6bfd459a9f4d933aec660ca29c579667589d0e8c62853')}

def retained_sources():
 need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'INDEXED_SPIN_EXACT_PUBLISHED431_REQUEST')
 value=json.loads((HERE/PRIOR).read_bytes())['sources']
 need(len(value)==431 and all(sha256_file(HERE/n)==h for n,h in value.items()),'INDEXED_SPIN_ALL431_RETAINED_BYTES')
 need(value['system_campaign_anchor_proofs.py']=='24f4c29ac2e4d5fe0392e86fb22cc24d00a8ec3493165fb98cbdbc21e3745193'
  and value['system_campaign_discovery_spinoff_deferral.py']=='b5f25544ed1ed987f7debe733f8e8480ec5f4b15c5b2a89530ec2d05cea94ee8',
  'INDEXED_SPIN_UNCHANGED_WRITER_AND_DEFERRAL')
 return value

def exact(module):
 value=retained_sources();raw=Path(module.__file__).read_bytes()
 need(hashlib.sha256(raw).hexdigest()==value[Path(module.__file__).name],'INDEXED_SPIN_EXACT_REUSED_MODULE')
 return raw

def specification(arm):
 need(arm in ARMS,'INDEXED_SPIN_ONLY_SELECTED_OWN_DIAGNOSTIC_PARENTS')
 value=json.loads((HERE/SPEC).read_bytes())['arms'][arm];artifact,count,day,next_day,cp=SELECTED[arm]
 old=original.specification(arm)
 need(value['schema']=='research.exact-indexed-diagnostic-spinoff-predecessor/1'
  and value['authority']==TAINT and value['financial_authority'] is False and value['arm']==arm
  and value['run_id']==41372098224 and value['head']=='c41861863d33c9f7ee2859dc4e9b4a8740bc924b'
  and value['artifact_id']==artifact and value['transitions']==count and value['selected_session']==day
  and value['next_session']==next_day and value['diagnostic_checkpoint_sha256']==cp
  and value['financial_strict_predecessor']==old['financial_strict_predecessor']
  and value['cumulative_expected_sessions']==old['cumulative_expected_sessions']
  and value['expected_remaining_sessions']==old['cumulative_expected_sessions']-count
  and value['strict_parent_outer_sha256']==old['strict_parent_outer_sha256']
  and value['input_sha256']==old['input_sha256']
  and value['source_sha256']==digest(old['financial_strict_predecessor']['base']['sources']),
  'INDEXED_SPIN_EXACT_RETAINED_STATE_SOURCE_INPUT_AND_DISTINCT_FINANCIAL_PARENT')
 return value

def read_checkpoint(path):return json.loads(gzip.decompress(Path(path).read_bytes()))

def indexed_seeds(root,saved,spec):
 """Only committed old index records plus its authenticated historical seed."""
 root=Path(root);old_root=root/'lineage/diagnostic-predecessor'
 old=original.specification(spec['arm']);old_path=old_root/old['diagnostic_checkpoint']
 need(sha256_file(old_path)==old['diagnostic_checkpoint_sha256']==saved['diagnostic_predecessor']['checkpoint_sha256'],
  'INDEXED_SPIN_EXACT_INITIAL_FLAT_EPOCH_CP')
 old_cp=original.validate_checkpoint(read_checkpoint(old_path),old)
 initial=qualified_anchor_seeds(old_root,old_cp,spec['source_sha256'])
 need(len(initial)==spec['initial_flat_seed_count'],'INDEXED_SPIN_EXACT_INITIAL_QUALIFIED_SEED_COUNT')
 commitment=saved['retained_anchor_qualifications']
 need(commitment==spec['retained_anchor_qualifications'] and saved['diagnostic_predecessor']==spec['old_diagnostic_reference'],
  'INDEXED_SPIN_EXACT_PARENT_INDEX_AND_PREDECESSOR_COMMITMENT')
 evidence=proof_prefix_evidence(root,commitment,seed_proofs=initial,predecessor=saved['diagnostic_predecessor'])
 need({k:v for k,v in evidence.items() if k!='committed_proofs'}==spec['old_index_evidence'],
  'INDEXED_SPIN_ALL_INDEX_TAIL_AND_ORPHAN_PROOF_BYTES_PRESERVED')
 anchors=original.verify_chain((root/'retained-anchor-events.jsonl').read_bytes(),saved['retained_source_anchors'],anchor=True)
 daily=[json.loads(line) for line in original.verify_prefix((root/'diagnostic-book/daily.jsonl').read_bytes(),saved['journals']['daily']).splitlines()]
 states={r['session']:r['state_sha256'] for r in daily}
 previous={daily[i]['session']:daily[i-1]['state_sha256'] for i in range(1,len(daily))}
 seeds=list(initial)
 for value in evidence['committed_proofs']:
  body=value['record'];proof=body['qualification']
  seeds.append(dict(proof,source_sha256=body['source_sha256'],input_sha256=body['input_sha256'],
   source_records=body['source_records'],source_records_sha256=body['source_records_sha256']))
 for proof in seeds:
  need(proof['status']==PROOF_STATUS and proof['financial_authority'] is False
   and proof['source_sha256']==spec['source_sha256'] and proof['input_sha256']==spec['input_sha256']
   and set(proof['security_ids'])==set(proof['source_records'])
   and proof['source_records_sha256']==digest(proof['source_records'])
   and states.get(proof['session'])==proof['next_state_sha256']
   and previous.get(proof['session'])==proof['prior_state_sha256'],
   'INDEXED_SPIN_ONLY_ACTUAL_COMMITTED_SOURCE_INPUT_PRIOR_AND_NEXT_STATE_QUALIFIED_SEED')
  for sid,record in proof['source_records'].items():
   matches=[r for r in anchors if r['session']==proof['session'] and r['security_id']==sid
    and r['prior_state_sha256']==proof['prior_state_sha256'] and r['source_anchor']==record]
   need(record['security_id']==sid and record['session']<proof['session'] and matches
    and all(r['source_sha256']==spec['source_sha256'] and r['input_sha256']==spec['input_sha256'] for r in matches),
    'INDEXED_SPIN_EXACT_COMMITTED_ANCHOR_USE_AND_HISTORICAL_RECORD')
 need(len(seeds)==spec['combined_committed_seed_count'] and digest(seeds)==spec['combined_committed_seed_sha256'],
  'INDEXED_SPIN_EXACT_COMBINED_AUTHENTICATED_SEED_COMMITMENT')
 # Older CPs retain their own committed index prefix and every later file/tail.
 for path in sorted((root/'diagnostic-book/retained-checkpoints').glob('*.json.gz')):
  cp=read_checkpoint(path)
  proof_prefix_evidence(root,cp['retained_anchor_qualifications'],seed_proofs=initial,predecessor=cp['diagnostic_predecessor'])
 return seeds,evidence

def stopped(value,entry,spec):
 fn,=[n for n in ast.parse(exact(stops)).body if isinstance(n,ast.FunctionDef) and n.name=='stopped']
 sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='/capital-system-factual-p02-']
 need(len(sites)==1,'INDEXED_SPIN_ONE_OLD_STOP_NAMESPACE_SITE');sites[0].value='/capital-system-diagnostic-suffix-'+spec['arm'].lower()+'-'
 sets=[n for n in ast.walk(fn) if isinstance(n,ast.Set) and all(isinstance(x,ast.Constant) for x in n.elts)
  and {ast.literal_eval(x) for x in n.elts}=={'/variant','/frozen','/driver','/out','/old'}]
 need(len(sets)==1,'INDEXED_SPIN_ONE_PREVIOUS_READONLY_MOUNT_SITE');sets[0].elts.append(ast.Constant('/previous'))
 cmd,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=="c['Cmd']"]
 cmd.comparators=[ast.parse(repr(['-B','-u','/driver/system_campaign_discovery_suffix_run.py','--arm',spec['arm'],
  '--spec','/out/spec.json','--request','/driver/'+OLD_REQUEST]),mode='eval').body]
 compile_body(fn,vars(stops))(value,entry['metadata'],'worker',str(spec['run_id']),OLD_REQUEST)
 need(value['Id']==entry['id'] and value['Name']==entry['name'],'INDEXED_SPIN_EXACT_OLD_ACTUAL_STOP_IDENTITY')

def validate_contents(root,spec,inventory=None):
 need(spec==specification(spec['arm']),'INDEXED_SPIN_EXACT_SELECTED_DESCRIPTOR')
 root=Path(root);expected=spec['full_inventory']
 need(digest(expected)==spec['inventory_sha256'] and len(expected)==spec['inventory_members']
  and (inventory is None or inventory==expected),'INDEXED_SPIN_COMPLETE_OLD_INVENTORY_IDENTITY')
 actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
 need(actual==set(expected),'INDEXED_SPIN_ALL_OLD_FILES_AND_LINEAGE_PRESENT')
 for name,entry in expected.items():
  path=root/name
  need(path.stat().st_size==entry['bytes'] and sha256_file(path)==entry['sha256'],'INDEXED_SPIN_COMPLETE_OLD_IMMUTABLE_BYTES:'+name)
 path=root/spec['diagnostic_checkpoint']
 need(path.stat().st_size==spec['checkpoint_bytes'] and sha256_file(path)==spec['diagnostic_checkpoint_sha256'],'INDEXED_SPIN_EXACT_CURRENT_GZIP')
 cp=original.validate_checkpoint(read_checkpoint(path),spec)
 need(cp['retained_anchor_qualifications']==spec['retained_anchor_qualifications']
  and cp['diagnostic_predecessor']==spec['old_diagnostic_reference'],'INDEXED_SPIN_VERSIONED_PARENT_NEVER_FLAT_OR_RESTARTED')
 for name,entry in cp['journals'].items():original.verify_prefix((root/'diagnostic-book'/(name+'.jsonl')).read_bytes(),entry,last=True)
 original.verify_chain((root/'discovery-events.jsonl').read_bytes(),cp['events'])
 original.verify_chain((root/'retained-anchor-events.jsonl').read_bytes(),cp['retained_source_anchors'],anchor=True)
 need(sha256_file(root/'source-bindings.json')==spec['source_binding_sha256'],'INDEXED_SPIN_EXACT_SAME515_SOURCE_BINDING')
 need(sha256_file(HERE/OLD_REQUEST)==OLD_REQUEST_SHA==spec['request_sha256'],'INDEXED_SPIN_EXACT_OLD_PUBLIC_RAW_REQUEST')
 model=json.loads((HERE/OLD_REQUEST).read_bytes());serialized=(json.dumps(model,sort_keys=True,indent=2)+'\n').encode()
 need((root/'request.json').read_bytes()==serialized and hashlib.sha256(serialized).hexdigest()==spec['private_request_sha256'],
  'INDEXED_SPIN_ALL_FIELDS_EXACT_ORIGINAL_WRITER_SERIALIZATION_NO_IDENTITY_EXCLUSION')
 need(json.loads((root/'spec.json').read_bytes())==original.specification(spec['arm']), 'INDEXED_SPIN_EXACT_PRIOR_SELECTED_SPEC')
 q=spec['reused_canonical_qualification'];need(sha256_file(root/q['path'])==q['sha256'],'INDEXED_SPIN_RETAINED_ORIGINAL_GATE_BYTES')
 proof=json.loads((root/q['path']).read_bytes())
 need(proof['status']=='QUALIFIED' and proof['synthetic_canonical_transitions']==3
  and proof['strict_parent_outer_sha256']==spec['strict_parent_outer_sha256'] and proof['actual_strict_checkpoint_rejection']
  and proof['original_runtime_hook_restored'] and not proof['actual_discovery_started'],'INDEXED_SPIN_REUSE_COMPLETED_ORIGINAL_GATE_ONLY')
 need(sha256_file(root/'worker.log')==spec['worker_log_sha256'],'INDEXED_SPIN_ORIGINAL_REFUSAL_LOG_BYTES_PRESERVED')
 for name,entry in spec['inspections'].items():stopped(json.loads((root/name).read_bytes()),entry,spec)
 indexed_seeds(root,cp,spec)
 return cp

def admission_tree():
 fn,=[n for n in ast.parse(exact(crypto)).body if isinstance(n,ast.FunctionDef) and n.name=='admit']
 boundary,=[i for i,n in enumerate(fn.body) if isinstance(n,ast.For) and ast.unparse(n.iter)=="spec['inspections'].items()"]
 fn.body=fn.body[:boundary]+ast.parse('validate_contents(dest,spec,inventory)\nreturn dest').body
 sets=[n for n in ast.walk(fn) if isinstance(n,ast.Set) and ast.unparse(n)=="{spec['receipt_name'], 'full-core-staging.json', asset['name']}"]
 need(len(sets)==1,'INDEXED_SPIN_ONE_EXACT_PUBLIC_ZIP_SET')
 sets[0].elts.extend([ast.Constant('export-qualification.json'),ast.Constant('phase.json')])
 container,=[n for n in fn.body if isinstance(n,ast.With) and ast.unparse(n.items[0].context_expr)=='zipfile.ZipFile(archive)']
 at,=[i for i,n in enumerate(container.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='(header, tag)']
 container.body[at:at]=ast.parse("""
need(r['status']==spec['source_receipt_status']=='DIAGNOSTIC_SUFFIX_REFUSED_KNOWN_STOP'
 and r['encrypted_output_exported'] is True and r['financial_authority'] is False
 and r['account_performance_computed'] is False and r['worker']==spec['inspections']['worker-inspect.json']['metadata'],
 'INDEXED_SPIN_EXACT_ORIGINAL_KNOWN_FAILED_STOP_EXPORT_NOT_RELABELLED')
need(hashlib.sha256(z.read('export-qualification.json')).hexdigest()==spec['public_probe_sha256']
 and hashlib.sha256(z.read('phase.json')).hexdigest()==spec['public_phase_sha256'],
 'INDEXED_SPIN_ORIGINAL_ACTUAL_MARKER_AND_SAFE_PHASE_BYTES')
""").body
 return ast.fix_missing_locations(fn)

def admit(spec,root,key):
 need(spec==specification(spec['arm']),'INDEXED_SPIN_EXACT_PUBLIC_PARENT_SELECTION')
 return compile_body(admission_tree(),dict(vars(crypto),validate_contents=validate_contents))(spec,root,key,max_zip_bytes=1024**3)
