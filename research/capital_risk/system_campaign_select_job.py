"""One hosted aggregation of authenticated training evidence; no market replay."""
import argparse,base64,json,os,re,shutil,subprocess
from pathlib import Path
from alpaca_fit_job import stopped_run,StopUnknown
from full_system_benchmark import need
from full_system_trials_job import command as base_command,seal
from system_campaign_numeric_job import SOURCES as NUMERICAL_SOURCES
from system_campaign_search_admit import admit
from system_campaign_source import build
from system_campaign_space import initial
from system_campaign_facts import digest
from probe import check_context,memory_bytes,FORBIDDEN_CREDENTIALS
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from stage import SECRET,PROTOCOL,IMAGE

HERE=Path(__file__).resolve().parent
SOURCES=tuple(dict.fromkeys((*NUMERICAL_SOURCES,'system_campaign_select_job.py','system_campaign_select.py',
    'system_campaign_search_admit.py','system_campaign_selection.py','system_campaign_acquire.py')))


def reference_gate():
    p=HERE/'system-campaign-reference-comparison.json';v=json.loads(p.read_bytes())
    need(v['schema']=='research.system-campaign-complete-reference-comparison/1'
         and v['status']=='COMPLETE_REFERENCE_FINANCIAL_PATH_EQUIVALENCE_PASSED'
         and v['formation']==126 and v['measured_closes']==2156
         and v['full_final_financial_controller_reporting_state_exact']
         and all(v['streams'][a+'/'+n]['count']==count and v['streams'][a+'/'+n]['exact_economics_and_evidence']
             for a in ('B0','P00') for n,count in (('formation',126),('daily',2156),('monthly',103))),
         'GLOBAL_SELECTION_ACTUAL_REFERENCE_EQUALITY')
    return sha256_file(p)


def expected_request(specs,expected_core_ids):
    return {'schema':'research.system-campaign-training-selection-request/1','campaign':'system-optimization-002',
        'protocol_sha256':sha256_file(HERE/'system-campaign-search-protocol.json'),
        'baseline_equivalence_sha256':reference_gate(),'expected_core_ids':expected_core_ids,'numerical_artifacts':specs,
        'sources':{n:sha256_file(HERE/n) for n in SOURCES},'training_cutoffs':['2020-12-31','2022-12-30'],
        'worker_wait_seconds':600,'artifact_retention_days':7,'new_core_financial_sessions':0,
        'evaluation_used':False,'global_optimum_claim':False,'production_contacted':False}


def inspect(name,identity=None):
    need(re.fullmatch('capital-system-selection-worker-[0-9]+-1',name) is not None,'GLOBAL_SELECTION_WORKER_NAME')
    v=json.loads(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    h,c=v['HostConfig'],v['Config'];m={x['Destination']:x for x in v['Mounts'] if x['Type']=='bind'}
    need(v['Name']=='/'+name and v['Image']==EXECUTION_IMAGE and (identity is None or v['Id']==identity),
         'GLOBAL_SELECTION_WORKER_IDENTITY')
    need(h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3 and h['NanoCpus']==2000000000
         and h['PidsLimit']==64 and h['ReadonlyRootfs'] and h['CapDrop']==['ALL']
         and any(x.startswith('no-new-privileges') for x in h['SecurityOpt']),'GLOBAL_SELECTION_FENCES')
    need(set(m)=={'/variant','/frozen','/driver','/out','/admitted'} and m['/out']['RW']
         and all(not x['RW'] for k,x in m.items() if k!='/out') and c['WorkingDir']=='/variant'
         and c['User']==f'{os.getuid()}:{os.getgid()}' and c['Labels']['research.study']=='full-system-search-20261029'
         and c['Labels']['research.role']=='worker' and c['Cmd'].count('/driver/system_campaign_select.py')==1,
         'GLOBAL_SELECTION_READONLY_INPUTS_AND_EXACT_ENTRY')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,'GITHUB_TOKEN','GH_TOKEN'}
    need(not any(k in forbidden and val for k,_,val in (x.partition('=') for x in c['Env'])),'GLOBAL_SELECTION_NO_CREDENTIALS')
    return v


def command(name,source,frozen,out,admitted):
    base=base_command(name,source,frozen,out,'economic');i=base.index('--entrypoint')
    return base[:i]+['--mount',f'type=bind,source={admitted},target=/admitted,readonly',
        '--entrypoint','python',EXECUTION_IMAGE,'-B','-u','/driver/system_campaign_select.py',
        '--admitted','/admitted/training.json','--output','/out/selection']


def main(a):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','GLOBAL_SELECTION_NO_FRESH_RERUN')
    r=json.loads(a.request.read_bytes());need(r==expected_request(r['numerical_artifacts'],r['expected_core_ids'])
         and 0<len(r['numerical_artifacts'])<=20 and set(v['id'] for v in initial())<=set(r['expected_core_ids']),
         'GLOBAL_SELECTION_EXACT_FROZEN_REQUEST')
    s=json.loads(a.staging.read_bytes())
    need(s['status']=='STAGING_PASSED' and s['run_id']==os.environ['GITHUB_RUN_ID'] and s['source_commit']==os.environ['GITHUB_SHA']
         and s['protocol_sha256']==PROTOCOL and s['runtime_image']==IMAGE and s['execution_image']==EXECUTION_IMAGE
         and s['source_files_verified']==514 and s['members_verified']==591
         and s['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and s['authenticated_before_parsing'] and s['offline_image_source_verified']
         and s['runtime_index_config_layer_chain_verified'] and not s['replay_started'],'GLOBAL_SELECTION_FROZEN_STAGING')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    known=False;out=temp/'campaign-search-output';out.mkdir(mode=0o700)
    receipt={'schema':'research.system-campaign-training-selection-receipt/1','run_id':os.environ['GITHUB_RUN_ID'],
        'head':os.environ['GITHUB_SHA'],'request_sha256':sha256_file(a.request),'protocol_sha256':r['protocol_sha256'],
        'status':'NOT_STARTED','production_contacted':False,'evaluation_used':False,'new_core_financial_sessions':0}
    try:
        budget=sum(v['zip_bytes'] for v in r['numerical_artifacts'].values())
        need(budget<=10*1024**3 and shutil.disk_usage(temp).free>budget+4*1024**3,'GLOBAL_SELECTION_BOUNDED_TRANSFER_CAPACITY')
        envelopes=[]
        for arm,spec in r['numerical_artifacts'].items():
            need(re.fullmatch('P[0-9]{2}',arm) and spec['arm']==arm,'GLOBAL_SELECTION_EXACT_ARM')
            envelopes.append(admit(spec,temp/('campaign-search-admit-'+arm),key))
        os.environ.pop('GH_TOKEN',None)
        private=temp/'campaign-search-admitted';private.mkdir(mode=0o700)
        raw={'schema':'research.system-campaign-admitted-training/1','baseline_equivalence_sha256':r['baseline_equivalence_sha256'],
            'expected_core_ids':r['expected_core_ids'],'cores':envelopes}
        (private/'training.json').write_text(json.dumps(raw,indent=2,allow_nan=False)+'\n')
        source=temp/'campaign-search-source';build(frozen/'source-fixed',source)
        for root in (source,private):
            for p in root.rglob('*'):os.chmod(p,0o555 if p.is_dir() else 0o444)
            os.chmod(root,0o555)
        need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=4*1024**3,'GLOBAL_SELECTION_RESOURCES')
        (out/'request.json').write_bytes(a.request.read_bytes())
        name='capital-system-selection-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        w=stopped_run(command(name,source,frozen,out,private),name,out,deadline=600,inspector=inspect)
        known=True;receipt['worker']=w;receipt['status']='GLOBAL_SELECTION_STOPPED_OUTPUT_PRESERVED'
        if w['exit_code']==0 and not w['oom_killed']:
            proof=json.loads((out/'selection/selection-summary.json').read_bytes())
            need(proof['status']=='TRAINING_LOCKED_DIRECT_FINALIST_CONFIRMATION_REQUIRED'
                 and not proof['evaluation_used'] and not proof['global_optimum_claim'] and not proof['production_contacted'],
                 'GLOBAL_SELECTION_ACTUAL_TRAINING_ONLY_RESULT')
            receipt['status']='GLOBAL_TRAINING_LOCKS_AND_ACQUISITIONS_COMPLETE_DIRECT_CONFIRMATION_REQUIRED'
    except StopUnknown:receipt['status']='GLOBAL_SELECTION_WORKER_STOP_UNKNOWN'
    except Exception as exc:
        receipt['status']='GLOBAL_SELECTION_REFUSED_KNOWN_OUTPUT' if known else 'GLOBAL_SELECTION_REFUSED_NO_NEW_FINANCIAL_SESSIONS'
        if known:(out/'failure.json').write_text(json.dumps({'type':type(exc).__name__,'message':str(exc)})+'\n')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if known:receipt['encrypted_output']=seal(out,a.output.parent/'campaign-training-selection.tar.crseal',key,a.request,
        'SEARCH',stage='multiyear-controller',protocol_sha256=r['protocol_sha256'])
    key=None;a.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='GLOBAL_TRAINING_LOCKS_AND_ACQUISITIONS_COMPLETE_DIRECT_CONFIRMATION_REQUIRED' else 2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('request','staging','output'):p.add_argument('--'+n,type=Path,required=True)
    main(p.parse_args())
