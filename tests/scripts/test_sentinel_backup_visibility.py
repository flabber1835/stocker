from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sentinel-base-backup.sh"


def test_backup_wal_and_marker_are_checked_inside_postgres_container():
    source = SCRIPT.read_text(encoding="utf-8")

    # A valid backup target may be 0700 postgres:postgres. The NAS host user
    # running the wrapper therefore must not stat or write inside wal/base.
    assert '[ -f "$BACKUP_ROOT/wal/$MARKER_WAL" ]' not in source
    assert '> "$METADATA"' not in source

    # Both the archived WAL proof and recovery-marker publication happen where
    # the bind mount is authoritative and readable: inside sentinel-postgres as
    # the postgres user.
    assert source.count("exec -T -u postgres sentinel-postgres") >= 3
    assert 'test -f "/sentinel-backup/wal/$wal"' in source
    assert 'test -r "/sentinel-backup/wal/$wal"' in source
    assert '> "/sentinel-backup/base/$name/sentinel-recovery-marker"' in source
    assert 'test -f "/sentinel-backup/base/$NAME/sentinel-recovery-marker"' in source
