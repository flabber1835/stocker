"""Own628 Buffer-context recovery host; full new request before old runtime."""
import argparse
import ast
import json
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
import p01_iac_unit_job as previous
from p01_iac_unit_recovery_export import (STAGE,RECEIPT_SCHEMA,QUALIFICATION_FILES,qualification,
    qualify_export,write_receipt,preserve_qualification,finish)

HERE=Path(__file__).parent
REQUEST='p01_iac_unit_recovery_request.json'
PRIOR_REQUEST='p01_iac_unit_request.json'
PRIOR_SHA='78dd0816f37f51e01014cba5978eec0ff858b01d4d47869ed5649b39d11eb127'
BASE_SHA='b61e8a1af67cf63b6e4420acdcb513c035157012c123057bed0875627ad4a401'
WORKFLOW='p01_iac_unit_recovery_financial.yml'
WORKFLOW_SHA='24afc6f39c07b5e0b2160eff61ebb625f948cb167fb9b60cc906a14c027cf1b6'
NEW=('p01_iac_unit_recovery_guard.py','p01_iac_unit_recovery_run.py',
    'p01_iac_unit_recovery_job.py','p01_iac_unit_recovery_export.py','p01_iac_unit_recovery_probe.py')
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
    raw=(HERE/PRIOR_REQUEST).read_bytes()
    need(sha256_file(HERE/PRIOR_REQUEST)==PRIOR_SHA,'RECOVERY_EXACT_PUBLIC_484_REQUEST_BYTES')
    prior=json.loads(raw)
    need(len(prior['sources'])==484 and prior==previous.expected_request()
         and all(sha256_file(HERE/n)==h for n,h in prior['sources'].items()),
         'RECOVERY_WHOLE_OLD484_MODEL_AND_EVERY_SOURCE_BYTE')
    result=dict(prior,schema='research.p01-own628-iac-unit-buffer-recovery-request/1',stage=STAGE,
        prior_request_file=PRIOR_REQUEST,prior_request_sha256=PRIOR_SHA,prior_driver_sources=484,
        actual_entrypoint='/driver/p01_iac_unit_recovery_run.py',worker_namespace='capital-system-p01-iac-unit-recovery',
        workflow=WORKFLOW,owner_workflow_sha256=WORKFLOW_SHA,
        recovery_reason='FROZEN_ADAPTER_BUFFER_IDENTITY_NOT_BACKTEST_MODULE_GLOBAL',
        failed_qualification_run_id=41444401941,failed_qualification_artifact_id=13141317500,
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
    return ['-B','-u','/driver/p01_iac_unit_recovery_run.py','--mode',mode,'--spec','/out/spec.json']


def check_qualification(proof,request,spec):
    qualification(proof)
    return previous.check_qualification(proof,request,spec)


def check_financial_input(outcome,proof,request):return previous.check_financial_input(outcome,proof,request)


def _body(name):
    raw=Path(previous.__file__).read_bytes()
    need(sha256_file(Path(previous.__file__))==BASE_SHA,'RECOVERY_SOURCE_BOUND_484_ORCHESTRATION')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='_body']
    node.name='_recovery_host_body'
    class Namespace(ast.NodeTransformer):
        def visit_Constant(self,item):
            if type(item.value) is str:item.value=item.value.replace('p01-iac-unit','p01-iac-unit-recovery')
            return item
    node=Namespace().visit(node)
    values=dict(vars(previous),**{k:v for k,v in globals().items() if not k.startswith('__')})
    values.update(previous=previous.previous,SOURCE_SHA=previous.SOURCE_SHA,__file__=__file__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<source-bound-recovery-host-builder>','exec'),values)
    return values['_recovery_host_body'](name)


def inspect(*a,**k):return _body('inspect')(*a,**k)
def worker_command(*a,**k):return _body('worker_command')(*a,**k)
def resources(*a,**k):return _body('resources')(*a,**k)
def note(*a,**k):return _body('note')(*a,**k)
def reconstruct(*a,**k):return _body('reconstruct')(*a,**k)
def main(args):return _body('main')(args)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','capacity','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
