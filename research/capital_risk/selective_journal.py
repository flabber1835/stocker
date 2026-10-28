"""Deterministic gzip journals with uncompressed prefix commitments."""
from pathlib import Path
import gzip,hashlib,json,os

def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(encode(v)).hexdigest()

class Journal:
    def __init__(self,path):
        self.path=Path(path);self.raw=self.path.open('xb');self.stream=gzip.GzipFile(filename='',fileobj=self.raw,mode='wb',mtime=0,compresslevel=1)
        self.bytes=0;self.records=0;self.sha=hashlib.sha256()
    def write(self,value):
        raw=encode(value)+b'\n';self.stream.write(raw);self.sha.update(raw);self.bytes+=len(raw);self.records+=1
    def commitment(self):return dict(bytes=self.bytes,records=self.records,prefix_sha256=self.sha.hexdigest())
    def flush(self):self.stream.flush();self.raw.flush();os.fsync(self.raw.fileno())
    def close(self):self.stream.close();self.raw.close()

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name(path.name+'.partial')
    with temporary.open('xb') as raw:
        with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0,compresslevel=1) as stream:stream.write(encode(value)+b'\n')
        raw.flush();os.fsync(raw.fileno())
    os.replace(temporary,path)

def load(path):
    with gzip.open(path,'rt') as stream:return json.load(stream)
