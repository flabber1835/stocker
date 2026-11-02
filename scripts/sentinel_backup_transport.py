#!/usr/bin/env python3
"""Native mount transport. USB lifetime never owns Engine/database lifetime.

Run by systemd in its host mount namespace. Configuration is root-owned public
storage identity, not an environment file. No broker or database mutations.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


def require(value, message):
    if not value:
        raise RuntimeError(message)


def run(args):
    return subprocess.check_output(args, text=True, timeout=15,
        env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8'}).strip()


def configuration(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
            and not info.st_mode & 0o022 and info.st_size <= 8192,
            'transport configuration ownership differs')
    value = json.loads(path.read_text())
    require(set(value) == {'uuid','mount','backup','transport'}, 'transport configuration shape')
    require(re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',value['uuid']),
            'transport UUID invalid')
    for key in ('mount','backup','transport'):
        raw = value[key]
        require(isinstance(raw,str) and re.fullmatch(r'/[A-Za-z0-9_./-]+', raw)
                and str(Path(raw)) == raw and '..' not in Path(raw).parts,
                'transport path invalid')
    require(Path(value['mount']) in Path(value['backup']).parents
            and re.fullmatch(r'/run/sentinel-backup-transport(?:-[A-Za-z0-9]+)?',value['transport']),
            'transport path boundary differs')
    return value


def mounts():
    result = {}
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        before, after = line.split(' - ',1)
        fields, detail = before.split(), after.split()
        result[fields[4]] = dict(id=int(fields[0]),device=fields[2],
            options=fields[5].split(','), optional=fields[6:],
            fstype=detail[0], source=detail[1], super_options=detail[2].split(','))
    return result


def _private_path(path):
    require(path.resolve() == path and not path.is_symlink(), 'transport path is aliased')
    info = path.stat()
    require(info.st_uid == 0 and not info.st_mode & 0o022, 'transport path ownership differs')


def _same_mount(current, recorded):
    # A removed ext4 device legitimately acquires the `shutdown` option. Its
    # immutable mount ID/device identity, not mutable flags, proves ownership.
    return (isinstance(current,dict) and isinstance(recorded,dict)
            and all(current.get(k)==recorded.get(k) for k in ('id','device','fstype','source')))


def primary_storage(config):
    daemon=Path('/var/lib/docker')
    _private_path(daemon)
    require(daemon.is_dir() and daemon.stat().st_dev==Path('/').stat().st_dev,
            'Docker primary storage is not on the internal root filesystem')
    require(not (Path(config['mount']) in daemon.parents), 'primary storage overlaps backup target')


def prepare(config, runner=run, observe=mounts):
    root = Path(config['transport'])
    if not root.exists():
        root.mkdir(mode=0o755)
    _private_path(root)
    current = observe().get(str(root))
    if current is not None:
        require(current['fstype']=='tmpfs' and 'ro' in current['options']
                and any(v.startswith('shared:') for v in current['optional']),
                'existing transport parent differs')
        for child in ('base','wal'):
            require((root/child).is_dir() and not (root/child).is_symlink(),
                    'transport parent child differs')
        return
    require(not list(root.iterdir()), 'transport mountpoint must start empty')
    runner(['mount','-t','tmpfs','-o','size=1m,mode=0755,nosuid,nodev,noexec',
            'sentinel-backup-transport',str(root)])
    for child in ('base','wal'):
        (root/child).mkdir(mode=0o555)
    runner(['mount','-o','remount,ro',str(root)])
    runner(['mount','--make-shared',str(root)])


def state_path(config):
    return Path(config['transport']+'.owner.json')


def _save(config, record):
    path = state_path(config)
    if path.exists() or path.is_symlink():
        _private_path(path)
        require(path.is_file() and path.stat().st_nlink == 1, 'transport owner file differs')
    fd, name = tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as output:
            os.fchmod(output.fileno(),0o600)
            json.dump(record,output,sort_keys=True)
            output.flush(); os.fsync(output.fileno())
        os.replace(name,path)
        fd = os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(name): os.unlink(name)


def verified_media(config, observe=mounts):
    mount = config['mount']
    current = observe().get(mount)
    expected = Path('/dev/disk/by-uuid')/config['uuid']
    require(expected.exists() and stat.S_ISBLK(expected.stat().st_mode), 'backup UUID absent')
    device = '%d:%d' % (os.major(expected.stat().st_rdev),os.minor(expected.stat().st_rdev))
    require(current is not None and current['device']==device and current['fstype']=='ext4'
            and 'rw' in current['options'] and 'shutdown' not in current['super_options'],
            'backup mount UUID/filesystem/state differs')
    # Actual USB ancestry, not a filesystem UUID copied onto an internal device.
    ancestry = Path('/sys/dev/block/'+device).resolve(strict=True)
    require(any((p/'subsystem').is_symlink() and (p/'subsystem').resolve()==Path('/sys/bus/usb')
                for p in (ancestry,*ancestry.parents)), 'backup target is not the expected USB storage')
    for child in ('base','wal'):
        source = Path(config['backup'])/child
        require(source.is_dir() and source.resolve()==source and source.stat().st_dev==expected.stat().st_rdev,
                'backup child is outside verified media')
        marker = source/'.sentinel-independent-durable-target-v1'
        require(marker.is_file() and not marker.is_symlink() and marker.stat().st_nlink==1
                and marker.read_text().strip()=='sentinel-independent-durable-target-v1',
                'existing independent backup marker is required; never initialize fallback')
    return device


def attach(config, runner=run, observe=mounts):
    device=verified_media(config,observe)
    prepare(config,runner,observe)
    # Repeated service start only verifies the exact previously recorded mounts.
    owner = state_path(config)
    if owner.exists():
        _private_path(owner)
        record=json.loads(owner.read_text())
        require(record.get('config')==config, 'transport owner configuration changed')
        if record.get('phase')=='ATTACHED':
            require(all(_same_mount(observe().get(config['transport']+'/'+child),record['mounts'][child])
                        for child in ('base','wal')), 'transport owner is stale; detach exact owner first')
            return
    require(all(config['transport']+'/'+child not in observe() for child in ('base','wal')),
            'transport submount already has an owner')
    record=dict(config=config,phase='ATTACHING',mounts={})
    _save(config,record)
    try:
        for child in ('base','wal'):
            target=config['transport']+'/'+child
            runner(['mount','--bind',config['backup']+'/'+child,target])
            observed=observe().get(target)
            require(observed is not None and observed['device']==device,'transport bind identity differs')
            record['mounts'][child]=observed
            _save(config,record)
        record['phase']='ATTACHED'
        _save(config,record)
    except BaseException:
        # Only recorded successful binds are owned. The next inspect/detach may
        # finish their cleanup; never unmount an unexpected target on failure.
        record['phase']='FAILED_INSPECT'
        _save(config,record)
        raise


def detach(config, runner=run, observe=mounts):
    owner = state_path(config)
    present = {child:observe().get(config['transport']+'/'+child) for child in ('base','wal')}
    if not owner.exists():
        require(not any(present.values()), 'unrecorded transport mounts; refuse unmount')
        return
    _private_path(owner)
    record=json.loads(owner.read_text())
    require(record.get('config')==config, 'transport owner configuration changed')
    for child, current in present.items():
        require(current is None or _same_mount(current,record.get('mounts',{}).get(child)),
                'transport mount is not the recorded owner')
    for child in ('wal','base'):
        target=config['transport']+'/'+child
        if present[child] is not None:
            # Detach the dead backup subtree even if an archive attempt still
            # has a file open. Its PGDATA filesystem is entirely separate.
            runner(['umount','--lazy','--',target])
            require(target not in observe(), 'owned transport mount remains')
    _save(config,dict(config=config,phase='DETACHED',mounts={}))


def unit_files(config, executable, config_path, runner=run):
    # Paths are machine-owned and restricted to shell/systemd-safe characters.
    for path in (executable,config_path):
        require(re.fullmatch(r'/[A-Za-z0-9_./-]+',path), 'unit path is invalid')
    mount_unit=runner(['systemd-escape','--path','--suffix=mount',config['mount']])
    invoke='/usr/bin/python3 '+executable+' --config '+config_path
    return {
      'sentinel-backup-transport-root.service':
        '[Unit]\nDescription=Sentinel stable backup transport parent\nBefore=docker.service\n'
        '[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart='+invoke+' prepare\n'
        '[Install]\nWantedBy=multi-user.target\n',
      'sentinel-backup-transport.service':
        '[Unit]\nDescription=Sentinel optional external backup submounts\n'
        'Requires=sentinel-backup-transport-root.service '+mount_unit+'\n'
        'BindsTo='+mount_unit+'\nAfter=sentinel-backup-transport-root.service '+mount_unit+'\n'
        '[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart='+invoke+' attach\n'
        'ExecStop='+invoke+' detach\nTimeoutStartSec=60\nTimeoutStopSec=30\n',
      'docker-storage.conf':
        '[Unit]\nWants=sentinel-backup-transport-root.service\n'
        'After=sentinel-backup-transport-root.service\n'
        '[Service]\nExecStartPre='+invoke+' primary\n',
      'udev.rules': 'ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_UUID}=="'+config['uuid']+
        '", ENV{ID_FS_TYPE}=="ext4", TAG+="systemd", ENV{SYSTEMD_WANTS}+="sentinel-backup-transport.service"\n'
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('operation',choices=('prepare','attach','detach','primary'))
    args=parser.parse_args()
    require(os.geteuid()==0,'native root required')
    config=configuration(args.config)
    (primary_storage if args.operation=='primary' else globals()[args.operation])(config)


if __name__=='__main__':
    main()
