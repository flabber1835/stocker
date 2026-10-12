import os
from pathlib import Path

import subprocess
import sys

import pytest
import yaml


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_base_backup_uses_explicit_private_authority_split():
    text = _read("scripts/sentinel-base-backup.sh")
    before_backup = text[: text.index("pg_basebackup")]
    assert "exec -T sentinel-postgres sh -ceu" in before_backup
    assert "exec -T -u postgres sentinel-postgres sh -ceu" not in before_backup
    assert text.index("pg_basebackup") < text.index("pg_verifybackup")

    wal_proof = 'exec -T -u postgres sentinel-postgres sh -ceu'
    marker_publish = 'exec -T sentinel-postgres sh -ceu'
    assert wal_proof in text[text.index("for _ in $(seq 1 60)") :]
    assert marker_publish in text[text.index(wal_proof) :]


def test_backup_preflight_proves_the_two_actual_filesystem_authorities():
    text = _read("scripts/sentinel-backup-lib.sh")
    assert '--user "$uid"' in text
    assert '-v "$root/wal:/probe"' in text
    assert "postgres uid $uid cannot write the WAL target" in text
    assert '-v "$root/base:/probe"' in text
    assert "container root cannot write the base-backup target" in text


def test_private_base_backup_contents_are_not_inspected_by_nas_host_user():
    status = _read("scripts/sentinel-backup-status.sh")
    restore = _read("scripts/sentinel-restore-drill.sh")

    for text in (status, restore):
        assert 'find "$BACKUP_ROOT/base"' not in text
        assert '[ -d "$LATEST" ]' not in text
        assert 'test -d "/sentinel-backup/base/$NAME"' in text
        assert 'test -f "/sentinel-backup/base/$NAME/backup_manifest"' in text

    assert 'stat -c %Y "/sentinel-backup/base/$NAME/backup_manifest"' in status
    assert 'file="/sentinel-backup/base/$1/sentinel-recovery-marker"' in restore


def _require_isolated_client(service):
    assert service.get('pid', 'private') == 'private'
    assert service['network_mode'] == 'service:sentinel-postgres'
    assert service['profiles'] == ['backup-client']
    assert service['entrypoint'] == ['timeout'] and service['command'] == ['--help']
    assert service['init'] is True and service['restart'] == 'no'
    assert set(service['environment']) == {'POSTGRES_PASSWORD'}
    assert {v['target'] for v in service['volumes']} == {'/usr/local/libexec', '/sentinel-backup/base'}


def test_physical_timeout_runs_only_in_disposable_client_pid_namespace():
    service = yaml.safe_load(_read('docker-compose.sentinel-backup.yml'))['services']['sentinel-backup-client']
    _require_isolated_client(service)
    primary = yaml.safe_load(_read('docker-compose.sentinel.yml'))['services']['sentinel-postgres']
    assert service['image'] == primary['image']
    script = _read('scripts/sentinel-base-backup.sh')
    assert 'run --rm -T --no-deps --entrypoint timeout sentinel-backup-client' in script
    assert 'exec -T sentinel-postgres timeout' not in script
    assert 'sentinel_media_lock /sentinel-backup/base exclusive' in script
    assert script.index('pg_verifybackup') < script.index('mv -T --no-clobber')


@pytest.mark.parametrize('pid', ['host', 'service:sentinel-postgres'])
def test_shared_pid_namespace_falsifier_is_rejected(pid):
    service = yaml.safe_load(_read('docker-compose.sentinel-backup.yml'))['services']['sentinel-backup-client']
    service['pid'] = pid
    with pytest.raises(AssertionError): _require_isolated_client(service)


def test_base_worker_grace_fits_host_deadline():
    from scripts import sentinel_backup_deadlines as deadlines
    value = subprocess.check_output([sys.executable, str(ROOT/'scripts/sentinel_backup_deadlines.py'),
                                     'base-worker'], text=True).strip()
    assert int(value) == deadlines.BASE_WORKER_SECONDS
    assert 600 < deadlines.BASE_WORKER_SECONDS < deadlines.BASE_COMMAND_SECONDS
    assert deadlines.BASE_WORKER_SECONDS + 30 < deadlines.BASE_COMMAND_SECONDS
