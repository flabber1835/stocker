from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sentinel import backup_guard


class _Cursor:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row):
        self.row = row

    def cursor(self):
        return _Cursor(self.row)


class _ProbeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.kind = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, *_args, **_kwargs):
        text = str(statement)
        if "pg_create_restore_point" in text:
            self.kind = "restore"
        elif "pg_switch_wal" in text:
            self.kind = "switch"
        elif "pg_stat_file" in text:
            self.kind = "file"
        elif "last_archived_wal" in text:
            self.kind = "archiver"
        elif "current_setting('archive_mode')" in text:
            self.kind = "status"
        else:  # pragma: no cover - contract guard
            raise AssertionError(text)

    def fetchone(self):
        if self.kind == "restore":
            return ("0/1FFFFFF",)
        if self.kind == "switch":
            return (self.conn.target_wal,)
        if self.kind == "file":
            return (self.conn.target_size, self.conn.target_size)
        if self.kind == "archiver":
            index = min(self.conn.archiver_reads, len(self.conn.archiver_rows) - 1)
            self.conn.archiver_reads += 1
            return self.conn.archiver_rows[index]
        if self.kind == "status":
            return self.conn.status_row
        raise AssertionError(self.kind)


class _ProbeConn:
    def __init__(self, *, target_wal, before, after, status_row,
                 target_size=16 * 1024 * 1024):
        self.target_wal = target_wal
        self.target_size = target_size
        self.archiver_rows = [before, after]
        self.archiver_reads = 0
        self.status_row = status_row

    def cursor(self):
        return _ProbeCursor(self)


def _repo_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if not (root / "docker-compose.sentinel-automation.yml").is_file():
        root = root / "repo"
    assert (root / "docker-compose.sentinel-automation.yml").is_file()
    return root


def test_fresh_archive_enabled_database_requires_active_first_archive_proof():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    result = backup_guard.status(_Conn(("on", None, None, 0, now)))

    assert result.state == "PROBE_REQUIRED"
    assert result.writes_permitted is False
    assert result.bulk_writes_permitted is False


def test_virgin_archiver_with_observed_failure_is_fenced():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    failed_at = now - timedelta(minutes=1)
    result = backup_guard.status(_Conn(("on", None, failed_at, 1, now)))

    assert result.state == "FENCED"
    assert result.unresolved_failure is True
    assert result.writes_permitted is False


def test_quiet_old_archive_requires_active_probe_before_mutation():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    old_success = now - timedelta(
        hours=backup_guard.BACKUP_HARD_MAX_AGE_HOURS + 12)
    # No failed archive exists after the old success. This is ambiguous rather
    # than proof of either health or failure, so a plain status cannot authorize
    # a new economic mutation.
    result = backup_guard.status(_Conn(("on", old_success, None, 0, now)))

    assert result.state == "PROBE_REQUIRED"
    assert result.writes_permitted is False
    assert result.bulk_writes_permitted is False


def test_active_wal_probe_promotes_only_after_exact_forced_file_is_durable():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    old_success = now - timedelta(
        hours=backup_guard.BACKUP_HARD_MAX_AGE_HOURS + 12)
    fresh_success = now - timedelta(seconds=1)
    target = "000000010000000000000002"
    conn = _ProbeConn(
        target_wal=target,
        before=("000000010000000000000001", old_success, None, 0),
        after=(target, fresh_success, None, 0),
        status_row=("on", fresh_success, None, 0, now),
    )
    ticks = iter((0.0, 1.0))

    result = backup_guard._probe_stale_archive_target(
        conn, operation="test economic mutation",
        sleep=lambda _seconds: None,
        monotonic=lambda: next(ticks))

    assert result.state == "HEALTHY"
    assert result.writes_permitted is True
    assert result.bulk_writes_permitted is True


def test_regenesis_approval_is_forwarded_to_authorized_automation():
    text = (_repo_root() / "docker-compose.sentinel-automation.yml").read_text(
        encoding="utf-8")
    assert (
        "SENTINEL_SHADOW_REGENESIS_APPROVAL_SHA256: "
        "${SENTINEL_SHADOW_REGENESIS_APPROVAL_SHA256:-}"
    ) in text


def test_nas_schema_and_recovery_mutations_cannot_bypass_backup_guard():
    root = _repo_root()
    entry = (root / "scripts" / "sentinel_go_validate_entry.py").read_text(
        encoding="utf-8")
    recovery = (root / "sentinel" / "feed" / "outage_recovery.py").read_text(
        encoding="utf-8")
    assert "from sentinel import backup_guard, schema" in entry

    # Schema bootstrap/migration is a real financial-database mutation and must
    # remain behind the external-WAL durability fence.
    schema_guard = entry.index("operation='NAS validation schema migration'")
    schema_mutation = entry.index("schema.ensure_schema(c)")
    assert schema_guard < schema_mutation

    # outage_recovery.catch_up() is the single daily/cursor reconciliation path.
    # Every branch that can still write independently proves the appropriate WAL
    # durability before the write: ordinary daily, bulk retained reseed, and the
    # final post-reseed daily publication.
    assert "outage_recovery.catch_up(c, target_session=target)" in entry
    daily_guard = recovery.index('operation="canonical outage daily catch-up"')
    daily_mutation = recovery.index("ingest.daily(conn, today=target)", daily_guard)
    bulk_guard = recovery.index('operation="retained full corpus reseed"')
    bulk_mutation = recovery.index(
        "ingest.seed(conn, date_from=retained_start, date_to=target)", bulk_guard)
    post_guard = recovery.index(
        'operation="post-reseed canonical daily publication"')
    post_mutation = recovery.index("ingest.daily(conn, today=target)", post_guard)
    assert daily_guard < daily_mutation
    assert bulk_guard < bulk_mutation
    assert post_guard < post_mutation

    # If catch_up reports ALREADY_CURRENT, there is deliberately no second vendor
    # ingest or other mutation to guard: current publication is terminal success.
    marker = "if recovered.mode == 'ALREADY_CURRENT':"
    start = entry.index(marker)
    end = entry.index("elif recovered.mode == 'RETAINED_FULL_RESEED':", start)
    already_current = entry[start:end]
    assert "ingest.daily" not in already_current
    assert "backup_guard.require_writes_permitted" not in already_current
