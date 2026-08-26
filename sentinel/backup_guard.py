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
restore-point WAL record, forces a WAL switch, and requires the *exact* forced
segment to exist at full segment size on the mounted durable archive target.
A new archive-enabled database with no prior successful archive uses that same
active proof before its first protected mutation rather than deadlocking on the
absence of historical evidence. Read-only broker recovery remains available
throughout.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import time


BACKUP_HARD_MAX_AGE_HOURS = 30
BACKUP_PROBE_TIMEOUT_SECONDS = 20
BACKUP_PROBE_POLL_SECONDS = 0.25
BACKUP_WAL_MOUNT = "/sentinel-backup/wal"
_WAL_NAME = re.compile(r"[0-9A-F]{24}\Z")


class BackupWriteFenced(RuntimeError):
    """Base class for backup-health refusals that fence new mutation."""


class BackupUnavailable(BackupWriteFenced):
    """External durability is temporarily unavailable and may self-heal."""


class BackupConfigurationRefused(BackupWriteFenced):
    """Backup configuration/integrity is invalid and requires intervention."""


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
        raise BackupConfigurationRefused(
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
        raise BackupConfigurationRefused(
            "PostgreSQL archive health is unavailable; refusing new mutation")
    mode, last_ok, last_fail, failed_count, database_now = row
    mode = str(mode or "")
    database_now = _aware(database_now)
    if database_now is None:
        raise BackupConfigurationRefused(
            "PostgreSQL archive clock is unavailable; refusing new mutation")
    last_ok = _aware(last_ok)
    last_fail = _aware(last_fail)
    failed_count = int(failed_count or 0)
    age = (None if last_ok is None else max(
        0, int((database_now - last_ok).total_seconds())))
    unresolved = bool(
        last_fail is not None and (last_ok is None or last_fail > last_ok))
    hard_seconds = BACKUP_HARD_MAX_AGE_HOURS * 3600
    if mode != "on":
        state = "FENCED"
    elif last_ok is None:
        # A fresh archive-enabled cluster has no historical success yet. If it
        # also has no observed failure, actively prove the target before the
        # first protected write. An already-failing virgin archiver is fenced.
        state = (
            "FENCED" if unresolved or failed_count > 0
            else "PROBE_REQUIRED")
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
        failed_count=failed_count)


def _archiver_observation(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_archived_wal,last_archived_time,last_failed_time,"
            " failed_count FROM pg_stat_archiver")
        row = cur.fetchone()
    if row is None or len(row) != 4:
        raise BackupConfigurationRefused(
            "PostgreSQL archive probe state is unavailable")
    wal, last_ok, last_fail, failed_count = row
    return str(wal or ""), _aware(last_ok), _aware(last_fail), int(failed_count or 0)


def _probe_wal_boundary(conn, *, operation: str) -> str:
    """Generate non-business WAL and return the exact segment that must archive."""
    try:
        with conn.cursor() as cur:
            # A bare pg_switch_wal() may do nothing after a completely quiet
            # segment. The uniquely named restore point is a small WAL-only
            # record (no strategy/feed/plan/order/account table mutation) and
            # guarantees activity before the switch. Include backend pid and
            # server timestamp so this probe cannot create duplicate recovery
            # target names.
            cur.execute(
                "SELECT pg_create_restore_point("
                "'sentinel-backup-probe-' || pg_backend_pid()::text || '-' || "
                "to_char(clock_timestamp(), 'YYYYMMDDHH24MISSUS'))")
            if cur.fetchone() is None:
                raise RuntimeError("restore point returned no row")
            cur.execute("SELECT pg_walfile_name(pg_switch_wal())")
            switched = cur.fetchone()
    except Exception as exc:
        raise BackupConfigurationRefused(
            f"{operation} fenced: could not force external-WAL liveness probe "
            f"({type(exc).__name__})") from exc
    target = str(switched[0] if switched else "")
    if _WAL_NAME.fullmatch(target) is None:
        raise BackupConfigurationRefused(
            f"{operation} fenced: PostgreSQL WAL switch returned malformed "
            "archive evidence")
    return target


def _exact_archived_file(conn, wal_name: str) -> tuple[int | None, int]:
    """Return exact durable-target file size and configured WAL segment size."""
    if _WAL_NAME.fullmatch(str(wal_name)) is None:
        raise BackupConfigurationRefused(
            "external WAL probe target name is malformed")
    path = f"{BACKUP_WAL_MOUNT}/{wal_name}"
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT (pg_stat_file(%s,true)).size, "
                "pg_size_bytes(current_setting('wal_segment_size'))",
                (path,))
            row = cur.fetchone()
    except Exception as exc:
        raise BackupConfigurationRefused(
            "external WAL durable-target file cannot be inspected "
            f"({type(exc).__name__})") from exc
    if row is None or len(row) != 2:
        raise BackupConfigurationRefused(
            "external WAL durable-target inspection returned no evidence")
    size = None if row[0] is None else int(row[0])
    expected = int(row[1])
    if expected <= 0:
        raise BackupConfigurationRefused(
            "configured WAL segment size is invalid")
    return size, expected


def _probe_stale_archive_target(
        conn, *, operation: str,
        sleep=time.sleep, monotonic=time.monotonic) -> BackupGuardStatus:
    """Force and observe archival of one exact harmless WAL segment."""
    _before_wal, before_ok, before_fail, before_failed_count = (
        _archiver_observation(conn))
    target_wal = _probe_wal_boundary(conn, operation=operation)

    deadline = monotonic() + BACKUP_PROBE_TIMEOUT_SECONDS
    while monotonic() < deadline:
        sleep(BACKUP_PROBE_POLL_SECONDS)
        size, expected_size = _exact_archived_file(conn, target_wal)
        _wal, last_ok, last_fail, failed_count = _archiver_observation(conn)
        exact_durable = size == expected_size
        success_advanced = (
            last_ok is not None
            and (before_ok is None or last_ok > before_ok))
        failure_advanced = (
            failed_count > before_failed_count
            or (last_fail is not None
                and (before_fail is None or last_fail > before_fail)))
        if exact_durable and success_advanced:
            # A later failure may already have moved the archiver to DEGRADED;
            # that policy permits small ordinary mutations but still blocks a
            # bulk reseed. The caller applies the appropriate write predicate.
            return status(conn)
        if failure_advanced and not exact_durable:
            result = status(conn)
            raise BackupUnavailable(_fence_message(result, operation=operation))

    result = status(conn)
    raise BackupUnavailable(
        f"{operation} fenced: external WAL target did not durably publish the "
        f"exact forced segment {target_wal} within "
        f"{BACKUP_PROBE_TIMEOUT_SECONDS}s; "
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


def _raise_fenced(result: BackupGuardStatus, *, operation: str) -> None:
    message = _fence_message(result, operation=operation)
    if result.archive_mode != "on":
        raise BackupConfigurationRefused(message)
    raise BackupUnavailable(message)


def require_writes_permitted(conn, *, operation: str) -> BackupGuardStatus:
    result = _resolved_for_mutation(conn, operation=operation)
    if not result.writes_permitted:
        _raise_fenced(result, operation=operation)
    return result


def require_bulk_writes_permitted(conn, *, operation: str) -> BackupGuardStatus:
    """Require a currently proven archive target before WAL-heavy recovery."""
    result = _resolved_for_mutation(conn, operation=operation)
    if not result.bulk_writes_permitted:
        _raise_fenced(result, operation=operation)
    return result


__all__ = [
    "BACKUP_HARD_MAX_AGE_HOURS", "BACKUP_PROBE_TIMEOUT_SECONDS",
    "BACKUP_WAL_MOUNT", "BackupConfigurationRefused", "BackupGuardStatus",
    "BackupUnavailable", "BackupWriteFenced", "require_bulk_writes_permitted",
    "require_writes_permitted", "status",
]
