"""Read-only wake hints for contention on the unchanged physical proof owner."""
from datetime import datetime

from sentinel import backup_integrity_reuse, backup_runtime_authority
from sentinel.backup_guard import BackupProofBusyReason


_BUSY_REASONS = {
    'another backup integrity proof owner is active': BackupProofBusyReason.OWNER_ACTIVE,
    'completed backup integrity proof does not cover current media': BackupProofBusyReason.COVERAGE_CHANGED,
    'completed backup integrity proof requires a fresh scrub': BackupProofBusyReason.RECEIPT_UNAVAILABLE,
    'completed backup integrity proof does not cover the advanced frontier': BackupProofBusyReason.FRONTIER_CHANGED,
    'completed backup integrity proof changed during admission': BackupProofBusyReason.RECEIPT_CHANGED,
}


def busy_reason(exc: backup_runtime_authority.BackupIntegrityBusy) -> BackupProofBusyReason:
    if (str(exc) == 'strict backup refusal PROOF_OWNER_BUSY'
            and type(exc.__cause__) is backup_runtime_authority.BackupIntegrityBusy):
        exc = exc.__cause__
    return _BUSY_REASONS.get(str(exc), BackupProofBusyReason.OWNER_ACTIVE)


def _completed_since(conn, failed_at: datetime) -> bool:
    # Map the optional wake threshold onto the PostgreSQL host that owns the
    # receipt uptime. Only an authenticated fresh, exact proof can wake.
    observed_at = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    if not 0 < (elapsed := (observed_at - failed_at).total_seconds()) < backup_integrity_reuse.MAX_AGE:
        return False
    system_id = backup_runtime_authority.current_system_id(conn)
    base = backup_runtime_authority._published_base(conn, system_id=system_id)
    operation = "backup proof retry wake"
    end, segment_size = backup_runtime_authority._archive_frontier(conn, operation=operation)
    start = backup_runtime_authority._manifest_end_wal(conn, base, segment_size=segment_size)
    owner = backup_integrity_reuse.Owner(conn, {
        "system_id": system_id, "base": base, "start": start,
        "segment_size": segment_size,
    }, read_only=True)
    if (owner.proof is None or owner.proof.end != end
            or owner.proof.completed_uptime <= owner.uptime - elapsed):
        return False
    owner.require_unchanged()
    return (backup_runtime_authority._published_base(conn, system_id=system_id) == base
            and backup_runtime_authority._archive_frontier(conn, operation=operation) == (end, segment_size))


def _read_completion(database_url: str, failed_at: datetime) -> bool:
    from sentinel.feed import store

    with store.connect(database_url, connect_timeout=1, statement_timeout_ms=1000) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        return _completed_since(conn, failed_at)


def completed_since(database_url: str, failed_at: datetime) -> bool:
    """A bounded read-only wake hint. The next callback redoes strict admission."""
    from sentinel import supervisor_io

    try:
        if not backup_integrity_reuse.selected():
            return False
        return supervisor_io.run(_read_completion, database_url, failed_at, timeout=2.0) is True
    except Exception:
        return False  # Optional scheduling evidence never changes the durable timer.
