#!/usr/bin/env python3
"""Native mount transport. USB lifetime never owns Engine/database lifetime.

Run by systemd in its host mount namespace. Configuration is root-owned public
storage identity, not an environment file. No broker or database mutations.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
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
        result[fields[4]] = dict(id=int(fields[0]),device=fields[2],root=fields[3],
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
            and all(current.get(k)==recorded.get(k) for k in ('id','device','fstype','source'))
            and ('root' not in recorded or current.get('root') == recorded['root']))


def _matches_bind(current, intent):
    fields = {'device', 'fstype', 'source', 'root'}
    return (isinstance(current, dict) and isinstance(intent, dict)
            and set(intent) == fields and all(intent[k] and current.get(k) == intent[k] for k in fields))


def _bind_intent(config, child, device, physical):
    require(physical is not None and physical['device'] == device
            and physical['fstype'] == 'ext4' and physical['root'].startswith('/'),
            'backup mount changed before transport bind')
    relative = (Path(config['backup']) / child).relative_to(config['mount'])
    return dict(device=device, fstype=physical['fstype'], source=physical['source'],
                root=str(Path(physical['root']) / relative))


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
    record = dict(config=config, phase='ATTACHING', mounts={}, pending={})
    owner = state_path(config)
    if owner.exists():
        _private_path(owner)
        record=json.loads(owner.read_text())
        require(record.get('config')==config, 'transport owner configuration changed')
    table = observe()
    pending = record.setdefault('pending', {})
    desired = {child: _bind_intent(config, child, device, table.get(config['mount']))
               for child in ('base', 'wal')}
    for child, intent in desired.items():
        current = table.get(config['transport'] + '/' + child)
        committed = record['mounts'].get(child)
        if committed is not None or record['phase'] == 'ATTACHED':
            require(_same_mount(current, committed), 'transport owner is stale; detach exact owner first')
        elif current is not None:
            require(_matches_bind(current, pending.get(child)) and pending[child] == intent,
                    'transport submount already has an owner')
            record['mounts'][child] = current
            pending.pop(child)
    if record['phase'] == 'ATTACHED':
        return
    record['phase'] = 'ATTACHING'
    for child, intent in desired.items():
        if child in record['mounts']:
            continue
        target = config['transport'] + '/' + child
        current = observe()
        require(target not in current and intent == _bind_intent(
            config, child, device, current.get(config['mount'])), 'transport bind source or target changed')
        pending[child] = intent
        _save(config,record)
        runner(['mount','--bind',config['backup']+'/'+child,target])
        observed = observe().get(target)
        require(_matches_bind(observed, intent), 'transport bind identity differs')
        record['mounts'][child] = observed
        pending.pop(child)
        _save(config,record)
    record['phase'] = 'ATTACHED'
    _save(config,record)


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
        committed = record.get('mounts', {}).get(child)
        owned = (_same_mount(current, committed) if committed is not None
                 else _matches_bind(current, record.get('pending', {}).get(child)))
        require(current is None or owned,
                'transport mount is not the recorded owner')
    for child in ('wal','base'):
        target=config['transport']+'/'+child
        if present[child] is not None:
            # Detach the dead backup subtree even if an archive attempt still
            # has a file open. Its PGDATA filesystem is entirely separate.
            runner(['umount','--lazy','--',target])
            require(target not in observe(), 'owned transport mount remains')
    _save(config,dict(config=config,phase='DETACHED',mounts={}))


@contextmanager
def _transport_lock(config):
    lock = state_path(config).with_suffix('.lock')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and not info.st_mode & 0o022, 'transport lock ownership differs')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


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
        'ExecStopPost='+invoke+' detach\nTimeoutStartSec=60\nTimeoutStopSec=30\n',
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
    if args.operation in {'attach', 'detach'}:
        with _transport_lock(config):
            (attach if args.operation == 'attach' else detach)(config)
    else:
        (primary_storage if args.operation == 'primary' else prepare)(config)


if __name__=='__main__':
    main()
