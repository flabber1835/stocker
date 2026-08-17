from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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
