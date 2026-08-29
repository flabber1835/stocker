from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sentinel-base-backup.sh"


def test_backup_wal_and_marker_are_checked_inside_postgres_container():
    source = SCRIPT.read_text(encoding="utf-8")

    # A valid backup target may be inaccessible to the NAS host user. The host
    # wrapper therefore must not stat or write inside the wal/base bind mounts.
    assert '[ -f "$BACKUP_ROOT/wal/$MARKER_WAL" ]' not in source
    assert '> "$METADATA"' not in source

    # WAL visibility is proven as postgres, the authority that archives WAL.
    # The private root-owned base-backup tree is mutated through the container
    # default user, including staged recovery-marker publication and fsync.
    assert "exec -T -u postgres sentinel-postgres" in source
    assert 'test -f "/sentinel-backup/wal/$wal"' in source
    assert 'test -r "/sentinel-backup/wal/$wal"' in source
    assert 'metadata="/sentinel-backup/base/$name/sentinel-recovery-marker"' in source
    assert 'sync "$metadata"' in source
    assert 'test -f "/sentinel-backup/base/$NAME/sentinel-recovery-marker"' in source
