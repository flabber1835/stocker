"""Admit completed REFERENCE qualification, never a diagnostic/financial book."""
import ast,gzip,json
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_facts import digest
from system_campaign_parallel_discovery import compile_body
from system_campaign_discovery_context import TAINT
import system_campaign_volatility_reference_parent as previous
import system_campaign_factual_admit as crypto
import system_campaign_p02_close_diagnostics as stops

HERE=Path(__file__).parent
SPEC='system-campaign-volatility-native-reference-predecessors-001.json'
PRIOR='system-campaign-volatility-admission-recovery-request-001.json'
PRIOR_SHA='b8a5349cdcd8f9017af4d1338f5b8a5fbf88ef049ddc28cba32f9083ba4d12bf'


def specification(arm):
    need(arm in ('P10','P11'),'V_NATIVE_ONLY_SELECTED_V_ARM')
    value=json.loads((HERE/SPEC).read_bytes());spec=value['arms'][arm]
    need(value['authority']==TAINT and value['financial_authority'] is False
         and spec['native_signal_closes']=={'P10':21,'P11':10}[arm]
         and spec['qualification_worker']['exit_code']==1 and spec['no_diagnostic_origin_or_worker'],
         'V_NATIVE_EXACT_COMPLETED_REFERENCE_AND_RETAINED_FAILURE')
    return spec


def original_bytes(module):
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'V_NATIVE_EXACT418_PRIOR_REQUEST')
    raw=Path(module.__file__).read_bytes()
    need(sha256_file(Path(module.__file__))==json.loads((HERE/PRIOR).read_bytes())['sources'][Path(module.__file__).name],
         'V_NATIVE_IMMUTABLE_PRIOR_DRIVER')
    return raw


def admission_tree():
    original_bytes(previous)
    fn=previous.admission_tree()
    site,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=='set(z.namelist())']
    need(len(site.comparators)==1 and isinstance(site.comparators[0],ast.Set),
         'V_NATIVE_ONE_EXACT_ORIGINAL_PUBLIC_ZIP_MEMBERS_SITE')
    site.comparators[0]=ast.parse("set(spec['public_members'])",mode='eval').body
    return ast.fix_missing_locations(fn)


def old_stopped(value,spec):
    fn,=[n for n in ast.parse(original_bytes(stops)).body if isinstance(n,ast.FunctionDef) and n.name=='stopped']
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='/capital-system-factual-p02-']
    need(len(sites)==1,'V_NATIVE_ONE_RETAINED_STOP_NAMESPACE')
    sites[0].value='/capital-system-parallel-discovery-'+spec['arm'].lower()+'-'
    cmd,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=="c['Cmd']"]
    cmd.comparators=[ast.parse(repr(['-B','-u','/driver/system_campaign_volatility_reference_run.py',
        '--mode','qualify','--arm',spec['arm'],'--spec','/out/spec.json']),mode='eval').body]
    mounts=[n for n in ast.walk(fn) if isinstance(n,ast.Set) and all(isinstance(v,ast.Constant) for v in n.elts)
            and {ast.literal_eval(v) for v in n.elts}=={'/variant','/frozen','/driver','/out','/old'}]
    need(len(mounts)==1,'V_NATIVE_ONE_EXACT_OLD_READONLY_PREVIOUS_MOUNT')
    mounts[0].elts.append(ast.Constant('/previous'))
    compile_body(fn,vars(stops))(value,spec['qualification_worker'],'qualify',str(spec['run_id']),spec['request_file'])
    need(value['Id']==spec['inspection']['id'] and value['Name']==spec['inspection']['name']
         and value['State']['ExitCode']==1 and not value['State']['OOMKilled'],
         'V_NATIVE_ACTUAL_FAILED_QUALIFIER_STOP_NOT_RELABELLED')


def validate_reference(spec,inventory,dest):
    need(spec==specification(spec['arm']) and len(inventory)==spec['inventory_members']==39
         and digest(inventory)==spec['inventory_sha256']
         and sum(v['bytes'] for v in inventory.values())<32*1024**2,'V_NATIVE_COMPLETE_REFERENCE_INVENTORY')
    need(not any(n.startswith('diagnostic-book/') for n in inventory)
         and 'qualification/discovery-canonical-qualification.json' not in inventory,
         'V_NATIVE_NO_DIAGNOSTIC_OR_COMPLETE_OLD_ADMISSION')
    dest=Path(dest)
    need(sha256_file(dest/'source-bindings.json')==spec['source_binding_sha256']
         and sha256_file(dest/'qualification/worker-inspect.json')==spec['inspection']['sha256'],
         'V_NATIVE_EXACT_OLD_SOURCE_AND_STOP_BYTES')
    old_stopped(json.loads((dest/'qualification/worker-inspect.json').read_bytes()),spec)
    for name,key in [('actual-runtime-path.json.gz','reference_path'),('discovery-canonical-qualification.json','reference_proof')]:
        path=dest/'qualification/reference'/name;entry=spec[key]
        need(path.stat().st_size==entry['bytes'] and sha256_file(path)==entry['sha256'],
             'V_NATIVE_COMPLETED_REFERENCE_BYTES')
    parent=dest/'qualification/strict-parent.json.gz'
    need(parent.stat().st_size==spec['strict_parent_gzip']['bytes']
         and sha256_file(parent)==spec['strict_parent_gzip']['sha256'],'V_NATIVE_ORIGINAL_STRICT_PARENT_GZIP')
    path=json.loads(gzip.decompress((dest/'qualification/reference/actual-runtime-path.json.gz').read_bytes()))
    proof=json.loads((dest/'qualification/reference/discovery-canonical-qualification.json').read_bytes())
    need(len(path)==3 and proof['synthetic_canonical_transitions']==3 and proof['status']=='QUALIFIED'
         and proof['strict_parent_outer_sha256']==spec['strict_parent_outer_sha256']
         and proof['sessions']==[v['session'] for v in path],'V_NATIVE_COMPLETED_THREE_REFERENCE_SESSIONS')
    for record in path:
        cp=record['checkpoint']
        need(cp['checkpoint_sha256']==digest({k:v for k,v in cp.items() if k!='checkpoint_sha256'})
             and cp['state_sha256']==digest(cp['state']),'V_NATIVE_ALL_RETAINED_REFERENCE_RUNTIME_HASHES')


def admit(arm,root,key):
    import hashlib
    original_bytes(crypto)
    return compile_body(admission_tree(),dict(vars(crypto),validate_fast=validate_reference,
        sha256_file_from_bytes=lambda raw:hashlib.sha256(raw).hexdigest()))(specification(arm),root,key)
