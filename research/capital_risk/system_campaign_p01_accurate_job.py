"""A bounded actual P01 financial segment, reviewed and encrypted after stop."""
import argparse,base64,json,os,shutil,traceback
from pathlib import Path
from full_system_benchmark import need
from full_system_trials_job import command
from alpaca_fit_job import stopped_run,StopUnknown
from probe import check_context,memory_bytes
from seal import sha256_file
from stage import SECRET
from system_campaign_variants import build
from system_campaign_p01_discovery_parent import SPEC,SPEC_SHA,scope,reference,admit
from system_campaign_parallel_discovery_job import stage_valid
from system_campaign_pxd_financial_body import function
from system_campaign_p01_accurate_export import STAGE,qualify_export,write_receipt,finish
import system_campaign_volatility_discovery_job as previous
import system_campaign_p02_continue_job as inspector_source

HERE=Path(__file__).parent
PRIOR=previous.REQUEST
PRIOR_SHA='bde08e881197634138f86d9f49dadcbb6d376cfa73139395575ea8ea02d04bd7'
REQUEST='system-campaign-p01-accurate-request-001.json'
SOURCES=tuple(dict.fromkeys((*previous.SOURCES,PRIOR,
    'system_campaign_p01_accurate_export.py','system_campaign_p01_accurate_run.py',
    'system_campaign_p01_accurate_job.py','system_campaign_p01_accurate_probe.py')))

def expected_request():
    need(sha256_file(HERE/PRIOR)==PRIOR_SHA,'P01_ACCURATE_EXACT_RETAINED397_REQUEST')
    previous_value=previous.expected_request()
    need(json.loads((HERE/PRIOR).read_bytes())==previous_value,'P01_ACCURATE_ALL397_OLD_DRIVERS_UNCHANGED')
    spec=scope(json.loads((HERE/SPEC).read_bytes()))
    return dict(schema='research.p01-accurate-financial-prefix-request/1',campaign='system-optimization-002',
        arm='P01',protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        predecessor_file=SPEC,predecessor_sha256=SPEC_SHA,parent_content_reference=reference(spec),
        execution_mode='CANONICAL_ACCURATE_FINANCIAL_REPLAY',new_origin=False,diagnostic_state_adopted=False,
        financial_source_changed=False,new_factual_overlay=False,repairs=8,
        financial_start='2019-09-03',processing_endpoint='2019-09-27',maximum_transitions=19,
        full_measurement_start='2018-01-02',full_measurement_end='2026-07-31',full_measured_closes=2156,
        first_segment_only=True,financial_wait_seconds=1200,review_wait_seconds=600,
        actual_export_roundtrip_before_parent_or_worker=True,atomic_public_stop_receipts=True,
        artifact_retention_days=7,initial_min_disk_bytes=12*1024**3,production_contacted=False,
        prior397_request_sha256=PRIOR_SHA,sources={n:sha256_file(HERE/n) for n in SOURCES})

def entrypoint(mode):
    need(mode in ('economic','review'),'P01_ACCURATE_EXACT_ENTRYPOINT_MODE')
    return ['-B','-u','/driver/system_campaign_p01_accurate_run.py','--mode',mode,'--spec','/out/spec.json']

def inspect(name,identity=None):
    value=function('system_campaign_p02_continue_job.py','inspect',{
        r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1':
        r'capital-system-p01-accurate-(?:worker|review)-[0-9]+-1'},vars(inspector_source))(name,identity)
    mode='review' if '-review-' in name else 'economic'
    need(value['Config']['Cmd']==entrypoint(mode),'P01_ACCURATE_EXACT_WORKER_ENTRYPOINT')
    return value

def worker_command(name,mode,source,frozen,out,old,evidence=None):
    values=command(name,source,frozen,out,mode)
    index=values.index('--entrypoint')
    mounts=['--mount',f'type=bind,source={old},target=/old,readonly']
    if evidence is not None:mounts+=['--mount',f'type=bind,source={evidence},target=/evidence,readonly']
    values[index:index]=mounts;values[values.index('-B'):]=entrypoint(mode)
    return values

def main(args):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','P01_ACCURATE_NO_BLIND_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(),'P01_ACCURATE_EXACT_FROZEN_REQUEST')
    stage_valid(json.loads(args.staging.read_bytes()));spec=scope(json.loads((HERE/SPEC).read_bytes()))
    temp=Path(os.environ['RUNNER_TEMP']);args.output.parent.mkdir(parents=True,exist_ok=True)
    probe=qualify_export(temp/'p01-accurate-export-probe',args.request)
    probe_path=args.output.parent/'p01-accurate-export-qualification.json'
    probe_path.write_bytes((json.dumps(probe,sort_keys=True,indent=2)+'\n').encode())
    receipt=dict(schema='research.p01-accurate-financial-prefix-receipt/1',arm='P01',stage=STAGE,
        run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],request_sha256=sha256_file(args.request),
        protocol_sha256=request['protocol_sha256'],strict_parent_outer_sha256=spec['outer_sha256'],
        strict_parent_run_id=spec['run_id'],status='EXPORT_PROBE_PASSED_PARENT_NOT_FETCHED',
        production_contacted=False,export_qualification_sha256=sha256_file(probe_path))
    write_receipt(args.output,receipt)
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'P01_ACCURATE_SEPARATE_KEY')
    out=temp/'p01-accurate-output';out.mkdir(mode=0o700);known=False
    try:
        need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'P01_ACCURATE_DISK_RESERVE')
        old=admit(spec,temp/'campaign-factual-transfer-p01-accurate',key)
        frozen=temp/'capital-risk-stage-001/inputs';source=temp/'p01-accurate-frozen-source'
        binding=json.loads((old/'source-bindings.json').read_bytes())
        need(build(frozen/'source-fixed',source,binding['parameters'])==binding,
             'P01_ACCURATE_IDENTICAL515_FINANCIAL_SOURCE')
        for directory in (source,old):
            for path in directory.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
            os.chmod(directory,0o555)
        os.environ.pop('GH_TOKEN',None)
        need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=10*1024**3,
             'P01_ACCURATE_ONE_WORKER_PER_VM_RESOURCES')
        for n,p in [('spec.json',HERE/SPEC),('request.json',args.request),('source-bindings.json',old/'source-bindings.json')]:shutil.copyfile(p,out/n)
        (out/'strict-parent-admission.json').write_bytes((json.dumps(reference(spec),sort_keys=True,indent=2)+'\n').encode())
        receipt['status']='ACCURATE_FINANCIAL_LAUNCH_ATTEMPTED';write_receipt(args.output,receipt)
        name='capital-system-p01-accurate-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        receipt['worker']=stopped_run(worker_command(name,'economic',source,frozen,out,old),name,out,
                                     deadline=request['financial_wait_seconds'],inspector=inspect)
        known=True;receipt['status']='FINANCIAL_STOPPED_PENDING_REVIEW';write_receipt(args.output,receipt)
        stop=receipt['worker'];need(stop['exit_code']==0 and not stop['oom_killed'],'P01_ACCURATE_FINANCIAL_WORKER_REFUSED')
        value=json.loads((out/'accurate-outcome.json').read_bytes())
        need(value['status']=='COMPLETE_ACCURATE_SEGMENT_PENDING_REVIEW'
             and value['source_input_identity_unchanged'] and value['repairs_unchanged'],
             'P01_ACCURATE_EXACT_SEGMENT_COMPLETE')
        review=temp/'p01-accurate-review';review.mkdir(mode=0o700);shutil.copyfile(HERE/SPEC,review/'spec.json')
        name='capital-system-p01-accurate-review-'+os.environ['GITHUB_RUN_ID']+'-1'
        try:
            receipt['reviewer']=stopped_run(worker_command(name,'review',source,frozen,review,old,out),name,review,
                                           deadline=request['review_wait_seconds'],inspector=inspect)
        except StopUnknown:
            receipt.update(status='FINANCIAL_STOPPED_REVIEW_STOP_UNKNOWN',review_stop_unknown=True)
        else:
            shutil.copytree(review,out/'stopped-review')
            s=receipt['reviewer'];receipt['status']='ACCURATE_SEGMENT_HOSTED_REVIEW_PASSED_PENDING_CLIENT' if (
                s['exit_code']==0 and not s['oom_killed']) else 'ACCURATE_SEGMENT_REVIEW_REFUSED_PRESERVED'
    except StopUnknown:
        known=False;receipt['status']='FINANCIAL_WRITER_STOP_UNKNOWN_NO_SNAPSHOT'
    except Exception:
        receipt['status']='ACCURATE_REFUSED_KNOWN_STOP' if known else 'ACCURATE_REFUSED_BEFORE_STOP_PROOF'
        if known:(out/'driver-failure.txt').write_text(traceback.format_exc())
    finish(receipt,out,args.output,key,args.request,known=known);key=None
    print(json.dumps(receipt),flush=True)
    raise SystemExit(0 if receipt['status']=='ACCURATE_SEGMENT_HOSTED_REVIEW_PASSED_PENDING_CLIENT' else 2)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
