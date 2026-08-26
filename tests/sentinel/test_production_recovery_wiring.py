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
        if "pg_switch_wal" in text:
            self.kind = "switch"
        elif "last_archived_wal" in text:
            self.kind = "archiver"
        elif "current_setting('archive_mode')" in text:
            self.kind = "status"
        else:  # pragma: no cover - contract guard
            raise AssertionError(text)

    def fetchone(self):
        if self.kind == "switch":
            return ("0/2000000",)
        if self.kind == "archiver":
            index = min(self.conn.archiver_reads, len(self.conn.archiver_rows) - 1)
            self.conn.archiver_reads += 1
            return self.conn.archiver_rows[index]
        if self.kind == "status":
            return self.conn.status_row
        raise AssertionError(self.kind)


class _ProbeConn:
    def __init__(self, *, before, after, status_row):
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


def test_active_wal_probe_promotes_only_after_fresh_archive_success():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    old_success = now - timedelta(
        hours=backup_guard.BACKUP_HARD_MAX_AGE_HOURS + 12)
    fresh_success = now - timedelta(seconds=1)
    conn = _ProbeConn(
        before=("000000010000000000000001", old_success, None, 0),
        after=("000000010000000000000002", fresh_success, None, 0),
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


def test_nas_current_daily_proof_cannot_bypass_backup_guard():
    text = (_repo_root() / "scripts" / "sentinel_go_validate_entry.py").read_text(
        encoding="utf-8")
    assert "from sentinel import backup_guard, schema" in text
    assert "NAS validation explicit daily publication" in text
    assert "backup_guard.require_writes_permitted" in text
