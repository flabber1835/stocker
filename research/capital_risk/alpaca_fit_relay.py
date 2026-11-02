"""Private bounded ciphertext relay. Provider credentials never enter this process."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import tarfile

from local_stage import dpapi
from seal import EncryptWriter, safe_name

REPO='flabber1835/stocker'
RELEASE='research-capital-risk-inputs-20261027'
PART=16*1024**2


def encoded(v):return (json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def require(v,reason):
    if not v:raise ValueError('REFUSED_'+reason)


def remote():
    result=subprocess.run(['gh','api',f'repos/{REPO}/releases/tags/{RELEASE}'],capture_output=True,text=True,timeout=30,check=True)
    value=json.loads(result.stdout)
    require(value['tag_name']==RELEASE and value['prerelease'],'RELEASE_IDENTITY')
    return {x['name']:x for x in value['assets']}


class Parts:
    def __init__(self,root,prefix,*,maximum=600*1024**2):
        self.root=root.resolve();self.prefix=prefix;self.buffer=bytearray();self.parts=[]
        self.maximum=maximum
        self.digest=hashlib.sha256();self.total=0
        require(self.root.is_dir() and not self.root.is_symlink(),'SPOOL_ROOT')

    def write(self,value):
        self.digest.update(value);self.total+=len(value)
        require(self.total<=self.maximum,'CIPHER_TOTAL_BOUND')
        remaining=memoryview(value)
        while remaining:
            take=min(PART-len(self.buffer),len(remaining));self.buffer.extend(remaining[:take]);remaining=remaining[take:]
            if len(self.buffer)==PART:self.flush_part()
        return len(value)

    def flush_part(self):
        if not self.buffer:return
        name=f'{self.prefix}.part-{len(self.parts):04d}.crseal';path=self.root/name
        require(path.parent.resolve()==self.root and not path.exists(),'EXACT_NEW_SPOOL_PATH')
        payload=bytes(self.buffer);part={'name':name,'bytes':len(payload),'sha256':sha(payload)}
        with path.open('xb') as f:f.write(payload)
        require(name not in remote(),'REMOTE_COLLISION')
        result=subprocess.run(['gh','release','upload',RELEASE,str(path),'--repo',REPO],capture_output=True,text=True,timeout=240)
        observed=remote().get(name)
        require(observed is not None and observed['state']=='uploaded' and observed['size']==part['bytes']
                and observed['digest']=='sha256:'+part['sha256'],'EXACT_REMOTE_CIPHERTEXT')
        self.parts.append(part)
        (self.root/'uploaded-parts.json').write_bytes(encoded({'parts':self.parts,'retained_ciphertext_bytes':self.total}))
        # Only this new, verified, non-recursive transfer spool file is removed.
        require(path.resolve().parent==self.root and path.name==name and path.is_file(),'VERIFIED_SPOOL_REMOVE_PATH')
        path.unlink();self.buffer.clear()
        print(json.dumps({'ciphertext_part_verified':len(self.parts),'bytes':part['bytes']}),flush=True)


def read_exact(stream,n):
    values=[];remaining=n
    while remaining:
        part=stream.read(remaining)
        if not part:raise ValueError('REFUSED_TRUNCATED_PROVIDER_STREAM')
        values.append(part);remaining-=len(part)
    return b''.join(values)


def relay(args):
    root=Path(args.output);root.mkdir(parents=True,exist_ok=False)
    protocol=Path(args.protocol).read_bytes();roster=Path(args.roster).read_bytes()
    selected=json.loads(protocol);long=selected.get('schema')=='research.bounded-alpaca-policy-fit/2'
    require(not long or selected.get('study_id')=='alpaca-owned55-long-fit-001' and selected.get('source_capture_scope')=='LONG_HISTORY','LONG_CAPTURE_SCOPE')
    maximum=2*1024**3+32*1024**2 if long else 600*1024**2
    member_max=10000 if long else 2500
    prefix=('alpaca-long-fit-001-' if long else 'alpaca-fit-001-')+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+sha(protocol)[:12]
    sink=Parts(root,prefix,maximum=maximum);key=dpapi(Path(args.key).read_bytes(),unprotect=True)
    writer=EncryptWriter(sink,key);members={};receipts=[];capture=None;status={'status':'FAILED','reason':'NO_END_FRAME'}
    require(len(key)==32,'KEY_LENGTH');key=None
    require(remote() is not None,'EXISTING_RESEARCH_DESTINATION')
    child=subprocess.Popen(args.collector,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        require(read_exact(child.stdout,8)==b'ALPCAP01','PROVIDER_STREAM_MAGIC')
        with tarfile.open(fileobj=writer,mode='w|') as archive:
            def add(name,payload):
                safe_name(name);require(name not in members and len(members)<member_max,'STREAM_INVENTORY')
                item=tarfile.TarInfo(name);item.size=len(payload);item.mode=0o600;archive.addfile(item,io.BytesIO(payload))
                members[name]={'bytes':len(payload),'sha256':sha(payload)}
            add('protocol.json',protocol);add('roster.json',roster)
            while True:
                ml,pl=struct.unpack('>II',read_exact(child.stdout,8))
                require(ml<=16*1024**2 and pl<=32*1024**2,'STREAM_FRAME_BOUNDS')
                meta=json.loads(read_exact(child.stdout,ml));payload=read_exact(child.stdout,pl)
                if meta['kind']=='END':status={k:v for k,v in meta.items() if k!='kind'};break
                require(meta['kind'] in ('PROVIDER','FILE'),'FRAME_KIND')
                name=meta['name'];safe_name(name)
                if meta['kind']=='PROVIDER':
                    receipt=meta['receipt'];require(name==receipt['file'] and sha(payload)==receipt['sha256'] and len(payload)==receipt['bytes'],'PROVIDER_FRAME_HASH')
                    receipts.append(receipt)
                if name=='capture.json':capture=json.loads(payload)
                add('capture/'+name,payload)
            add('capture/request-receipts.jsonl',b''.join(encoded(r) for r in receipts))
            manifest={'schema':'research.alpaca-fit-stream-inputs/1','status':status['status'],
                'protocol_sha256':sha(protocol),'roster_sha256':sha(roster),'manifest_position':'LAST',
                'members':dict(sorted(members.items())),'market_capture_status':None if capture is None else capture['status'],
                'production_contacted':False,'provider_credentials_exported':False}
            payload=encoded(manifest);item=tarfile.TarInfo('manifest.json');item.size=len(payload);item.mode=0o600
            archive.addfile(item,io.BytesIO(payload));manifest_sha=sha(payload)
        writer.finish();sink.flush_part()
        code=child.wait(timeout=15)
        receipt={'schema':'research.alpaca-fit-stream-transport/1','status':status['status'],'capture_status':status,
            'release':RELEASE,'repository':REPO,'parts':sink.parts,'ciphertext_bytes':sink.total,'ciphertext_sha256':sink.digest.hexdigest(),
            'manifest_sha256':manifest_sha,'protocol_sha256':sha(protocol),'roster_sha256':sha(roster),
            'collector_exit_code':code,'provider_credentials_exported':False,'public_plaintext_financial_payload':False,
            'complete_financial_inputs_admitted':False,'completed_at':datetime.now(timezone.utc).isoformat()}
        (root/'transport.json').write_bytes(encoded(receipt))
        (root/'manifest.json').write_bytes(payload)
        require(status['status']=='COMPLETE' and capture is not None and capture['status']=='COMPLETE' and code==0,'COMPLETE_MARKET_CAPTURE')
        print(json.dumps({'status':'ENCRYPTED_MARKET_CAPTURE_UPLOADED','parts':len(sink.parts),'gzip_payload_members':len(receipts)}))
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('output','protocol','roster','key'):p.add_argument('--'+n,required=True)
    p.add_argument('collector',nargs=argparse.REMAINDER);a=p.parse_args()
    if a.collector and a.collector[0]=='--':a.collector=a.collector[1:]
    require(bool(a.collector),'COLLECTOR_COMMAND')
    relay(a)
