"""One hosted synthetic CELG worker; own438 supplies source identity only."""
import argparse
import ast
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from alpaca_fit_job import stopped_run,StopUnknown
from full_system_benchmark import need,save
from full_system_trials_job import command
from probe import check_context,memory_bytes
from seal import sha256_file
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE
from system_campaign_variants import build
from system_campaign_parallel_discovery import compile_body
from p01_action_clock_parent import specification,reference,admit
from p01_celg_export import STAGE,AUTHORITY,PRIOR,PRIOR_SHA,pinned,qualify_export,write_receipt,finish
from p01_celg_source import write_disjoint,PHYSICAL_SHA,FINANCIAL_SHA,digest
from ephemeral_runner_capacity import validate_prepared_receipt
import full_system_trials_job as fence_source

HERE=Path(__file__).parent
REQUEST='p01_celg_component_request.json'
CAPACITY='ephemeral_runner_capacity.py'
NEW=('p01_celg_multileg_facts.py','p01_celg_multileg_primary.json',
     'p01_celg_component.py','p01_celg_source.py','p01_celg_accounting.py','p01_celg_component_run.py',
     'p01_celg_export.py','p01_celg_job.py','p01_celg_probe.py',CAPACITY)
SOURCES=tuple(dict.fromkeys((*json.loads((HERE/PRIOR).read_bytes())['sources'],PRIOR,*NEW)))


def expected_request():
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'CELG_EXACT_PUBLISHED_P01_418_REQUEST')
    old=json.loads((HERE/PRIOR).read_bytes())
    need(len(old['sources'])==418 and all(sha256_file(HERE/n)==h for n,h in old['sources'].items()),
         'CELG_ALL418_PUBLISHED_P01_DRIVER_BYTES_UNCHANGED')
    spec=specification()
    return dict(schema='research.p01-celg-synthetic-component-request/1',arm='P01',campaign='system-optimization-002',
        stage=STAGE,authority=AUTHORITY,financial_authority=False,financial_replay_authorized=False,
        financial_predecessor_selected=False,source_parent_file='p01_action_clock_predecessor.json',
        source_parent_sha256=sha256_file(HERE/'p01_action_clock_predecessor.json'),source_parent_reference=reference(spec),
        source_parent_usage='AUTHENTICATED_SOURCE_BINDING_AND_PARAMETERS_ONLY_NO_BOOK_MOUNT',
        prior_p01_418_request_sha256=PRIOR_SHA,protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        original_physical_source_files=515,successor_physical_source_files=516,
        original_canonical_identity_files=223,successor_canonical_identity_files=224,
        original_physical_manifest_sha256=PHYSICAL_SHA,original_financial_manifest_sha256=FINANCIAL_SHA,
        actual_own_book_restored=False,financial_input_admitted=False,source_bridge_implemented=False,
        recognition_clock_admitted=False,native_nov20_action_removed=False,nov21_quote_backdated=False,
        all_positions_and_prices_explicitly_synthetic=True,retained_right_quote_authenticated=False,
        actual_provider_response_transferred=False,synthetic_right_open='2.30',synthetic_right_close='2.25',
        required_positive_cases=1,required_negative_cases=10,actual_ledger_state_report_accounting_roundtrips=True,
        capacity_preparation_required=True,capacity_source_file=CAPACITY,
        capacity_source_sha256=sha256_file(HERE/CAPACITY),capacity_before_encrypted_staging=True,
        actual_new_scope_marker_before_parent_or_worker=True,one_worker_only=True,
        worker_wait_seconds=900,orchestration_timeout_minutes=35,job_timeout_minutes=65,
        capacity_step_timeout_minutes=5,staging_timeout_minutes=8,
        artifact_retention_days=7,initial_min_disk_bytes=12*1024**3,
        preworker_min_disk_bytes=10*1024**3,preworker_min_memory_bytes=10*1024**3,
        unknown_worker_never_snapshots=True,durable_partial_case_proofs=True,no_blind_rerun=True,
        production_contacted=False,sources={n:sha256_file(HERE/n) for n in SOURCES})


def entrypoint():
    return ['-B','-u','/driver/p01_celg_component_run.py','--manifest','/out/source-manifest.json']


def worker_command(name,source,frozen,out):
    values=command(name,source,frozen,out,'qualify')
    values[values.index('-B'):]=entrypoint()
    return values


def inspect(name,identity=None):
    fn=pinned(fence_source,'inspect')
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value==
           r'capital-full-core-(?:b0|b|c1|c2|c3)-(?:worker|review)-[0-9]+-1']
    need(len(sites)==1,'CELG_ONE_EXACT_SYNTHETIC_WORKER_NAMESPACE_SITE')
    sites[0].value=r'capital-system-p01-celg-component-worker-[0-9]+-1'
    value=compile_body(fn,vars(fence_source))(name,identity)
    need(value['Config']['Cmd']==entrypoint(),'CELG_EXACT_SINGLE_COMPONENT_ENTRYPOINT')
    return value


PHASES={'CAPACITY_AND_STAGING_VERIFIED','BEFORE_MARKER','MARKER_PASSED','BEFORE_INITIAL_DISK_GATE',
        'BEFORE_PARENT_FETCH','SOURCE_PARENT_ADMITTED','ORIGINAL515_IDENTICAL','SUCCESSOR516_RENDERED',
        'BEFORE_WORKER_RESOURCE_GATE','WORKER_LAUNCH_ATTEMPTED','WORKER_STOPPED','UNKNOWN_NO_SNAPSHOT',
        'FAILURE','BEFORE_EXPORT','FINISHED'}


def note(path,phase,error=None):
    need(phase in PHASES,'CELG_PUBLIC_PHASE_ALLOWLIST')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    old=json.loads(path.read_bytes()) if path.exists() else None
    history=old['phase_history'] if old else []
    need(len(history)<32,'CELG_BOUNDED_PUBLIC_PHASE_HISTORY')
    value=dict(schema='research.p01-celg-nonfinancial-phase/1',arm='P01',authority=AUTHORITY,
        run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],phase=phase,
        previous_phase=old['phase'] if old else None,phase_history=[*history,phase],
        free_disk_bytes=shutil.disk_usage(Path(os.environ['RUNNER_TEMP'])).free,
        available_memory_bytes=memory_bytes()['MemAvailable'],exception_class=type(error).__name__ if error else None,
        code_locations=[dict(file=Path(f.filename).name,function=f.name,line=f.lineno)
                        for f in traceback.extract_tb(error.__traceback__)] if error else [],
        exception_values_included=False,financial_or_market_payload_included=False,production_contacted=False)
    pending=path.with_suffix('.partial')
    with pending.open('wb') as stream:
        stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode());stream.flush();os.fsync(stream.fileno())
    os.replace(pending,path)


def stage_valid(value):
    need(value['status']=='STAGING_PASSED' and value['run_id']==os.environ['GITHUB_RUN_ID']
         and value['source_commit']==os.environ['GITHUB_SHA'] and value['protocol_sha256']==PROTOCOL
         and value['runtime_image']==IMAGE and value['execution_image']==EXECUTION_IMAGE
         and value['source_files_verified']==514 and value['members_verified']==591
         and value['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and value['authenticated_before_parsing'] and value['offline_image_source_verified']
         and value['runtime_index_config_layer_chain_verified'] and not value['replay_started'],
         'CELG_ORIGINAL_AUTHENTICATED_FROZEN_INPUTS_AND_OFFLINE_RUNTIME')


def main(args):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','CELG_NO_BLIND_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(),'CELG_EXACT_FROZEN_REQUEST_SOURCE_CLOSURE')
    need(args.capacity.resolve()==(args.output.parent/'ephemeral-runner-capacity.json').resolve(),
         'CELG_EXACT_PRESTAGING_CAPACITY_RECEIPT_PATH')
    validate_prepared_receipt(json.loads(args.capacity.read_bytes()),head=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'],source_sha256=request['capacity_source_sha256'])
    stage_valid(json.loads(args.staging.read_bytes()))
    temp=Path(os.environ['RUNNER_TEMP']);args.output.parent.mkdir(parents=True,exist_ok=True)
    phase=args.output.parent/'p01-celg-component-phase.json'
    receipt=dict(schema='research.p01-celg-synthetic-component-receipt/1',arm='P01',stage=STAGE,authority=AUTHORITY,
        financial_authority=False,production_contacted=False,run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(args.request),protocol_sha256=request['protocol_sha256'],
        source_parent_outer_sha256=specification()['outer_sha256'],capacity_receipt_sha256=sha256_file(args.capacity),
        status='CAPACITY_AND_STAGING_VERIFIED')
    write_receipt(args.output,receipt);note(phase,'CAPACITY_AND_STAGING_VERIFIED')
    out=temp/'p01-celg-synthetic-component-output';out.mkdir(mode=0o700);key=None;known=False
    try:
        note(phase,'BEFORE_MARKER')
        proof=qualify_export(temp/'p01-celg-new-scope-marker',args.request)
        probe=args.output.parent/'p01-celg-component-export-qualification.json';save(probe,proof)
        receipt['export_qualification_sha256']=sha256_file(probe);note(phase,'MARKER_PASSED')
        key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'CELG_SEPARATE_KEY')
        note(phase,'BEFORE_INITIAL_DISK_GATE')
        need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'CELG_INITIAL_12GIB_RESERVE')
        note(phase,'BEFORE_PARENT_FETCH')
        old=admit(temp/'campaign-factual-transfer-p01-celg-source-only',key)
        note(phase,'SOURCE_PARENT_ADMITTED')
        frozen=temp/'capital-risk-stage-001/inputs';original=temp/'p01-celg-original515-source'
        binding=json.loads((old/'source-bindings.json').read_bytes())
        need(build(frozen/'source-fixed',original,binding['parameters'])==binding
             and digest(binding['all_sources'])==PHYSICAL_SHA,'CELG_EXACT_ORIGINAL515_SOURCE_NO_CONVERSION')
        note(phase,'ORIGINAL515_IDENTICAL')
        files={p.relative_to(original).as_posix():p.read_bytes() for p in original.rglob('*') if p.is_file()}
        successor=temp/'p01-celg-successor516-source'
        manifest=write_disjoint(files,binding['all_sources'],successor);note(phase,'SUCCESSOR516_RENDERED')
        for directory in (old,original,successor):
            for path in directory.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
            os.chmod(directory,0o555)
        # No old checkpoint/book is copied into or mounted by the worker.
        save(out/'source-manifest.json',manifest)
        shutil.copyfile(old/'source-bindings.json',out/'source-bindings.json')
        shutil.copyfile(args.request,out/'request.json')
        save(out/'source-parent-admission.json',dict(reference=reference(specification()),
            usage='SOURCE_CRYPTO_AND_PARAMETERS_ONLY',actual_book_or_checkpoint_adopted=False))
        os.environ.pop('GH_TOKEN',None);note(phase,'BEFORE_WORKER_RESOURCE_GATE')
        need(memory_bytes()['MemAvailable']>=request['preworker_min_memory_bytes']
             and shutil.disk_usage(temp).free>=request['preworker_min_disk_bytes'],'CELG_WORKER_10GIB_RESOURCES')
        receipt['status']='SYNTHETIC_COMPONENT_LAUNCH_ATTEMPTED';write_receipt(args.output,receipt)
        note(phase,'WORKER_LAUNCH_ATTEMPTED')
        name='capital-system-p01-celg-component-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        receipt['worker']=stopped_run(worker_command(name,successor,frozen,out),name,out,
            deadline=request['worker_wait_seconds'],inspector=inspect)
        known=True;note(phase,'WORKER_STOPPED');receipt['status']='STOPPED_SYNTHETIC_COMPONENT_PENDING_INDEPENDENT_REVIEW'
        write_receipt(args.output,receipt)
        if receipt['worker']['exit_code']!=0 or receipt['worker']['oom_killed']:
            receipt['status']='STOPPED_SYNTHETIC_COMPONENT_REFUSAL_PRESERVED'
    except StopUnknown as error:
        known=False;receipt['status']='SYNTHETIC_COMPONENT_STOP_UNKNOWN_NO_SNAPSHOT';note(phase,'UNKNOWN_NO_SNAPSHOT',error)
    except Exception as error:
        receipt['status']='SYNTHETIC_COMPONENT_REFUSED_KNOWN_STOP' if known else 'SYNTHETIC_COMPONENT_REFUSED_BEFORE_STOP_PROOF'
        note(phase,'FAILURE',error)
        if known:(out/'driver-failure.txt').write_text(traceback.format_exc())
    note(phase,'BEFORE_EXPORT');finish(receipt,out,args.output,key,args.request,known=known);key=None
    note(phase,'FINISHED');print(json.dumps(receipt),flush=True)
    raise SystemExit(0 if receipt['status']=='STOPPED_SYNTHETIC_COMPONENT_PENDING_INDEPENDENT_REVIEW' else 2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','staging','capacity','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
