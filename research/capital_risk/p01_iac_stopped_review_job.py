"""One fresh read-only review of stopped evidence; no qualifier or financial worker."""
import argparse,base64,json,os,re,shutil,subprocess,traceback
from pathlib import Path
from full_system_benchmark import need
from seal import sha256_file
import p01_iac_namespace_job as previous
from p01_iac_stopped_review_target import HERE,TARGET,TARGET_SHA,target,encoded,plain,read
from p01_iac_stopped_review_transport import authenticate,fences
from p01_iac_stopped_review_export import STAGE,SCHEMA,qualify_export,write_receipt,finish
from p01_iac_unit_contract import specification,SPEC
REQUEST='p01_iac_stopped_review_request.json'
PRIOR='p01_iac_namespace_request.json'
PRIOR_SHA='9068e16677950f58dcf3055bc5b7cbee39f898115bfab2587478bbad96e8b230'
PRIOR_JOB_SHA='f1b60118dd076ece8514e7ba7c53720b5cfa767cc13109bd15e9f9934463987a'
WORKFLOW='p01_iac_stopped_review.yml'
WORKFLOW_SHA='21af18d1e1d4e9f500e784e0f827a6bad8fbb2b1169da3b2017ee3693d368d92'
NEW=('p01_iac_namespace_review_recovery.py','p01_iac_stopped_review_target.py','p01_iac_stopped_review_target.json',
 'p01_iac_stopped_review_transport.py','p01_iac_stopped_review_run.py','p01_iac_stopped_review_job.py','p01_iac_stopped_review_probe.py','p01_iac_stopped_review_export.py')
SOURCES=tuple(dict.fromkeys((*plain(read(HERE/PRIOR))['sources'],PRIOR,*NEW)))
SECRET=previous.SECRET;stopped_run=previous.stopped_run;StopUnknown=previous.StopUnknown


def expected_request():
    need(sha256_file(Path(previous.__file__))==PRIOR_JOB_SHA and sha256_file(HERE/PRIOR)==PRIOR_SHA,'STOPPED_REVIEW_EXACT_ORIGINAL515_REQUEST_HOST')
    old=plain(read(HERE/PRIOR));need(old==previous.expected_request() and len(old['sources'])==515
        and all(sha256_file(HERE/n)==h for n,h in old['sources'].items()),'STOPPED_REVIEW_WHOLE_PRIOR_MODEL_EVERY_SOURCE_BYTE')
    spec=target()
    return dict(schema='research.p01-stopped-evidence-review-request/1',campaign='system-optimization-002',protocol_sha256=old['protocol_sha256'],
        target_file=TARGET,target_sha256=TARGET_SHA,target_request_sha256=PRIOR_SHA,target_source_count=515,
        prior_request_file=PRIOR,prior_request_sha256=PRIOR_SHA,execution_role='READ_ONLY_STOPPED_EVIDENCE_REVIEW',
        qualification_or_financial_replay_authorized=False,financial_resume_authorized=False,financial_authority=False,
        source_financial_file=old['source_financial_file'],quote_descriptor=old['quote_descriptor'],capacity_source_sha256=old['capacity_source_sha256'],
        initial_min_disk_bytes=old['initial_min_disk_bytes'],preworker_min_disk_bytes=old['preworker_min_disk_bytes'],
        preworker_min_memory_bytes=old['preworker_min_memory_bytes'],review_wait_seconds=1800,shutdown_reserve_seconds=270,
        workflow=WORKFLOW,owner_workflow_sha256=WORKFLOW_SHA,artifact_retention_days=7,production_contacted=False,
        actual_entrypoint='/driver/p01_iac_stopped_review_run.py',sources={n:sha256_file(HERE/n) for n in SOURCES})


def validate_worker_request(path):
    need(Path(path)==HERE/REQUEST,'STOPPED_REVIEW_FIXED_NEW_DRIVER_REQUEST')
    raw=read(path);expected=expected_request()
    need(raw==encoded(expected) and plain(raw)==expected and read('/out/request.json')==raw,
        'STOPPED_REVIEW_ENTIRE_NEW_REQUEST_FLAT_CLOSURE_AND_RAW_COPY_FIRST')
    return expected


def entrypoint():return ['-B','-u','/driver/p01_iac_stopped_review_run.py','--spec','/out/spec.json']


def worker_command(name,source,frozen,out,old,capsule,evidence):
    cmd=previous.worker_command(name,'review',source,frozen,out,old,capsule,evidence)
    cmd[cmd.index('-B'):]=entrypoint();return cmd


def inspect(name,identity=None):
    need(re.fullmatch('capital-system-p01-stopped-review-review-[0-9]+-1',name) is not None,'STOPPED_REVIEW_WORKER_NAMESPACE')
    value=plain(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    fences(value,name,entrypoint());need(identity is None or value['Id']==identity,'STOPPED_REVIEW_EXACT_CURRENT_ID')
    need(value['Config']['Labels']['research.role']=='review','STOPPED_REVIEW_ONLY_REVIEW_ROLE');return value


def note(path,phase,error=None):
    allowed={'START','MARKER_PASSED','TARGET_AUTHENTICATED','ANCESTRY_AUTHENTICATED','SOURCE_IDENTICAL','REVIEW_LAUNCH_ATTEMPTED','REVIEW_STOPPED','STOP_UNKNOWN','FAILURE','EXPORTED','FINISHED_NO_EXPORT'}
    need(phase in allowed,'STOPPED_REVIEW_STATIC_PHASE')
    value=dict(schema='research.p01-stopped-review-phase/1',phase=phase,run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],financial_authority=False)
    if error is not None:
        text=str(error);value.update(error_type=type(error).__name__,error_code=text if re.fullmatch('REFUSED_[A-Z0-9_]+',text) else 'REVIEW_OPERATION_FAILED')
    path=Path(path);pending=path.with_suffix('.partial')
    with pending.open('xb') as stream:stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
    os.replace(pending,path)


def main(args):
    previous.check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','STOPPED_REVIEW_SINGLE_ATTEMPT')
    request=expected_request();need(read(args.request)==encoded(request),'STOPPED_REVIEW_WHOLE_HOST_REQUEST')
    previous.validate_prepared_receipt(plain(read(args.capacity)),head=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],source_sha256=request['capacity_source_sha256'])
    previous.stage_valid(plain(read(args.staging)))
    spec=target();origin=spec['original'];temp=Path(os.environ['RUNNER_TEMP']);args.output.parent.mkdir(parents=True,exist_ok=True)
    phase=args.output.parent/'p01-iac-stopped-review-phase.json';note(phase,'START')
    receipt=dict(schema=SCHEMA,stage=STAGE,run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],request_sha256=sha256_file(args.request),source_count=len(request['sources']),
        protocol_sha256=request['protocol_sha256'],target_run_id=origin['run_id'],target_head=origin['head'],target_request_sha256=origin['request_sha256'],target_source_count=515,
        target_sha256=TARGET_SHA,status='REVIEW_NOT_STARTED',production_contacted=False,financial_authority=False,financial_resume_authorized=False,original_review_exit_code=1,output_exported=False)
    write_receipt(args.output,receipt);out=temp/'p01-stopped-review-output';out.mkdir(mode=0o700);known=False;key=None
    try:
        marker=qualify_export(temp/'p01-stopped-review-export-probe',args.request);marker_path=args.output.parent/'p01-iac-stopped-review-export-qualification.json'
        marker_path.write_bytes(encoded(marker));receipt['export_qualification_sha256']=sha256_file(marker_path);write_receipt(args.output,receipt);note(phase,'MARKER_PASSED')
        key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'STOPPED_REVIEW_SEPARATE_KEY')
        need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'STOPPED_REVIEW_INITIAL_TWELVE_GIB')
        evidence=authenticate(spec,temp/'campaign-factual-transfer-p01-stopped-evidence',key);note(phase,'TARGET_AUTHENTICATED')
        # Original target GCM/full inventories/stops precede any old or current CP parser.
        old=previous.admit(temp/'campaign-factual-transfer-p01-stopped-ancestry',key,specification())
        capsule=temp/'p01-stopped-review-approved-quote';previous.authenticate_capsule(request['quote_descriptor'],capsule,key=key);note(phase,'ANCESTRY_AUTHENTICATED')
        frozen=temp/'capital-risk-stage-001/inputs';original,source=previous.reconstruct(frozen,old,temp);note(phase,'SOURCE_IDENTICAL')
        for root in (original,source,old,capsule,evidence.qualification_root,evidence.financial_root):previous.freeze(root)
        os.environ.pop('GH_TOKEN',None)
        for filename,sourcepath in (('request.json',args.request),('target.json',HERE/TARGET),('spec.json',HERE/SPEC)):shutil.copyfile(sourcepath,out/filename)
        (out/'review-authentication.json').write_bytes(encoded(evidence.authentication))
        (out/'review-execution.json').write_bytes(encoded(dict(schema='research.p01-stopped-evidence-review-execution/1',run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],
            request_sha256=sha256_file(args.request),source_count=len(request['sources']),target_request_sha256=origin['request_sha256'],target_run_id=origin['run_id'],target_head=origin['head'],
            financial_authority=False,qualification_or_financial_replay_authorized=False)))
        previous.resources(request,temp);note(phase,'REVIEW_LAUNCH_ATTEMPTED')
        name='capital-system-p01-stopped-review-review-'+os.environ['GITHUB_RUN_ID']+'-1'
        receipt['reviewer']=stopped_run(worker_command(name,source,frozen,out,old,capsule,evidence.financial_root),name,out,deadline=request['review_wait_seconds'],inspector=inspect)
        known=True;note(phase,'REVIEW_STOPPED');receipt['review_log_copy_failed']=(out/'log-copy-failure.json').exists()
        stop=receipt['reviewer'];receipt['status']='STOPPED_EVIDENCE_READONLY_REVIEW_REFUSED_PRESERVED'
        if stop['exit_code']==0 and stop['oom_killed'] is False:
            link=plain(read(out/'review-result-link.json'))
            need(link['schema']=='research.p01-stopped-review-result-link/1'
                and link['adapter_sha256']==spec['adapter']['sha256']
                and link['execution_request_sha256']==receipt['request_sha256'] and link['target_request_sha256']==origin['request_sha256']
                and link['review_returned_without_exception'] is True and link['financial_authority'] is False
                and link['report']==dict(bytes=(out/'iac-unit-financial-review.json').stat().st_size,sha256=sha256_file(out/'iac-unit-financial-review.json')),
                'STOPPED_REVIEW_FRESH_REPORT_LINK_AFTER_ACTUAL_STOP_ZERO')
            receipt['status']='STOPPED_EVIDENCE_READONLY_REVIEW_PASSED_PENDING_CLIENT'
    except StopUnknown as error:
        known=False;receipt['status']='STOPPED_REVIEW_WRITER_UNKNOWN_NO_MUTABLE_SNAPSHOT';note(phase,'STOP_UNKNOWN',error)
    except Exception as error:
        receipt['status']='STOPPED_EVIDENCE_READONLY_REVIEW_REFUSED_PRESERVED';note(phase,'FAILURE',error)
        if known:(out/'driver-error.txt').write_text(traceback.format_exc(),encoding='utf8')
    finish(receipt,out,args.output,key,args.request,known=known);key=None
    note(phase,'EXPORTED' if receipt['output_exported'] else 'FINISHED_NO_EXPORT')
    raise SystemExit(0 if receipt['status']=='STOPPED_EVIDENCE_READONLY_REVIEW_PASSED_PENDING_CLIENT' and receipt['output_exported'] else 2)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('request','staging','capacity','output'):parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
