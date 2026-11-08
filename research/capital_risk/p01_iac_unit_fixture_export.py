"""Source-bound complete fixture qualification; old evidence stays distinct."""
import ast
import json
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
import p01_iac_unit_export as previous
from p01_iac_unit_contract import CHILD,OLD_MATCH

BASE_SHA='e87052164d0a91e44078c424e778e43314220c3665e517670a73064c8ae80321'
STAGE='campaign-p01-iac-unit-fixture-financial'
QUALIFICATION_STAGE='campaign-p01-iac-unit-fixture-qualification'
RECEIPT_SCHEMA='research.p01-own628-iac-unit-fixture-receipt/1'
QUALIFICATION_FILES=previous.QUALIFICATION_FILES
OUTER=previous.OUTER;INPUT=previous.INPUT
PUBLIC=previous.PUBLIC;STOP=previous.STOP;ASSET=previous.ASSET
FIXTURE_CASE_IDS=tuple(sid+'/'+role for sid in (CHILD,OLD_MATCH)
    for role in ('HELD','CLOSE_PENDING','DOLLAR_BUY_PENDING','EXIT_FLAG_ONLY'))+('POST_EVENT_SOURCE_BUY',)
_NAMESPACE=None


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
            if type(node.value) is str:node.value=node.value.replace('p01-iac-unit','p01-iac-unit-fixture')
            return node
    tree=Namespace().visit(ast.Module(body=functions,type_ignores=[]))
    values=dict(vars(previous),STAGE=STAGE,QUALIFICATION_STAGE=QUALIFICATION_STAGE,
        RECEIPT_SCHEMA=RECEIPT_SCHEMA,__file__=__file__)
    exec(compile(ast.fix_missing_locations(tree),'<source-bound-recovery-export>','exec'),values)
    values['_legacy_qualification']=values['qualification']
    values['qualification']=qualification
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
    return _scope()['preserve_qualification'](receipt,root,path,key,request)
def failure_member(*a,**k):return _scope()['failure_member'](*a,**k)
def preserve_qualification_failure(*a,**k):return _scope()['preserve_qualification_failure'](*a,**k)
def qualification_only_inventory(*a,**k):return _scope()['qualification_only_inventory'](*a,**k)
def finish(*a,**k):return _scope()['finish'](*a,**k)
