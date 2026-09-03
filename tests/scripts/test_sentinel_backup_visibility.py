from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sentinel-base-backup.sh"
LIB = ROOT / "scripts" / "sentinel-backup-lib.sh"


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


def test_durable_target_marker_bootstrap_uses_container_authority():
    source = LIB.read_text(encoding="utf-8")

    # The first-install marker must follow the same authority model as the
    # backup data. The historical host redirection fails on a correctly
    # postgres-owned WAL directory on Synology.
    assert (
        'printf \'%s\\n\' "$SENTINEL_BACKUP_TARGET_MARKER_CONTENT" > "$marker"'
        not in source
    )
    assert "_sentinel_backup_marker_container" in source
    assert '"$parent" "$marker_uid" "$marker_mode"' in source
    assert 'marker_uid="$uid"' in source
    assert 'chmod 0444 "$tmp"' in source
    assert 'stat -c %a "$marker"' in source
    assert 'if [ "$permissions" != 444 ]' in source
    assert 'sync "$tmp"' in source
    assert 'sync /probe' in source
    assert 'ln "$tmp" "$marker"' in source
