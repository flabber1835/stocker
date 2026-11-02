"""Host capacity publication and lock naming remain independent of USB lifetime."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import backup_continuity as continuity
import sentinel_backup_lock as locks
import sentinel_backup_capacity as capacity


def test_missing_backup_directory_keeps_only_explicit_continuity_lock_namespace(tmp_path):
    root=tmp_path/'external'/'backup'
    env={locks.LOCK_ROOT_ENV:str(root)}
    assert locks._lock_path(env) is None
    env[continuity.POLICY_ENV]=continuity.POLICY
    absent=locks._lock_path(env)
    assert absent is not None
    root.mkdir(parents=True)
    assert locks._lock_path(env)==absent


def test_lock_namespace_never_licenses_a_symlink(tmp_path):
    target=tmp_path/'real';target.mkdir()
    link=tmp_path/'alias';link.symlink_to(target,target_is_directory=True)
    assert locks._lock_path({locks.LOCK_ROOT_ENV:str(link),continuity.POLICY_ENV:continuity.POLICY}) is None


def test_transport_availability_checks_no_broker_or_media_writer(monkeypatch):
    import sentinel_backup_transport as transport
    config=dict(backup='/mnt/fixture/backup',transport='/run/sentinel-backup-transport')
    monkeypatch.setattr(continuity,'selected',lambda:True)
    monkeypatch.setattr(transport,'configuration',lambda p:config)
    monkeypatch.setenv('SENTINEL_BACKUP_DIR',config['backup'])
    monkeypatch.setenv('SENTINEL_BACKUP_TRANSPORT_DIR',config['transport'])
    monkeypatch.setenv('SENTINEL_BACKUP_BIND_PROPAGATION','rslave')
    calls=[]
    capacity.transport_root(lambda args:calls.append(args) or '')
    assert calls==[['systemctl','is-active','--quiet','sentinel-backup-transport-root.service']]
    monkeypatch.setenv('SENTINEL_BACKUP_DIR','/mnt/foreign')
    with pytest.raises(RuntimeError,match='differs'):capacity.transport_root(lambda a:calls.append(a))
    assert len(calls)==1


def test_windows_backing_free_space_is_not_replaced_by_virtual_free(monkeypatch):
    monkeypatch.setattr(continuity,'selected',lambda:True)
    monkeypatch.setenv(continuity.KEY_ENV,'private-host-capacity-fixture-'*3)
    monkeypatch.setattr(capacity,'runtime_image',lambda runner:'ghcr.io/fixture@sha256:'+'a'*64)
    class NativePath:
        def __init__(self,path):self.path=str(path)
        def is_absolute(self):return True
        def is_dir(self):return True
        def stat(self):return SimpleNamespace(st_dev=123)
        def read_text(self):return 'microsoft-standard-WSL2'
    monkeypatch.setattr(capacity,'Path',NativePath)
    physical=5*1024**3
    windows=[]
    def backing(runner,**kwargs):
        windows.append(kwargs)
        return dict(distro_path=r'C:\Users\fixture\Ubuntu',free={'C:':physical})
    monkeypatch.setattr(capacity,'windows_storage',backing)
    monkeypatch.setattr(capacity.shutil,'disk_usage',lambda p:SimpleNamespace(free=1024**5))
    info=dict(ID='fixture-native-engine',DockerRootDir='/var/lib/docker',OperatingSystem='Ubuntu')
    sql=[]
    def query(statement,runner):
        sql.append(statement)
        return json.dumps(dict(system_identifier='42',postmaster_start_us=123,observed_at=100))
    monkeypatch.setattr(capacity,'sql',query)
    captured=[]
    original=continuity.seal
    def seal(kind,proof):captured.append((kind,proof));return original(kind,proof)
    monkeypatch.setattr(continuity,'seal',seal)
    capacity.publish(lambda args:json.dumps(info))
    assert windows==[{'docker_desktop':False}]
    assert captured==[('CAPACITY',dict(system_identifier='42',postmaster_start_us=123,
        observed_at=100,engine_id='fixture-native-engine',physical_free_bytes=physical))]
    assert len(sql)==2 and sql[-1].startswith('COPY')
    # Reporting unsafe space is honest; the runtime must not turn this into
    # permission to continue. It separately checks the real database filesystem.
    with pytest.raises(continuity.BackupUnavailable):
        continuity.validate_capacity(captured[0][1],dict(system_identifier='42',postmaster_start_us=123,now=100))
