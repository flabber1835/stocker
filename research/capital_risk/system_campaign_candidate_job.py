"""Bounded fresh candidate books on dedicated fenced hosted VMs; never PAPER."""
import argparse,base64,json,os,re,shutil,subprocess,traceback
from pathlib import Path
from system_campaign_variants import build
from system_campaign_space import initial,digest
from full_system_trials_job import command,seal
from full_system_benchmark import need
from alpaca_fit_job import stopped_run,StopUnknown
from probe import check_context,memory_bytes,FORBIDDEN_CREDENTIALS
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file

HERE=Path(__file__).resolve().parent
SOURCES=('system_campaign_candidate_job.py','system_campaign_candidate.py','system_campaign_variants.py','system_campaign_space.py',
    'system_campaign_observe.py','system_campaign_qualify.py','system_campaign_acceleration.py','system_campaign_baseline.py','system_campaign_readonly.py',
    'full_system_core.py','full_system_source.py','full_system_trials_job.py','full_system_benchmark.py',
    'build_core_variants.py','core_manifest.py','core_accounting_snapshot.py','core-source-basis.json','core_window_review.py',
    'alpaca_fit_job.py','alpaca_fit_stage.py','probe.py','runtime_identity.py','seal.py','stage.py')
def expected_request():
    return {'schema':'research.system-campaign-candidate-request/1','campaign':'system-optimization-002',
        'search_protocol_sha256':sha256_file(HERE/'system-campaign-search-protocol.json'),
        'sources':{n:sha256_file(HERE/n) for n in SOURCES},'initial_candidates':initial(),
        'financial_wait_seconds':12600,'review_wait_seconds':2700,'artifact_retention_days':7,'production_contacted':False,
        'ordinary_baseline_gate_required_before_efficacy':True}
def inspect(name,identity=None):
    need(re.fullmatch(r'capital-system-campaign-p[0-9]{2}-(?:worker|review)-[0-9]+-1',name) is not None,'CAMPAIGN_CANDIDATE_NAME')
    v=json.loads(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    h,c=v['HostConfig'],v['Config'];m={x['Destination']:x for x in v['Mounts'] if x['Type']=='bind'}
    need(v['Name']=='/'+name and v['Image']==EXECUTION_IMAGE and (identity is None or v['Id']==identity),'CAMPAIGN_CANDIDATE_IDENTITY')
    need(h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3 and h['NanoCpus']==2000000000 and h['PidsLimit']==64
        and h['ReadonlyRootfs'] and h['CapDrop']==['ALL'] and any(x.startswith('no-new-privileges') for x in h['SecurityOpt']),'CAMPAIGN_CANDIDATE_FENCES')
    need(set(m)==({'/variant','/frozen','/driver','/out','/evidence'} if '-review-' in name else {'/variant','/frozen','/driver','/out'}) and m['/out']['RW'] and all(not x['RW'] for k,x in m.items() if k!='/out')
        and c['WorkingDir']=='/variant' and c['User']==f'{os.getuid()}:{os.getgid()}'
        and c['Labels']['research.study']=='full-system-search-20261029' and c['Labels']['research.role']==('review' if '-review-' in name else 'worker'),'CAMPAIGN_CANDIDATE_MOUNTS')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,'GITHUB_TOKEN','GH_TOKEN'}
    need(not any(k in forbidden and val for k,_,val in (s.partition('=') for s in c['Env'])),'CAMPAIGN_CANDIDATE_CREDENTIALS')
    return v
def main(a):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_CANDIDATE_RERUN')
    request=json.loads(a.request.read_bytes());need(request==expected_request(),'EXACT_CAMPAIGN_CANDIDATE_REQUEST')
    need(type(a.index) is int and 0<=a.index<12,'INITIAL_CANDIDATE_INDEX')
    stage=json.loads(a.staging.read_bytes());need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
        and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL and stage['runtime_image']==IMAGE
        and stage['execution_image']==EXECUTION_IMAGE and stage['source_files_verified']==514 and stage['members_verified']==591
        and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
        and stage['authenticated_before_parsing'] and stage['offline_image_source_verified'] and stage['runtime_index_config_layer_chain_verified']
        and not stage['replay_started'],'CAMPAIGN_CANDIDATE_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs';source=temp/'campaign-variant'
    root=temp/'campaign-candidate';root.mkdir(mode=0o700);diagnostic=temp/'campaign-candidate-diagnostic';diagnostic.mkdir(mode=0o700)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=12*1024**3,'CAMPAIGN_CANDIDATE_CAPACITY')
    proposal=initial()[a.index];binding=build(frozen/'source-fixed',source,proposal['parameters'])
    (root/'source-bindings.json').write_text(json.dumps(binding,indent=2)+'\n');(root/'request.json').write_bytes(a.request.read_bytes())
    (root/'search-protocol.json').write_bytes((HERE/'system-campaign-search-protocol.json').read_bytes())
    for p in source.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
    os.chmod(source,0o555);arm=f'P{a.index:02d}'
    receipt={'schema':'research.system-campaign-candidate-receipt/1','arm':arm,'candidate_id':proposal['id'],'run_id':os.environ['GITHUB_RUN_ID'],
        'head':os.environ['GITHUB_SHA'],'request_sha256':sha256_file(a.request),'protocol_sha256':request['search_protocol_sha256'],
        'production_contacted':False,'performance_admitted':False,'status':'NOT_STARTED'}
    def cmd(name,mode,output=None):
        values=command(name,source,frozen,output or root,mode);values[values.index('/driver/full_system_core.py')]='/driver/system_campaign_candidate.py'
        if mode=='review':
            i=values.index('--entrypoint');values[i:i]=['--mount',f'type=bind,source={root},target=/evidence,readonly'];values+=['--evidence-root','/evidence']
        return values
    known=False
    try:
        name='capital-system-campaign-'+arm.lower()+'-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        w=stopped_run(cmd(name,'economic'),name,root,deadline=12600,inspector=inspect)
        known=True;receipt['worker']=w;receipt['status']='STOPPED_CANDIDATE_PREFIX_PRESERVED'
        shutil.copyfile(root/'worker-inspect.json',root/'economic-worker-inspect.json');shutil.copyfile(root/'worker.log',root/'economic-worker.log')
        if (root/'book/checkpoint.json.gz').is_file() and not w['oom_killed']:
            audit=temp/'campaign-candidate-review';audit.mkdir(mode=0o700)
            name='capital-system-campaign-'+arm.lower()+'-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            r=stopped_run(cmd(name,'review',audit),name,audit,deadline=2700,inspector=inspect)
            receipt['reviewer']=r;shutil.copytree(audit,root/'independent-review-stop')
            if r['exit_code']==0 and not r['oom_killed']:
                proof=json.loads((audit/'core-review.json').read_bytes());shutil.copyfile(audit/'core-review.json',root/'core-review.json')
                receipt['status']='COMPLETE_CANDIDATE_CORE_REVIEWED' if proof['complete'] and w['exit_code']==0 else 'PARTIAL_CANDIDATE_PREFIX_REVIEWED'
    except StopUnknown:
        receipt['status']='REVIEW_STOP_UNKNOWN_CANDIDATE_PRESERVED' if known else 'CANDIDATE_STOP_UNKNOWN'
        (diagnostic/'exception-chain.txt').write_text(traceback.format_exc())
    except Exception:
        receipt['status']='CANDIDATE_REFUSED_KNOWN_PREFIX' if known else 'CANDIDATE_REFUSED_NO_FINANCIAL_ADMISSION'
        (diagnostic/'exception-chain.txt').write_text(traceback.format_exc())
        if known:shutil.copytree(diagnostic,root/'driver-diagnostics')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if known:receipt['encrypted_output']=seal(root,a.output.parent/('campaign-candidate-'+arm+'.tar.crseal'),key,a.request,arm,
        stage='campaign-candidate',protocol_sha256=request['search_protocol_sha256'])
    elif any(diagnostic.iterdir()):receipt['diagnostic_output']=seal(diagnostic,a.output.parent/('campaign-diagnostic-'+arm+'.tar.crseal'),key,a.request,arm,
        stage='campaign-candidate',protocol_sha256=request['search_protocol_sha256'])
    key=None;a.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));raise SystemExit(0 if receipt['status']=='COMPLETE_CANDIDATE_CORE_REVIEWED' else 2)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('request','staging','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--index',type=int,required=True);main(p.parse_args())
