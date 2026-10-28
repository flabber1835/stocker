"""Authenticate the complete streamed market capture before any worker parsing."""
from __future__ import annotations
import argparse
import base64
import hashlib
import gzip
import json
import os
import ssl
import time
from pathlib import Path
import subprocess
import tarfile
from urllib import request,parse,error

from seal import decrypt,safe_name,sha256_file
from runtime_identity import verify_archive,verify_loaded,EXECUTION_IMAGE

REPO='flabber1835/stocker';RELEASE='research-capital-risk-inputs-20261027'
SECRET='CAPITAL_RISK_RESEARCH_KEY_20261027'


def need(v,reason):
    if not v:raise ValueError('REFUSED_'+reason)


def acquire(name,spec,root):
    safe_name(name);path=root/name
    need(path.parent==root and not path.exists(),'ASSET_PATH_OR_COLLISION')
    url=f'https://github.com/{REPO}/releases/download/{RELEASE}/'+parse.quote(name,safe='')
    partial=path.with_name(path.name+'.partial');need(not partial.exists(),'PARTIAL_COLLISION')
    for attempt in range(3):
        total=0;digest=hashlib.sha256()
        try:
            with request.urlopen(url,timeout=45) as response,partial.open('xb') as f:
                while chunk:=response.read(1024**2):
                    total+=len(chunk);need(total<=spec['bytes'],'ASSET_LENGTH_BOUND');digest.update(chunk);f.write(chunk)
            break
        except (ssl.SSLError,error.URLError,TimeoutError):
            need(partial.parent.resolve()==root.resolve(),'EXACT_PARTIAL_PATH')
            partial.unlink(missing_ok=True)
            if attempt==2:raise ValueError('REFUSED_BOUNDED_DOWNLOAD_RETRIES') from None
            time.sleep(2*(attempt+1))
    need(total==spec['bytes'] and digest.hexdigest()==spec['sha256'],'ASSET_HASH_OR_LENGTH')
    partial.rename(path)
    return path


def extract_streamed(archive,root,expected_manifest,protocol_sha,*,failed_prefix_scope=None):
    need(failed_prefix_scope in (None,'TLS_FAILED_PREFIX','WIRE_ORDER_WITNESS'),'PREFIX_SCOPE')
    need(not root.exists(),'EXTRACTION_COLLISION')
    found={};manifest=None;manifest_payload=None;total=0
    with tarfile.open(archive,'r:') as tar:
        for item in tar:
            safe_name(item.name)
            need(item.isfile() and item.name not in found and len(found)<2501 and manifest is None,'STREAM_MEMBER_SHAPE')
            need(0<=item.size<=32*1024**2,'MEMBER_SIZE')
            data=tar.extractfile(item).read();need(len(data)==item.size,'MEMBER_TRUNCATION')
            total+=len(data);need(total<=600*1024**2,'EXPANSION_BOUND')
            if item.name=='manifest.json':
                manifest_payload=data;need(hashlib.sha256(data).hexdigest()==expected_manifest,'FINAL_MANIFEST_HASH')
                manifest=json.loads(data)
            else:found[item.name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    expected_status={None:'COMPLETE','TLS_FAILED_PREFIX':'FAILED','WIRE_ORDER_WITNESS':'INCOMPLETE'}[failed_prefix_scope]
    need(manifest is not None and manifest['schema']=='research.alpaca-fit-stream-inputs/1'
        and manifest['status']==expected_status
        and manifest['market_capture_status']==('COMPLETE' if failed_prefix_scope is None else 'INCOMPLETE')
        and manifest['protocol_sha256']==protocol_sha and manifest['manifest_position']=='LAST'
        and manifest['members']==found,'COMPLETE_STREAM_INVENTORY')
    root.mkdir(mode=0o700)
    with tarfile.open(archive,'r:') as tar:
        for item in tar:
            safe_name(item.name);target=root/item.name
            need(root.resolve() in target.resolve().parents,'EXTRACTION_PATH')
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as f:
                source=tar.extractfile(item)
                while chunk:=source.read(1024**2):f.write(chunk)
    return manifest


def successor(root,req):
    from alpaca_fit_compare import compare
    prefix=root/'prefix/inputs';witness=root/'corroboration/inputs';suffix=root/'market/inputs'
    before=[json.loads(r) for r in (prefix/'capture/request-receipts.jsonl').read_bytes().splitlines()][-1]
    newer=[json.loads(r) for r in (witness/'capture/request-receipts.jsonl').read_bytes().splitlines()]
    need(len(newer)==1 and newer[0]['purpose']=='EXACT_PREDECESSOR_CORROBORATION','WITNESS_SCOPE')
    after=newer[0]
    def raw(folder,proof):
        with gzip.open(folder/'capture'/proof['file'],'rb') as f:value=f.read(32*1024**2+1)
        need(len(value)==proof['raw_bytes'] and hashlib.sha256(value).hexdigest()==proof['raw_sha256'],'WITNESS_RAW_PREIMAGE')
        return value
    old,new=raw(prefix,before),raw(witness,after)
    need(before['params']==after['params'] and before['endpoint']==after['endpoint'] and compare(old,new),'EXACT_JSON_PREDECESSOR')
    review=json.loads((suffix/'capture/corroboration.json').read_bytes())['review']
    capture=json.loads((suffix/'capture/capture.json').read_bytes())
    need(review['old_manifest_sha256']==req['captures']['prefix']['manifest_sha256']
        and review['new_manifest_sha256']==req['captures']['corroboration']['manifest_sha256']
        and review['old_raw_sha256']==before['raw_sha256'] and review['new_raw_sha256']==after['raw_sha256']
        and review['corroborated_next_page_token']==json.loads(new).get('next_page_token')
        and capture['predecessor_manifest_sha256']==req['captures']['prefix']['manifest_sha256']
        and capture['corroboration_manifest_sha256']==req['captures']['corroboration']['manifest_sha256']
        and capture['remaining_query_plan_complete'] is True,'SUCCESSOR_BINDING')
    need(json.loads((prefix/'capture/capture.json').read_bytes())['failure']=='SSLError'
        and json.loads((witness/'capture/capture.json').read_bytes())['failure']=='REFUSED_CHANGED_PREDECESSOR_PAGE','RETAINED_FAILURE_IDENTITIES')
    return {'whole_json_values_and_array_order_equal':True,'wire_bytes_equal':old==new,
        'old_raw_sha256':before['raw_sha256'],'witness_raw_sha256':after['raw_sha256'],
        'successor_cursor_verified':True,'failed_prefixes_not_relabelled':True}


def stage(args):
    need(os.environ.get('GITHUB_REPOSITORY')==REPO and os.environ.get('GITHUB_REF')=='refs/heads/codex/capital-risk-research'
         and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','HOSTED_CONTEXT')
    req=json.loads(Path(args.request).read_bytes());root=Path(args.output)
    need(req['schema']=='research.alpaca-fit-hosted-request/1' and req['study_id']=='alpaca-owned55-fit-001'
         and req['stage']=='INPUT_AND_CANONICAL_BASELINE' and req['production_contacted'] is False
         and set(req['captures'])=={'prefix','corroboration','market','bil'},'REQUEST_SCOPE')
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'RESEARCH_KEY')
    counts={}
    for label in ('prefix','corroboration','market','bil'):
        capture=req['captures'][label];folder=root/label;folder.mkdir()
        failed=label in ('prefix','corroboration')
        expected_status={'prefix':'FAILED','corroboration':'INCOMPLETE','market':'COMPLETE','bil':'COMPLETE'}[label]
        need(capture['status']==expected_status and capture['collector_exit_code']==(1 if failed else 0)
             and capture['release']==RELEASE and capture['repository']==REPO
             and capture['protocol_sha256']==req['protocol_sha256']
             and 0<len(capture['parts'])<=40,'CAPTURE_SCOPE')
        cipher=folder/'market.tar.crseal';digest=hashlib.sha256();count=0;names=set()
        with cipher.open('xb') as destination:
            for part in capture['parts']:
                need(part['name'] not in names and '/' not in part['name'] and 0<part['bytes']<=16*1024**2,'PART_SHAPE')
                names.add(part['name']);path=acquire(part['name'],part,folder)
                with path.open('rb') as source:
                    while chunk:=source.read(1024**2):destination.write(chunk);digest.update(chunk);count+=len(chunk)
        need(count==capture['ciphertext_bytes'] and digest.hexdigest()==capture['ciphertext_sha256'],'FULL_CIPHER_REASSEMBLY')
        plain=folder/'market.tar';decrypt(cipher,plain,key,capture['ciphertext_sha256'])
        scope={'prefix':'TLS_FAILED_PREFIX','corroboration':'WIRE_ORDER_WITNESS'}.get(label)
        manifest=extract_streamed(plain,folder/'inputs',capture['manifest_sha256'],req['protocol_sha256'],failed_prefix_scope=scope)
        need(sha256_file(folder/'inputs/protocol.json')==req['protocol_sha256']
             and sha256_file(folder/'inputs/roster.json')==req['roster_sha256'],'EXACT_PROTOCOL_AND_ROSTER')
        counts[label]=len(manifest['members'])
    comparison=successor(root,req)
    dataset={'schema':'research.alpaca-composite-input/1','protocol_sha256':req['protocol_sha256'],
        'roster_sha256':req['roster_sha256'],'manifests':{k:v['manifest_sha256'] for k,v in req['captures'].items()}}
    need(hashlib.sha256(json.dumps(dataset,sort_keys=True,separators=(',',':')).encode()).hexdigest()==req['dataset_sha256'],'COMPOSITE_DATASET_IDENTITY')
    runtime=req['runtime'];asset=acquire('runtime.tar.crseal',runtime,root)
    decrypt(asset,root/'runtime.tar',key,runtime['sha256']);key=None
    portable=verify_archive(root/'runtime.tar')
    with (root/'runtime.tar').open('rb') as f:subprocess.run(['docker','load','--quiet'],stdin=f,capture_output=True,timeout=120,check=True)
    observed=json.loads(subprocess.run(['docker','image','inspect',EXECUTION_IMAGE],capture_output=True,timeout=20,check=True).stdout)[0]
    verify_loaded(observed)
    receipt={'schema':'research.alpaca-fit-staging/1','status':'AUTHENTICATED_INPUTS_AND_RUNTIME',
        'run_id':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],'protocol_sha256':req['protocol_sha256'],
        'capture_manifest_sha256':{label:c['manifest_sha256'] for label,c in req['captures'].items()},'input_members':counts,
        'execution_image':EXECUTION_IMAGE,'runtime_archive_sha256':portable['archive_sha256'],
        'dataset_sha256':req['dataset_sha256'],'successor_review':comparison,
        'authenticated_before_parsing':True,'financial_replay_started':False,'production_contacted':False,
        'inputs_root':str(root/'market/inputs'),'prefix_inputs_root':str(root/'prefix/inputs'),'bil_inputs_root':str(root/'bil/inputs')}
    (root/'staging.json').write_text(json.dumps(receipt,indent=2)+'\n');print('ALPACA_INPUTS_AND_RUNTIME_AUTHENTICATED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--output',required=True)
    stage(p.parse_args())
