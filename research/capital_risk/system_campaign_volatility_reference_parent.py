"""Authenticate immutable completed FAST qualification, never admit a book."""
import ast,gzip,json
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_facts import digest
from system_campaign_parallel_discovery import compile_body
from system_campaign_discovery_context import TAINT
import system_campaign_factual_admit as crypto
import system_campaign_p02_close_diagnostics as stops

HERE=Path(__file__).parent
SPEC='system-campaign-volatility-fast-predecessors-001.json'
PRIOR='system-campaign-volatility-discovery-request-002.json'
PRIOR_SHA='40774539921540348cf90cff4b95c81d08ab5ec1f0e6b028efaf1167cc93e4e0'


def specification(arm):
    need(arm in ('P10','P11'),'V_REFERENCE_ONLY_OWN_V_ARM')
    value=json.loads((HERE/SPEC).read_bytes())
    need(value['run_id']==41362963470 and value['head']=='5ff2a080af04094416e27103ec9195bd6762eec8'
         and value['authority']==TAINT and value['financial_authority'] is False,'V_REFERENCE_EXACT_FAST_SOURCE')
    return value['arms'][arm]


def exact_source(module):
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'V_REFERENCE_EXACT408_REQUEST')
    raw=Path(module.__file__).read_bytes()
    need(sha256_file(Path(module.__file__))==json.loads((HERE/PRIOR).read_bytes())['sources'][Path(module.__file__).name],
         'V_REFERENCE_ORIGINAL_CRYPTO_AND_STOP_IMPLEMENTATION')
    return raw


def admission_tree():
    fn,=[n for n in ast.parse(exact_source(crypto)).body if isinstance(n,ast.FunctionDef) and n.name=='admit']
    ends=[i for i,n in enumerate(fn.body) if isinstance(n,ast.For) and ast.unparse(n.target)=='(n, e)'
          and ast.unparse(n.iter)=="spec['inspections'].items()"]
    need(len(ends)==1,'V_REFERENCE_ONE_BOUNDARY_BEFORE_FINANCIAL_ADMISSION')
    fn.body=fn.body[:ends[0]]+ast.parse('validate_fast(spec, inventory, dest)\nreturn dest').body
    sets=[n for n in ast.walk(fn) if isinstance(n,ast.Set)
          and ast.unparse(n)=="{spec['receipt_name'], 'full-core-staging.json', asset['name']}"]
    need(len(sets)==1,'V_REFERENCE_ONE_PUBLIC_PROBE_MEMBER_ADDITION')
    sets[0].elts.append(ast.Constant('export-qualification.json'))
    # The allowlisted probe is public metadata and hash-bound before plaintext parsing.
    container,=[n for n in fn.body if isinstance(n,ast.With)
                and ast.unparse(n.items[0].context_expr)=='zipfile.ZipFile(archive)']
    auth=next(i for i,n in enumerate(container.body) if isinstance(n,ast.Assign)
              and ast.unparse(n.targets[0])=='(header, tag)')
    container.body[auth:auth]=ast.parse("need(sha256_file_from_bytes(z.read('export-qualification.json'))==spec['public_probe_sha256'], 'V_REFERENCE_OLD_EXPORT_PROBE_BYTES')").body
    return ast.fix_missing_locations(fn)


def old_stopped(value,spec):
    fn,=[n for n in ast.parse(exact_source(stops)).body if isinstance(n,ast.FunctionDef) and n.name=='stopped']
    names=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='/capital-system-factual-p02-']
    need(len(names)==1,'V_REFERENCE_ONE_OLD_STOP_NAMESPACE')
    names[0].value='/capital-system-parallel-discovery-'+spec['arm'].lower()+'-'
    cmd,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=="c['Cmd']"]
    cmd.comparators=[ast.parse(repr(['-B','-u','/driver/system_campaign_volatility_discovery_run_v2.py',
        '--mode','qualify','--arm',spec['arm'],'--spec','/out/spec.json']),mode='eval').body]
    compile_body(fn,vars(stops))(value,spec['qualification_worker'],'qualify',str(spec['run_id']),PRIOR)
    need(value['Id']==spec['inspection']['id'] and value['Name']==spec['inspection']['name']
         and value['State']['ExitCode']==137 and not value['State']['OOMKilled'],
         'V_REFERENCE_RETAINED_NONZERO_QUALIFIER_NEVER_RELABELLED')


def validate_fast(spec,inventory,dest):
    need(spec==specification(spec['arm']) and len(inventory)==spec['inventory_members']==24
         and digest(inventory)==spec['inventory_sha256']
         and sum(v['bytes'] for v in inventory.values())<32*1024**2,'V_REFERENCE_EXACT_COMPLETE_FAST_INVENTORY')
    need(not any(n.startswith('diagnostic-book/') for n in inventory)
         and 'qualification/reference/actual-runtime-path.json.gz' not in inventory
         and 'qualification/discovery-canonical-qualification.json' not in inventory,
         'V_REFERENCE_REUSES_ONLY_INCOMPLETE_QUALIFICATION_NO_DIAGNOSTIC_STATE')
    dest=Path(dest)
    need(sha256_file(dest/'source-bindings.json')==spec['source_binding_sha256']
         and sha256_file(dest/'qualification/worker-inspect.json')==spec['inspection']['sha256'],
         'V_REFERENCE_EXACT_SOURCE_AND_ACTUAL_OLD_STOP_BYTES')
    old_stopped(json.loads((dest/'qualification/worker-inspect.json').read_bytes()),spec)
    for name,key in [('actual-runtime-path.json.gz','actual_fast_path'),('discovery-canonical-qualification.json','actual_fast_proof')]:
        path=dest/'qualification/fast'/name;entry=spec[key]
        need(path.stat().st_size==entry['bytes'] and sha256_file(path)==entry['sha256'],'V_REFERENCE_ACTUAL_FAST_BYTES')
    path=json.loads(gzip.decompress((dest/'qualification/fast/actual-runtime-path.json.gz').read_bytes()))
    proof=json.loads((dest/'qualification/fast/discovery-canonical-qualification.json').read_bytes())
    need(len(path)==3 and proof['synthetic_canonical_transitions']==3 and proof['status']=='QUALIFIED'
         and proof['strict_parent_outer_sha256']==spec['strict_parent_outer_sha256']
         and proof['sessions']==[v['session'] for v in path],'V_REFERENCE_COMPLETED_THREE_SESSION_FAST_PATH')
    for value in path:
        cp=value['checkpoint']
        need(cp['checkpoint_sha256']==digest({k:v for k,v in cp.items() if k!='checkpoint_sha256'})
             and cp['state_sha256']==digest(cp['state']),'V_REFERENCE_COMPLETE_ACTUAL_FAST_RUNTIME_HASHES')


def admit(arm,root,key):
    import hashlib
    spec=specification(arm)
    return compile_body(admission_tree(),dict(vars(crypto),validate_fast=validate_fast,
        sha256_file_from_bytes=lambda raw:hashlib.sha256(raw).hexdigest()))(spec,root,key)
