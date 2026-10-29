"""Authenticate the exact stopped predecessor for a hosted suffix."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile
from seal import decrypt,safe_name,sha256_file
from alpaca_fit_inputs import need


def extract(plain,destination,spec,previous,protocol,*,stage='canonical-baseline'):
    need(not destination.exists(),'PREDECESSOR_EXTRACTION_COLLISION')
    with tarfile.open(plain,'r:') as tar:
        members=tar.getmembers();first=members[0]
        need(first.name=='manifest.json' and first.isfile() and first.size<2*1024**2,'PREDECESSOR_MANIFEST')
        body=tar.extractfile(first).read();need(hashlib.sha256(body).hexdigest()==spec['manifest_sha256'],'PREDECESSOR_MANIFEST_HASH')
        manifest=json.loads(body)
        need(manifest['schema']=='research.alpaca-fit-output/1' and manifest['kind']=='FULL_STOPPED_EVIDENCE'
            and manifest['stage']==stage and manifest['run_id']==str(previous['run_id'])
            and manifest['head']==previous['head'] and manifest['protocol_sha256']==protocol,'PREDECESSOR_MANIFEST_IDENTITY')
        inventory=manifest['members'];seen=set();need(len(members)==len(inventory)+1<=5000,'PREDECESSOR_MEMBER_COUNT')
        for item in members[1:]:
            safe_name(item.name);need(item.isfile() and item.name in inventory and item.name not in seen,'PREDECESSOR_MEMBER')
            seen.add(item.name);expected=inventory[item.name]
            need(item.size==expected['bytes'] and item.size<=(512 if stage=='funded-fit' else 128)*1024**2
                and hashlib.file_digest(tar.extractfile(item),'sha256').hexdigest()==expected['sha256'],'PREDECESSOR_MEMBER_HASH')
        destination.mkdir(mode=0o700)
        for item in members[1:]:
            path=destination/item.name;need(destination.resolve() in path.resolve().parents,'PREDECESSOR_MEMBER_PATH')
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as output:
                stream=tar.extractfile(item)
                while part:=stream.read(1024**2):output.write(part)
    return manifest


def stage_previous(req,root,key):
    spec=req['continuation'];previous=spec['artifact'];folder=root/'market/inputs/_continuation';folder.mkdir(mode=0o700)
    archive=folder/'previous.zip'
    with archive.open('xb') as f:
        subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{previous['id']}/zip"],stdout=f,check=True,timeout=90)
    need(archive.stat().st_size==previous['bytes'] and sha256_file(archive)==previous['sha256'],'PREDECESSOR_ZIP_HASH')
    with zipfile.ZipFile(archive) as source:
        expected={'alpaca-fit-baseline.json','alpaca-fit-baseline-full.tar.crseal','alpaca-fit-baseline-summary.tar.crseal'}
        need(set(source.namelist())==expected and len(source.infolist())==3,'PREDECESSOR_ZIP_SHAPE')
        for item in source.infolist():
            need(item.file_size<512*1024**2,'PREDECESSOR_ZIP_MEMBER_SIZE')
            with (folder/item.filename).open('xb') as f:f.write(source.read(item))
    receipt=json.loads((folder/'alpaca-fit-baseline.json').read_bytes())
    need(receipt['run_id']==str(previous['run_id']) and receipt['head']==previous['head']
        and receipt['protocol_sha256']==req['protocol_sha256'],'PREDECESSOR_RECEIPT')
    full=receipt['encrypted_outputs']['full'];need(full==previous['full'],'EXACT_PREDECESSOR_CIPHER_SPEC')
    cipher=folder/full['name'];need(cipher.stat().st_size==full['bytes'] and sha256_file(cipher)==full['sha256'],'PREDECESSOR_CIPHER')
    plain=folder/'previous.tar';decrypt(cipher,plain,key,full['sha256'])
    extract(plain,folder/'previous',full,previous,req['protocol_sha256'])
    old=folder/'previous';item=json.loads((old/'worker-inspect.json').read_bytes())
    need(item['Name']=='/capital-alpaca-fit-baseline-'+str(previous['run_id'])+'-1'
        and item['Image']=='sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d'
        and item['State']['Running'] is False and item['State']['OOMKilled'] is False,'PREDECESSOR_ACTUAL_STOP')
    reviewed=json.loads((old/'stopped-independent-review/review/independent-review.json').read_bytes())
    need(reviewed['status']=='PARTIAL_PREFIX_REVIEWED' and reviewed['last_committed_session']==spec['checkpoint']['session']
        and reviewed['uncommitted_tail_bytes']==0,'PREDECESSOR_INDEPENDENT_REVIEW')
    cp=old/'book'/spec['checkpoint']['file']
    need(cp.stat().st_size==spec['checkpoint']['bytes'] and sha256_file(cp)==spec['checkpoint']['sha256'],'PREDECESSOR_CHECKPOINT')
    reference=req['input_reference'];source=folder/'source';source.mkdir()
    reply=subprocess.run(['gh','api','repos/flabber1835/stocker/contents/'+reference['path']+'?ref='+reference['commit']],
        capture_output=True,check=True,timeout=30)
    body=base64.b64decode(json.loads(reply.stdout)['content'])
    need(len(body)==reference['bytes'] and hashlib.sha256(body).hexdigest()==reference['sha256'],'EXACT_INPUT_REFERENCE_SOURCE')
    (source/'alpaca_fit_inputs.py').write_bytes(body)
    admission={'schema':'research.alpaca-predecessor-staging/1','previous_run_id':previous['run_id'],
        'previous_head':previous['head'],'checkpoint':spec['checkpoint'],'archive_cipher_inventory_verified':True,
        'actual_stopped':True,'independent_partial_prefix_review_passed':True,'financial_origin_recreated':False}
    (folder/'admission.json').write_text(json.dumps(admission,indent=2)+'\n')
    return admission
