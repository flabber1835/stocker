from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_base_backup_creation_runs_as_postgres():
    text = _read("scripts/sentinel-base-backup.sh")
    postgres_exec = "exec -T -u postgres sentinel-postgres sh -ceu"
    assert postgres_exec in text
    assert text.index(postgres_exec) < text.index("pg_basebackup")
    assert text.index("pg_basebackup") < text.index("pg_verifybackup")


def test_backup_preflight_proves_postgres_can_write_wal_and_base_targets():
    text = _read("scripts/sentinel-backup-lib.sh")
    assert "for child in wal base; do" in text
    assert '-v "$root/$child:/probe"' in text
    assert 'cannot write the $child backup target' in text
