"""GitHub-hosted ONLY: authenticate an encrypted branch, never a local replay."""
import gzip,hashlib,json,os,re,shutil,subprocess,tarfile,zipfile
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from full_system_benchmark import need
from probe import check_context
from seal import MAGIC,safe_name,sha256_file


def hosted_destination(root):
    # This guard runs before any filesystem creation, credential or network use.
    check_context(os.environ)
    root=Path(root).resolve();temp=Path(os.environ['RUNNER_TEMP']).resolve()
    need(os.name=='posix' and str(temp)=='/home/runner/work/_temp'
         and root.parent==temp and root.name.startswith('campaign-factual-transfer-')
         and shutil.disk_usage(temp).free>=12*1024**3,'HOSTED_FACTUAL_DESTINATION_CAPACITY')
    return root


def authenticate(z,asset,key):
    h=hashlib.sha256();size=0;tail=b''
    with z.open(asset['name']) as source:
        header=source.read(20);need(header.startswith(MAGIC) and len(header)==20,'FACTUAL_CIPHER_HEADER')
        h.update(header);size=20
        dec=Cipher(algorithms.AES256(key),modes.GCM(header[-12:])).decryptor();dec.authenticate_additional_data(header)
        while chunk:=source.read(1024**2):
            h.update(chunk);size+=len(chunk);raw=tail+chunk
            if len(raw)>16:dec.update(raw[:-16]);tail=raw[-16:]
            else:tail=raw
        dec.finalize_with_tag(tail)
    need(size==asset['bytes'] and h.hexdigest()==asset['sha256'],'FACTUAL_CIPHER_LENGTH_HASH_GCM')
    return header,tail


class AuthenticatedStream:
    def __init__(self,source,asset,key,header,tag):
        need(source.read(20)==header,'FACTUAL_CIPHER_SAME_HEADER')
        self.source,self.left,self.tag,self.done=source,asset['bytes']-36,tag,False
        self.dec=Cipher(algorithms.AES256(key),modes.GCM(header[-12:],tag)).decryptor()
        self.dec.authenticate_additional_data(header)
    def read(self,n=-1):
        if n==0 or self.done:return b''
        if self.left:
            raw=self.source.read(min(self.left,n if n>0 else 1024**2));need(bool(raw),'FACTUAL_CIPHER_NOT_TRUNCATED')
            self.left-=len(raw);return self.dec.update(raw)
        need(self.source.read(16)==self.tag and self.source.read(1)==b'','FACTUAL_CIPHER_FOOTER')
        self.dec.finalize();self.done=True;return b''


def admit(spec,root,key):
    root=hosted_destination(root);root.mkdir(mode=0o700)
    need(spec['zip_bytes']<256*1024**2,'FACTUAL_ENCRYPTED_DOWNLOAD_BOUND')
    archive=root/'predecessor.zip'
    with archive.open('xb') as out:
        subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{spec['artifact_id']}/zip"],stdout=out,check=True,timeout=180)
    need(archive.stat().st_size==spec['zip_bytes'] and sha256_file(archive)==spec['zip_sha256'],'FACTUAL_OLD_ZIP')
    with zipfile.ZipFile(archive) as z:
        raw=z.read(spec['receipt_name']);need(hashlib.sha256(raw).hexdigest()==spec['receipt_sha256'],'FACTUAL_OLD_RECEIPT')
        r=json.loads(raw);asset=r['encrypted_output']
        need(r['schema']==spec['receipt_schema'] and int(r['run_id'])==spec['run_id'] and r['head']==spec['head']
             and r['arm']==spec['arm'] and asset==spec['encrypted_output'] and not r['production_contacted']
             and r['protocol_sha256']==spec['protocol_sha256'] and r['request_sha256']==spec['request_sha256'],'FACTUAL_OLD_SCOPE')
        need(set(z.namelist())=={spec['receipt_name'],'full-core-staging.json',asset['name']}
             and z.getinfo(asset['name']).file_size==asset['bytes'],'FACTUAL_OLD_ZIP_MEMBERS')
        header,tag=authenticate(z,asset,key)  # Authenticate before parsing plaintext.
        dest=root/'admitted';dest.mkdir(mode=0o700)
        with z.open(asset['name']) as source:
            plain=AuthenticatedStream(source,asset,key,header,tag)
            with tarfile.open(fileobj=plain,mode='r|gz') as tar:
                first=tar.next();need(first.name=='manifest.json' and first.isfile() and first.size<2*1024**2,'FACTUAL_OLD_MANIFEST')
                raw=tar.extractfile(first).read();need(hashlib.sha256(raw).hexdigest()==asset['manifest_sha256'],'FACTUAL_OLD_MANIFEST_HASH')
                m=json.loads(raw)
                need(m['schema']=='research.full-system-output/1' and m['stage']==spec['stage'] and m['arm']==spec['arm']
                     and int(m['run_id'])==spec['run_id'] and m['head']==spec['head']
                     and m['request_sha256']==spec['request_sha256'] and m['protocol_sha256']==spec['protocol_sha256'],'FACTUAL_OLD_MANIFEST_BINDINGS')
                inventory=m['members'];need(len(inventory)<5000 and sum(v['bytes'] for v in inventory.values())<1024**3,'FACTUAL_PLAINTEXT_BOUND')
                seen=set()
                while item:=tar.next():
                    safe_name(item.name);need(item.isfile() and item.name in inventory and item.name not in seen,'FACTUAL_OLD_MEMBER')
                    seen.add(item.name);expected=inventory[item.name];need(item.size==expected['bytes'],'FACTUAL_OLD_MEMBER_LENGTH')
                    target=dest/item.name;need(target.resolve().is_relative_to(dest),'FACTUAL_HOSTED_EXTRACTION_BOUNDARY')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with tar.extractfile(item) as src,target.open('xb') as out:shutil.copyfileobj(src,out,length=1024**2)
                    os.chmod(target,0o600);need(sha256_file(target)==expected['sha256'],'FACTUAL_OLD_MEMBER_HASH')
                need(seen==set(inventory),'FACTUAL_OLD_COMPLETE_INVENTORY')
            while plain.read(1024**2):pass
    for n,e in spec['inspections'].items():
        need(sha256_file(dest/n)==(e['sha256'] or inventory[n]['sha256']),'FACTUAL_OLD_STOP_BYTES');v=json.loads((dest/n).read_bytes());h=v['HostConfig']
        need(v['Name']==e['name'] and re.fullmatch('[a-f0-9]{64}',v['Id']) is not None and (e['id'] is None or v['Id']==e['id']) and not v['State']['Running'] and not v['State']['OOMKilled']
             and v['State']['ExitCode']==e['exit_code'],'FACTUAL_OLD_ACTUAL_STOP')
        need(v['Image']=='sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d'
             and h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3 and h['NanoCpus']==2000000000
             and h['ReadonlyRootfs'] and h['PidsLimit']==64 and h['CapDrop']==['ALL']
             and any(x.startswith('no-new-privileges') for x in h['SecurityOpt']),'FACTUAL_OLD_FENCES')
        mounts={x['Destination']:x for x in v['Mounts'] if x['Type']=='bind'}
        need(mounts['/out']['RW'] and all(not x['RW'] for k,x in mounts.items() if k!='/out'),'FACTUAL_OLD_INPUT_MOUNTS')
    need(sha256_file(dest/'source-bindings.json')==spec['source_binding_sha256'],'FACTUAL_OLD_SOURCE_REVIEW')
    if spec.get('unadvanced_qualification_failure'):
        prove_unadvanced(spec,inventory,dest)
    else:
        need(sha256_file(dest/'core-review.json')==spec['review_sha256'],'FACTUAL_OLD_REVIEW_BYTES')
    p=dest/spec['selected_checkpoint'];need(sha256_file(p)==spec['selected_file']['sha256'],'FACTUAL_SELECTED_GZIP')
    cp=json.loads(gzip.decompress(p.read_bytes()))
    need(cp['sha256']==spec['outer_sha256'] and cp['run']['checkpoint_sha256']==spec['inner_sha256']
         and cp['run']['state_sha256']==spec['state_sha256'] and cp['run']['input_sha256']==spec['input_sha256']
         and cp['base']==spec['base'] and cp['source_cursor']==spec['selected_session']
         and cp['journals']==spec['journals'] and cp['repairs']==spec['repairs'],'FACTUAL_SELECTED_BINDINGS')
    for n,c in cp['journals'].items():
        with (dest/f'book/{n}.jsonl').open('rb') as f:raw=f.read(c['bytes'])
        need(len(raw)==c['bytes'] and hashlib.sha256(raw).hexdigest()==c['prefix_sha256'],'FACTUAL_SELECTED_PREFIX')
    return dest


def prove_unadvanced(spec,inventory,root):
    """Refuse any unexpected progress instead of adopting an earlier checkpoint."""
    need('book/status.json' not in inventory and 'factual-input-qualification.json' not in inventory,
         'FACTUAL_QUALIFIER_NEVER_REACHED_FINANCIAL_ENTRY')
    prefix='lineage/old-branch/'
    nested={n[len(prefix):]:v for n,v in inventory.items() if n.startswith(prefix)}
    digest=hashlib.sha256(json.dumps(nested,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    need(digest==spec['immutable_old_branch_inventory_sha256'],'FACTUAL_IMMUTABLE_WHOLE_OLD_BRANCH')
    for n in ('formation','daily','monthly','watch'):
        need(inventory[f'book/{n}.jsonl']==nested[f'book/{n}.jsonl'],'FACTUAL_NO_NEW_FINANCIAL_OR_TAIL_BYTES')
    need(inventory['book/checkpoint.json.gz']==spec['selected_file'],'FACTUAL_NO_CHECKPOINT_ADVANCEMENT')
    log=(root/'economic-worker.log').read_text()
    need('in qualify_inputs' in log and 'ValueError: suppressed original spinoff differs' in log
         and '"status": "VERIFYING_INPUTS"' not in log,'FACTUAL_ACTUAL_PRE_FINANCIAL_REFUSAL')
    proof=json.loads((root/'old-branch-canonical-review.json').read_bytes())
    need(proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified'] and not proof['complete'],
         'FACTUAL_UNADVANCED_CANONICAL_PREFIX_REVIEW')
