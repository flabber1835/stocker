"""Exact official baseline continuation; diagnostics are separate from old receipts."""
import argparse,base64,json,os,shutil,traceback
from pathlib import Path
from system_campaign_job import ARMS,worker_command
from system_campaign_source import build
from system_campaign_predecessor import admit
from full_system_trials_job import inspect,seal
from full_system_benchmark import need
from alpaca_fit_job import stopped_run,StopUnknown
from probe import check_context,memory_bytes
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file

HERE=Path(__file__).resolve().parent
from system_campaign_job import SOURCES as BASE_SOURCES
SOURCES=(*BASE_SOURCES,'system_campaign_continue_job.py','system_campaign_continue.py','system_campaign_predecessor.py')
def expected_request():
    return {'schema':'research.system-campaign-continuation-request/1','campaign':'system-optimization-002',
        'protocol_sha256':sha256_file(HERE/'system-campaign-protocol.json'),
        'predecessors_sha256':sha256_file(HERE/'system-campaign-predecessors.json'),
        'sources':{n:sha256_file(HERE/n) for n in SOURCES},'arms':ARMS,'financial_wait_seconds':12600,
        'review_wait_seconds':2700,'all_financial_source_bytes_identical':True,'production_contacted':False,'artifact_retention_days':7}

def main(a):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_CAMPAIGN_CONTINUATION_RERUN')
    request=json.loads(a.request.read_bytes());need(request==expected_request(),'EXACT_CAMPAIGN_CONTINUATION_REQUEST')
    stage=json.loads(a.staging.read_bytes());need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
        and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
        and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE and stage['source_files_verified']==514
        and stage['members_verified']==591 and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
        and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],'CAMPAIGN_CONTINUATION_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    transfer=temp/('campaign-transfer-'+a.arm);transfer.mkdir(mode=0o700)
    spec=json.loads((HERE/'system-campaign-predecessors.json').read_bytes())['arms'][a.arm]
    old=admit(spec,transfer,key,a.arm);os.environ.pop('GH_TOKEN',None)
    source=temp/('campaign-continuation-source-'+a.arm);binding=build(frozen/'source-fixed',source)
    need(binding==json.loads((old/'source-bindings.json').read_bytes()),'ENTIRE_FINANCIAL_SOURCE_IDENTICAL')
    out=temp/('campaign-continuation-'+a.arm);shutil.copytree(old,out)
    lineage=out/'segment-001-lineage';lineage.mkdir()
    for name in ('core-review.json','worker-inspect.json','worker.log','economic-worker-inspect.json','economic-worker.log',
                 'acceleration-proof.json','campaign-segment.json','independent-review-stop'):
        if (out/name).exists():shutil.move(out/name,lineage/name)
    shutil.copyfile(out/'book/checkpoint.json.gz',out/'book/predecessor-checkpoints'/(spec['outer_sha256']+'.json.gz'))
    (out/'continuation-predecessor.json').write_text(json.dumps(spec,indent=2)+'\n')
    (out/'continuation-request.json').write_bytes(a.request.read_bytes())
    for p in source.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
    os.chmod(source,0o555)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'CAMPAIGN_CONTINUATION_RESOURCES')
    diagnostic=temp/('campaign-continuation-diagnostics-'+a.arm);diagnostic.mkdir(mode=0o700)
    receipt={'schema':'research.system-campaign-continuation-receipt/1','arm':a.arm,'run_id':os.environ['GITHUB_RUN_ID'],
        'head':os.environ['GITHUB_SHA'],'request_sha256':sha256_file(a.request),'protocol_sha256':request['protocol_sha256'],
        'predecessor_run_id':spec['run_id'],'predecessor_outer_sha256':spec['outer_sha256'],
        'production_contacted':False,'performance_admitted':False,'status':'NOT_STARTED'}
    def cmd(name,mode):
        values=worker_command(name,source,frozen,out,a.arm,mode)
        values[values.index('/driver/system_campaign_baseline.py')]='/driver/system_campaign_continue.py';return values
    known=False
    try:
        name='capital-full-core-'+a.arm.lower()+'-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        w=stopped_run(cmd(name,'economic'),name,out,deadline=12600,inspector=inspect)
        known=True;receipt['worker']=w;receipt['status']='STOPPED_CAMPAIGN_CONTINUATION_PRESERVED'
        shutil.copyfile(out/'worker-inspect.json',out/'economic-worker-inspect.json');shutil.copyfile(out/'worker.log',out/'economic-worker.log')
        if not w['oom_killed']:
            audit=temp/('campaign-continuation-review-'+a.arm);audit.mkdir(mode=0o700)
            name='capital-full-core-'+a.arm.lower()+'-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            r=stopped_run(cmd(name,'review'),name,audit,deadline=2700,inspector=inspect)
            receipt['reviewer']=r;shutil.copytree(audit,out/'independent-review-stop')
            if r['exit_code']==0 and not r['oom_killed']:
                proof=json.loads((out/'core-review.json').read_bytes())
                receipt['status']='COMPLETE_CAMPAIGN_BASELINE_REVIEWED' if proof['complete'] and w['exit_code']==0 else 'PARTIAL_CAMPAIGN_PREFIX_REVIEWED'
    except StopUnknown:
        receipt['status']='REVIEW_STOP_UNKNOWN_CAMPAIGN_PRESERVED' if known else 'CAMPAIGN_STOP_UNKNOWN'
        (diagnostic/'exception-chain.txt').write_text(traceback.format_exc())
    except Exception:
        receipt['status']='CAMPAIGN_REFUSED_KNOWN_PREFIX' if known else 'CAMPAIGN_REFUSED_NO_FINANCIAL_ADMISSION'
        (diagnostic/'exception-chain.txt').write_text(traceback.format_exc())
        if known:shutil.copytree(diagnostic,out/'driver-diagnostics')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if known:receipt['encrypted_output']=seal(out,a.output.parent/('campaign-continuation-'+a.arm+'.tar.crseal'),key,a.request,a.arm,
        stage='campaign-continuation',protocol_sha256=request['protocol_sha256'])
    elif any(diagnostic.iterdir()):receipt['diagnostic_output']=seal(diagnostic,a.output.parent/('campaign-diagnostic-'+a.arm+'.tar.crseal'),key,a.request,a.arm,
        stage='campaign-continuation',protocol_sha256=request['protocol_sha256'])
    key=None;a.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));raise SystemExit(0 if receipt['status']=='COMPLETE_CAMPAIGN_BASELINE_REVIEWED' else 2)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('request','staging','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--arm',choices=ARMS,required=True);main(p.parse_args())
