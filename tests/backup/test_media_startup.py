"""Late media is retried through the normal bounded maintenance entry point."""
import inspect
import contextlib
import io
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

import sentinel_backup_integrity_report as report
import sentinel_backup_maintenance as coordinator
import sentinel_backup_renewal as renewal
from sentinel import backup_maintenance_integrity as worker
from test_renewal_deadlines import Clock, FreshBoundary, IMAGE


def absent_failure(**changes):
    fields = dict(origin='HOST',code='PHYSICAL_UNAVAILABLE',stage='HOST_MEDIA',cause_type='OSError',
        proof_lock='NOT_ACQUIRED',worker_container='NOT_STARTED',
        exception_chain=[dict(type='OSError',sqlstate=None,errno=2)])
    fields.update(changes)
    return report.failure(**fields)


def test_absent_media_uses_real_bounded_shell_entry_without_touching_docker(tmp_path):
    root = tmp_path/'late-usb'/'backup'
    binary = tmp_path/'bin'
    binary.mkdir()
    log = tmp_path/'docker-called'
    docker = binary/'docker'
    docker.write_text(f'#!/bin/sh\ntouch "{log}"\nexit 95\n')
    docker.chmod(0o755)
    env = dict(PATH=str(binary)+os.pathsep+os.environ['PATH'], HOME=str(tmp_path/'home'), LANG='C.UTF-8',
        SENTINEL_HOST_PYTHON=sys.executable, SENTINEL_BACKUP_DIR=str(root),
        SENTINEL_POSTGRES_PASSWORD='isolated-backup-startup-password',
        SENTINEL_PUBLICATION_RECEIPT_KEY='isolated-backup-startup-receipt-key-0123456789')
    result = subprocess.run(['bash','scripts/sentinel-backup-maintenance.sh'],
        cwd=coordinator.ROOT,env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode == 75, (result.stdout,result.stderr)
    record = renewal.parse(result.stdout)
    assert record['outcome'] == 'RETRYABLE'
    assert record['phase'] == 'PREFLIGHT' and record['code'] == 'PHYSICAL_UNAVAILABLE'
    assert record['failure']['stage'] == 'HOST_MEDIA'
    assert record['failure']['exception_chain'][0]['errno'] == 2
    assert not root.exists() and not log.exists()


@pytest.mark.parametrize('publication_age', [None, 500, 900])
def test_media_recovery_backoff_does_not_borrow_or_renew_authority(publication_age):
    clock = Clock()
    clock.now = 1000
    original = clock.publication(clock.now-publication_age) if publication_age is not None else None
    schedule = renewal.Schedule(original,clock=clock.monotonic,wallclock=clock.wall)
    deadline = schedule.deadline
    for expected in [1,2,5,10,20,30,30,30]:
        schedule.consume(renewal.result(outcome='RETRYABLE',phase='PREFLIGHT',code='PHYSICAL_UNAVAILABLE',
            cause_type='Refused',failure=absent_failure(),publication_at=original))
        assert schedule.delay() == expected
        assert schedule.deadline == deadline and schedule.publication() == original
        clock.now += expected
    current = clock.publication()
    schedule.consume(renewal.result(outcome='SUCCESS',phase='COMPLETE',code='OK',publication_at=current))
    assert schedule.publication() == current and schedule.deadline == clock.now+600
    assert schedule.delay() == 300


def test_one_supervisor_recovers_when_original_media_arrives(tmp_path, monkeypatch, capsys):
    from tests.sentinel.test_backup_contract import _write_fake_backup_docker

    media = tmp_path/'media'
    detached = tmp_path/'detached'
    for name in ('base','wal'):
        parent = detached/name
        parent.mkdir(parents=True)
        (parent/'.sentinel-independent-durable-target-v1').write_text(
            'sentinel-independent-durable-target-v1\n')
    binary = tmp_path/'bin'
    binary.mkdir()
    _write_fake_backup_docker(binary/'docker')
    values = dict(PATH=str(binary)+os.pathsep+os.environ['PATH'], HOME=str(tmp_path/'home'), LANG='C.UTF-8',
        SENTINEL_HOST_PYTHON=sys.executable, SENTINEL_BACKUP_DIR=str(media),
        SENTINEL_BASE_BACKUP_LOCK_ROOT=str(media), SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED='1',
        SENTINEL_POSTGRES_PASSWORD='isolated-backup-startup-password',
        SENTINEL_PUBLICATION_RECEIPT_KEY='isolated-backup-startup-receipt-key-0123456789',
        SENTINEL_RUNTIME_IMAGE_REF=IMAGE, SENTINEL_BACKUP_SHARED_INTEGRITY='REQUIRED_V1')
    for key,value in values.items(): monkeypatch.setenv(key,value)
    monkeypatch.setattr(coordinator,'_latest_publication',lambda:None)
    native_run = subprocess.run
    boundary = FreshBoundary()
    attempts = []

    def runner(command, **options):
        if len(command) == 5 and command[3] == 'sentinel-maintenance-media':
            return coordinator.run(command, **options)
        value = boundary(command, **options)
        if command[:2] == ['bash','scripts/sentinel-backup-status.sh']:
            value = value.replace('base=/media/', 'base='+str(media)+'/')
        return value

    def child(command, **options):
        assert coordinator.supervise() == 0
        if not attempts:
            result = native_run(command,cwd=coordinator.ROOT,env=values,
                capture_output=True,text=True,timeout=20,pass_fds=options['pass_fds'])
            assert result.returncode == 75, (result.stdout,result.stderr)
        else:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                coordinator.tick(str(media),runner)
            result = SimpleNamespace(returncode=0,stdout=output.getvalue(),stderr='')
        attempts.append(renewal.parse(result.stdout))
        return result

    def sleep(delay):
        if len(attempts) == 1:
            assert 0.5 < delay <= 1 and not media.exists()
            detached.rename(media)
        else:
            assert 290 < delay <= 300
            raise KeyboardInterrupt

    monkeypatch.setattr(coordinator.subprocess,'run',child)
    monkeypatch.setattr(coordinator,'time',SimpleNamespace(monotonic=coordinator.time.monotonic,sleep=sleep))
    with pytest.raises(KeyboardInterrupt): coordinator.supervise()
    assert [value['outcome'] for value in attempts] == ['RETRYABLE','SUCCESS']
    assert attempts[0]['publication_at'] is None
    assert attempts[1]['publication_at'] is not None
    assert any(value.get('schema') == 'sentinel.maintenance-integrity/1' for value in boundary.published)
    assert not detached.exists()
    for name in ('base','wal'):
        assert (media/name/'.sentinel-independent-durable-target-v1').read_text() == (
            'sentinel-independent-durable-target-v1\n')


@pytest.mark.parametrize('change', [dict(code='INTEGRITY_REFUSED'),dict(origin='WORKER'),
    dict(stage='HOST_POLICY'),dict(exception_chain=[dict(type='OSError',sqlstate=None,errno=13)]),
    dict(proof_lock='FAILED'),dict(worker_container='FAILED'),dict(cause_type='BackupRuntimeUnavailable')])
def test_media_retry_requires_actual_absence_and_no_work_started(change):
    if change.get('origin') == 'WORKER':
        with pytest.raises(ValueError): absent_failure(**change)
        return
    failure = absent_failure(**change)
    assert not failure['retryable']
    assert worker.MaintenanceFailure.model_validate(failure).retryable is False


def test_host_and_worker_agree_on_precise_media_failure():
    failure = absent_failure()
    assert worker.MaintenanceFailure.model_validate(failure).model_dump() == failure


def test_mounted_or_aliased_refusal_does_not_become_absent_media(tmp_path):
    target = tmp_path/'media'
    target.mkdir()
    original = coordinator.Refused('mounted target identity failed')
    def refusing(*args,**kwargs): raise original
    with pytest.raises(coordinator.Refused) as caught:
        coordinator.admit_media(str(target),refusing)
    assert caught.value is original and caught.value.failure is None
    target.rmdir()
    alias = tmp_path/'alias'
    alias.symlink_to(target,target_is_directory=True)
    with pytest.raises(coordinator.Refused) as caught:
        coordinator.admit_media(str(alias),refusing)
    assert caught.value is original and caught.value.failure is None


def test_old_media_retry_schedule_fails_the_recovery_regression():
    source = inspect.getsource(renewal.Schedule.consume)
    assert source.count("media_wait = value['outcome'] == 'RETRYABLE'") == 1
    mutant = source.replace("media_wait = value['outcome'] == 'RETRYABLE' and value['failure']['stage'] == 'HOST_MEDIA'",
                            'media_wait = False')
    import textwrap
    namespace = dict(vars(renewal))
    exec(compile(textwrap.dedent(mutant),'<media-retry-disabled>','exec'),namespace)
    clock = Clock()
    clock.now = 900
    schedule = clock.schedule()
    value = renewal.result(outcome='RETRYABLE',phase='PREFLIGHT',code='PHYSICAL_UNAVAILABLE',
        cause_type='Refused',failure=absent_failure(),publication_at=clock.publication(0))
    namespace['consume'](schedule,value)
    assert schedule.delay() == 300
    schedule.consume(value)
    assert schedule.delay() == 1
