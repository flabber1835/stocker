"""Host transport, explicit selection and honest common byte-proof reporting."""
import inspect
import json
import os
import sys
from types import SimpleNamespace

import pytest

from test_recurring_maintenance import Boundary, IMAGE, SEGMENT, SYSTEM, coordinator
from test_shell_lifecycle import ShellLab
import sentinel_backup_integrity_report as report
import sentinel_backup_shared_integrity as bridge
from sentinel import backup_maintenance_integrity as worker


def proof(reads=6, full=True):
    return dict(schema='sentinel.maintenance-integrity/1', enabled=True,
        system_identifier=SYSTEM, base_backup='base-20260919T120000Z',
        recoverable_from_wal='00000001000000000000000B',
        recovery_marker_wal='00000001000000000000000C',
        recoverable_through_wal='00000001000000000000000D', wal_segments=3,
        timeline_history=None, wal_integrity='sha256-sidecar-v1',
        integrity_objects_hashed=reads, integrity_full_scrub=full,
        integrity_read_passes=2 if reads else 0, integrity_max_reuse_seconds=300,
        wal_segment_bytes=SEGMENT, integrity_completed_uptime=1000.0,
        integrity_observed_uptime=1200.0)


def status(value):
    return ('wal_chain_ready:true start_index=11 end=00000001000000000000000D '
        'segments=3 marker=00000001000000000000000C history=none\n'
        'shared_integrity_proof:'+json.dumps(value)+'\n'
        'backup_ready:true base=/media/base/base-20260919T120000Z '
        'age_hours=0 wal_age_hours=0 system_id='+SYSTEM)


@pytest.mark.parametrize('reads,full', [(6, True), (2, False), (0, False)])
def test_full_incremental_and_hit_preserve_actual_work_and_original_clock(reads, full):
    value = proof(reads, full)
    assert report.validate(value) == worker.MaintenanceProof.model_validate(value).model_dump()
    observation = dict(system_id=SYSTEM, segment_size=SEGMENT, timeline='00000001')
    actual = coordinator.runtime_chain_proof(status(value), Boundary().selected(), observation, '/media')
    assert actual == value
    assert actual['integrity_completed_uptime'] == 1000


@pytest.mark.parametrize('field,value', [
    ('enabled', False), ('schema', 'legacy'), ('base_backup', '../other'),
    ('system_identifier', 123), ('wal_segment_bytes', True), ('wal_segments', 2),
    ('integrity_objects_hashed', 1), ('integrity_objects_hashed', 8),
    ('integrity_read_passes', 1), ('integrity_full_scrub', 1),
    ('integrity_max_reuse_seconds', 301), ('integrity_observed_uptime', 1300.0),
    ('integrity_observed_uptime', 999.0), ('integrity_observed_uptime', float('nan')),
    ('integrity_completed_uptime', False), ('timeline_history', '00000001.history'),
    ('recovery_marker_wal', '00000002000000000000000C')])
def test_closed_report_refuses_bad_types_counts_scope_and_original_expiry(field, value):
    actual = proof(); actual[field] = value
    with pytest.raises((ValueError, TypeError)):
        report.validate(actual)
    with pytest.raises(ValueError):
        worker.MaintenanceProof.model_validate(actual)


def test_extra_and_duplicate_report_cannot_hide_in_legacy_parser():
    value = proof(); value['invented_permission'] = True
    with pytest.raises(ValueError): report.validate(value)
    observation = dict(system_id=SYSTEM, segment_size=SEGMENT, timeline='00000001')
    for raw in (status(value), status(proof())+'\nshared_integrity_proof:'+json.dumps(proof())):
        with pytest.raises(coordinator.Refused):
            coordinator.runtime_chain_proof(raw, Boundary().selected(), observation, '/media')


def test_typed_counts_must_describe_the_textual_interval():
    value = proof(); value['base_backup'] = 'base-20260919T120001Z'
    observation = dict(system_id=SYSTEM, segment_size=SEGMENT, timeline='00000001')
    with pytest.raises(coordinator.Refused):
        coordinator.runtime_chain_proof(status(value), Boundary().selected(), observation, '/media')


def values():
    return dict(PATH='/usr/bin:/bin', HOME='/home/private', LANG='C',
        SENTINEL_POSTGRES_PASSWORD='private-only-password',
        SENTINEL_PUBLICATION_RECEIPT_KEY='private-only-integrity-key-0123456789',
        SENTINEL_LOCAL_PAPER_MODE=bridge.MODE, SENTINEL_LOCAL_PAPER_ACCOUNT_ID='PAprivate',
        SENTINEL_LOCAL_PAPER_BACKUP_POLICY='REQUIRED_V1',
        SENTINEL_RUNTIME_BACKUP_AUTHORITY='REQUIRED_V1',
        ALPACA_API_KEY='must-not-leave-host', APCA_API_SECRET_KEY='must-not-leave-host',
        ALPACA_SECRET_KEY='must-not-leave-host', UNRELATED_SECRET='must-not-leave-host')


class UnusedSession:
    autocommit = True
    def execute(self, *_args, **_kwargs):
        raise AssertionError('refused maintenance inputs touched PostgreSQL')


def test_worker_refuses_live_before_any_database_or_archive_work(monkeypatch):
    for key, value in values().items():
        monkeypatch.setenv(key,value)
    monkeypatch.setenv('ALPACA_BASE_URL','https://api.alpaca.markets')
    with pytest.raises(worker.authority.BackupRuntimeRefused,match='backed PAPER'):
        worker.prove(UnusedSession(),base_backup=proof()['base_backup'],system_identifier=SYSTEM,
                     wal_segment_bytes=SEGMENT,observed_frontier=proof()['recoverable_through_wal'])


@pytest.mark.parametrize('size',[True,0,3*1024**2,2**31,'16777216',float('nan')])
def test_invalid_direct_worker_geometry_refuses_before_archive_work(monkeypatch,size):
    monkeypatch.setattr(worker.reuse,'selected',lambda:True)
    monkeypatch.setattr(worker.authority,'enabled',lambda:True)
    with pytest.raises(worker.authority.BackupRuntimeRefused):
        worker.prove(UnusedSession(),base_backup=proof()['base_backup'],system_identifier=SYSTEM,
                     wal_segment_bytes=size,observed_frontier=proof()['recoverable_through_wal'])


def test_cli_arms_independent_deadline_and_clears_it_on_connection_failure(monkeypatch,capsys):
    import psycopg
    calls=[]
    monkeypatch.setattr(worker.signal,'signal',lambda *_args:None)
    monkeypatch.setattr(worker.signal,'alarm',calls.append)
    monkeypatch.setattr(psycopg,'connect',lambda *_args,**_kwargs:(_ for _ in ()).throw(
        OSError('a driver message must not expose connection credentials')))
    monkeypatch.setenv('SENTINEL_DATABASE_URL','postgresql://private-secret@invalid')
    monkeypatch.setattr(sys,'argv',['worker','--base-backup',proof()['base_backup'],
        '--system-identifier',SYSTEM,'--wal-segment-bytes',str(SEGMENT),
        '--observed-frontier',proof()['recoverable_through_wal']])
    with pytest.raises(SystemExit) as exc: worker.main()
    assert exc.value.code==4 and calls==[540,0]
    errors=capsys.readouterr().err
    assert 'OSError' in errors and 'private-secret' not in errors and 'driver message' not in errors


@pytest.mark.parametrize('field,value', [('ALPACA_BASE_URL', 'https://api.alpaca.markets'),
    ('SENTINEL_LOCAL_PAPER_MODE', ''), ('SENTINEL_LOCAL_PAPER_BACKUP_POLICY', ''),
    ('SENTINEL_RUNTIME_BACKUP_AUTHORITY', 'OTHER'), ('SENTINEL_PUBLICATION_RECEIPT_KEY', 'short'),
    ('SENTINEL_POSTGRES_PASSWORD', 'unsafe@password'), ('SENTINEL_LOCAL_PAPER_ACCOUNT_ID', 'foreign')])
def test_host_transport_requires_explicit_backed_paper(field, value):
    actual = values(); actual[field] = value
    with pytest.raises(bridge.Refused): bridge.environment(actual)


def test_unique_broker_free_worker_uses_canonical_postgres_and_is_reaped(monkeypatch):
    calls = []; container = 'c'*64
    monkeypatch.setattr(bridge, 'runtime_image', lambda runner: IMAGE)
    def runner(args):
        return container if args[:3] == bridge.COMPOSE[:3] else container+' true'
    def bounded(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(proof()))
    args = SimpleNamespace(base_backup=proof()['base_backup'], system_identifier=SYSTEM,
        wal_segment_bytes=SEGMENT, observed_frontier=proof()['recoverable_through_wal'])
    assert bridge.observe(args, values=values(), runner=runner, bounded=bounded) == proof()
    command, options = calls[0]
    assert command[command.index('--network')+1] == 'container:'+container
    assert command[command.index('--entrypoint')+1:][:4] == ['python', IMAGE, '-m', 'sentinel.backup_maintenance_integrity']
    assert '--read-only' in command and '--cap-drop' in command
    assert not any(k in options['env'] for k in ('ALPACA_API_KEY','ALPACA_SECRET_KEY',
                                                'APCA_API_SECRET_KEY','UNRELATED_SECRET'))
    assert all('must-not-leave-host' not in str(v) for v in options['env'].values())
    assert calls[1][0] == ['docker', 'rm', '-f', command[command.index('--name')+1]]
    assert options['timeout']+calls[1][1]['timeout'] < 600


@pytest.mark.parametrize('mode', ['failed', 'bad_json', 'wrong_scope', 'expired'])
def test_worker_transport_failure_refuses_and_still_reaps_its_unique_worker(monkeypatch, mode):
    monkeypatch.setattr(bridge, 'runtime_image', lambda runner: IMAGE)
    container='d'*64; calls=[]
    def runner(args): return container if args[:3] == bridge.COMPOSE[:3] else container+' true'
    def bounded(command, **kwargs):
        calls.append(command)
        data=proof()
        if mode=='wrong_scope': data['system_identifier']='123'
        if mode=='expired': data['integrity_observed_uptime']=1300
        return SimpleNamespace(returncode=124 if mode=='failed' else 0,
            stdout='malformed' if mode=='bad_json' else json.dumps(data))
    args=SimpleNamespace(base_backup=proof()['base_backup'], system_identifier=SYSTEM,
        wal_segment_bytes=SEGMENT, observed_frontier=proof()['recoverable_through_wal'])
    with pytest.raises((bridge.Refused, ValueError)):
        bridge.observe(args, values=values(), runner=runner, bounded=bounded)
    assert len(calls)==2 and calls[-1][:3]==['docker','rm','-f']


def test_selected_maintenance_tick_publishes_actual_hit_without_legacy_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(coordinator, 'ROOT', tmp_path)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_REF', IMAGE)
    monkeypatch.setenv('SENTINEL_BACKUP_SHARED_INTEGRITY', 'REQUIRED_V1')
    boundary=Boundary()
    def runner(command, **kwargs):
        if command[:2]==['bash','scripts/sentinel-backup-status.sh']:
            assert command[2]=='--shared-integrity'
            boundary.calls.append(command)
            return status(proof(0,False))
        return boundary(command, **kwargs)
    assert coordinator.tick('/media',runner)['retention_ready']
    published=[p for p in boundary.published if p.get('wal_integrity')=='sha256-sidecar-v1'
               and 'integrity_objects_hashed' in p]
    assert published==[proof(0,False)]
    boundary.calls.clear()
    def missing(command, **kwargs):
        if command[:2]==['bash','scripts/sentinel-backup-status.sh']:
            return boundary(command,**kwargs)  # Legacy output is not a shared proof.
        return boundary(command,**kwargs)
    with pytest.raises(coordinator.Refused,match='no common proof'):
        coordinator.tick('/media',missing)
    assert not any('retain' in c for c in boundary.calls)


def test_explicit_shell_mode_preserves_fresh_guards_and_never_falls_back(tmp_path):
    lab=ShellLab(tmp_path)
    assert lab.run().returncode==0
    base=lab.base/'base-20260910T120000Z'
    os.utime(base/'backup_manifest',(1789041600,1789041600))
    helper=lab.scripts/'sentinel_backup_shared_integrity.py'
    helper.write_text("raise SystemExit(4)\n")
    result=lab.run('sentinel-backup-status.sh','--shared-integrity','--backup',str(base))
    assert result.returncode==4 and 'BASE_BACKUP_SHARED_INTEGRITY_REFUSED' in result.stderr
    assert 'backup_ready:true' not in result.stdout and 'wal_chain_ready:true' not in result.stdout
    # A broken fresh shell guard refuses before the new helper is invoked.
    helper.write_text("raise RuntimeError('shared helper must not run')\n")
    (base/'sentinel-recovery-marker').unlink()
    result=lab.run('sentinel-backup-status.sh','--shared-integrity','--backup',str(base))
    assert result.returncode==4 and 'BASE_BACKUP_SYSTEM_ID_MISMATCH' in result.stderr
    assert 'shared helper must not run' not in result.stderr


def test_removed_original_clock_guard_is_detected_by_executed_report_falsifier(monkeypatch):
    source=inspect.getsource(report.validate)
    guard='or not 0 <= stamps[1]-stamps[0] < 300'
    assert source.count(guard)==1
    namespace=dict(vars(report));exec(compile(source.replace(guard,'or False'),'<removed common proof expiry>','exec'),namespace)
    monkeypatch.setattr(report,'validate',namespace['validate'])
    with pytest.raises(pytest.fail.Exception):
        test_closed_report_refuses_bad_types_counts_scope_and_original_expiry('integrity_observed_uptime',1300.0)


def test_removed_paper_selection_guard_is_detected_before_any_sql(monkeypatch):
    source=inspect.getsource(worker.prove)
    guard='not reuse.selected() or '
    assert source.count(guard)==1
    namespace=dict(vars(worker));exec(compile(source.replace(guard,''),'<removed maintenance PAPER guard>','exec'),namespace)
    monkeypatch.setattr(worker,'prove',namespace['prove'])
    with pytest.raises(AssertionError,match='touched PostgreSQL'):
        test_worker_refuses_live_before_any_database_or_archive_work(monkeypatch)
