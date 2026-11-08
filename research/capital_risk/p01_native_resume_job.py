"""Source-bound stopped orchestration; one-session native627 qualification."""
import argparse
import ast
import json
import os
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_parallel_discovery import compile_body
from p01_native_resume_parent import admit,PRIOR,PRIOR_SHA,ROOT_ADMISSION,MAP_IDENTITY,INPUT
from p01_native_resume_export import (STAGE,RECEIPT_SCHEMA,QUALIFICATION_FILES,
    qualification,qualify_export,write_receipt,preserve_qualification,finish)
import p01_factual_batch_job as previous
from p01_factual_batch_job import (stopped_run,StopUnknown,check_context,validate_prepared_receipt,
    stage_valid,authenticate_capsule,build,write_disjoint,inspector_source,SECRET)

HERE=Path(__file__).parent
REQUEST='p01_native_resume_request.json';DESCRIPTOR=previous.DESCRIPTOR;SOURCE_MAP=previous.SOURCE_MAP
NEW=('p01_native_resume_parent.py','p01_native_resume_epoch.py','p01_native_resume_contract.py',
    'p01_native_resume_guard.py','p01_native_resume_run.py','p01_native_resume_accounting.py',
    'p01_native_resume_review.py','p01_native_resume_job.py','p01_native_resume_export.py',
    'p01_native_resume_probe.py','p01_native_resume_predecessor.json')
SOURCES=tuple(dict.fromkeys((*json.loads((HERE/PRIOR).read_bytes())['sources'],PRIOR,*NEW)))
SOURCE_SHA='7e46e427a910f5b9fa6c53473a508d962c4f2224b3a179165c19efe6a1c925c7'


def expected_request():
    from p01_native_resume_contract import specification,SPEC,END,MAXIMUM
    from p01_native_resume_parent import digest
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'P01_NATIVE_EXACT_PRIOR456_REQUEST')
    prior=json.loads((HERE/PRIOR).read_bytes())
    need(len(prior['sources'])==456 and all(sha256_file(HERE/n)==h for n,h in prior['sources'].items()),
         'P01_NATIVE_ALL456_OLD_SOURCE_BYTES_UNCHANGED')
    spec=specification();mapping=json.loads((HERE/SOURCE_MAP).read_bytes())
    need(END=='2020-06-30' and MAXIMUM==1 and digest(mapping)==MAP_IDENTITY,'P01_NATIVE_EXACT_ENDPOINT_AND_SOURCE_MAP')
    return dict(schema='research.p01-own627-native-resume-request/1',arm='P01',campaign='system-optimization-002',stage=STAGE,
        protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),source_financial_file=SPEC,
        source_financial_sha256=sha256_file(HERE/SPEC),root_admission_descriptor_sha256=ROOT_ADMISSION,
        original_outer_sha256=spec['outer_sha256'],original_inner_sha256=spec['inner_sha256'],
        original_state_sha256=spec['state_sha256'],original_input_sha256=INPUT,original_inputs=11,new_typed_factual_input=0,
        source_epoch_physical_files=516,canonical_source_files=224,source_map_file_sha256=sha256_file(HERE/SOURCE_MAP),
        source_map_identity_sha256=MAP_IDENTITY,prior_source_binding_is_historical_515=True,financial_source_changed=False,
        quote_descriptor=json.loads((HERE/DESCRIPTOR).read_bytes()),quote_descriptor_sha256=sha256_file(HERE/DESCRIPTOR),
        quote_release_asset_id=700454247,actual_quote_transport_sha256='b5b9ff12a66d9ca7bf66c3c934af2e9262924f1e7ca71a026fb78fc86b74bb42',
        capacity_source_sha256='c7e90aa846dae28823d4be6b2ce9fa3092ab48e8346dcf21adb8d8fd7c6e3379',
        no_plaintext_market_response_in_public_sources=True,all_historical_codecs_before_restore=True,
        source_epoch_boundary_reemitted=False,input_boundary_reemitted=False,actual_epoch_zero_startup_required=True,
        qualified_full_runtime_sessions=1,qualification_state_adoption=False,request_serialization='COPY_EXACT_SOURCE_BYTES',
        financial_start='2020-06-30',processing_endpoint=END,maximum_financial_transitions=MAXIMUM,
        expected_completed=627+MAXIMUM,full_measurement_end='2026-07-31',
        qualification_wait_seconds=2400,financial_wait_seconds=5400,review_wait_seconds=1800,shutdown_reserve_seconds=270,
        financial_step_timeout_minutes=210,workflow_job_timeout_minutes=240,initial_min_disk_bytes=12*1024**3,
        preworker_min_disk_bytes=10*1024**3,preworker_min_memory_bytes=10*1024**3,
        actual_export_marker_before_parent_or_worker=True,artifact_retention_days=7,
        sources={n:sha256_file(HERE/n) for n in SOURCES},production_contacted=False)


def entrypoint(mode):
    need(mode in ('qualify','economic','review'),'P01_NATIVE_EXACT_MODE')
    return ['-B','-u','/driver/p01_native_resume_run.py','--mode',mode,'--spec','/out/spec.json']


def check_qualification(proof,request,spec):
    qualification(proof)
    need(proof['epoch_zero_outer_sha256']==spec['outer_sha256']
         and proof['original_input_sha256']==request['original_input_sha256']
         and proof['original_inputs']==request['original_inputs']
         and proof['component_transitions']==request['qualified_full_runtime_sessions']==1
         and proof['qualified_through']==request['processing_endpoint']=='2020-06-30'
         and request['maximum_financial_transitions']==1 and request['expected_completed']==628,
         'P01_NATIVE_ACTUAL_OWN627_QUALIFIER_BINDING')


def check_financial_input(outcome,proof,request):
    need(outcome['original_input_sha256']==proof['original_input_sha256']==request['original_input_sha256']
         and outcome['original_inputs']==proof['original_inputs']==11
         and outcome['source_epoch_boundary_reemitted'] is False and outcome['input_boundary_reemitted'] is False,
         'P01_NATIVE_FRESH_FINANCE_RETAINS_SAME_ELEVEN_INPUTS')


def _body(name):
    raw=Path(previous.__file__).read_bytes();need(sha256_file(Path(previous.__file__))==SOURCE_SHA,'P01_NATIVE_FROZEN_HOST_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    gates=[];imports=[]
    class Scope(ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.module=='p01_factual_batch_contract':node.module='p01_native_resume_contract';imports.append(node)
            return node
        def visit_Constant(self,node):
            if type(node.value) is str:
                value=node.value.replace('p01-factual-batch','p01-native-resume').replace('P01_BATCH_','P01_NATIVE_')
                value={'batch-outcome.json':'native-resume-outcome.json',
                    'COMPLETE_FACTUAL_BATCH_SEGMENT_PENDING_REVIEW':'COMPLETE_NATIVE_RESUME_SEGMENT_PENDING_REVIEW',
                    'EPOCH_INPUT_QUALIFICATION_LAUNCH_ATTEMPTED':'EPOCH_ZERO_QUALIFICATION_LAUNCH_ATTEMPTED',
                    'EPOCH_INPUT_QUALIFIED_ORIGINAL526_NOT_ADVANCED':'EPOCH_QUALIFIED_ORIGINAL627_NOT_ADVANCED',
                    'FRESH_OWN526_FINANCIAL_LAUNCH_ATTEMPTED':'FRESH_OWN627_FINANCIAL_LAUNCH_ATTEMPTED',
                    'FACTUAL_BATCH_REFUSED_KNOWN_STOP':'NATIVE_RESUME_REFUSED_KNOWN_STOP',
                    'FACTUAL_BATCH_REFUSED_BEFORE_STOP_PROOF':'NATIVE_RESUME_REFUSED_BEFORE_STOP_PROOF'}.get(value,value)
                node.value=value
            return node
        def visit_Expr(self,node):
            labels={n.value for n in ast.walk(node) if isinstance(n,ast.Constant) and type(n.value) is str}
            if 'P01_BATCH_ACTUAL_FULL_RUNTIME_QUALIFIER_GATE' in labels:
                gates.append('qualifier');return ast.copy_location(ast.parse('check_qualification(proof,request,specification())').body[0],node)
            if 'P01_BATCH_FRESH_FINANCE_SAME_QUALIFIED_INPUT' in labels:
                gates.append('financial_input');return ast.copy_location(ast.parse('check_financial_input(outcome,proof,request)').body[0],node)
            return self.generic_visit(node)
    fn=Scope().visit(fn)
    need(gates==(['qualifier','financial_input'] if name=='main' else [])
         and len(imports)==(1 if name=='main' else 0),'P01_NATIVE_EXACT_DECLARED_HOST_ADAPTATION_SITES')
    namespace=dict(vars(previous),**{k:v for k,v in globals().items() if not k.startswith('__')},__file__=__file__)
    return compile_body(fn,namespace)


def inspect(name,identity=None):return _body('inspect')(name,identity)
def worker_command(name,mode,source,frozen,out,old,capsule,evidence=None):
    return _body('worker_command')(name,mode,source,frozen,out,old,capsule,evidence)
def resources(request,temp):return _body('resources')(request,temp)
def note(path,phase,error=None):return _body('note')(path,phase,error)
def reconstruct(frozen,old,temp):return _body('reconstruct')(frozen,old,temp)
freeze=previous.freeze;collect_stop=previous.collect_stop
def main(args):return _body('main')(args)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','capacity','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
