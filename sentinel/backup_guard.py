"""Runtime durability guard for prolonged external-backup loss.

The PostgreSQL archive_command correctly retains WAL when the second durable
backup target disappears. That is data-safe at first but cannot be allowed to
continue indefinitely: WAL accumulation consumes the primary database disk and
a live-money system should not keep creating new economic obligations after its
recovery point has been unprotected for days.

A recent unresolved archive failure is DEGRADED: bounded ordinary operations may
continue so a short USB/NAS interruption does not immediately idle the book.
Once an unresolved failure has persisted beyond the reviewed hard age, new
data/plan/order mutation is fenced. A merely old successful archive with *no*
newer failure is ambiguous: the database may have been quiet, or the target may
have disappeared without PostgreSQL having generated a new archive attempt.
Before any new economic/data mutation in that state, Sentinel writes a harmless
restore-point WAL record, forces a WAL switch, and requires the archiver to reach
that forced segment. Thus a disconnected quiet disk cannot be discovered only
after a broker order has already been authorized, and a large stale WAL backlog
cannot masquerade as current durability merely because one older file moved.
Read-only broker recovery remains available throughout.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import time


BACKUP_HARD_MAX_AGE_HOURS = 30
BACKUP_PROBE_TIMEOUT_SECONDS = 20
BACKUP_PROBE_POLL_SECONDS = 0.25
_WAL_NAME = re.compile(r"[0-9A-F]{24}\Z")


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

    @property
    def bulk_writes_permitted(self) -> bool:
        return self.state == "HEALTHY"

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "archive_mode": self.archive_mode,
            "last_success_age_seconds": self.last_success_age_seconds,
            "unresolved_failure": self.unresolved_failure,
            "failed_count": self.failed_count,
            "hard_max_age_hours": BACKUP_HARD_MAX_AGE_HOURS,
            "writes_permitted": self.writes_permitted,
            "bulk_writes_permitted": self.bulk_writes_permitted,
        }


def _aware(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise BackupWriteFenced(
            "PostgreSQL archive timestamp is malformed; refusing new mutation")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


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
    database_now = _aware(database_now)
    if database_now is None:
        raise BackupWriteFenced(
            "PostgreSQL archive clock is unavailable; refusing new mutation")
    last_ok = _aware(last_ok)
    last_fail = _aware(last_fail)
    age = (None if last_ok is None else max(
        0, int((database_now - last_ok).total_seconds())))
    unresolved = bool(
        last_fail is not None and (last_ok is None or last_fail > last_ok))
    hard_seconds = BACKUP_HARD_MAX_AGE_HOURS * 3600
    if mode != "on" or last_ok is None:
        state = "FENCED"
    elif unresolved and age is not None and age > hard_seconds:
        state = "FENCED"
    elif unresolved:
        state = "DEGRADED"
    elif age is not None and age > hard_seconds:
        state = "PROBE_REQUIRED"
    else:
        state = "HEALTHY"
    return BackupGuardStatus(
        state=state, archive_mode=mode,
        last_success_age_seconds=age,
        unresolved_failure=unresolved,
        failed_count=int(failed_count or 0))


def _archiver_observation(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_archived_wal,last_archived_time,last_failed_time,"
            " failed_count FROM pg_stat_archiver")
        row = cur.fetchone()
    if row is None or len(row) != 4:
        raise BackupWriteFenced(
            "PostgreSQL archive probe state is unavailable")
    wal, last_ok, last_fail, failed_count = row
    wal = str(wal or "")
    if wal and _WAL_NAME.fullmatch(wal) is None:
        raise BackupWriteFenced(
            "PostgreSQL last_archived_wal is malformed")
    return wal, _aware(last_ok), _aware(last_fail), int(failed_count or 0)


def _probe_wal_boundary(conn, *, operation: str) -> str:
    """Generate non-business WAL and return the exact segment that must archive."""
    try:
        with conn.cursor() as cur:
            # A bare pg_switch_wal() may do nothing after a completely quiet
            # segment. A restore point is a small WAL-only record (no strategy,
            # feed, plan, order or account table mutation) and guarantees there
            # is activity to switch/archive under the configured wal_level.
            cur.execute(
                "SELECT pg_create_restore_point('sentinel-backup-probe')")
            if cur.fetchone() is None:
                raise RuntimeError("restore point returned no row")
            cur.execute("SELECT pg_walfile_name(pg_switch_wal())")
            switched = cur.fetchone()
    except Exception as exc:
        raise BackupWriteFenced(
            f"{operation} fenced: could not force external-WAL liveness probe "
            f"({type(exc).__name__})") from exc
    target = str(switched[0] if switched else "")
    if _WAL_NAME.fullmatch(target) is None:
        raise BackupWriteFenced(
            f"{operation} fenced: PostgreSQL WAL switch returned malformed "
            "archive evidence")
    return target


def _probe_stale_archive_target(
        conn, *, operation: str,
        sleep=time.sleep, monotonic=time.monotonic) -> BackupGuardStatus:
    """Force and observe archival through an exact harmless WAL boundary."""
    _before_wal, before_ok, before_fail, before_failed_count = (
        _archiver_observation(conn))
    target_wal = _probe_wal_boundary(conn, operation=operation)

    deadline = monotonic() + BACKUP_PROBE_TIMEOUT_SECONDS
    while monotonic() < deadline:
        sleep(BACKUP_PROBE_POLL_SECONDS)
        wal, last_ok, last_fail, failed_count = _archiver_observation(conn)
        # WAL filenames are fixed-width hexadecimal timeline/log/segment names.
        # The configured primary does not change timeline during this runtime;
        # reaching the target or a later name proves the forced boundary made it
        # to the external archive, not merely that an older backlog file moved.
        target_reached = (
            bool(wal) and wal >= target_wal
            and last_ok is not None
            and (before_ok is None or last_ok > before_ok))
        failure_advanced = (
            failed_count > before_failed_count
            or (last_fail is not None
                and (before_fail is None or last_fail > before_fail)))
        if target_reached and (
                last_fail is None or last_ok is not None and last_ok >= last_fail):
            result = status(conn)
            if result.state == "HEALTHY":
                return result
        if failure_advanced and not target_reached:
            result = status(conn)
            raise BackupWriteFenced(_fence_message(result, operation=operation))

    result = status(conn)
    raise BackupWriteFenced(
        f"{operation} fenced: external WAL target did not archive the forced "
        f"segment {target_wal} within {BACKUP_PROBE_TIMEOUT_SECONDS}s; "
        + _fence_message(result, operation=operation))


def _fence_message(result: BackupGuardStatus, *, operation: str) -> str:
    age = ("never" if result.last_success_age_seconds is None
           else f"{result.last_success_age_seconds // 3600}h")
    return (
        f"{operation} fenced: external WAL durability is {result.state} "
        f"(archive_mode={result.archive_mode}, last_success_age={age}, "
        f"unresolved_failure={result.unresolved_failure}); reconnect/repair "
        "the backup target and wait for PostgreSQL to archive WAL successfully")


def _resolved_for_mutation(conn, *, operation: str) -> BackupGuardStatus:
    result = status(conn)
    if result.state == "PROBE_REQUIRED":
        result = _probe_stale_archive_target(conn, operation=operation)
    return result


def require_writes_permitted(conn, *, operation: str) -> BackupGuardStatus:
    result = _resolved_for_mutation(conn, operation=operation)
    if not result.writes_permitted:
        raise BackupWriteFenced(_fence_message(result, operation=operation))
    return result


def require_bulk_writes_permitted(conn, *, operation: str) -> BackupGuardStatus:
    """Require a currently proven archive target before WAL-heavy recovery."""
    result = _resolved_for_mutation(conn, operation=operation)
    if not result.bulk_writes_permitted:
        raise BackupWriteFenced(_fence_message(result, operation=operation))
    return result


__all__ = [
    "BACKUP_HARD_MAX_AGE_HOURS", "BACKUP_PROBE_TIMEOUT_SECONDS",
    "BackupGuardStatus", "BackupWriteFenced", "require_bulk_writes_permitted",
    "require_writes_permitted", "status",
]
