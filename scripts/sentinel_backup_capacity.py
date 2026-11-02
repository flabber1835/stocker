#!/usr/bin/env python3
"""One bounded capacity observation from the existing maintenance owner."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sentinel import backup_continuity as continuity
from sentinel_storage_capacity import windows_storage, windows_drive
from sentinel_backup_maintenance import run, sql, runtime_image


def lock_root():
    """Only loop ownership, never backup-media or archive-write authority."""
    root = Path(os.environ.get('SENTINEL_BACKUP_DIR', ''))
    repo = Path(__file__).resolve().parents[1]
    if (not root.is_absolute() or root.is_symlink()
            or (root.exists() and not root.is_dir())
            or root.resolve(strict=False) != root or root in (Path('/'), Path.home(), repo)
            or repo in root.parents or str(root).startswith('/var/lib/docker/')):
        raise RuntimeError('continuity maintenance lock root is invalid')
    return str(root)


def transport_root(runner=run):
    if not continuity.selected():
        raise RuntimeError('transport requires explicit backed PAPER continuity')
    from sentinel_backup_transport import configuration
    config=configuration(Path('/etc/sentinel-backup-transport.json'))
    if (config['backup']!=os.environ.get('SENTINEL_BACKUP_DIR')
            or config['transport']!=os.environ.get('SENTINEL_BACKUP_TRANSPORT_DIR')
            or os.environ.get('SENTINEL_BACKUP_BIND_PROPAGATION')!='rslave'):
        raise RuntimeError('configured native transport differs')
    runner(['systemctl','is-active','--quiet','sentinel-backup-transport-root.service'])


def publish(runner=run):
    if not continuity.selected():
        return
    runtime_image(runner)  # Existing exact clean checkout/signed image check.
    info = json.loads(runner(['docker', '--context', 'default', 'info', '--format', '{{json .}}']))
    daemon = Path(info['DockerRootDir'])
    if (not daemon.is_absolute() or not daemon.is_dir()
            or 'docker desktop' in str(info.get('OperatingSystem', '')).lower()
            or daemon.stat().st_dev != Path('/').stat().st_dev
            or not isinstance(info.get('ID'), str) or not info['ID']):
        raise RuntimeError('continuity requires internal native Engine storage')
    # On WSL Linux free space is virtual. Read the actual Windows backing disk.
    kernel = Path('/proc/sys/kernel/osrelease').read_text().lower()
    if 'microsoft' in kernel:
        storage = windows_storage(runner, docker_desktop=False)
        free = storage['free'].get(windows_drive(storage['distro_path']))
    else:
        free = shutil.disk_usage(daemon).free
    if type(free) is not int or free < 0:
        raise RuntimeError('physical primary free space is unavailable')
    observation = json.loads(sql("SELECT json_build_object("
        "'system_identifier',system_identifier::text,"
        "'postmaster_start_us',floor(extract(epoch FROM pg_postmaster_start_time())*1000000)::bigint,"
        "'observed_at',floor(extract(epoch FROM clock_timestamp()))::bigint)"
        " FROM pg_control_system()", runner))
    if (not re.fullmatch(r'[1-9][0-9]{0,19}', str(observation.get('system_identifier', '')))
            or type(observation.get('postmaster_start_us')) is not int
            or type(observation.get('observed_at')) is not int):
        raise RuntimeError('invalid capacity primary identity')
    record = dict(observation, engine_id=info['ID'], physical_free_bytes=free)
    sql(continuity.publication_sql(continuity.CAPACITY, continuity.seal('CAPACITY', record)), runner)


def checkpoint(chain, runner=run):
    """Retain this tick's actual verified chain, without a duplicate chain scan."""
    if not continuity.selected():
        return
    image=runtime_image(runner)
    head=runner(['git','rev-parse','HEAD'])
    value=json.loads(sql("SELECT json_build_object("
        "'system_identifier',system_identifier::text,"
        "'postmaster_start_us',floor(extract(epoch FROM pg_postmaster_start_time())*1000000)::bigint,"
        "'now',floor(extract(epoch FROM clock_timestamp()))::bigint,"
        "'last_archive_at',floor(extract(epoch FROM last_archived_time))::bigint,"
        "'last_archived_wal',last_archived_wal,"
        "'deployment_id',deployment_id,'broker',broker,'broker_account_id',broker_account_id,"
        "'takeover_epoch',takeover_epoch,'ownership_state',ownership_state)"
        " FROM pg_control_system() CROSS JOIN pg_stat_archiver CROSS JOIN sentinel_account_binding"
        " WHERE id=1",runner))
    if (value.get('ownership_state')!='SENTINEL_OWNED' or value.get('broker')!='alpaca'
            or value.get('broker_account_id')!=os.environ.get('SENTINEL_LOCAL_PAPER_ACCOUNT_ID')
            or type(value.get('takeover_epoch')) is not int or value['takeover_epoch']<1
            or chain.get('enabled') is not True or chain.get('backup_state')=='DEGRADED'
            or chain.get('system_identifier')!=value.get('system_identifier')):
        raise RuntimeError('continuity checkpoint does not match bound verified chain')
    if chain.get('recoverable_through_wal')!=value.get('last_archived_wal'):
        return False  # Archive advanced during scan; never retime its prefix.
    if (type(value.get('last_archive_at')) is not int or type(value.get('now')) is not int
            or not 0<=value['now']-value['last_archive_at']<continuity.MAX_AGE):
        raise RuntimeError('continuity archive time is invalid')
    raw=sql("SELECT coalesce(pg_read_file('"+continuity.CAPACITY+"',0,16385,true),'')",runner)
    if not raw:
        return False
    try:
        capacity=continuity.validate_capacity(continuity.authenticate(raw.encode(),'CAPACITY'),value)
    except continuity.BackupUnavailable:
        return False
    context={k:value[k] for k in ('system_identifier','postmaster_start_us','deployment_id',
                                  'broker','broker_account_id','takeover_epoch')}
    context.update(git_commit=head,runtime_image_digest=image.split('@')[-1])
    proof=dict(context=context,engine_id=capacity['engine_id'],
               last_archive_at=value['last_archive_at'],chain=chain)
    sql(continuity.publication_sql(continuity.CHECKPOINT,continuity.seal('CHECKPOINT',proof)),runner)
    return True


def main():
    if sys.argv[1:] == ['lock-root'] and continuity.selected():
        print(lock_root())
    elif sys.argv[1:] == ['transport-root']:
        transport_root()
    elif not sys.argv[1:]:
        publish()
    else:
        raise RuntimeError('unsupported capacity command')


if __name__ == '__main__':
    main()
