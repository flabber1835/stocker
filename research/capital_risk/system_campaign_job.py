"""Fresh official baseline books, separate receipts and bounded hosted segments."""
import argparse,base64,json,os,shutil,traceback
from pathlib import Path
from full_system_trials_job import command,inspect,seal
from full_system_benchmark import need
from system_campaign_source import build
from alpaca_fit_job import stopped_run,StopUnknown
from probe import check_context,memory_bytes
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file

HERE=Path(__file__).resolve().parent
SOURCES=('system_campaign_job.py','system_campaign_source.py','system_campaign_baseline.py','system_campaign_acceleration.py',
    'full_system_trials_job.py','full_system_source.py','full_system_core.py','full_system_benchmark.py',
    'build_core_variants.py','core_manifest.py','core_accounting_snapshot.py','core-source-basis.json','core_window_review.py',
    'alpaca_fit_job.py','alpaca_fit_stage.py','probe.py','runtime_identity.py','seal.py','stage.py')
ARMS={'B':'FAST','B0':'REFERENCE'}

def expected_request():
    return {'schema':'research.system-campaign-baseline-request/1','campaign':'system-optimization-002',
        'protocol_sha256':sha256_file(HERE/'system-campaign-protocol.json'),
        'sources':{n:sha256_file(HERE/n) for n in SOURCES},'arms':ARMS,'canonical_transitions_per_first_segment':134,
        'fresh_origins_not_unknown_branch_recovery':True,'production_contacted':False,
        'financial_wait_seconds':1800,'independent_review_seconds':600,'artifact_retention_days':7}

def worker_command(name,source,frozen,out,arm,mode):
    values=command(name,source,frozen,out,mode);i=values.index('/driver/full_system_core.py')
    return values[:i]+['/driver/system_campaign_baseline.py','--mode',mode,'--acceleration',ARMS[arm]]

def main(a):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_BASELINE_RERUN')
    request=json.loads(a.request.read_bytes());need(request==expected_request(),'EXACT_CAMPAIGN_REQUEST')
    stage=json.loads(a.staging.read_bytes());need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
        and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
        and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE and stage['source_files_verified']==514
        and stage['members_verified']==591 and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
        and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],'CAMPAIGN_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs';source=temp/('campaign-source-'+a.arm)
    out=temp/('campaign-baseline-'+a.arm);out.mkdir(mode=0o700);diagnostic=temp/('campaign-diagnostics-'+a.arm);diagnostic.mkdir(mode=0o700)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'CAMPAIGN_RESOURCES')
    binding=build(frozen/'source-fixed',source)
    (out/'source-bindings.json').write_text(json.dumps(binding,indent=2)+'\n');(out/'request.json').write_bytes(a.request.read_bytes())
    (out/'protocol.json').write_bytes((HERE/'system-campaign-protocol.json').read_bytes())
    for p in source.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
    os.chmod(source,0o555)
    receipt={'schema':'research.system-campaign-baseline-receipt/1','arm':a.arm,'acceleration':ARMS[a.arm],
        'run_id':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],'request_sha256':sha256_file(a.request),
        'protocol_sha256':request['protocol_sha256'],'production_contacted':False,'performance_admitted':False,'status':'NOT_STARTED'}
    known=False
    try:
        name='capital-full-core-'+a.arm.lower()+'-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        w=stopped_run(worker_command(name,source,frozen,out,a.arm,'economic'),name,out,deadline=1800,inspector=inspect)
        known=True;receipt['worker']=w;receipt['status']='STOPPED_BASELINE_PREFIX_PRESERVED'
        shutil.copyfile(out/'worker-inspect.json',out/'economic-worker-inspect.json');shutil.copyfile(out/'worker.log',out/'economic-worker.log')
        if (out/'book/checkpoint.json.gz').is_file() and not w['oom_killed']:
            audit=temp/('campaign-review-'+a.arm);audit.mkdir(mode=0o700)
            name='capital-full-core-'+a.arm.lower()+'-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            r=stopped_run(worker_command(name,source,frozen,out,a.arm,'review'),name,audit,deadline=600,inspector=inspect)
            receipt['reviewer']=r;shutil.copytree(audit,out/'independent-review-stop')
            if r['exit_code']==0 and not r['oom_killed']:
                proof=json.loads((out/'core-review.json').read_bytes())
                complete=(proof['counts']=={'formation':126,'daily':8} and w['exit_code']==0)
                receipt['status']='FIRST_BASELINE_SEGMENT_REVIEWED' if complete else 'PARTIAL_BASELINE_PREFIX_REVIEWED'
    except StopUnknown:
        receipt['status']='REVIEW_STOP_UNKNOWN_BASELINE_PRESERVED' if known else 'BASELINE_STOP_UNKNOWN'
        (diagnostic/'exception-chain.txt').write_text(traceback.format_exc())
    except Exception:
        receipt['status']='BASELINE_REFUSED_KNOWN_PREFIX' if known else 'BASELINE_REFUSED_NO_FINANCIAL_ADMISSION'
        (diagnostic/'exception-chain.txt').write_text(traceback.format_exc())
        if known:shutil.copytree(diagnostic,out/'driver-diagnostics')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if known:receipt['encrypted_output']=seal(out,a.output.parent/('campaign-baseline-'+a.arm+'.tar.crseal'),key,a.request,a.arm,
        stage='campaign-baseline',protocol_sha256=request['protocol_sha256'])
    elif any(diagnostic.iterdir()):receipt['diagnostic_output']=seal(diagnostic,a.output.parent/('campaign-diagnostic-'+a.arm+'.tar.crseal'),key,a.request,a.arm,
        stage='campaign-baseline',protocol_sha256=request['protocol_sha256'])
    key=None;a.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));raise SystemExit(0 if receipt['status']=='FIRST_BASELINE_SEGMENT_REVIEWED' else 2)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--arm',choices=ARMS,required=True);main(p.parse_args())
