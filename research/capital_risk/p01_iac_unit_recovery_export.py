"""Source-bound successor stages; old qualifier/financial bytes stay distinct."""
import ast
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
import p01_iac_unit_export as previous

BASE_SHA='e87052164d0a91e44078c424e778e43314220c3665e517670a73064c8ae80321'
STAGE='campaign-p01-iac-unit-recovery-financial'
QUALIFICATION_STAGE='campaign-p01-iac-unit-recovery-qualification'
RECEIPT_SCHEMA='research.p01-own628-iac-unit-recovery-receipt/1'
QUALIFICATION_FILES=previous.QUALIFICATION_FILES
OUTER=previous.OUTER;INPUT=previous.INPUT
PUBLIC=previous.PUBLIC;STOP=previous.STOP;ASSET=previous.ASSET
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
            if type(node.value) is str:node.value=node.value.replace('p01-iac-unit','p01-iac-unit-recovery')
            return node
    tree=Namespace().visit(ast.Module(body=functions,type_ignores=[]))
    values=dict(vars(previous),STAGE=STAGE,QUALIFICATION_STAGE=QUALIFICATION_STAGE,
        RECEIPT_SCHEMA=RECEIPT_SCHEMA,__file__=__file__)
    exec(compile(ast.fix_missing_locations(tree),'<source-bound-recovery-export>','exec'),values)
    _NAMESPACE=values;return values


def qualification(*a,**k):return _scope()['qualification'](*a,**k)
def sealed(*a,**k):return _scope()['sealed'](*a,**k)
def qualify_export(*a,**k):return _scope()['qualify_export'](*a,**k)
def write_receipt(*a,**k):return _scope()['write_receipt'](*a,**k)
def preserve_qualification(*a,**k):return _scope()['preserve_qualification'](*a,**k)
def failure_member(*a,**k):return _scope()['failure_member'](*a,**k)
def preserve_qualification_failure(*a,**k):return _scope()['preserve_qualification_failure'](*a,**k)
def qualification_only_inventory(*a,**k):return _scope()['qualification_only_inventory'](*a,**k)
def finish(*a,**k):return _scope()['finish'](*a,**k)
