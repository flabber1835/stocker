"""Atomic shared configuration with exact native-reader continuity."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

from .model import DeliveryRefused, require

MAX_BYTES = 1024 * 1024
MAX_PROCESSES = 16384


@dataclass(frozen=True)
class Reader:
    pid: int
    start_ticks: int
    uid: int
    gid: int
    groups: tuple[int, ...]


def _read(path, limit):
    with path.open('rb') as stream:
        value=stream.read(limit+1)
    require(len(value)<=limit,'ENVIRONMENT_READER_FACT_EXCEEDS_BOUND')
    return value


def _reader(pid, deployment):
    process=Path('/proc')/str(pid)
    with (process/'cmdline').open('rb') as stream:raw_command=stream.read(8193)
    if len(raw_command)>8192:
        return None  # An unrelated large argv is not the exact three-argument owner.
    command=raw_command.rstrip(b'\0').split(b'\0')
    if (len(command)!=3 or command[2]!=b'--loop'
            or re.fullmatch(rb'python(?:3(?:\.[0-9]+)?)?',command[0].rsplit(b'/',1)[-1]) is None):
        return None
    cwd=Path(os.readlink(process/'cwd'))
    script=Path(os.fsdecode(command[1]))
    script=script if script.is_absolute() else cwd/script
    if cwd!=deployment or script.resolve()!=deployment/'scripts/sentinel_backup_maintenance.py':
        return None
    first=_read(process/'stat',8192).rpartition(b')')[2].split()
    fields={}
    for line in _read(process/'status',16384).decode('ascii').splitlines():
        key,_,value=line.partition(':')
        if key in {'Uid','Gid','Groups'}:fields[key]=tuple(int(v) for v in value.split())
    require(len(fields.get('Uid',()))==4 and len(fields.get('Gid',()))==4
        and 'Groups' in fields and len(fields['Groups'])<=256,'ENVIRONMENT_READER_CREDENTIALS_MALFORMED')
    second=_read(process/'stat',8192).rpartition(b')')[2].split()
    require(len(first)>19 and len(second)>19 and first[19]==second[19],
            'ENVIRONMENT_READER_PROCESS_CHANGED')
    return Reader(pid,int(first[19]),fields['Uid'][3],fields['Gid'][3],tuple(sorted(fields['Groups'])))


def readers(deployment, *, required):
    result=[]
    processes=[p for p in Path('/proc').iterdir() if p.name.isdecimal()]
    require(len(processes)<=MAX_PROCESSES,'ENVIRONMENT_PROCESS_INVENTORY_EXCEEDS_BOUND')
    for process in processes:
        try:value=_reader(int(process.name),deployment)
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
        if value is not None:result.append(value)
    require(len(result)<=1 and (bool(result) or not required),'ENVIRONMENT_NATIVE_READER_UNAVAILABLE')
    return tuple(result)


def _same_readers(deployment, selected):
    for reader in selected:
        try:current=_reader(reader.pid,deployment)
        except (FileNotFoundError,ProcessLookupError,PermissionError):current=None
        require(current==reader,'ENVIRONMENT_NATIVE_READER_CHANGED')


READ_AS_READER = '''import hashlib,json,os,stat,sys
value=json.load(sys.stdin)
if os.geteuid()==0:
    os.setgroups(value['groups']);os.setgid(value['gid']);os.setuid(value['uid'])
else:
    assert os.geteuid()==value['uid'] and os.getegid()==value['gid'] and sorted(os.getgroups())==value['groups']
for item in value['files']:
    fd=os.open(item['path'],os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    try:
        metadata=os.fstat(fd)
        assert stat.S_ISREG(metadata.st_mode) and metadata.st_nlink==1 and metadata.st_size<=1048576
        raw=b''
        while len(raw)<=1048576:
            block=os.read(fd,min(65536,1048577-len(raw)))
            if not block:break
            raw+=block
        assert len(raw)<=1048576 and hashlib.sha256(raw).hexdigest()==item['sha256']
    finally:os.close(fd)
print('ENVIRONMENT_READER_OK')
'''


def _probe(host, selected, files):
    _same_readers(host.deployment,selected)
    for reader in selected:
        value=asdict(reader)
        value.update(groups=list(reader.groups),files=[dict(path=str(p),sha256=d) for p,d in files])
        try:
            result=host.run([sys.executable,'-I','-B','-c',READ_AS_READER],
                data=json.dumps(value,sort_keys=True).encode(),timeout=5)
        except subprocess.TimeoutExpired:
            raise DeliveryRefused('ENVIRONMENT_NATIVE_READER_TIMEOUT') from None
        require(result.stdout.strip()==b'ENVIRONMENT_READER_OK','ENVIRONMENT_NATIVE_READER_REFUSED')
    _same_readers(host.deployment,selected)


def _identity(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_gid,info.st_nlink,
            info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _metadata(fd):
    info=os.fstat(fd)
    require(stat.S_ISREG(info.st_mode) and info.st_nlink==1
        and 0<=info.st_size<=MAX_BYTES,'ENVIRONMENT_FILE_UNSAFE')
    require(not os.listxattr(fd),'ENVIRONMENT_EXTENDED_METADATA_UNSUPPORTED')
    return info


def _raw(fd):
    os.lseek(fd,0,os.SEEK_SET)
    with os.fdopen(os.dup(fd),'rb') as stream:value=stream.read(MAX_BYTES+1)
    require(len(value)<=MAX_BYTES,'ENVIRONMENT_FILE_EXCEEDS_BOUND')
    return value


def install(host, previous, raw=None):
    """None validates an already committed selection without rewriting it."""
    directory=host.deployment
    require(directory==directory.resolve() and not any(p.is_symlink() for p in (directory,*directory.parents)),
            'ENVIRONMENT_DIRECTORY_ALIASED')
    directory_fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    old_fd=new_fd=None;temporary=None
    try:
        directory_identity=os.fstat(directory_fd)
        def same_directory():
            current=directory.lstat()
            require(stat.S_ISDIR(current.st_mode)
                and (current.st_dev,current.st_ino)==(directory_identity.st_dev,directory_identity.st_ino),
                'ENVIRONMENT_DIRECTORY_CHANGED')
        old_fd=os.open('.env',os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=directory_fd)
        original=_metadata(old_fd)
        require(host.load_values()==previous,'ENVIRONMENT_CHANGED_BEFORE_INSTALL')
        original_raw=_raw(old_fd)
        def same_original():
            same_directory()
            require(_identity(os.stat('.env',dir_fd=directory_fd,follow_symlinks=False))==_identity(original)
                and _identity(_metadata(old_fd))==_identity(original)
                and _raw(old_fd)==original_raw,'ENVIRONMENT_ORIGINAL_CHANGED')
        same_original()
        selected=readers(directory,required=previous.get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY')=='REQUIRED_V1')
        original_digest=hashlib.sha256(original_raw).hexdigest()
        if raw is None:
            _probe(host,selected,[(directory/'.env',original_digest)])
            same_original();os.fsync(directory_fd)
            return
        require(isinstance(raw,bytes) and len(raw)<=MAX_BYTES,'ENVIRONMENT_CANDIDATE_EXCEEDS_BOUND')
        new_fd,temporary=tempfile.mkstemp(prefix='.env.local-delivery-',dir=directory)
        os.fchown(new_fd,original.st_uid,original.st_gid)
        os.fchmod(new_fd,stat.S_IMODE(original.st_mode))
        require(not os.listxattr(new_fd),'ENVIRONMENT_EXTENDED_METADATA_UNSUPPORTED')
        with os.fdopen(os.dup(new_fd),'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        installed=_metadata(new_fd)
        require((installed.st_uid,installed.st_gid,stat.S_IMODE(installed.st_mode))==
            (original.st_uid,original.st_gid,stat.S_IMODE(original.st_mode)),
            'ENVIRONMENT_METADATA_NOT_PRESERVED')
        digest=hashlib.sha256(raw).hexdigest()
        _probe(host,selected,[(directory/'.env',original_digest),(Path(temporary),digest)])
        same_original()
        require(_identity(os.stat(temporary,follow_symlinks=False))==_identity(installed)
            and _raw(new_fd)==raw,'ENVIRONMENT_TEMPORARY_CHANGED')
        os.replace(Path(temporary).name,'.env',src_dir_fd=directory_fd,dst_dir_fd=directory_fd)
        temporary=None
        os.fsync(directory_fd)
        same_directory()
        current=_metadata(new_fd)
        require((current.st_uid,current.st_gid,stat.S_IMODE(current.st_mode))==
            (original.st_uid,original.st_gid,stat.S_IMODE(original.st_mode))
            and _identity(os.stat('.env',dir_fd=directory_fd,follow_symlinks=False))==_identity(current)
            and _raw(new_fd)==raw,'ENVIRONMENT_INSTALLED_FILE_CHANGED')
        _probe(host,selected,[(directory/'.env',digest)])
        current=_metadata(new_fd)
        require(_identity(os.stat('.env',dir_fd=directory_fd,follow_symlinks=False))==_identity(current)
            and (current.st_uid,current.st_gid,stat.S_IMODE(current.st_mode))==
                (original.st_uid,original.st_gid,stat.S_IMODE(original.st_mode))
            and _raw(new_fd)==raw,'ENVIRONMENT_INSTALLED_FILE_CHANGED')
    finally:
        if temporary is not None:
            try:
                found=os.stat(Path(temporary).name,dir_fd=directory_fd,follow_symlinks=False)
                owned=os.fstat(new_fd)
                if (found.st_dev,found.st_ino)==(owned.st_dev,owned.st_ino):
                    os.unlink(Path(temporary).name,dir_fd=directory_fd)
            except FileNotFoundError:pass
        for fd in (new_fd,old_fd,directory_fd):
            if fd is not None:os.close(fd)
