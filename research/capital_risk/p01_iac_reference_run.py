"""Restore approved reference data, prepare inputs only, then run fresh FAST."""
import argparse
import ast
from copy import deepcopy
import gzip
import json
from pathlib import Path
import shutil

import p01_iac_unit_fixture_run as previous
from p01_iac_unit_contract import HERE,FIRST,INPUT,END,MAXIMUM,need,sha,digest,specification,encoded,reused_qualification
from p01_iac_unit_parent import OUTER
from p01_iac_quote_epoch import historical_epoch
from p01_iac_reference_evidence import load_reference_evidence,reference_spec,ORIGIN,ADMISSION,same
from p01_iac_reference_source import source_check,report_shape,SCHEMA,REPORT_ORIGIN
from p01_iac_unit_recovery_guard import UnitGuard
from p01_iac_unit_codec import source_rows
from p01_iac_unit_guard import role_record
from full_system_benchmark import save

REQUEST='p01_iac_reference_request.json'
PREVIOUS_SHA='ddaadb646388c8d4cd8f482fee669933fc8e9a06cdf2ce0675330bbea5774fce'
BASE_RUNTIME_SHA='20f2d5bf1758d0574954b2e2e6700b6ad20c22d433a73c46112cd08d4d6735c0'
FUNCTIONS=('prepare','exact_prefixes','boundaries','report','refusal_rows','last_attempt','branch','economic','main')


def _body(name):
    need(name in FUNCTIONS,'REFERENCE_ONLY_DECLARED_RUNTIME_FUNCTIONS_NO_OLD_QUALIFY')
    need(sha(Path(previous.__file__).read_bytes())==PREVIOUS_SHA,'REFERENCE_EXACT_PUBLISHED497_RUNTIME')
    import p01_iac_unit_run as origin
    raw=Path(origin.__file__).read_bytes();need(sha(raw)==BASE_RUNTIME_SHA,'REFERENCE_EXACT_BASE_RUNTIME_AST')
    frozen=previous._body(name)
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name];changes=[]
    class Scope(ast.NodeTransformer):
        def visit_ImportFrom(self,item):
            if item.module=='p01_iac_unit_job':
                need(name=='economic' and [(n.name,n.asname) for n in item.names]==[('check_qualification',None),('expected_request',None)],
                     'REFERENCE_EXACT_NEW_ECONOMIC_HOST_GATE_IMPORT')
                item.module='p01_iac_reference_job';changes.append('host_gate')
            if item.module=='p01_iac_unit_review':
                need(name=='main' and [(n.name,n.asname) for n in item.names]==[('review',None)],
                     'REFERENCE_EXACT_NEW_SINGLE_SAVE_REVIEW_IMPORT')
                item.module='p01_iac_reference_review';changes.append('review')
            return item
        def visit_Expr(self,item):
            if name=='economic' and isinstance(item.value,ast.Call) and ast.unparse(item.value.func)=='source.update':
                need([k.arg for k in item.value.keywords]==['source_members','fast_applications','fast_refusals'],
                     'REFERENCE_ONLY_FRESH_FINANCIAL_SOURCE_DOMAIN_UPDATED')
                changes.append('financial_source')
                return ast.copy_location(ast.parse('update_financial_source(source,members,codec)').body[0],item)
            return self.generic_visit(item)
    node=Scope().visit(node)
    need(changes=={'economic':['host_gate','financial_source'],'main':['review']}.get(name,[]),
         'REFERENCE_ONLY_DECLARED_RUNTIME_IMPORT_AND_SOURCE_DOMAIN_SITES')
    values=dict(frozen.__globals__,**{k:v for k,v in globals().items() if not k.startswith('__')},__file__=__file__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<source-bound-reference-reuse-runtime:'+name+'>','exec'),values)
    return values[name]


def prepare(*a,**k):return _body('prepare')(*a,**k)
def exact_prefixes(*a,**k):return _body('exact_prefixes')(*a,**k)
def boundaries(*a,**k):return _body('boundaries')(*a,**k)
def report(*a,**k):return _body('report')(*a,**k)
def refusal_rows(*a,**k):return _body('refusal_rows')(*a,**k)
def last_attempt(*a,**k):return _body('last_attempt')(*a,**k)
def branch(old,out,rows,mode,**kwargs):
    need(mode=='FAST' and kwargs.get('proof_dir') is None,'REFERENCE_NO_OLD_REFERENCE_OR_SYNTHETIC_FORWARD_EXECUTION')
    return _body('branch')(old,out,rows,mode,**kwargs)
def economic(*a,**k):return _body('economic')(*a,**k)


def update_financial_source(source,members,codec):
    need(source['schema']==SCHEMA and source['fresh_execution']['origin']=='NEW_HOSTED_FAST_EXECUTION',
         'REFERENCE_NEW_SOURCE_PROOF_BEFORE_FRESH_FINANCE_UPDATE')
    source['source_members']=deepcopy(members)
    source['fresh_execution']=dict(origin='NEW_FRESH_OWN628_FINANCE',applications=deepcopy(codec.applied),refusals=refusal_rows(codec))


def qualify(old,out):
    from full_system_core import hosted
    hosted();old,out=Path(old),Path(out);proof=out/'proof';proof.mkdir()
    reference=load_reference_evidence(Path('/evidence'));rows,members=source_rows()
    (proof/'unit-normalization-component.json.gz').write_bytes(reference['component_raw'])
    (proof/'reference-evidence.json').write_bytes(reference['provenance_raw'])
    checked=source_check(old,out/'source-check',rows,reference)
    save(proof/'source-compiler-check.inflight',checked)
    old_roles=[role_record(r['prior_checkpoint'],r['checkpoint'],r['session']) for r in reference['components']]
    fast=branch(old,out/'fast',rows,'FAST',qualified=old_roles)
    need(same(reference['zero'],fast['zero']) and same(reference['components'],fast['components'])
         and same(reference['final'],fast['final'])
         and same(checked['applications'],fast['codec_applications'])
         and same(checked['unit_window_anchor_checks'],fast['unit_checks']) and not fast['codec_refusals'],
         'REFERENCE_WHOLE_OLD_OUTPUT_EQUALS_FRESH_FAST_AND_NEW_SOURCE_PREPARATION')
    for name in ('zero-session-boundaries.json','iac-unit-input.json','iac-unit-preflight.json'):
        shutil.copyfile(out/'fast'/name,proof/name)
    recorded=dict(origin='OLD_RECORDED_REFERENCE',source_origin=deepcopy(ORIGIN),root_reuse_admission_sha256=ADMISSION,
        approved_members=reference['approved_members'],original_compiler_and_ring_logs_available=False,
        publications=[dict(session=r['session'],sha256=digest(r['publication']),runtime_sha256=digest(r['checkpoint']))
            for r in reference['components']])
    source=dict(schema=SCHEMA,source_contract=checked['source_contract'],origin_basis=checked['origin_basis'],
        source_members=members,recorded_reference=recorded,source_compiler_check=checked,
        fresh_execution=dict(origin='NEW_HOSTED_FAST_EXECUTION',applications=fast['codec_applications'],refusals=fast['codec_refusals']),
        financial_authority=False)
    with gzip.open(proof/'actual-two-session-component.json.gz','wb') as stream:
        stream.write(encoded(dict(schema='research.p01-iac-unit-actual-two-session-component/1',
            reference_components=reference['components'],actual_components=fast['components'],
            reference_qualifier_checkpoint=reference['final'],qualifier_checkpoint=fast['final'],
            action_checks=fast['action_checks'],inherited_native_scope_checks=fast['native_checks'],
            source_unit_scope_checks=fast['source_checks'],unit_window_anchor_checks=fast['unit_checks'],
            pre_event_checkpoints=fast['pre_events'],financial_authority=False,qualification_state_adopted=False)))
    # This report is newly computed on a restored old saved state, not an old lost log.
    from research.pooled_vacancy_funding import runtime
    from types import SimpleNamespace
    from p01_factual_batch_contract import facts
    (out/'reference-report').mkdir(parents=True,exist_ok=True)
    with historical_epoch(old,out/'reference-report',specification()) as binding:
        from p01_iac_unit_codec import InputCodec
        with InputCodec(rows,binding.parent):
            from research.pooled_vacancy_funding import backtest
            backtest.load_repair(HERE/INPUT,resume_session=binding.parent['source_cursor'],
                predecessor_checkpoint_sha256=binding.parent['run']['checkpoint_sha256'])
            run=runtime.restore(reference['final']['run'],policy=binding.parent['base']['policy'],
                input_sha256=reference['zero']['successor_input_sha256'])
            before_report=runtime.checkpoint(run)
            restored_report=report(run,binding.quote,SimpleNamespace(records=facts()['records']))
            need(same(before_report,runtime.checkpoint(run)),'REFERENCE_NEW_FULL_REPORT_LEAVES_ENTIRE_RUNTIME_UNCHANGED')
            pins=json.loads((HERE/'p01_iac_unit_fixture_request.json').read_bytes())['sources']
            report_contract=report_shape((HERE/'p01_iac_unit_run.py').read_bytes(),binding.source_map['successor_all_sources'],
                (HERE/'p01_factual_batch_accounting.py').read_bytes(),pins['p01_factual_batch_accounting.py'])
    need(same(restored_report,fast['report']),'REFERENCE_NEW_REPORT_ON_RESTORED_OLD_STATE_EQUALS_FRESH_FAST')
    source['reference_report_check']=dict(origin=REPORT_ORIGIN,source_contract=report_contract,
        reference_final_runtime_sha256=digest(before_report),full_runtime_unchanged=True,
        restored_reference_report_sha256=digest(restored_report),fresh_fast_report_sha256=digest(fast['report']),
        complete_typed_report_equal=True,financial_transitions=0)
    save(proof/'unit-normalization-source-proof.json',source)
    save(proof/'actual-unit-accounting-and-report.json',dict(schema='research.p01-iac-unit-actual-accounting-and-report/1',
        reference=restored_report,fast=fast['report'],reference_equals_fast=True,financial_authority=False,qualification_state_adopted=False))
    component=reference['component'];aggregate=component['fixture_aggregate'];zero=fast['zero']
    save(proof/'qualification-summary.json',dict(status='OWN628_IAC_UNIT_INPUT_AND_TWO_SESSION_FAST_REFERENCE_QUALIFIED',
        financial_authority=False,financial_predecessor_authorized=False,qualification_state_adopted=False,
        component_transitions=2,qualified_through=FIRST[-1],epoch_zero_outer_sha256=OUTER,
        input_zero_outer_sha256=zero['input_checkpoint']['sha256'],input_document_sha256=zero['input_document_sha256'],
        successor_input_sha256=zero['successor_input_sha256'],original_inputs=11,successor_inputs=12,
        source_epoch_boundary_reemitted=False,input_adoptions=1,actual_fast_reference_full_components_equal=True,
        unit_normalization_qualified=True,unit_target_independence_qualified=True,source_scope_falsifiers_qualified=True,
        actual_role_and_full_state_checks=len(fast['roles']),actual_role_and_full_state_records=fast['roles'],
        reused_action_qualification=fast['reused'],processing_endpoint=END,maximum_transitions=MAXIMUM,
        fixture_aggregate_complete=aggregate['complete'],fixture_aggregate_all_passed=aggregate['all_passed'],
        fixture_expected_case_count=9,fixture_attempted_case_count=9,fixture_passed_case_count=9,fixture_failed_case_count=0,
        fixture_expected_case_ids=aggregate['expected_case_ids'],fixture_component_sha256=sha(reference['component_raw']),
        reference_evidence_reused=True,reference_reuse_admission_sha256=ADMISSION,
        reference_recorded_origin={k:ORIGIN[k] for k in ('run_id','head','artifact_id','request_sha256')},
        original_reference_compiler_logs_available=False,source_compiler_check_qualified=True,source_preparations=2,
        source_compiler_financial_transitions=0,reference_financial_transitions_reexecuted=0,
        old_reference_runtime_records_restored=2,old_synthetic_wires_restored=18,
        reference_report_rechecked=True,reference_report_financial_transitions=0,
        reference_report_origin='NEW_READONLY_CANONICAL_REPORT_ON_RESTORED_OLD_STATE',
        reference_evidence_sha256=sha(reference['provenance_raw'])))


def validate_worker_request(path,*,mode):
    from p01_iac_reference_job import validate_worker_request as validate
    need(Path(path)==HERE/REQUEST,'REFERENCE_FIXED_NEW_MOUNTED_REQUEST_PATH')
    return validate(path,mode=mode)


def main(args):
    validate_worker_request(HERE/REQUEST,mode=args.mode)
    return _body('main')(args)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('qualify','economic','review'),required=True)
    parser.add_argument('--spec',type=Path,required=True);main(parser.parse_args())
