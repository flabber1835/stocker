"""Execute the native WAL batch, with real filesystem and checksum commands."""
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'scripts/sentinel-backup-verify-chain.sh'


def run_batch(tmp_path,*,count=4,fault=None,bypass_hash=False):
    media=tmp_path/'wal';media.mkdir()
    files=[]
    for index in range(1,count+1):
        path=media/f'0000000100000000{index:08X}'
        raw=bytes([index%256])*128;path.write_bytes(raw)
        path.with_name(path.name+'.sha256').write_text('sha256='+hashlib.sha256(raw).hexdigest()+'\n')
        files.append(path)
    final=files[-1];sidecar=final.with_name(final.name+'.sha256')
    if fault=='bytes':final.write_bytes(b'x'*128)
    elif fault=='sidecar':sidecar.write_text(sidecar.read_text()+'junk')
    elif fault=='symlink':
        other=media/'other';final.rename(other);final.symlink_to(other)
    elif fault=='hardlink':os.link(final,media/'alias')
    commands=tmp_path/'calls'
    functions=''
    for name in ['stat','wc','sed','sha256sum','find']:
        actual=shutil.which(name);assert actual
        body='printf "%s\\n" '+shlex.quote(name)+' >> '+shlex.quote(str(commands))+'\n'
        if name=='sha256sum' and bypass_hash:body+='return 0\n'
        elif name=='sha256sum' and fault=='race':
            body+=shlex.quote(actual)+' "$@"\ncode=$?\nprintf x >> '+shlex.quote(str(sidecar))+'\nreturn "$code"\n'
        else:body+=shlex.quote(actual)+' "$@"\n'
        functions+=name+'(){\n'+body+'}\n'
    tail='work="$(mktemp -d)"'+SCRIPT.read_text().split('work="$(mktemp -d)"',1)[1]
    program=('set -euo pipefail\nrefuse(){ printf "REFUSED: %s\\n" "$*" >&2; exit 4; }\n'
        f'wal_root={shlex.quote(str(media))}\nwal_bytes=128\nfirst_index=1\nlast_index={count}\n'
        f'start_timeline=1\nsegments_per_log=33554432\nlast_wal={final.name}\nmarker_wal={final.name}\nhistory=""\n'+functions+tail)
    result=subprocess.run(['bash','-c',program],capture_output=True,text=True,timeout=15)
    return result,commands.read_text().splitlines() if commands.exists() else []


@pytest.mark.parametrize('count',[1,16])
def test_archive_process_count_is_constant_and_every_object_verified(tmp_path,count):
    result,calls=run_batch(tmp_path,count=count)
    assert result.returncode==0,result.stderr
    assert f'segments={count}' in result.stdout
    assert calls.count('sha256sum')==1 and calls.count('find')==2
    assert not {'stat','wc','sed'}&set(calls)


@pytest.mark.parametrize('fault',['bytes','sidecar','symlink','hardlink','race'])
def test_archive_batch_refuses_corruption_alias_or_mid_read_change(tmp_path,fault):
    result,_=run_batch(tmp_path,fault=fault)
    assert result.returncode==4 and 'REFUSED' in result.stderr


def test_removing_byte_verification_is_detected(tmp_path):
    result,_=run_batch(tmp_path,fault='bytes',bypass_hash=True)
    # This deliberately broken implementation is accepted only to prove that
    # the real corruption test depends on reading and checking the bytes.
    with pytest.raises(AssertionError):
        assert result.returncode==4
