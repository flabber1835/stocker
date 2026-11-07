"""Same stopped-only two-cipher export protocol, scoped to own628 IAC unit input."""
import ast
import json
from pathlib import Path
import re
import shutil

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_parallel_discovery import compile_body
from p01_iac_unit_parent import INPUT,OUTER
import p01_factual_batch_export as previous

STAGE='campaign-p01-iac-unit-financial'
QUALIFICATION_STAGE='campaign-p01-iac-unit-qualification'
RECEIPT_SCHEMA='research.p01-own628-iac-unit-receipt/1'
QUALIFICATION_FILES=('zero-session-boundaries.json','iac-unit-input.json','iac-unit-preflight.json',
    'unit-normalization-source-proof.json','unit-normalization-component.json.gz',
    'actual-two-session-component.json.gz','actual-unit-accounting-and-report.json','qualification-summary.json')
SOURCE_SHA='197bd22b4f55dd8fa8ef8349213caae2c408ca464bd1d735380bf927df986fa8'
PUBLIC=previous.PUBLIC;STOP=previous.STOP;ASSET=previous.ASSET


def qualification(proof):
    def is_hash(value):return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)
    need(proof['status']=='OWN628_IAC_UNIT_INPUT_AND_TWO_SESSION_FAST_REFERENCE_QUALIFIED'
         and proof['financial_authority'] is False and proof['financial_predecessor_authorized'] is False
         and all(type(proof[k]) is int for k in ('component_transitions','original_inputs','successor_inputs',
             'input_adoptions','actual_role_and_full_state_checks'))
         and proof['component_transitions']==2 and proof['qualified_through']=='2020-07-02'
         and proof['epoch_zero_outer_sha256']==OUTER and proof['original_inputs']==11 and proof['successor_inputs']==12
         and proof['input_adoptions']==1 and proof['source_epoch_boundary_reemitted'] is False
         and proof['actual_fast_reference_full_components_equal'] is True
         and proof['actual_role_and_full_state_checks']==2
         and is_hash(proof['input_zero_outer_sha256']) and proof['input_zero_outer_sha256']!=OUTER
         and is_hash(proof['input_document_sha256']) and is_hash(proof['successor_input_sha256']),
         'P01_IAC_ACTUAL_TWO_SESSION_FULL_REFERENCE_AND_TWELFTH_INPUT_QUALIFICATION')


def _body(name):
    raw=Path(previous.__file__).read_bytes();need(sha256_file(Path(previous.__file__))==SOURCE_SHA,'P01_IAC_FROZEN_EXPORT_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    gates=[]
    class Scope(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str:node.value=node.value.replace('p01-factual-batch','p01-iac-unit')
            return node
        def visit_Expr(self,node):
            if any(isinstance(n,ast.Constant) and n.value=='P01_BATCH_ACTUAL_NONFINANCIAL_QUALIFICATION' for n in ast.walk(node)):
                gates.append(node);return ast.copy_location(ast.parse('qualification(proof)').body[0],node)
            return self.generic_visit(node)
    fn=Scope().visit(fn)
    need(len(gates)==(1 if name=='preserve_qualification' else 0),'P01_IAC_EXACT_EXPORT_GATE_SITE')
    namespace=dict(vars(previous),**{k:v for k,v in globals().items() if not k.startswith('__')},__file__=__file__)
    return compile_body(fn,namespace)


def sealed(root,target,key,request,*,stage=STAGE):return _body('sealed')(root,target,key,request,stage=stage)
def qualify_export(path,request):return _body('qualify_export')(path,request)
def write_receipt(path,value):
    for field in ('qualification_encrypted_output','encrypted_output'):
        if field not in value:continue
        asset=value[field]
        need(type(asset) is dict and set(asset)==ASSET and type(asset['name']) is str
             and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',asset['name']) is not None
             and type(asset['bytes']) is int and asset['bytes']>0
             and all(type(asset[k]) is str and re.fullmatch('[0-9a-f]{64}',asset[k]) is not None
                for k in ('sha256','manifest_sha256'))
             and type(asset['compression']) is str and asset['compression']=='TAR_GZIP_V1',
             'P01_IAC_PUBLIC_ASSET_STATIC_SCALARS_ONLY')
    if 'export_error' in value:
        error=value['export_error']
        need(type(error) is dict and set(error)=={'type','code'}
             and type(error['type']) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,79}',error['type']) is not None
             and type(error['code']) is str and re.fullmatch('REFUSED_[A-Z0-9_]+|EXPORT_OPERATION_FAILED',error['code']) is not None,
             'P01_IAC_PUBLIC_ERROR_STATIC_SCALARS_ONLY')
    return _body('write_receipt')(path,value)
def preserve_qualification(receipt,root,path,key,request):return _body('preserve_qualification')(receipt,root,path,key,request)
def failure_member(name):
    parts=name.split('/')
    if any(not re.fullmatch('[A-Za-z0-9_.-]+',v) or v in ('.','..') for v in parts):return False
    if len(parts)==1:return name in {'spec.json','source-map.json','worker-inspect.json','worker.log','log-copy-failure.json'}
    if parts[0]=='proof':return len(parts)==2 and parts[1] in {*QUALIFICATION_FILES,'unit-normalization-component.inflight'}
    if parts[0] not in ('reference','fast'):return False
    if len(parts)==2:return parts[1] in {'source-successor.json','hydrated-factual-catalog.json',
        'hydrated-distribution-catalog.json','iac-unit-preflight.json','iac-unit-input.json','zero-session-boundaries.json'}
    return len(parts)<=64 and parts[1] in ('book','lineage','contexts','retained-qualification') and re.fullmatch(
        r'.+\.(?:json|jsonl|json\.gz)(?:\.tmp-[0-9a-f]+)?',parts[-1]) is not None


def preserve_qualification_failure(root,qualifier,stop):
    root,qualifier=Path(root),Path(qualifier)
    need(type(stop) is dict and set(stop)==STOP and stop['stopped'] is True
         and type(stop['exit_code']) is int and type(stop['oom_killed']) is bool
         and type(stop['wait_error']) in (str,type(None))
         and (qualifier/'worker-inspect.json').is_file(),
         'P01_IAC_ONLY_ACTUAL_KNOWN_STOPPED_QUALIFIER_FAILURE_STATE')
    paths=sorted(qualifier.rglob('*'));members={}
    need(not qualifier.is_symlink() and not any(p.is_symlink() for p in paths),
         'P01_IAC_QUALIFIER_FAILURE_NO_SYMLINK')
    for source in paths:
        if not source.is_file():continue
        name=source.relative_to(qualifier).as_posix()
        need(failure_member(name),'P01_IAC_QUALIFIER_FAILURE_SOURCE_CONTROLLED_PATHS')
        members[name]=dict(bytes=source.stat().st_size,sha256=sha256_file(source))
    existing_files=[p for p in root.rglob('*') if p.is_file()]
    existing=sum(p.stat().st_size for p in existing_files)
    total=sum(v['bytes'] for v in members.values())
    value=dict(schema='research.p01-iac-unit-qualification-failure-scope/1',qualifier_stop=stop,
        preserved_members=members,ancestry_excluded=[],financial_authority=False,financial_worker_launched=False,
        financial_snapshot_or_predecessor_admitted=False,qualification_state_adopted=False,incomplete_files_parsed=False)
    scope=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    need(len(existing_files)+len(members)+1<5000 and existing+total+len(scope)<=2*1024**3
         and shutil.disk_usage(root).free>=2*1024**3+2*(existing+total+len(scope)),
         'P01_IAC_QUALIFIER_FAILURE_TWO_GIB_BOUND_AND_EXPORT_RESERVE')
    destination=root/'qualification-failure';destination.mkdir()
    for name,entry in members.items():
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(qualifier/name,target)
        need(target.stat().st_size==entry['bytes'] and sha256_file(target)==entry['sha256'],
             'P01_IAC_QUALIFIER_FAILURE_EVERY_STOPPED_RAW_BYTE_PRESERVED')
    (destination/'export-scope.json').write_bytes(scope)
    return value


def qualification_only_inventory(root):
    roots={'spec.json','request.json','source-map.json','source-bindings.json','driver-failure.txt'}
    for path in Path(root).rglob('*'):
        need(not path.is_symlink(),'P01_IAC_QUALIFICATION_ONLY_NO_SYMLINK')
        if not path.is_file():continue
        name=path.relative_to(root).as_posix()
        permitted=name in roots or name.startswith('qualification/') and name.split('/',1)[1] in {
            *QUALIFICATION_FILES,'unit-normalization-component.inflight','worker-inspect.json','worker.log','log-copy-failure.json'}
        if name.startswith('qualification-failure/'):
            relative=name.split('/',1)[1];permitted=relative=='export-scope.json' or failure_member(relative)
        need(permitted,'P01_IAC_QUALIFICATION_ONLY_NO_FINANCIAL_BOOK_NAMESPACE')


def finish(receipt,root,path,key,request,*,known):
    if not (known and 'worker' not in receipt and 'qualification_worker' in receipt):
        return _body('finish')(receipt,root,path,key,request,known=known)
    receipt['encrypted_output_exported']=False
    need('encrypted_output' not in receipt and 'reviewer' not in receipt,
         'P01_IAC_QUALIFICATION_ONLY_HAS_NO_FINANCIAL_WORKER_OR_CIPHER')
    if not receipt.get('qualification_exported',False):
        try:
            preserve_qualification_failure(root,Path(root).parent/'p01-iac-unit-qualification-output',receipt['qualification_worker'])
            qualification_only_inventory(root)
            receipt['qualification_encrypted_output']=sealed(Path(root),Path(path).parent/'p01-iac-unit-qualification.tar.crseal',
                key,request,stage=QUALIFICATION_STAGE)
            receipt['qualification_exported']=True
        except Exception as error:
            code=str(error);receipt['export_error']=dict(type=type(error).__name__,
                code=code if re.fullmatch('REFUSED_[A-Z0-9_]+',code) else 'EXPORT_OPERATION_FAILED')
            receipt['status']='KNOWN_STOP_QUALIFICATION_EXPORT_FAILED_NO_PLAINTEXT_FALLBACK'
            write_receipt(path,receipt);return
    receipt['status']='QUALIFICATION_ONLY_KNOWN_STOP_REFUSAL_PRESERVED';write_receipt(path,receipt)
