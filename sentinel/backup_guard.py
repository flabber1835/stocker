"""Runtime durability guard for prolonged external-backup loss.

The PostgreSQL archive_command correctly retains WAL when the second durable
backup target disappears. That is data-safe at first but cannot be allowed to
continue indefinitely: WAL accumulation consumes the primary database disk and
a live-money system should not keep creating new economic obligations after its
recovery point has been unprotected for days.

This guard is intentionally recovery-friendly. A recent unresolved archive
failure is DEGRADED but permitted, allowing transient USB/NAS interruptions to
heal. Once the last successful WAL archive is older than the reviewed hard age,
new data writes/plans/orders are retryably fenced. Read-only broker recovery is
not fenced, so uncertain in-flight orders can still be reconciled when Alpaca
returns. Reconnecting the backup target automatically clears the fence after a
new successful WAL archive; no manual control-generation reset is required.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


BACKUP_HARD_MAX_AGE_HOURS = 30


class BackupWriteFenced(RuntimeError):
    """New economic/data mutation is temporarily forbidden by backup health."""


@dataclass(frozen=True)
class BackupGuardStatus:
    state: str
    archive_mode: str
    last_success_age_seconds: int | None
    unresolved_failure: bool
    failed_count: int

    @property
    def writes_permitted(self) -> bool:
        return self.state in {"HEALTHY", "DEGRADED"}

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "archive_mode": self.archive_mode,
            "last_success_age_seconds": self.last_success_age_seconds,
            "unresolved_failure": self.unresolved_failure,
            "failed_count": self.failed_count,
            "hard_max_age_hours": BACKUP_HARD_MAX_AGE_HOURS,
            "writes_permitted": self.writes_permitted,
        }


def status(conn) -> BackupGuardStatus:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT current_setting('archive_mode'), last_archived_time, "
            "last_failed_time, failed_count, clock_timestamp() "
            "FROM pg_stat_archiver")
        row = cur.fetchone()
    if row is None or len(row) != 5:
        raise BackupWriteFenced(
            "PostgreSQL archive health is unavailable; refusing new mutation")
    mode, last_ok, last_fail, failed_count, database_now = row
    mode = str(mode or "")
    if not isinstance(database_now, datetime):
        raise BackupWriteFenced(
            "PostgreSQL archive clock is unavailable; refusing new mutation")
    if database_now.tzinfo is None:
        database_now = database_now.replace(tzinfo=timezone.utc)
    if last_ok is not None and last_ok.tzinfo is None:
        last_ok = last_ok.replace(tzinfo=timezone.utc)
    if last_fail is not None and last_fail.tzinfo is None:
        last_fail = last_fail.replace(tzinfo=timezone.utc)
    age = (None if last_ok is None else max(
        0, int((database_now - last_ok).total_seconds())))
    unresolved = bool(
        last_fail is not None and (last_ok is None or last_fail > last_ok))
    hard_seconds = BACKUP_HARD_MAX_AGE_HOURS * 3600
    if mode != "on" or last_ok is None:
        state = "FENCED"
    elif age is not None and age > hard_seconds:
        state = "FENCED"
    elif unresolved:
        state = "DEGRADED"
    else:
        state = "HEALTHY"
    return BackupGuardStatus(
        state=state, archive_mode=mode,
        last_success_age_seconds=age,
        unresolved_failure=unresolved,
        failed_count=int(failed_count or 0))


def require_writes_permitted(conn, *, operation: str) -> BackupGuardStatus:
    result = status(conn)
    if not result.writes_permitted:
        age = ("never" if result.last_success_age_seconds is None
               else f"{result.last_success_age_seconds // 3600}h")
        raise BackupWriteFenced(
            f"{operation} fenced: external WAL durability has no acceptable "
            f"recent success (archive_mode={result.archive_mode}, "
            f"last_success_age={age}, unresolved_failure="
            f"{result.unresolved_failure}); reconnect/repair the backup target "
            "and wait for PostgreSQL to archive WAL successfully")
    return result


__all__ = [
    "BACKUP_HARD_MAX_AGE_HOURS", "BackupGuardStatus", "BackupWriteFenced",
    "require_writes_permitted", "status",
]
