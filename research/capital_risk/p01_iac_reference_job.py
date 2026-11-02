"""Own628 approved reference reuse plus fresh FAST; exact stopped orchestration."""
import argparse
import ast
import json
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
import p01_iac_unit_job as previous
import p01_iac_unit_fixture_job as predecessor
from p01_iac_reference_admit import admit_reference
from p01_iac_reference_evidence import reference_spec,SPEC as REFERENCE_SPEC,ORIGIN,ADMISSION
from system_campaign_parallel_discovery import compile_body as original_compile_body
from p01_iac_reference_export import (STAGE,RECEIPT_SCHEMA,QUALIFICATION_FILES,qualification,
    qualify_export,write_receipt,preserve_qualification,finish)

HERE=Path(__file__).parent
REQUEST='p01_iac_reference_request.json'
PRIOR_REQUEST='p01_iac_unit_fixture_request.json'
PRIOR_SHA='fd2ff79b00472f482e53df2b411cdeec5c999e27529be287bcfc6f9c914216a7'
PREDECESSOR_SHA='c531ea87f283dc14ea3b9e3cc860f9a035285cd6033310bddf8cafd72f547f0f'
BASE_SHA='b61e8a1af67cf63b6e4420acdcb513c035157012c123057bed0875627ad4a401'
WORKFLOW='p01_iac_reference_financial.yml'
WORKFLOW_SHA='e355b174825667a6f38bf0fc61eb6f0a998f7a5f469c4372022f3412e96c7e9a'
NEW=('p01_iac_quote_epoch.py','p01_iac_unit_review_recovery_adapter.py',
    'p01_iac_reference_evidence_spec.json','p01_iac_reference_evidence.py','p01_iac_reference_source.py',
    'p01_iac_reference_run.py','p01_iac_reference_review.py','p01_iac_reference_admit.py',
    'p01_iac_reference_job.py','p01_iac_reference_export.py','p01_iac_reference_probe.py')
SOURCES=tuple(dict.fromkeys((*json.loads((HERE/PRIOR_REQUEST).read_bytes())['sources'],PRIOR_REQUEST,*NEW)))
SECRET=previous.SECRET
admit=previous.admit
stopped_run=previous.stopped_run;StopUnknown=previous.StopUnknown
freeze=previous.freeze;collect_stop=previous.collect_stop
check_context=previous.check_context;validate_prepared_receipt=previous.validate_prepared_receipt
stage_valid=previous.stage_valid;authenticate_capsule=previous.authenticate_capsule
build=previous.build;write_disjoint=previous.write_disjoint;inspector_source=previous.inspector_source


def encoded_request(value):
    return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()


def expected_request():
    need(sha256_file(Path(previous.__file__))==BASE_SHA,'RECOVERY_FROZEN_484_HOST')
    need(sha256_file(Path(predecessor.__file__))==PREDECESSOR_SHA,'REFERENCE_EXACT_497_HOST_PREDECESSOR')
    raw=(HERE/PRIOR_REQUEST).read_bytes()
    need(sha256_file(HERE/PRIOR_REQUEST)==PRIOR_SHA,'REFERENCE_EXACT_PUBLIC_497_REQUEST_BYTES')
    prior=json.loads(raw)
    need(len(prior['sources'])==497 and prior==predecessor.expected_request()
         and all(sha256_file(HERE/n)==h for n,h in prior['sources'].items()),
         'REFERENCE_WHOLE_OLD497_MODEL_AND_EVERY_SOURCE_BYTE')
    reference_spec()
    result=dict(prior,schema='research.p01-own628-reference-reuse-request/1',stage=STAGE,
        prior_request_file=PRIOR_REQUEST,prior_request_sha256=PRIOR_SHA,prior_driver_sources=497,
        actual_entrypoint='/driver/p01_iac_reference_run.py',worker_namespace='capital-system-p01-iac-reference',
        workflow=WORKFLOW,owner_workflow_sha256=WORKFLOW_SHA,
        recovery_reason='EXACT_QUOTE_EPOCH_AND_ROOT_APPROVED_REFERENCE_COMPONENT_REUSE',
        reference_spec_file=REFERENCE_SPEC,reference_spec_sha256=sha256_file(HERE/REFERENCE_SPEC),
        reference_reuse_admission_sha256=ADMISSION,reference_recorded_origin=ORIGIN,
        original_reference_compiler_logs_available=False,source_compiler_preparation_only_required=True,
        source_compiler_financial_transitions=0,reference_financial_transitions_reexecuted=0,
        reference_evidence_readonly_by_role=True,qualification_proof_members=15,
        historical_quote_epoch_source_sha256='7f1f80279eaf7c6c5b9504545bb2f3808e80a1ef46a29d0c16404192446355ab',
        single_save_review_adapter_sha256='8bfd5cbb445a0cd4e3b594d7bf4614b377f10437dde39f68c64d9cc196c7870c',
        required_synthetic_fixture_cases=9,all_independent_synthetic_fixtures_required_before_finance=True,
        failed_qualification_run_id=41462104626,failed_qualification_artifact_id=13149998336,
        failed_qualification_state_adopted=False,new_request_before_any_old_runtime=True,
        worker_request_serialization='SORTED_INDENT2_LF_EXACT_SOURCE_COPY',
        sources={n:sha256_file(HERE/n) for n in SOURCES})
    need(result['original_inputs']==11 and result['successor_inputs']==12
         and result['input_document_sha256']=='0f1f4672e1a3ee3f64f8281d25f3348d9f53f28ea6146d71c4f71a8378d515b7'
         and result['successor_input_sha256']=='ce0615156c89367169ac5da437c5418747b5d290c7634a79f52a415fb68262b8',
         'RECOVERY_SAME_ORIGINAL628_EXACT_INPUT12_NO_PARAMETER_OR_STATE_CHANGE')
    return result


def _worker_copy(mode):
    return Path('/out/request.json') if mode=='economic' else Path('/evidence/request.json')


def validate_worker_request(path,*,mode):
    need(mode in ('qualify','economic','review'),'RECOVERY_EXACT_WORKER_MODE')
    path=Path(path)
    need(path.resolve()==(HERE/REQUEST).resolve(),'RECOVERY_FIXED_MOUNTED_NEW_REQUEST')
    raw=path.read_bytes();expected=expected_request()
    need(raw==encoded_request(expected) and json.loads(raw)==expected,
         'RECOVERY_ENTIRE_NEW_REQUEST_AND_ALL_SOURCE_BYTES_BEFORE_OLD_RUNTIME')
    if mode!='qualify':
        need(_worker_copy(mode).read_bytes()==raw,'RECOVERY_RAW_WORKER_REQUEST_COPY_EQUALS_DRIVER_SOURCE')
    return expected


def entrypoint(mode):
    need(mode in ('qualify','economic','review'),'RECOVERY_EXACT_ENTRYPOINT_MODE')
    return ['-B','-u','/driver/p01_iac_reference_run.py','--mode',mode,'--spec','/out/spec.json']


def check_qualification(proof,request,spec):
    qualification(proof)
    return previous.check_qualification(proof,request,spec)


def check_financial_input(outcome,proof,request):return previous.check_financial_input(outcome,proof,request)


def compile_body(node,namespace):
    if node.name=='main':
        insertions=[];commands=[];body=[]
        for item in node.body:
            # The guarded orchestration is inside the original single try block.
            body.append(item)
        class Reference(ast.NodeTransformer):
            def visit_Assign(self,item):
                if any(isinstance(t,ast.Name) and t.id=='old' for t in item.targets) and isinstance(item.value,ast.Call) and ast.unparse(item.value.func)=='admit':
                    insertions.append(item)
                    return [item,*ast.parse("reference = admit_reference(temp/'campaign-factual-transfer-p01-reference',key,reference_spec())\nfreeze(reference)").body]
                return self.generic_visit(item)
            def visit_Call(self,item):
                item=self.generic_visit(item)
                if isinstance(item.func,ast.Name) and item.func.id=='worker_command' and len(item.args)>1 and isinstance(item.args[1],ast.Constant) and item.args[1].value=='qualify':
                    need(not item.keywords,'REFERENCE_ONE_EXACT_QUALIFIER_COMMAND_EVIDENCE_SITE')
                    item.keywords=[ast.keyword(arg='evidence',value=ast.Name(id='reference',ctx=ast.Load()))];commands.append(item)
                return item
        node=Reference().visit(node)
        need(len(insertions)==len(commands)==1,'REFERENCE_ONLY_PARENT_AFTER_MARKER_AND_QUALIFIER_EVIDENCE_INSERTIONS')
    return original_compile_body(node,namespace)


def _body(name):
    raw=Path(previous.__file__).read_bytes()
    need(sha256_file(Path(previous.__file__))==BASE_SHA,'RECOVERY_SOURCE_BOUND_484_ORCHESTRATION')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='_body']
    node.name='_recovery_host_body'
    class Namespace(ast.NodeTransformer):
        def visit_Constant(self,item):
            if type(item.value) is str:item.value=item.value.replace('p01-iac-unit','p01-iac-reference')
            return item
    node=Namespace().visit(node)
    values=dict(vars(previous),**{k:v for k,v in globals().items() if not k.startswith('__')})
    values.update(previous=previous.previous,SOURCE_SHA=previous.SOURCE_SHA,__file__=__file__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<source-bound-fixture-host-builder>','exec'),values)
    return values['_recovery_host_body'](name)


def inspection_bindings(value):
    binds=[row for row in value['Mounts'] if row['Type']=='bind']
    user=value['Config']['User']
    need(len(binds)==8 and len({row['Destination'] for row in binds})==8
         and type(user) is str and inspector_source.re.fullmatch(r'[0-9]+:[0-9]+',user) is not None
         and all(int(part)>0 for part in user.split(':')),
         'REFERENCE_EIGHT_UNIQUE_BIND_DESTINATIONS_AND_POSITIVE_UID_GID')


def inspect(name,identity=None):
    raw=Path(inspector_source.__file__).read_bytes()
    need(sha256_file(Path(inspector_source.__file__))==json.loads((HERE/PRIOR_REQUEST).read_bytes())['sources']['system_campaign_p02_continue_job.py'],
         'REFERENCE_EXACT_OLD_INSPECTOR_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='inspect']
    pattern,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value==r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1']
    pattern.value=r'capital-system-p01-iac-reference-(?:qualify|worker|review)-[0-9]+-1'
    assignment,=[n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='expected' for t in n.targets)]
    assignment.value=ast.parse("{'/variant','/frozen','/driver','/out','/old','/celg-input','/celg-input-descriptor.json','/evidence'}",mode='eval').body
    fetched,=[n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='v' for t in n.targets)]
    fn.body.insert(fn.body.index(fetched)+1,ast.parse('inspection_bindings(v)').body[0])
    value=original_compile_body(fn,dict(vars(inspector_source),inspection_bindings=inspection_bindings))(name,identity)
    mode='qualify' if '-qualify-' in name else 'review' if '-review-' in name else 'economic'
    need(value['Config']['Cmd']==entrypoint(mode),'REFERENCE_EXACT_NEW_ENTRYPOINT_AND_ROLE_MOUNTS')
    return value
def worker_command(name,mode,source,frozen,out,old,capsule,evidence=None):
    need(evidence is not None,'REFERENCE_EXPLICIT_ROLE_EVIDENCE_READONLY_REQUIRED')
    return _body('worker_command')(name,mode,source,frozen,out,old,capsule,evidence)
def resources(*a,**k):return _body('resources')(*a,**k)
def note(*a,**k):return _body('note')(*a,**k)
def reconstruct(*a,**k):return _body('reconstruct')(*a,**k)
def main(args):return _body('main')(args)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','capacity','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
