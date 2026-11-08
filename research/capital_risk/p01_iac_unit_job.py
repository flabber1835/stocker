"""Source-bound stopped orchestration; two-session own628 unit-input qualification."""
import argparse
import ast
import json
import os
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_parallel_discovery import compile_body
from p01_iac_unit_parent import admit,PRIOR,PRIOR_SHA,ROOT_ADMISSION,MAP_IDENTITY,INPUT
from p01_iac_unit_export import (STAGE,RECEIPT_SCHEMA,QUALIFICATION_FILES,
    qualification,qualify_export,write_receipt,preserve_qualification,finish)
import p01_factual_batch_job as previous
from p01_factual_batch_job import (stopped_run,StopUnknown,check_context,validate_prepared_receipt,
    stage_valid,authenticate_capsule,build,write_disjoint,inspector_source,SECRET)

HERE=Path(__file__).parent
REQUEST='p01_iac_unit_request.json';DESCRIPTOR=previous.DESCRIPTOR;SOURCE_MAP=previous.SOURCE_MAP
NEW=('p01_iac_unit_parent.py','p01_iac_unit_epoch.py','p01_iac_unit_contract.py',
    'p01_iac_unit_codec.py','p01_iac_unit_guard.py','p01_iac_unit_component.py','p01_iac_unit_run.py',
    'p01_iac_unit_accounting.py','p01_iac_unit_review.py','p01_iac_unit_job.py',
    'p01_iac_unit_export.py','p01_iac_unit_probe.py','p01_iac_unit_predecessor.json',
    'p01_iac_unit_facts.json','p01_iac_unit_input.json')
SOURCES=tuple(dict.fromkeys((*json.loads((HERE/PRIOR).read_bytes())['sources'],PRIOR,*NEW)))
SOURCE_SHA='7e46e427a910f5b9fa6c53473a508d962c4f2224b3a179165c19efe6a1c925c7'


def expected_request():
    from p01_iac_unit_contract import specification,SPEC,INPUT as INPUT_FILE,END,MAXIMUM,document,encoded
    from p01_iac_unit_parent import digest,sha,INNER
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'P01_IAC_EXACT_PRIOR468_REQUEST')
    prior=json.loads((HERE/PRIOR).read_bytes())
    need(len(prior['sources'])==468 and all(sha256_file(HERE/n)==h for n,h in prior['sources'].items()),
         'P01_IAC_ALL468_OLD_SOURCE_BYTES_UNCHANGED')
    spec=specification();mapping=json.loads((HERE/SOURCE_MAP).read_bytes())
    need(END=='2021-06-29' and MAXIMUM==251 and digest(mapping)==MAP_IDENTITY,'P01_IAC_EXACT_ENDPOINT_AND_SOURCE_MAP')
    raw=(HERE/INPUT_FILE).read_bytes();need(raw==encoded(document()),'P01_IAC_WHOLE_EXACT_TWELFTH_INPUT_DOCUMENT')
    input_sha=sha(raw)
    descriptor=dict(filename=input_sha+'.json',sha256=input_sha,resume_session='2020-06-30',
        predecessor_checkpoint_sha256=INNER)
    successor=digest(dict(base=spec['base'],repairs=[*spec['repairs'],descriptor]))
    return dict(schema='research.p01-own628-iac-unit-request/1',arm='P01',campaign='system-optimization-002',stage=STAGE,
        protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),source_financial_file=SPEC,
        source_financial_sha256=sha256_file(HERE/SPEC),root_admission_descriptor_sha256=ROOT_ADMISSION,
        original_outer_sha256=spec['outer_sha256'],original_inner_sha256=spec['inner_sha256'],
        original_state_sha256=spec['state_sha256'],original_input_sha256=INPUT,original_inputs=11,
        successor_inputs=12,new_typed_factual_input=1,input_document_sha256=input_sha,successor_input_sha256=successor,
        source_epoch_physical_files=516,canonical_source_files=224,source_map_file_sha256=sha256_file(HERE/SOURCE_MAP),
        source_map_identity_sha256=MAP_IDENTITY,prior_source_binding_is_historical_515=True,financial_source_changed=False,
        quote_descriptor=json.loads((HERE/DESCRIPTOR).read_bytes()),quote_descriptor_sha256=sha256_file(HERE/DESCRIPTOR),
        quote_release_asset_id=700454247,actual_quote_transport_sha256='b5b9ff12a66d9ca7bf66c3c934af2e9262924f1e7ca71a026fb78fc86b74bb42',
        capacity_source_sha256='c7e90aa846dae28823d4be6b2ce9fa3092ab48e8346dcf21adb8d8fd7c6e3379',
        no_plaintext_market_response_in_public_sources=True,all_historical_codecs_before_restore=True,
        source_epoch_boundary_reemitted=False,input_adoptions=1,actual_epoch_zero_startup_required=True,
        qualified_full_runtime_sessions=2,qualified_through='2020-07-02',actual_fast_reference_full_components_required=True,
        qualification_state_adoption=False,request_serialization='COPY_EXACT_SOURCE_BYTES',
        financial_start='2020-07-01',processing_endpoint=END,maximum_financial_transitions=MAXIMUM,
        expected_completed=628+MAXIMUM,full_measurement_end='2026-07-31',
        qualification_wait_seconds=2400,financial_wait_seconds=5400,review_wait_seconds=1800,shutdown_reserve_seconds=270,
        financial_step_timeout_minutes=210,workflow_job_timeout_minutes=240,initial_min_disk_bytes=12*1024**3,
        preworker_min_disk_bytes=10*1024**3,preworker_min_memory_bytes=10*1024**3,
        actual_export_marker_before_parent_or_worker=True,artifact_retention_days=7,
        sources={n:sha256_file(HERE/n) for n in SOURCES},production_contacted=False)


def entrypoint(mode):
    need(mode in ('qualify','economic','review'),'P01_IAC_EXACT_MODE')
    return ['-B','-u','/driver/p01_iac_unit_run.py','--mode',mode,'--spec','/out/spec.json']


def check_qualification(proof,request,spec):
    qualification(proof)
    need(proof['epoch_zero_outer_sha256']==spec['outer_sha256']
         and proof['input_document_sha256']==request['input_document_sha256']
         and proof['successor_input_sha256']==request['successor_input_sha256']
         and proof['original_inputs']==request['original_inputs']==11
         and proof['successor_inputs']==request['successor_inputs']==12
         and proof['component_transitions']==request['qualified_full_runtime_sessions']==2
         and proof['qualified_through']==request['qualified_through']=='2020-07-02'
         and all(proof[k] is True for k in ('unit_normalization_qualified',
             'unit_target_independence_qualified','source_scope_falsifiers_qualified')),
         'P01_IAC_ACTUAL_OWN628_AND_EXACT_TWELFTH_INPUT_QUALIFIER_BINDING')


def check_financial_input(outcome,proof,request):
    need(all(type(outcome[k]) is int for k in ('original_inputs','successor_inputs','input_adoptions','maximum_transitions'))
         and outcome['input_document_sha256']==proof['input_document_sha256']==request['input_document_sha256']
         and outcome['successor_input_sha256']==proof['successor_input_sha256']==request['successor_input_sha256']
         and outcome['original_inputs']==11 and outcome['successor_inputs']==12
         and outcome['fresh_from_original628'] is True and outcome['qualification_state_adopted'] is False
         and outcome['source_epoch_boundary_reemitted'] is False
         and type(outcome['input_adoptions']) is int and outcome['input_adoptions']==1
         and outcome['maximum_transitions']==request['maximum_financial_transitions']==251
         and outcome['processing_endpoint']==request['processing_endpoint']=='2021-06-29'
         and outcome['full_measurement_end']==request['full_measurement_end']=='2026-07-31',
         'P01_IAC_FRESH_FINANCE_EXACT_QUALIFIED_TWELFTH_INPUT_AND_SCOPE')


def _body(name):
    raw=Path(previous.__file__).read_bytes();need(sha256_file(Path(previous.__file__))==SOURCE_SHA,'P01_IAC_FROZEN_HOST_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    gates=[];imports=[]
    class Scope(ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.module=='p01_factual_batch_contract':node.module='p01_iac_unit_contract';imports.append(node)
            return node
        def visit_Constant(self,node):
            if type(node.value) is str:
                value=node.value.replace('p01-factual-batch','p01-iac-unit').replace('P01_BATCH_','P01_IAC_')
                value={'batch-outcome.json':'iac-unit-outcome.json',
                    'COMPLETE_FACTUAL_BATCH_SEGMENT_PENDING_REVIEW':'COMPLETE_IAC_UNIT_SEGMENT_PENDING_REVIEW',
                    'EPOCH_INPUT_QUALIFICATION_LAUNCH_ATTEMPTED':'EPOCH_INPUT_UNIT_QUALIFICATION_LAUNCH_ATTEMPTED',
                    'EPOCH_INPUT_QUALIFIED_ORIGINAL526_NOT_ADVANCED':'EPOCH_INPUT_UNIT_QUALIFIED_ORIGINAL628_NOT_ADVANCED',
                    'FRESH_OWN526_FINANCIAL_LAUNCH_ATTEMPTED':'FRESH_OWN628_FINANCIAL_LAUNCH_ATTEMPTED',
                    'FACTUAL_BATCH_REFUSED_KNOWN_STOP':'IAC_UNIT_REFUSED_KNOWN_STOP',
                    'FACTUAL_BATCH_REFUSED_BEFORE_STOP_PROOF':'IAC_UNIT_REFUSED_BEFORE_STOP_PROOF'}.get(value,value)
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
         and len(imports)==(1 if name=='main' else 0),'P01_IAC_EXACT_DECLARED_HOST_ADAPTATION_SITES')
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
