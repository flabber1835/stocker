"""Authenticate two provider preimages without storing a broad local archive."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import ssl
import tarfile
import time
from urllib import request,parse,error
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from local_stage import dpapi
from seal import safe_name,MAGIC
from alpaca_fit_relay import REPO,RELEASE


def need(value,reason):
    if not value:raise ValueError('REFUSED_PROVIDER_PREIMAGE_'+reason)


def asset(part):
    name=safe_name(part['name']);need('/' not in name and 0<part['bytes']<=16*1024**2,'ASSET_NAME_OR_SIZE')
    url=f'https://github.com/{REPO}/releases/download/{RELEASE}/'+parse.quote(name,safe='')
    for attempt in range(3):
        try:
            buffer=bytearray()
            with request.urlopen(url,timeout=45) as response:
                while chunk:=response.read(1024**2):
                    buffer.extend(chunk);need(len(buffer)<=part['bytes'],'PART_LENGTH')
            need(len(buffer)==part['bytes'] and hashlib.sha256(buffer).hexdigest()==part['sha256'],'PART_HASH')
            return bytes(buffer)
        except (ssl.SSLError,error.URLError,TimeoutError):
            if attempt==2:raise ValueError('REFUSED_BOUNDED_CIPHERTEXT_NETWORK_RETRIES') from None
            time.sleep(2*(attempt+1))


def plaintext(spec,key):
    """Bounded chunks; tag/hash verification must complete on every pass."""
    global_hash=hashlib.sha256();total=0;header=b'';tail=b'';cipher=None
    for part in spec['parts']:
        payload=asset(part)
        for offset in range(0,len(payload),1024**2):
            chunk=payload[offset:offset+1024**2];total+=len(chunk);global_hash.update(chunk)
            if cipher is None:
                need(len(chunk)>=20,'TRUNCATED_HEADER');header=chunk[:20]
                # The first provider chunk always includes the 20-byte header.
                need(len(header)==20 and header.startswith(MAGIC),'HEADER')
                cipher=Cipher(algorithms.AES256(key),modes.GCM(header[-12:])).decryptor();cipher.authenticate_additional_data(header)
                chunk=chunk[20:]
            buffer=tail+chunk
            if len(buffer)>16:
                yield cipher.update(buffer[:-16]);tail=buffer[-16:]
            else:tail=buffer
    need(total==spec['ciphertext_bytes'] and global_hash.hexdigest()==spec['ciphertext_sha256'],'FULL_CIPHER_HASH')
    need(cipher is not None and len(tail)==16,'TAG_SHAPE');yield cipher.finalize_with_tag(tail)


class Reader:
    def __init__(self,iterator):self.iterator=iter(iterator);self.buffer=b'';self.done=False
    def read(self,n):
        while len(self.buffer)<n and not self.done:
            try:self.buffer+=next(self.iterator)
            except StopIteration:self.done=True
        value,self.buffer=self.buffer[:n],self.buffer[n:];return value
    def drain(self):
        self.buffer=b''
        for _ in self.iterator:pass
        self.done=True


def member(spec,key,name):
    # First pass authenticates the ENTIRE ciphertext without parsing plaintext.
    for _ in plaintext(spec,key):pass
    stream=Reader(plaintext(spec,key));found={};selected=None;manifest=None;manifest_raw=None
    with tarfile.open(fileobj=stream,mode='r|') as tar:
        for item in tar:
            safe_name(item.name);need(item.isfile() and item.size<=32*1024**2 and manifest is None and item.name not in found,'MEMBER')
            payload=tar.extractfile(item).read();need(len(payload)==item.size,'TRUNCATED_MEMBER')
            if item.name=='manifest.json':manifest_raw=payload;manifest=json.loads(payload)
            else:
                found[item.name]={'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
                if item.name==name:selected=payload
    stream.drain()
    need(manifest is not None and hashlib.sha256(manifest_raw).hexdigest()==spec['manifest_sha256']
        and manifest['members']==found and selected is not None,'INVENTORY')
    return selected


def compare(old,new):
    # JSON object order is not economic content. Arrays and every value must
    # still agree; this function cannot admit a changed price or page token.
    def equal(a,b):
        if type(a) is not type(b):return False
        if type(a) is dict:return set(a)==set(b) and all(equal(a[k],b[k]) for k in a)
        if type(a) is list:return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
        return a==b
    return equal(json.loads(old),json.loads(new))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('old-transport','new-transport','key','old-receipt','new-receipt','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();old=json.loads(Path(a.old_transport).read_bytes());new=json.loads(Path(a.new_transport).read_bytes())
    before=json.loads(Path(a.old_receipt).read_bytes().splitlines()[-1]);after=json.loads(Path(a.new_receipt).read_bytes().splitlines()[0])
    key=dpapi(Path(a.key).read_bytes(),unprotect=True)
    old_raw=gzip.decompress(member(old,key,'capture/'+before['file']))
    new_raw=gzip.decompress(member(new,key,'capture/'+after['file']));key=None
    need(hashlib.sha256(old_raw).hexdigest()==before['raw_sha256'] and hashlib.sha256(new_raw).hexdigest()==after['raw_sha256'],'EXACT_RAW_PREIMAGES')
    result={'schema':'research.alpaca-provider-preimage-comparison/1','old_manifest_sha256':old['manifest_sha256'],
        'new_manifest_sha256':new['manifest_sha256'],'old_raw_sha256':before['raw_sha256'],'new_raw_sha256':after['raw_sha256'],
        'wire_bytes_equal':old_raw==new_raw,'parsed_json_values_and_array_order_equal':compare(old_raw,new_raw),
        'same_query':before['params']==after['params'],'both_complete_ciphertexts_authenticated_before_parsing':True,
        'both_full_inventories_verified':True,'financial_replay_started':False,'production_contacted':False}
    Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
