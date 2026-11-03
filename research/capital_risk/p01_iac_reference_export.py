"""Source-bound approved reference and fresh FAST qualification; old stops stay distinct."""
import ast
import json
import shutil
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from probe import memory_bytes
import p01_iac_unit_export as previous
from p01_iac_unit_contract import CHILD,OLD_MATCH
from p01_iac_reference_evidence import ORIGIN,ADMISSION,APPROVED,COMPONENT,PROVENANCE_SCHEMA,reference_spec,encoded
from p01_iac_unit_contract import unique

BASE_SHA='e87052164d0a91e44078c424e778e43314220c3665e517670a73064c8ae80321'
STAGE='campaign-p01-iac-reference-financial'
QUALIFICATION_STAGE='campaign-p01-iac-reference-qualification'
RECEIPT_SCHEMA='research.p01-own628-iac-reference-receipt/1'
QUALIFICATION_FILES=(*previous.QUALIFICATION_FILES,'reference-evidence.json')
OUTER=previous.OUTER;INPUT=previous.INPUT
PUBLIC=previous.PUBLIC;STOP=previous.STOP;ASSET=previous.ASSET
FIXTURE_CASE_IDS=tuple(sid+'/'+role for sid in (CHILD,OLD_MATCH)
    for role in ('HELD','CLOSE_PENDING','DOLLAR_BUY_PENDING','EXIT_FLAG_ONLY'))+('POST_EVENT_SOURCE_BUY',)
_NAMESPACE=None
QUALIFICATION_LIMIT=128*1024**2


def _scope():
    global _NAMESPACE
    if _NAMESPACE is not None:return _NAMESPACE
    raw=Path(previous.__file__).read_bytes()
    need(sha256_file(Path(previous.__file__))==BASE_SHA,'RECOVERY_EXACT_484_EXPORT_SOURCE')
    functions=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)]
    names={n.name for n in functions}
    need(names=={'qualification','_body','sealed','qualify_export','write_receipt','preserve_qualification',
        'failure_member','preserve_qualification_failure','qualification_only_inventory','finish'},
        'RECOVERY_EXACT_FROZEN_EXPORT_FUNCTIONS')
    class Namespace(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str:node.value=node.value.replace('p01-iac-unit','p01-iac-reference')
            return node
    tree=Namespace().visit(ast.Module(body=functions,type_ignores=[]))
    inventories=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualification_only_inventory']
    added=[]
    for item in ast.walk(inventories[0]):
        if isinstance(item,ast.Set) and any(isinstance(v,ast.Constant) and v.value=='unit-normalization-component.inflight' for v in item.elts):
            item.elts.append(ast.Constant('source-compiler-check.inflight'));added.append(item)
    need(len(added)==1,'REFERENCE_ONE_FAILURE_ONLY_COMPILER_INFLIGHT_ALLOWLIST')
    values=dict(vars(previous),STAGE=STAGE,QUALIFICATION_STAGE=QUALIFICATION_STAGE,QUALIFICATION_FILES=QUALIFICATION_FILES,
        RECEIPT_SCHEMA=RECEIPT_SCHEMA,__file__=__file__)
    exec(compile(ast.fix_missing_locations(tree),'<source-bound-recovery-export>','exec'),values)
    values['_legacy_qualification']=values['qualification']
    values['qualification']=qualification
    values['_legacy_failure_member']=values['failure_member']
    values['failure_member']=failure_member
    _NAMESPACE=values;return values


def qualification(proof):
    _scope()['_legacy_qualification'](proof)
    need(all(proof.get(k) is True for k in ('fixture_aggregate_complete','fixture_aggregate_all_passed'))
         and all(type(proof.get(k)) is int and proof[k]==9 for k in (
             'fixture_expected_case_count','fixture_attempted_case_count','fixture_passed_case_count'))
         and type(proof.get('fixture_expected_case_ids')) is list
         and proof['fixture_expected_case_ids']==list(FIXTURE_CASE_IDS)
         and type(proof.get('fixture_failed_case_count')) is int and proof['fixture_failed_case_count']==0
         and type(proof.get('fixture_component_sha256')) is str
         and len(proof['fixture_component_sha256'])==64
         and all(c in '0123456789abcdef' for c in proof['fixture_component_sha256']),
         'FIXTURE_COMPLETE_NINE_CASE_AGGREGATE_AND_COMPONENT_HASH_BEFORE_FINANCE')
    recorded={k:ORIGIN[k] for k in ('run_id','head','artifact_id','request_sha256')}
    need(proof.get('reference_evidence_reused') is True and proof.get('reference_reuse_admission_sha256')==ADMISSION
         and proof.get('reference_recorded_origin')==recorded
         and proof.get('original_reference_compiler_logs_available') is False
         and proof.get('source_compiler_check_qualified') is True
         and proof.get('reference_report_rechecked') is True
         and type(proof.get('reference_report_financial_transitions')) is int
         and proof['reference_report_financial_transitions']==0
         and proof.get('reference_report_origin')=='NEW_READONLY_CANONICAL_REPORT_ON_RESTORED_OLD_STATE'
         and all(type(proof.get(k)) is int and proof[k]==v for k,v in (
             ('source_preparations',2),('source_compiler_financial_transitions',0),('reference_financial_transitions_reexecuted',0),
             ('old_reference_runtime_records_restored',2),('old_synthetic_wires_restored',18)))
         and proof['fixture_component_sha256']==APPROVED[COMPONENT]['sha256']
         and type(proof.get('reference_evidence_sha256')) is str and len(proof['reference_evidence_sha256'])==64
         and all(c in '0123456789abcdef' for c in proof['reference_evidence_sha256']),
         'REFERENCE_EXACT_ADMITTED_ORIGIN_PREPARE_ONLY_TWO_FRESH_FAST_NO_OLD_LOG_CLAIM')

def sealed(*a,**k):return _scope()['sealed'](*a,**k)
def qualify_export(*a,**k):return _scope()['qualify_export'](*a,**k)
def write_receipt(*a,**k):return _scope()['write_receipt'](*a,**k)
def preserve_qualification(receipt,root,path,key,request):
    stop=receipt.get('qualification_worker',{})
    need(stop.get('stopped') is True and type(stop.get('exit_code')) is int and stop['exit_code']==0
         and stop.get('oom_killed') is False,'FIXTURE_COMPONENT_HASH_ONLY_AFTER_KNOWN_SUCCESSFUL_QUALIFIER_STOP')
    root=Path(root);summary=root/'qualification/qualification-summary.json'
    component=root/'qualification/unit-normalization-component.json.gz'
    need(summary.is_file() and component.is_file() and not summary.is_symlink() and not component.is_symlink()
         and summary.stat().st_size<=1024**2 and component.stat().st_size<=128*1024**2,
         'FIXTURE_BOUNDED_REGULAR_SUMMARY_AND_COMPONENT_BEFORE_SEAL')
    proof=json.loads(summary.read_bytes());qualification(proof)
    need(sha256_file(component)==proof['fixture_component_sha256'],
         'FIXTURE_ACTUAL_COMPONENT_BYTES_EQUAL_QUALIFIED_AGGREGATE_HASH')
    reference=root/'qualification/reference-evidence.json'
    need(reference.is_file() and not reference.is_symlink() and reference.stat().st_size<=2*1024**2
         and sha256_file(reference)==proof['reference_evidence_sha256'],'REFERENCE_ACTUAL_Q15_PROVENANCE_BYTES')
    provenance=json.loads(reference.read_bytes());raw_request=provenance['original_raw_request_utf8'].encode('utf8')
    need(provenance['schema']==PROVENANCE_SCHEMA and provenance['specification']==reference_spec()
         and provenance['all_old_driver_sources_authenticated'] is True and provenance['full_qualification_inventory_authenticated'] is True
         and type(provenance['original_qualification_worker_exit_code']) is int and provenance['original_qualification_worker_exit_code']==1
         and provenance['financial_worker_started'] is provenance['financial_authority'] is provenance['qualification_state_adopted'] is False
         and __import__('hashlib').sha256(raw_request).hexdigest()==ORIGIN['request_sha256'],
         'REFERENCE_Q15_ORIGINAL_OLD_STOP1_AND_WHOLE_RAW_REQUEST_PROVENANCE')
    required={'spec.json','request.json','source-map.json','source-bindings.json'}|{
        'qualification/'+n for n in (*QUALIFICATION_FILES,'worker-inspect.json')}
    optional={'qualification/worker.log','qualification/log-copy-failure.json'}
    progress='qualification/source-compiler-check.inflight'
    files=[p for p in root.rglob('*') if p.is_file()]
    actual={p.relative_to(root).as_posix() for p in files}
    total=sum(p.stat().st_size for p in files)
    progress_path=root/progress
    progress_bytes=progress_path.stat().st_size if progress in actual else 0
    need(required<=actual<=required|optional|{progress} and bool(actual&optional)
         and not root.is_symlink() and not any(p.is_symlink() for p in root.rglob('*'))
         and total<=2*QUALIFICATION_LIMIT and progress_bytes<=QUALIFICATION_LIMIT
         and total-progress_bytes<=QUALIFICATION_LIMIT,
         'REFERENCE_ORIGINAL_Q15_ONLY_PLUS_EXACT_COMPILER_PROGRESS')
    if progress in actual:
        need(progress_path.is_file() and not progress_path.is_symlink()
             and progress_path.stat().st_size<=QUALIFICATION_LIMIT,
             'REFERENCE_BOUNDED_REGULAR_COMPILER_PROGRESS_BEFORE_PARSE')
        need(memory_bytes()['MemAvailable']>=10*1024**3
             and shutil.disk_usage(root).free>=10*1024**3+2*total,
             'REFERENCE_Q15_COPY_ACTUAL_MEMORY_AND_DISK_HEADROOM')
        early=json.loads(progress_path.read_bytes(),object_pairs_hook=unique)
        final=json.loads((root/'qualification/unit-normalization-source-proof.json').read_bytes(),object_pairs_hook=unique)
        need(encoded(early)==encoded(final['source_compiler_check']),
             'REFERENCE_ENTIRE_EARLY_COMPILER_PROGRESS_EQUALS_FINAL_TYPED_PROOF')
        snapshot=root.parent/'p01-iac-reference-qualification-seal-snapshot';snapshot.mkdir(mode=0o700)
        for name in sorted(actual-{progress}):
            source=root/name;target=snapshot/name;target.parent.mkdir(parents=True,exist_ok=True)
            expected=dict(bytes=source.stat().st_size,sha256=sha256_file(source));shutil.copyfile(source,target)
            need(dict(bytes=target.stat().st_size,sha256=sha256_file(target))==expected
                 and dict(bytes=source.stat().st_size,sha256=sha256_file(source))==expected,
                 'REFERENCE_EVERY_Q15_SNAPSHOT_COPY_EXACT_AND_ORIGINAL_UNCHANGED')
        need({p.relative_to(snapshot).as_posix() for p in snapshot.rglob('*') if p.is_file()}==actual-{progress},
             'REFERENCE_EXACT_DISJOINT_SUCCESSFUL_Q15_SNAPSHOT')
        return _scope()['preserve_qualification'](receipt,snapshot,path,key,request)
    return _scope()['preserve_qualification'](receipt,root,path,key,request)
def failure_member(name):
    if _scope()['_legacy_failure_member'](name):return True
    parts=name.split('/')
    if any(v in ('.','..') or previous.re.fullmatch('[A-Za-z0-9_.-]+',v) is None for v in parts):return False
    if parts==['proof','source-compiler-check.inflight']:return True
    return (3<=len(parts)<=64 and parts[0] in ('source-check','reference-report') and parts[1]=='contexts'
        and previous.re.fullmatch(r'.+\.(?:json|jsonl|json\.gz)(?:\.tmp-[0-9a-f]+)?',parts[-1]) is not None)
def preserve_qualification_failure(*a,**k):return _scope()['preserve_qualification_failure'](*a,**k)
def qualification_only_inventory(*a,**k):return _scope()['qualification_only_inventory'](*a,**k)
def finish(*a,**k):return _scope()['finish'](*a,**k)
