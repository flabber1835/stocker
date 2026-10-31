"""Exact encrypted trace/account artifact admission before hosted parsing."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import zipfile

from alpaca_fit_stage import stage,SECRET,need
from alpaca_fit_prior import extract
from seal import decrypt,sha256_file
from runtime_identity import EXECUTION_IMAGE
from probe import FORBIDDEN_CREDENTIALS


def stopped(item,run,kind,*,require_stopped=True):
    need(item['Name']=='/capital-alpaca-fit-'+kind+'-'+str(run)+'-1' and item['Image']==EXECUTION_IMAGE
         and (not require_stopped or item['State']['Running'] is False and item['State']['OOMKilled'] is False),'FUNDED_PREDECESSOR_STOP')
    h=item['HostConfig'];need(h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3
        and h['NanoCpus']==2000000000 and h['ReadonlyRootfs'] and h['CapDrop']==['ALL']
        and h['PidsLimit']==64 and any(v.startswith('no-new-privileges') for v in h['SecurityOpt']),'FUNDED_PREDECESSOR_FENCES')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,'GH_TOKEN','GITHUB_TOKEN'}
    need(not any(k in forbidden and v for k,_,v in (e.partition('=') for e in item['Config']['Env'])),'FUNDED_PREDECESSOR_CREDENTIAL')


def artifact(spec,root,key,protocol,*,funded=False):
    root.mkdir(mode=0o700,exist_ok=False);archive=root/'artifact.zip'
    with archive.open('xb') as f:subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{spec['id']}/zip"],stdout=f,check=True,timeout=150)
    need(archive.stat().st_size==spec['bytes'] and sha256_file(archive)==spec['sha256'],'FUNDED_ARTIFACT_ZIP')
    receipt_name='alpaca-funded.json' if funded else 'alpaca-fit-baseline.json'
    allowed={receipt_name,spec['full']['name']}
    if not funded:allowed.add('alpaca-fit-baseline-summary.tar.crseal')
    with zipfile.ZipFile(archive) as z:
        need(set(z.namelist())==allowed and len(z.infolist())==len(allowed),'FUNDED_ARTIFACT_MEMBERS')
        for item in z.infolist():
            need(item.file_size<=3*1024**3,'FUNDED_ARTIFACT_SIZE')
            with z.open(item) as src,(root/item.filename).open('xb') as f:shutil.copyfileobj(src,f,1024**2)
    receipt=json.loads((root/receipt_name).read_bytes())
    need(receipt['run_id']==str(spec['run_id']) and receipt['head']==spec['head'] and receipt['protocol_sha256']==protocol
         and receipt['production_contacted'] is False and receipt['encrypted_outputs']['full']==spec['full'],'FUNDED_ARTIFACT_RECEIPT')
    cipher=root/spec['full']['name'];need(cipher.stat().st_size==spec['full']['bytes'] and sha256_file(cipher)==spec['full']['sha256'],'FUNDED_ARTIFACT_CIPHER')
    plain=root/'evidence.tar';decrypt(cipher,plain,key,spec['full']['sha256'])
    extract(plain,root/'full',spec['full'],spec,protocol,stage='funded-fit' if funded else 'canonical-baseline')
    stopped(json.loads((root/'full/worker-inspect.json').read_bytes()),spec['run_id'],'funded' if funded else 'baseline')
    stopped(json.loads((root/'full/stopped-independent-review/worker-inspect.json').read_bytes()),spec['run_id'],'funded-review' if funded else 'review')
    audit=json.loads((root/'full/stopped-independent-review/review/independent-review.json').read_bytes())
    need(audit['status'] in (('COMPLETE_REVIEWED','PARTIAL_PREFIXES_REVIEWED') if funded else ('COMPLETE_TRACE_REVIEWED','PARTIAL_PREFIX_REVIEWED')),
         'FUNDED_PREDECESSOR_REVIEW')
    return receipt,audit


def main(a):
    req=json.loads(Path(a.request).read_bytes());root=Path(a.output);root.mkdir(mode=0o700,parents=True,exist_ok=False)
    need(req['schema']=='research.alpaca-funded-request/1' and req['stage'] in ('TRAINING','DIAGNOSTIC')
        and req['production_contacted'] is False,'FUNDED_STAGE_SCOPE')
    raw_key=os.environ[SECRET];key=base64.b64decode(raw_key,validate=True);need(len(key)==32,'FUNDED_KEY')
    old=dict(req['input_request']);old.pop('continuation',None);old.pop('input_reference',None)
    need(old['dataset_sha256']==req['dataset_sha256'] and old['protocol_sha256']==req['protocol_sha256'],'FUNDED_SOURCE_DATA')
    temporary=root/'input-stage-request.json';temporary.write_text(json.dumps(old)+'\n')
    stage(SimpleNamespace(request=str(temporary),output=str(root/'market-stage')))
    staged=json.loads((root/'market-stage/staging.json').read_bytes());inputs=Path(staged['inputs_root'])
    core_receipt,audit=artifact(req['core_artifact'],inputs/'_core',key,req['protocol_sha256'])
    need(sha256_file(inputs/'_core/full/stopped-independent-review/review/independent-review.json')==req['core_independent_review_sha256'],
         'FUNDED_EXACT_CORE_REVIEW')
    cutoff=req['required_core_end']
    need(audit['last_committed_session']>=cutoff and audit['uncommitted_tail_bytes']==0,'FUNDED_COMPLETE_SOURCE_PERIOD')
    previous=None
    if req.get('previous_artifact'):
        previous,audit=artifact(req['previous_artifact'],inputs/'_funded',key,req['protocol_sha256'],funded=True)
        if req['stage']=='DIAGNOSTIC':
            need(sha256_file(inputs/'_funded/full/stopped-independent-review/review/locked-selection.json')==req['locked_selection_sha256'],
                 'FUNDED_EXACT_LOCKED_SELECTION')
    else:(inputs/'_empty').mkdir()
    shutil.copytree(staged['bil_inputs_root'],inputs/'_bil')
    result={**staged,'schema':'research.alpaca-funded-staging/1','status':'FUNDED_INPUTS_AND_PREDECESSORS_AUTHENTICATED',
        'core_evidence_root':str(inputs/'_core/full'),'previous_evidence_root':str(inputs/'_funded/full') if previous else None,
        'empty_root':str(inputs/'_empty'),'core_artifact':req['core_artifact'],'previous_artifact':req.get('previous_artifact'),
        'request_sha256':sha256_file(a.request)}
    (root/'staging.json').write_text(json.dumps(result,indent=2)+'\n');key=None;raw_key=None
    print('FUNDED_TRACE_AND_INPUTS_AUTHENTICATED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--output',required=True);main(p.parse_args())
