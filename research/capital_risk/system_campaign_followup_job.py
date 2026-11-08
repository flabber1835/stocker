"""One own-checkpoint factual suffix on an isolated GitHub-hosted VM."""
import argparse,base64,json,os,re,shutil,subprocess,traceback
from pathlib import Path
from full_system_benchmark import need
from full_system_trials_job import command,seal
from system_campaign_candidate_job import SOURCES as CANDIDATE_SOURCES
from system_campaign_factual_admit import admit
from system_campaign_variants import build as candidate_source
from system_campaign_source import build as baseline_source
from alpaca_fit_job import stopped_run,StopUnknown
from probe import check_context,memory_bytes,FORBIDDEN_CREDENTIALS
from stage import SECRET,PROTOCOL,IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file

HERE=Path(__file__).resolve().parent
SOURCES=tuple(dict.fromkeys((*CANDIDATE_SOURCES,'system_campaign_source.py','system_campaign_facts.py',
    'system_campaign_factual_job.py','system_campaign_factual_admit.py','system_campaign_factual_run.py','system_campaign_terminal_job.py','system_campaign_terminal_run.py','system_campaign_terminal_facts.py','system_campaign_march_job.py','system_campaign_march_run.py','system_campaign_march_facts.py','system_campaign_winter_job.py','system_campaign_winter_run.py','system_campaign_winter_facts.py','system_campaign_spring_job.py','system_campaign_spring_run.py','system_campaign_spring_facts.py','system_campaign_tgi_facts.py','system_campaign_followup_job.py','system_campaign_followup_run.py','system_campaign_followup_facts.py')))


def expected_request():
    return {'schema':'research.system-campaign-followup-suffix-request/1','campaign':'system-optimization-002',
        'protocol_sha256':sha256_file(HERE/'system-campaign-search-protocol.json'),
        'predecessors_sha256':sha256_file(HERE/'system-campaign-followup-predecessors.json'),
        'catalog_sha256':sha256_file(HERE/'system-campaign-factual-catalog.json'),
        'additional_catalog_sha256':sha256_file(HERE/'system-campaign-additional-terminal-facts.json'),
        'march_catalog_sha256':sha256_file(HERE/'system-campaign-march-cash-facts.json'),
        'winter_catalog_sha256':sha256_file(HERE/'system-campaign-corrected-winter-facts.json'),
        'spring_catalog_sha256':sha256_file(HERE/'system-campaign-spring-terminal-facts.json'),
        'followup_catalog_sha256':sha256_file(HERE/'system-campaign-followup-terminal-facts.json'),
        'tgi_catalog_sha256':sha256_file(HERE/'system-campaign-tgi-cash-facts.json'),
        'sources':{n:sha256_file(HERE/n) for n in SOURCES},'financial_wait_seconds':12600,
        'review_wait_seconds':2700,'artifact_retention_days':7,'production_contacted':False,
        'all_financial_source_bytes_identical':True,'old_branches_preserved':True,'new_origin':False}


def inspect(name,identity=None):
    need(re.fullmatch(r'capital-system-factual-(?:b|b0|p[0-9]{2})-(?:worker|review)-[0-9]+-1',name) is not None,'FACTUAL_WORKER_NAME')
    v=json.loads(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    h,c=v['HostConfig'],v['Config'];m={x['Destination']:x for x in v['Mounts'] if x['Type']=='bind'}
    need(v['Name']=='/'+name and v['Image']==EXECUTION_IMAGE and (identity is None or v['Id']==identity),'FACTUAL_WORKER_IDENTITY')
    need(h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3 and h['NanoCpus']==2000000000
         and h['PidsLimit']==64 and h['ReadonlyRootfs'] and h['CapDrop']==['ALL']
         and any(s.startswith('no-new-privileges') for s in h['SecurityOpt']),'FACTUAL_WORKER_FENCES')
    expected={'/variant','/frozen','/driver','/out','/old'}|({'/evidence'} if '-review-' in name else set())
    need(set(m)==expected and m['/out']['RW'] and all(not x['RW'] for k,x in m.items() if k!='/out')
         and c['WorkingDir']=='/variant' and c['User']==f'{os.getuid()}:{os.getgid()}'
         and c['Labels']['research.study']=='full-system-search-20261029'
         and c['Labels']['research.role']==('review' if '-review-' in name else 'worker'),'FACTUAL_WORKER_MOUNTS')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,'GITHUB_TOKEN','GH_TOKEN'}
    need(not any(k in forbidden and value for k,_,value in (s.partition('=') for s in c['Env'])),'FACTUAL_WORKER_CREDENTIALS')
    return v


def main(a):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_FACTUAL_SUFFIX_RERUN')
    request=json.loads(a.request.read_bytes());need(request==expected_request(),'EXACT_FACTUAL_SUFFIX_REQUEST')
    specifications=json.loads((HERE/'system-campaign-followup-predecessors.json').read_bytes())['arms']
    spec=specifications[a.arm]
    stage=json.loads(a.staging.read_bytes())
    need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
         and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
         and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
         and stage['source_files_verified']==514 and stage['members_verified']==591
         and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],'FACTUAL_SUFFIX_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    old=admit(spec,temp/('campaign-factual-transfer-'+a.arm),key);os.environ.pop('GH_TOKEN',None)
    source=temp/'campaign-factual-source'
    old_binding=json.loads((old/'source-bindings.json').read_bytes())
    binding=candidate_source(frozen/'source-fixed',source,old_binding['parameters']) if a.arm.startswith('P') else baseline_source(frozen/'source-fixed',source)
    need(binding==old_binding,'FACTUAL_ENTIRE_FINANCIAL_SOURCE_IDENTICAL')
    out=temp/'campaign-factual-output';out.mkdir(mode=0o700)
    (out/'source-bindings.json').write_bytes((old/'source-bindings.json').read_bytes())
    (out/'request.json').write_bytes(a.request.read_bytes());(out/'spec.json').write_text(json.dumps(spec,indent=2)+'\n')
    diagnostic=temp/'campaign-factual-diagnostic';diagnostic.mkdir(mode=0o700)
    for root in (source,old):
        for p in root.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
        os.chmod(root,0o555)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=10*1024**3,'FACTUAL_SUFFIX_RESOURCES')
    receipt={'schema':'research.system-campaign-factual-suffix-receipt/1','arm':a.arm,'run_id':os.environ['GITHUB_RUN_ID'],
        'head':os.environ['GITHUB_SHA'],'request_sha256':sha256_file(a.request),'protocol_sha256':request['protocol_sha256'],
        'predecessor_run_id':spec['run_id'],'selected_predecessor_outer_sha256':spec['outer_sha256'],
        'catalog_sha256':request['catalog_sha256'],'additional_catalog_sha256':request['additional_catalog_sha256'],
        'march_catalog_sha256':request['march_catalog_sha256'],'winter_catalog_sha256':request['winter_catalog_sha256'],'spring_catalog_sha256':request['spring_catalog_sha256'],'followup_catalog_sha256':request['followup_catalog_sha256'],'tgi_catalog_sha256':request['tgi_catalog_sha256'],
        'production_contacted':False,'performance_admitted':False,'status':'NOT_STARTED'}
    def cmd(name,mode,output):
        values=command(name,source,frozen,output,mode);values[values.index('/driver/full_system_core.py')]='/driver/system_campaign_followup_run.py'
        i=values.index('--entrypoint');values[i:i]=['--mount',f'type=bind,source={old},target=/old,readonly']
        if mode=='review':
            i=values.index('--entrypoint');values[i:i]=['--mount',f'type=bind,source={out},target=/evidence,readonly']
        values+=['--spec','/evidence/spec.json' if mode=='review' else '/out/spec.json'];return values
    known=False
    try:
        name=f'capital-system-factual-{a.arm.lower()}-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        w=stopped_run(cmd(name,'economic',out),name,out,deadline=12600,inspector=inspect)
        known=True;receipt['worker']=w;receipt['status']='STOPPED_FACTUAL_PREFIX_PRESERVED'
        shutil.copyfile(out/'worker-inspect.json',out/'economic-worker-inspect.json');shutil.copyfile(out/'worker.log',out/'economic-worker.log')
        if (out/'book/checkpoint.json.gz').is_file() and not w['oom_killed']:
            audit=temp/'campaign-factual-review';audit.mkdir(mode=0o700)
            name=f'capital-system-factual-{a.arm.lower()}-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            r=stopped_run(cmd(name,'review',audit),name,audit,deadline=2700,inspector=inspect)
            receipt['reviewer']=r;shutil.copytree(audit,out/'independent-review-stop')
            if r['exit_code']==0 and not r['oom_killed']:
                proof=json.loads((audit/'core-review.json').read_bytes());shutil.copyfile(audit/'core-review.json',out/'core-review.json')
                receipt['status']='COMPLETE_FACTUAL_SUFFIX_REVIEWED' if proof['complete'] and w['exit_code']==0 else 'PARTIAL_FACTUAL_PREFIX_REVIEWED'
    except StopUnknown:
        receipt['status']='REVIEW_STOP_UNKNOWN_FACTUAL_PREFIX_PRESERVED' if known else 'FACTUAL_WRITER_STOP_UNKNOWN'
        (diagnostic/'exception-chain.txt').write_text(traceback.format_exc())
    except Exception:
        receipt['status']='FACTUAL_REFUSED_KNOWN_PREFIX' if known else 'FACTUAL_REFUSED_NO_NEW_FINANCIAL_ADMISSION'
        (diagnostic/'exception-chain.txt').write_text(traceback.format_exc())
        if known:shutil.copytree(diagnostic,out/'driver-diagnostics')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if known:
        # Only after every relevant current writer is positively stopped. The
        # immutable old branch was a separate RO mount during all financial work.
        shutil.copytree(old,out/'lineage/old-branch')
        receipt['encrypted_output']=seal(out,a.output.parent/('campaign-factual-'+a.arm+'.tar.crseal'),key,a.request,a.arm,
            stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
    elif any(diagnostic.iterdir()):
        receipt['diagnostic_output']=seal(diagnostic,a.output.parent/('campaign-factual-diagnostic-'+a.arm+'.tar.crseal'),key,a.request,a.arm,
            stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
    key=None;a.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='COMPLETE_FACTUAL_SUFFIX_REVIEWED' else 2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('request','staging','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--arm',required=True);main(p.parse_args())
