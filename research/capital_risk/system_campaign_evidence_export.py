"""Explicit two-GiB retained research evidence export; no financial execution."""
import hashlib,io,json,os,re,tarfile
from full_system_benchmark import need
from seal import EncryptWriter,sha256_file


def seal(root,target,key,request,arm,*,stage,protocol_sha256):
    need(stage=='campaign-factual-suffix' and arm=='P02'
         and re.fullmatch('[a-f0-9]{64}',protocol_sha256) is not None,
         'RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE')
    members={p.relative_to(root).as_posix():dict(bytes=p.stat().st_size,sha256=sha256_file(p))
             for p in sorted(root.rglob('*')) if p.is_file()}
    need(len(members)<5000 and sum(v['bytes'] for v in members.values())<=2*1024**3
         and not any(p.is_symlink() for p in root.rglob('*')),'RETAINED_EXPORT_EXPLICIT_TWO_GIB_BOUND')
    manifest=json.dumps(dict(schema='research.full-system-output/1',stage=stage,arm=arm,
        run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],request_sha256=sha256_file(request),
        protocol_sha256=protocol_sha256,compression='TAR_GZIP_V1',members=members),sort_keys=True).encode()+b'\n'
    temporary=target.with_suffix('.partial')
    with temporary.open('xb') as output:
        writer=EncryptWriter(output,key)
        with tarfile.open(fileobj=writer,mode='w|gz',compresslevel=1) as archive:
            first=tarfile.TarInfo('manifest.json');first.size=len(manifest);archive.addfile(first,io.BytesIO(manifest))
            for name,spec in members.items():
                info=tarfile.TarInfo(name);info.size=spec['bytes'];info.mode=0o600
                with (root/name).open('rb') as stream:archive.addfile(info,stream)
        writer.finish();output.flush();os.fsync(output.fileno())
    os.replace(temporary,target)
    return dict(name=target.name,bytes=target.stat().st_size,sha256=sha256_file(target),
                manifest_sha256=hashlib.sha256(manifest).hexdigest(),compression='TAR_GZIP_V1')
