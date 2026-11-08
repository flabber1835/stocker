"""Same stopped-only two-cipher export protocol, scoped to native OWN627."""
import ast
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_parallel_discovery import compile_body
from p01_native_resume_parent import INPUT,OUTER
import p01_factual_batch_export as previous

STAGE='campaign-p01-native-continuation-financial'
QUALIFICATION_STAGE='campaign-p01-native-continuation-qualification'
RECEIPT_SCHEMA='research.p01-own627-native-resume-receipt/1'
QUALIFICATION_FILES=('zero-session-resume.json','native-resume-preflight.json','native-scope-source-proof.json',
    'actual-one-session-component.json.gz','scope-refusal-falsifiers.json','qualification-summary.json')
SOURCE_SHA='197bd22b4f55dd8fa8ef8349213caae2c408ca464bd1d735380bf927df986fa8'
PUBLIC=previous.PUBLIC;STOP=previous.STOP;ASSET=previous.ASSET


def qualification(proof):
    need(proof['status']=='OWN627_NATIVE_EPOCH_AND_ONE_SESSION_QUALIFIED'
         and proof['financial_authority'] is False and proof['financial_predecessor_authorized'] is False
         and type(proof['component_transitions']) is int and proof['component_transitions']==1
         and proof['qualified_through']=='2020-06-30'
         and proof['epoch_zero_outer_sha256']==OUTER
         and proof['original_input_sha256']==INPUT and proof['original_inputs']==11
         and proof['source_epoch_boundary_reemitted'] is False and proof['input_boundary_reemitted'] is False,
         'P01_NATIVE_ACTUAL_ONE_SESSION_UNCHANGED_EPOCH_QUALIFICATION')


def _body(name):
    raw=Path(previous.__file__).read_bytes();need(sha256_file(Path(previous.__file__))==SOURCE_SHA,'P01_NATIVE_FROZEN_EXPORT_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    gates=[]
    class Scope(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str:node.value=node.value.replace('p01-factual-batch','p01-native-resume')
            return node
        def visit_Expr(self,node):
            if any(isinstance(n,ast.Constant) and n.value=='P01_BATCH_ACTUAL_NONFINANCIAL_QUALIFICATION' for n in ast.walk(node)):
                gates.append(node);return ast.copy_location(ast.parse('qualification(proof)').body[0],node)
            return self.generic_visit(node)
    fn=Scope().visit(fn)
    need(len(gates)==(1 if name=='preserve_qualification' else 0),'P01_NATIVE_EXACT_EXPORT_GATE_SITE')
    namespace=dict(vars(previous),**{k:v for k,v in globals().items() if not k.startswith('__')},__file__=__file__)
    return compile_body(fn,namespace)


def sealed(root,target,key,request,*,stage=STAGE):return _body('sealed')(root,target,key,request,stage=stage)
def qualify_export(path,request):return _body('qualify_export')(path,request)
def write_receipt(path,value):return _body('write_receipt')(path,value)
def preserve_qualification(receipt,root,path,key,request):return _body('preserve_qualification')(receipt,root,path,key,request)
def finish(receipt,root,path,key,request,*,known):return _body('finish')(receipt,root,path,key,request,known=known)
