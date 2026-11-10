"""Local authenticated DATA admission only; never execute the stop screen."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

from job import IMAGE,SECRET,FORBIDDEN,DOC,ROOT,REQUEST,expected_request,need,sha,save


def stopped(value, role, run_id):
    c,h,s = value['Config'],value['HostConfig'],value['State']
    need(value['Name']==f'/wider-stop-{role}-{run_id}-1' and value['Image']==IMAGE
         and not s['Running'] and not s['OOMKilled'] and s['ExitCode']==0
         and re.fullmatch('[a-f0-9]{64}',value['Id']), 'POSITIVE_STOPPED_IDENTITY')
    need(h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['Memory']==h['MemorySwap']==8*1024**3
         and h['NanoCpus']==2000000000 and h['PidsLimit']==64 and h['CapDrop']==['ALL']
         and any(v.startswith('no-new-privileges') for v in h['SecurityOpt']), 'ARCHIVED_FENCES')
    mounts={m['Destination']:m for m in value['Mounts'] if m['Type']=='bind'}
    need(set(mounts)==({'/current','/stoprepo','/frozen','/p00','/out'}|({'/evidence'} if role=='review' else set()))
         and mounts['/out']['RW'] and all(not m['RW'] for k,m in mounts.items() if k!='/out'), 'ARCHIVED_MOUNTS')
    cmd=['-B','-u',f'/current/research/wider_stop/{role}.py','--book','/p00/book',
         '--archive','/frozen/archive/corpus.zip','--bundle','/frozen/bundle','--out','/out/'+role]
    if role=='review':cmd+=['--evidence','/evidence/worker']
    need(c['Entrypoint']==['python'] and c['Cmd']==cmd and c['WorkingDir']=='/current'
         and re.fullmatch('[1-9][0-9]*:[1-9][0-9]*',c['User'])
         and c['Labels'].get('research.study')=='wider-stop-20261109'
         and c['Labels'].get('research.role')==role, 'ARCHIVED_ENTRYPOINT')
    need(not any(k in FORBIDDEN|{SECRET,'GH_TOKEN','GITHUB_TOKEN'} and v
                 for k,_,v in (s.partition('=') for s in c['Env'])), 'ARCHIVED_CREDENTIALS')


def admit(args):
    need(json.loads(REQUEST.read_bytes())==expected_request(), 'UNCHANGED_SOURCE_REQUEST')
    receipt=json.loads(args.receipt.read_bytes())
    need(receipt['status']=='REVIEWED_PENDING_ARTIFACT_ADMISSION' and receipt['head']==args.head
         and receipt['run_id']==args.run_id and receipt['request_sha256']==sha(REQUEST)
         and receipt['Core_steps']==receipt['Sentinel_steps']==0 and not receipt['production_contacted']
         and not receipt['portfolio_performance_admitted'], 'EXACT_DIAGNOSTIC_RECEIPT')
    need(receipt['frozen_manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and receipt['post_exit_corpus_sha256']=='c0a62a6bbb8b67f77a1fca34f5e836a36f90bdf67dd83e196ef3d3369a7925f6',
         'AUTHENTICATED_POST_EXIT_SOURCE')
    sys.path.insert(0,str(args.legacy/'research/capital_risk'))
    from local_stage import dpapi
    from seal import decrypt,safe_name
    asset=receipt['encrypted_output']
    need(args.cipher.name==asset['name'] and args.cipher.stat().st_size==asset['bytes'], 'CIPHER_SCOPE')
    key=dpapi(args.key.read_bytes(),unprotect=True)
    plain=args.output.parent/'authenticated-output.tar.gz'
    decrypt(args.cipher,plain,key,asset['sha256']);key=None
    args.output.mkdir(mode=0o700,exist_ok=False)
    with tarfile.open(plain,'r:gz') as tar:
        first=tar.next()
        need(first.name=='manifest.json' and first.isfile() and first.size<2*1024**2, 'MANIFEST_FIRST')
        raw=tar.extractfile(first).read()
        need(hashlib.sha256(raw).hexdigest()==asset['manifest_sha256'], 'MANIFEST_HASH')
        manifest=json.loads(raw)
        need(manifest['schema']=='research.full-system-output/1' and manifest['stage']=='campaign-candidate'
             and manifest['arm']=='P00' and manifest['head']==args.head and manifest['run_id']==args.run_id
             and manifest['request_sha256']==sha(REQUEST) and manifest['protocol_sha256']==sha(ROOT/DOC), 'MANIFEST_SCOPE')
        members=manifest['members']
        need(len(members)<5000 and sum(v['bytes'] for v in members.values())<1024**3, 'INVENTORY_BOUND')
        seen=set()
        while item:=tar.next():
            safe_name(item.name)
            need(item.isfile() and item.name in members and item.name not in seen, 'MEMBER_TYPE')
            seen.add(item.name);spec=members[item.name]
            need(item.size==spec['bytes'], 'MEMBER_SIZE')
            target=args.output/item.name
            need(target.resolve().is_relative_to(args.output.resolve()), 'MEMBER_PATH')
            target.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(item) as src,target.open('xb') as dest:shutil.copyfileobj(src,dest)
            need(sha(target)==spec['sha256'], 'MEMBER_HASH')
        need(seen==set(members), 'COMPLETE_INVENTORY')
    need(sha(args.output/'request.json')==sha(REQUEST), 'PRESERVED_REQUEST')
    stopped(json.loads((args.output/'worker-inspect.json').read_bytes()),'worker',args.run_id)
    stopped(json.loads((args.output/'independent-review-stop/worker-inspect.json').read_bytes()),'review',args.run_id)
    reviewed=json.loads((args.output/'independent-review-stop/review/independent-review.json').read_bytes())
    need(reviewed['status']=='WIDER_STOP_DIAGNOSTIC_REVIEW_PASSED', 'INDEPENDENT_DIAGNOSTIC_REVIEW')
    save(args.output.parent/'verification.json',dict(status='WIDER_DIAGNOSTIC_AUTHENTICATED_AND_REVIEWED',
        diagnostic_qualified=True,portfolio_performance_admitted=False,head=args.head,run_id=args.run_id,
        request_sha256=sha(REQUEST),manifest_sha256=asset['manifest_sha256'],members_verified=len(members),
        Core_steps=0,Sentinel_steps=0,production_contacted=False))
    print('WIDER_DIAGNOSTIC_AUTHENTICATED_AND_REVIEWED')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('legacy','key','receipt','cipher','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--head',required=True);parser.add_argument('--run-id',required=True)
    admit(parser.parse_args())
