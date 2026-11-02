"""Host only: qualify retained epoch/input, then freshly continue OWN526."""
import argparse
import ast
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from full_system_benchmark import need
from alpaca_fit_job import stopped_run, StopUnknown
from probe import check_context, memory_bytes
from seal import sha256_file
from stage import SECRET
from system_campaign_variants import build
from system_campaign_parallel_discovery_job import stage_valid
from system_campaign_parallel_discovery import compile_body
from p01_epoch_parent import admit, PRIOR, PRIOR_SHA, MAP_IDENTITY, ROOT_ADMISSION
from p01_celg_bridge_source import write_disjoint
from p01_celg_input_transport import authenticate_capsule
from ephemeral_runner_capacity import validate_prepared_receipt
from p01_factual_batch_export import (STAGE, RECEIPT_SCHEMA, QUALIFICATION_FILES,
    qualify_export, write_receipt, preserve_qualification, finish)
import p01_action_clock_job as phases
import system_campaign_p02_continue_job as inspector_source

HERE=Path(__file__).parent
REQUEST='p01_factual_batch_request.json'
DESCRIPTOR='p01_celg_bridge_quote_descriptor.json'
SOURCE_MAP='p01_celg_bridge_source_map.json'
NEW=('p01_epoch_parent.py','p01_epoch_resume.py','p01_factual_batch_predecessor.json',
    'p01_factual_batch_facts.json','p01_factual_batch_contract.py','p01_factual_batch_codec.py',
    'p01_factual_batch_guard.py','p01_factual_batch_pause.py','p01_factual_batch_component.py',
    'p01_factual_batch_run.py','p01_factual_batch_accounting.py','p01_factual_batch_review.py',
    'p01_factual_batch_job.py','p01_factual_batch_export.py','p01_factual_batch_probe.py','p01_factual_batch_input.json')
SOURCES=tuple(dict.fromkeys((*json.loads((HERE/PRIOR).read_bytes())['sources'],PRIOR,*NEW)))


def expected_request():
    from p01_factual_batch_contract import specification, document, SPEC, INPUT, END, MAXIMUM
    from p01_epoch_parent import digest
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA, 'P01_BATCH_EXACT_PRIOR439_REQUEST')
    prior=json.loads((HERE/PRIOR).read_bytes())
    need(len(prior['sources'])==439 and all(sha256_file(HERE/n)==h for n,h in prior['sources'].items()),
         'P01_BATCH_ALL439_SOURCE_BYTES_UNCHANGED')
    spec=specification();descriptor=json.loads((HERE/DESCRIPTOR).read_bytes())
    mapping=json.loads((HERE/SOURCE_MAP).read_bytes())
    need(END=='2020-06-29' and MAXIMUM==101 and digest(mapping)==MAP_IDENTITY,
         'P01_BATCH_EXACT_BOUNDED_ENDPOINT_AND_RETAINED_SOURCE_MAP')
    need(json.loads((HERE/INPUT).read_bytes())==document(), 'P01_BATCH_EXACT_STATIC_TYPED_INPUT')
    return dict(schema='research.p01-own526-grouped-factual-request/1',arm='P01',campaign='system-optimization-002',
        stage=STAGE,protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        source_financial_file=SPEC,source_financial_sha256=sha256_file(HERE/SPEC),
        root_admission_descriptor_sha256=ROOT_ADMISSION,original_outer_sha256=spec['outer_sha256'],
        original_inner_sha256=spec['inner_sha256'],original_state_sha256=spec['state_sha256'],
        original_input_sha256=spec['input_sha256'],original_inputs=10,new_typed_factual_input=1,
        input_document_file=INPUT,input_document_sha256=sha256_file(HERE/INPUT),
        input_document_model_sha256=digest(document()),source_epoch_physical_files=516,canonical_source_files=224,
        source_map_file_sha256=sha256_file(HERE/SOURCE_MAP),source_map_identity_sha256=MAP_IDENTITY,
        prior_source_binding_is_historical_515=True,financial_source_changed=False,
        quote_descriptor=descriptor,quote_descriptor_sha256=sha256_file(HERE/DESCRIPTOR),quote_release_asset_id=700454247,
        actual_quote_transport_sha256='b5b9ff12a66d9ca7bf66c3c934af2e9262924f1e7ca71a026fb78fc86b74bb42',
        capacity_source_sha256='c7e90aa846dae28823d4be6b2ce9fa3092ab48e8346dcf21adb8d8fd7c6e3379',
        no_plaintext_market_response_in_public_sources=True,all_historical_codecs_before_restore=True,
        source_epoch_boundary_reemitted=False,actual_epoch_zero_startup_required=True,
        qualified_full_runtime_sessions=2,qualification_state_adoption=False,
        request_serialization='COPY_EXACT_SOURCE_BYTES',financial_start='2020-02-05',processing_endpoint=END,
        maximum_financial_transitions=MAXIMUM,expected_completed=526+MAXIMUM,full_measurement_end='2026-07-31',
        qualification_wait_seconds=2400,financial_wait_seconds=5400,review_wait_seconds=1800,
        shutdown_reserve_seconds=270,financial_step_timeout_minutes=210,workflow_job_timeout_minutes=240,
        initial_min_disk_bytes=12*1024**3,preworker_min_disk_bytes=10*1024**3,preworker_min_memory_bytes=10*1024**3,
        actual_export_marker_before_parent_or_worker=True,artifact_retention_days=7,
        sources={n:sha256_file(HERE/n) for n in SOURCES},production_contacted=False)


def entrypoint(mode):
    need(mode in ('qualify','economic','review'), 'P01_BATCH_EXACT_MODE')
    return ['-B','-u','/driver/p01_factual_batch_run.py','--mode',mode,'--spec','/out/spec.json']


def inspect(name,identity=None):
    raw=Path(inspector_source.__file__).read_bytes()
    need(sha256_file(Path(inspector_source.__file__))==json.loads((HERE/PRIOR).read_bytes())['sources'][
        'system_campaign_p02_continue_job.py'], 'P01_BATCH_FROZEN_INSPECTOR')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='inspect']
    site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value==
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1']
    site.value=r'capital-system-p01-factual-batch-(?:qualify|worker|review)-[0-9]+-1'
    assignment,=[n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='expected' for t in n.targets)]
    assignment.value=ast.parse("{'/variant','/frozen','/driver','/out','/old','/celg-input','/celg-input-descriptor.json'} | (set() if '-qualify-' in name else {'/evidence'})",mode='eval').body
    value=compile_body(fn,vars(inspector_source))(name,identity)
    mode='qualify' if '-qualify-' in name else 'review' if '-review-' in name else 'economic'
    need(value['Config']['Cmd']==entrypoint(mode), 'P01_BATCH_EXACT_WORKER_ENTRYPOINT')
    return value


def worker_command(name,mode,source,frozen,out,old,capsule,evidence=None):
    from system_campaign_p01_accurate_job import worker_command as original
    values=original(name,'review' if mode=='review' else 'economic',source,frozen,out,old,evidence)
    index=values.index('--entrypoint')
    values[index:index]=['--mount',f'type=bind,source={capsule},target=/celg-input,readonly',
        '--mount',f'type=bind,source={HERE/DESCRIPTOR},target=/celg-input-descriptor.json,readonly']
    values[values.index('-B'):]=entrypoint(mode)
    return values


def resources(request,temp):
    need(memory_bytes()['MemAvailable']>=request['preworker_min_memory_bytes']
         and shutil.disk_usage(temp).free>=request['preworker_min_disk_bytes'], 'P01_BATCH_PREWORKER_RESERVE')


def note(path,phase,error=None):
    fn,=[n for n in ast.parse(Path(phases.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='note']
    site,=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='research.p01-action-clock-public-phase/1']
    site.value='research.p01-factual-batch-public-phase/1'
    return compile_body(fn,dict(vars(phases),AUTHORITY='NONFINANCIAL_HOST_PHASE_METADATA',
        PHASES=phases.PHASES|{'QUALIFIER_LAUNCH_ATTEMPTED','QUALIFIER_STOPPED','FINANCIAL_LAUNCH_ATTEMPTED',
            'FINANCIAL_STOPPED','REVIEW_LAUNCH_ATTEMPTED','REVIEW_STOPPED','REVIEW_STOP_UNKNOWN'},
        PUBLIC_CODES=phases.PUBLIC_CODES|{'REFUSED_FULL_SYSTEM_P01_BATCH_INITIAL_RESERVE',
            'REFUSED_FULL_SYSTEM_P01_BATCH_PREWORKER_RESERVE'}))(path,phase,error)


def freeze(root):
    for p in Path(root).rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
    os.chmod(root,0o555)


def collect_stop(source,destination,receipt,role):
    """Only call after stopped_run returned its durable actual inspection."""
    source,destination=Path(source),Path(destination);destination.mkdir(parents=True,exist_ok=True)
    need((source/'worker-inspect.json').is_file(), 'P01_BATCH_DURABLE_INSPECTION_BEFORE_COPY')
    for name in ('worker-inspect.json','worker.log','log-copy-failure.json'):
        if (source/name).exists():shutil.copyfile(source/name,destination/name)
    failed=(source/'log-copy-failure.json').exists()
    need((source/'worker.log').exists() or failed, 'P01_BATCH_LOG_OR_EXPLICIT_LOG_FAILURE')
    receipt[role+'_log_copy_failed']=failed


def reconstruct(frozen,old,temp):
    binding=json.loads((old/'source-bindings.json').read_bytes())
    mapping=json.loads((old/'source-map.json').read_bytes())
    original=temp/'p01-factual-batch-original515';source=temp/'p01-factual-batch-current516'
    need(build(frozen/'source-fixed',original,binding['parameters'])==binding, 'P01_BATCH_ORIGINAL515_SOURCE')
    files={p.relative_to(original).as_posix():p.read_bytes() for p in original.rglob('*') if p.is_file()}
    rendered=write_disjoint(files,binding['all_sources'],source,
        financial_sources=mapping['predecessor_financial_sources'])
    need(rendered==mapping==json.loads((HERE/SOURCE_MAP).read_bytes()), 'P01_BATCH_RETAINED_EXACT516_SOURCE_MAP')
    return original,source


def main(args):
    from p01_factual_batch_contract import specification,SPEC
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1', 'P01_BATCH_NO_BLIND_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(), 'P01_BATCH_EXACT_REQUEST')
    validate_prepared_receipt(json.loads(args.capacity.read_bytes()),head=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],source_sha256=request['capacity_source_sha256'])
    stage_valid(json.loads(args.staging.read_bytes()))
    temp=Path(os.environ['RUNNER_TEMP']);args.output.parent.mkdir(parents=True,exist_ok=True)
    phase_path=args.output.parent/'p01-factual-batch-phase.json'
    receipt=dict(schema=RECEIPT_SCHEMA,arm='P01',stage=STAGE,run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(args.request),protocol_sha256=request['protocol_sha256'],
        strict_parent_outer_sha256=specification()['outer_sha256'],status='BEFORE_EXPORT_PROBE',
        production_contacted=False,qualification_exported=False)
    write_receipt(args.output,receipt)
    out=temp/'p01-factual-batch-financial-output';out.mkdir(mode=0o700)
    known=False;key=None
    try:
        note(phase_path,'BEFORE_EXPORT_PROBE')
        probe=qualify_export(temp/'p01-factual-batch-export-probe',args.request)
        probe_path=args.output.parent/'p01-factual-batch-export-qualification.json'
        probe_path.write_bytes((json.dumps(probe,sort_keys=True,indent=2)+'\n').encode())
        receipt['export_qualification_sha256']=sha256_file(probe_path);note(phase_path,'EXPORT_PROBE_PASSED')
        key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32, 'P01_BATCH_SEPARATE_KEY')
        note(phase_path,'BEFORE_INITIAL_DISK_GATE')
        need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'], 'P01_BATCH_INITIAL_RESERVE')
        note(phase_path,'BEFORE_PARENT_FETCH')
        old=admit(temp/'campaign-factual-transfer-p01-batch',key,specification());note(phase_path,'PARENT_ADMITTED')
        capsule=temp/'p01-factual-batch-approved-quote';authenticate_capsule(request['quote_descriptor'],capsule,key=key)
        frozen=temp/'capital-risk-stage-001/inputs';original,source=reconstruct(frozen,old,temp)
        note(phase_path,'SOURCE_IDENTICAL')
        for root in (original,source,old,capsule):freeze(root)
        os.environ.pop('GH_TOKEN',None)
        for name,path in [('spec.json',HERE/SPEC),('request.json',args.request),
                          ('source-bindings.json',old/'source-bindings.json'),('source-map.json',old/'source-map.json')]:
            shutil.copyfile(path,out/name)
        qual=temp/'p01-factual-batch-qualification-output';qual.mkdir(mode=0o700)
        for name in ('spec.json','source-map.json'):shutil.copyfile(out/name,qual/name)
        note(phase_path,'BEFORE_WORKER_RESOURCE_GATE');resources(request,temp);note(phase_path,'QUALIFIER_LAUNCH_ATTEMPTED')
        name='capital-system-p01-factual-batch-qualify-'+os.environ['GITHUB_RUN_ID']+'-1'
        receipt['status']='EPOCH_INPUT_QUALIFICATION_LAUNCH_ATTEMPTED';write_receipt(args.output,receipt)
        receipt['qualification_worker']=stopped_run(worker_command(name,'qualify',source,frozen,qual,old,capsule),name,qual,
            deadline=request['qualification_wait_seconds'],inspector=inspect)
        known=True;note(phase_path,'QUALIFIER_STOPPED')
        (out/'qualification').mkdir()
        if (qual/'proof').exists():shutil.copytree(qual/'proof',out/'qualification',dirs_exist_ok=True)
        collect_stop(qual,out/'qualification',receipt,'qualification')
        stopped=receipt['qualification_worker'];need(stopped['exit_code']==0 and not stopped['oom_killed'], 'P01_BATCH_QUALIFIER_REFUSED')
        proof=json.loads((qual/'proof/qualification-summary.json').read_bytes())
        need(proof['status']=='OWN526_GROUPED_FACTUAL_INPUT_AND_RUNTIME_QUALIFIED'
             and proof['financial_authority'] is False and proof['financial_predecessor_authorized'] is False
             and proof['component_transitions']==2 and proof['source_epoch_boundary_reemitted'] is False
             and proof['input_document_sha256']==request['input_document_sha256']
             and proof['epoch_zero_outer_sha256']==specification()['outer_sha256'], 'P01_BATCH_ACTUAL_FULL_RUNTIME_QUALIFIER_GATE')
        receipt['status']='EPOCH_INPUT_QUALIFIED_ORIGINAL526_NOT_ADVANCED';preserve_qualification(receipt,out,args.output,key,args.request)
        freeze(qual)
        note(phase_path,'BEFORE_WORKER_RESOURCE_GATE');resources(request,temp);note(phase_path,'FINANCIAL_LAUNCH_ATTEMPTED')
        name='capital-system-p01-factual-batch-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        known=False;receipt['status']='FRESH_OWN526_FINANCIAL_LAUNCH_ATTEMPTED';write_receipt(args.output,receipt)
        receipt['worker']=stopped_run(worker_command(name,'economic',source,frozen,out,old,capsule,qual),name,out,
            deadline=request['financial_wait_seconds'],inspector=inspect)
        known=True;note(phase_path,'FINANCIAL_STOPPED')
        receipt['worker_log_copy_failed']=(out/'log-copy-failure.json').exists()
        receipt['status']='FINANCIAL_STOPPED_PENDING_SUFFIX_REVIEW';write_receipt(args.output,receipt)
        outcome=json.loads((out/'batch-outcome.json').read_bytes())
        need(outcome['input_document_sha256']==proof['input_document_sha256'], 'P01_BATCH_FRESH_FINANCE_SAME_QUALIFIED_INPUT')
        review=temp/'p01-factual-batch-review-output';review.mkdir(mode=0o700);shutil.copyfile(HERE/SPEC,review/'spec.json')
        note(phase_path,'BEFORE_WORKER_RESOURCE_GATE');resources(request,temp);note(phase_path,'REVIEW_LAUNCH_ATTEMPTED')
        name='capital-system-p01-factual-batch-review-'+os.environ['GITHUB_RUN_ID']+'-1'
        try:
            receipt['reviewer']=stopped_run(worker_command(name,'review',source,frozen,review,old,capsule,out),name,review,
                deadline=request['review_wait_seconds'],inspector=inspect)
        except StopUnknown:
            receipt['status']='FINANCIAL_STOPPED_REVIEW_STOP_UNKNOWN';receipt['review_stop_unknown']=True
            note(phase_path,'REVIEW_STOP_UNKNOWN')
        else:
            note(phase_path,'REVIEW_STOPPED');receipt['review_log_copy_failed']=(review/'log-copy-failure.json').exists()
            write_receipt(args.output,receipt);shutil.copytree(review,out/'stopped-review')
            stopped=receipt['reviewer']
            receipt['status']=('FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT' if
                outcome['status']=='COMPLETE_FACTUAL_BATCH_SEGMENT_PENDING_REVIEW' else
                'PARTIAL_FINANCIAL_PREFIX_HOSTED_REVIEWED_REFUSAL_PRESERVED') if stopped['exit_code']==0 and not stopped['oom_killed'] \
                else 'FINANCIAL_SUFFIX_REVIEW_REFUSED_PRESERVED'
    except StopUnknown as error:
        known=False;receipt['status']='ACTIVE_WRITER_STOP_UNKNOWN_NO_MUTABLE_SNAPSHOT';note(phase_path,'STOP_UNKNOWN',error)
    except Exception as error:
        receipt['status']='FACTUAL_BATCH_REFUSED_KNOWN_STOP' if known else 'FACTUAL_BATCH_REFUSED_BEFORE_STOP_PROOF'
        note(phase_path,'FAILURE',error)
        if known:(out/'driver-failure.txt').write_text(traceback.format_exc())
    note(phase_path,'BEFORE_EXPORT');finish(receipt,out,args.output,key,args.request,known=known);key=None
    note(phase_path,'FINISHED');print(json.dumps(receipt),flush=True)
    raise SystemExit(0 if receipt['status']=='FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT' else 2)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','capacity','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
