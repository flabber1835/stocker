"""Authenticate one exact campaign segment before hosted own-prefix continuation."""
import gzip,hashlib,json,shutil,subprocess,tarfile,zipfile
from pathlib import Path
from full_system_benchmark import need
from seal import decrypt,safe_name,sha256_file

def admit(spec,root,key,arm):
    folder=root/'transfer';folder.mkdir();archive=folder/'predecessor.zip'
    with archive.open('xb') as f:subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{spec['artifact_id']}/zip"],stdout=f,check=True,timeout=120)
    need(archive.stat().st_size==spec['zip_bytes'] and sha256_file(archive)==spec['zip_sha256'],'CAMPAIGN_PREDECESSOR_ZIP')
    with zipfile.ZipFile(archive) as z:
        name=f'campaign-baseline-{arm}.json';raw=z.read(name)
        need(hashlib.sha256(raw).hexdigest()==spec['receipt_sha256'],'CAMPAIGN_PREDECESSOR_RECEIPT')
        receipt=json.loads(raw);asset=receipt['encrypted_output']
        need(receipt['schema']=='research.system-campaign-baseline-receipt/1' and int(receipt['run_id'])==spec['run_id']
            and receipt['head']==spec['head'] and receipt['arm']==arm and receipt['status']=='FIRST_BASELINE_SEGMENT_REVIEWED'
            and not receipt['production_contacted'] and asset==spec['encrypted_output'],'CAMPAIGN_PREDECESSOR_SCOPE')
        need(set(z.namelist())=={'full-core-staging.json',name,asset['name']} and z.getinfo(asset['name']).file_size==asset['bytes'],'CAMPAIGN_PREDECESSOR_MEMBERS')
        cipher=folder/'old.crseal'
        with z.open(asset['name']) as src,cipher.open('xb') as out:shutil.copyfileobj(src,out)
    plain=folder/'authenticated.tar.gz';decrypt(cipher,plain,key,asset['sha256']);dest=root/'admitted';dest.mkdir()
    with tarfile.open(plain,'r:gz') as tar:
        first=tar.next();need(first.name=='manifest.json' and first.isfile() and first.size<2*1024**2,'CAMPAIGN_PREDECESSOR_MANIFEST')
        raw=tar.extractfile(first).read();need(hashlib.sha256(raw).hexdigest()==asset['manifest_sha256'],'CAMPAIGN_PREDECESSOR_MANIFEST_HASH')
        m=json.loads(raw);need(m['schema']=='research.full-system-output/1' and m['stage']=='campaign-baseline'
            and m['arm']==arm and int(m['run_id'])==spec['run_id'] and m['head']==spec['head']
            and m['request_sha256']==receipt['request_sha256'] and m['protocol_sha256']==receipt['protocol_sha256'],'CAMPAIGN_PREDECESSOR_BINDINGS')
        inventory=m['members'];need(len(inventory)<5000 and sum(v['bytes'] for v in inventory.values())<1024**3,'CAMPAIGN_PREDECESSOR_BOUND');seen=set()
        for item in tar:
            safe_name(item.name);need(item.isfile() and item.name in inventory and item.name not in seen,'CAMPAIGN_PREDECESSOR_MEMBER');seen.add(item.name)
            expected=inventory[item.name];need(item.size==expected['bytes'],'CAMPAIGN_PREDECESSOR_LENGTH')
            target=dest/item.name;target.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(item) as src,target.open('xb') as out:shutil.copyfileobj(src,out)
            need(sha256_file(target)==expected['sha256'],'CAMPAIGN_PREDECESSOR_HASH')
        need(seen==set(inventory),'CAMPAIGN_PREDECESSOR_INVENTORY')
    for name,expected in spec['inspections'].items():
        need(sha256_file(dest/name)==expected,'CAMPAIGN_PREDECESSOR_STOP_BYTES')
        v=json.loads((dest/name).read_bytes());role='review' if name.startswith('independent-') else 'worker'
        need(v['Name']==f"/capital-full-core-{arm.lower()}-{role}-{spec['run_id']}-1"
            and not v['State']['Running'] and not v['State']['OOMKilled'] and v['State']['ExitCode']==0,'CAMPAIGN_PREDECESSOR_ACTUAL_STOP')
    need(sha256_file(dest/'core-review.json')==spec['review_sha256'],'CAMPAIGN_PREDECESSOR_REVIEW')
    need(sha256_file(dest/'book/checkpoint.json.gz')==spec['checkpoint_file_sha256'],'CAMPAIGN_PREDECESSOR_CHECKPOINT_FILE')
    cp=json.loads(gzip.decompress((dest/'book/checkpoint.json.gz').read_bytes()))
    need(cp['sha256']==spec['outer_sha256'] and cp['run']['checkpoint_sha256']==spec['inner_sha256']
        and cp['run']['state_sha256']==spec['state_sha256'] and cp['run']['input_sha256']==spec['input_sha256']
        and cp['source_cursor']==spec['session'] and cp['journals']==spec['journals'],'CAMPAIGN_PREDECESSOR_CHECKPOINT_BINDINGS')
    for n,commit in spec['journals'].items():
        raw=(dest/f'book/{n}.jsonl').read_bytes();need(len(raw)==commit['bytes'] and hashlib.sha256(raw).hexdigest()==commit['prefix_sha256'],'CAMPAIGN_PREDECESSOR_PREFIX')
    return dest

def preserve(root,spec):
    proofs={}
    for n,commit in spec['journals'].items():
        with (root/f'{n}.jsonl').open('rb') as f:raw=f.read(commit['bytes'])
        need(len(raw)==commit['bytes'] and hashlib.sha256(raw).hexdigest()==commit['prefix_sha256'],'CAMPAIGN_OLD_PREFIX_PRESERVED')
        proofs[n]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    p=root/'predecessor-checkpoints'/(spec['outer_sha256']+'.json.gz')
    need(sha256_file(p)==spec['checkpoint_file_sha256'],'CAMPAIGN_OLD_GZIP_PRESERVED')
    return proofs
