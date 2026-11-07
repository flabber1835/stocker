"""Bounded isolated funded accounts and stopped independent reviewer."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from alpaca_fit_job import stopped_run,StopUnknown,seal_output
from alpaca_fit_stage import SECRET,need
from alpaca_fit_funded_stage import stopped
from probe import check_context,memory_bytes
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file


def inspect_kind(name,identity,kind):
    need(re.fullmatch('capital-alpaca-fit-'+kind+'-[0-9]+-1',name) is not None,'FUNDED_WORKER_NAME')
    item=json.loads(subprocess.run(['docker','inspect',name],capture_output=True,check=True,timeout=20).stdout)[0]
    stopped(item,os.environ['GITHUB_RUN_ID'],kind,require_stopped=False)
    need(identity is None or item['Id']==identity,'FUNDED_WORKER_ID')
    c=item['Config'];m={x['Destination']:x for x in item['Mounts'] if x['Type']=='bind'}
    need(set(m)=={'/src','/inputs','/prefix','/core','/evidence','/out'} and m['/out']['RW']
        and not any(m[p]['RW'] for p in m if p!='/out') and c['WorkingDir']=='/src'
        and c['User']==f'{os.getuid()}:{os.getgid()}'
        and c['Labels'].get('research.study')=='alpaca-owned55-fit-001'
        and c['Labels'].get('research.stage')==kind,'FUNDED_MOUNTS_AND_ROLE')
    need('ALPACA_FIT_HOSTED=1' in c['Env'] and 'HOLDING_QUAL_HOSTED=1' in c['Env'],'FUNDED_HOSTED_BOUNDARY')
    return item


def command(kind,source,stage,evidence,output,previous=False):
    name='capital-alpaca-fit-'+kind+'-'+os.environ['GITHUB_RUN_ID']+'-1'
    argv=['docker','run','-d','--name',name,'--pull','never','--network','none','--read-only','--memory','8g','--memory-swap','8g',
        '--cpus','2','--pids-limit','64','--cap-drop','ALL','--security-opt','no-new-privileges','--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
        '--user',f'{os.getuid()}:{os.getgid()}','-w','/src','--label','research.study=alpaca-owned55-fit-001','--label','research.stage='+kind,
        '-e','PYTHONPATH=/src:/src/shared:/src/research/capital_risk','-e','ALPACA_FIT_HOSTED=1','-e','HOLDING_QUAL_HOSTED=1',
        '-e','OPENBLAS_NUM_THREADS=1','-e','OMP_NUM_THREADS=1']
    for path,target in [(source,'/src'),(stage['inputs_root'],'/inputs'),(stage['prefix_inputs_root'],'/prefix'),
                        (stage['core_evidence_root'],'/core'),(evidence,'/evidence')]:
        argv+=['--mount',f'type=bind,source={path},target={target},readonly']
    argv+=['--mount',f'type=bind,source={output},target=/out','--entrypoint','python',EXECUTION_IMAGE,'-B','-u',
        '/src/research/capital_risk/alpaca_fit_funded_'+('book' if kind=='funded' else 'review')+'.py',
        '--request','/src/research/capital_risk/alpaca-funded-request.json','--protocol','/src/research/capital_risk/alpaca-fit-protocol.json',
        '--core-evidence','/core/book','--inputs','/inputs','--prefix-inputs','/prefix','--bil-inputs','/inputs/_bil',
        '--output','/out/book' if kind=='funded' else '/out/review']
    if kind=='funded' and previous:argv+=['--previous','/evidence/book']
    if kind=='funded-review':argv+=['--evidence','/evidence']
    return name,argv


def main(a):
    check_context(os.environ);need(os.environ['GITHUB_RUN_ATTEMPT']=='1','FUNDED_NO_FRESH_RERUN')
    req=json.loads(Path(a.request).read_bytes());stage=json.loads(Path(a.staging).read_bytes())
    need(stage['status']=='FUNDED_INPUTS_AND_PREDECESSORS_AUTHENTICATED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
        and stage['head']==os.environ['GITHUB_SHA'] and stage['request_sha256']==sha256_file(a.request),'FUNDED_STAGE_IDENTITY')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'FUNDED_JOB_KEY')
    private=Path(os.environ['RUNNER_TEMP'])/'alpaca-funded-output';private.mkdir(mode=0o700,exist_ok=False)
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
    receipt={'schema':'research.alpaca-funded-receipt/1','run_id':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],
        'protocol_sha256':req['protocol_sha256'],'dataset_sha256':req['dataset_sha256'],'request_sha256':sha256_file(a.request),
        'stage':req['stage'],'status':'NOT_STARTED','production_contacted':False,'financial_replay_started':False,'encrypted_outputs':{}}
    known=False
    try:
        need((os.cpu_count() or 0)>=4 and memory_bytes()['MemAvailable']>=11*1024**3
             and shutil.disk_usage(private).free>=14*1024**3,'FUNDED_CAPACITY')
        previous=stage['previous_evidence_root'];evidence=previous or stage['empty_root']
        name,argv=command('funded',os.environ['GITHUB_WORKSPACE'],stage,evidence,private,bool(previous))
        receipt['financial_replay_started']=True
        receipt['worker']=stopped_run(argv,name,private,3120,inspector=lambda n,i:inspect_kind(n,i,'funded'));known=True
        receipt['status']='STOPPED_FUNDED_EVIDENCE_PRESERVED'
        if (private/'book/fit-status.json').is_file():
            audit=Path(os.environ['RUNNER_TEMP'])/'alpaca-funded-review';audit.mkdir(mode=0o700,exist_ok=False)
            name,argv=command('funded-review',os.environ['GITHUB_WORKSPACE'],stage,private/'book',audit)
            result=stopped_run(argv,name,audit,900,inspector=lambda n,i:inspect_kind(n,i,'funded-review'))
            receipt['review_worker']=result
            shutil.copytree(audit,private/'stopped-independent-review')
            receipt['status']='FUNDED_REVIEWED' if result['exit_code']==0 and not result['oom_killed'] else 'FUNDED_REVIEW_REFUSED_PRESERVED'
    except StopUnknown:receipt['status']='REVIEWER_STOP_UNKNOWN_FINANCIAL_PRESERVED' if known else 'WRITER_STOP_UNKNOWN'
    except Exception as exc:
        receipt['status']='FUNDED_REFUSED';receipt['error_type']=type(exc).__name__
        known=known or not receipt['financial_replay_started']
    if known:
        receipt['encrypted_outputs']['full']=seal_output(private,output.parent/'alpaca-funded-full.tar.crseal',key,req['protocol_sha256'],
            'FULL_STOPPED_EVIDENCE',stage='funded-fit')
    key=None;output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    return 0 if receipt['status']=='FUNDED_REVIEWED' else 2


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','staging','output'):p.add_argument('--'+name,required=True)
    raise SystemExit(main(p.parse_args()))
