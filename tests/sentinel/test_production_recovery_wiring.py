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


def _repo_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if not (root / "docker-compose.sentinel-automation.yml").is_file():
        root = root / "repo"
    assert (root / "docker-compose.sentinel-automation.yml").is_file()
    return root


def test_quiet_old_archive_allows_small_probe_but_not_bulk_reseed():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    old_success = now - timedelta(
        hours=backup_guard.BACKUP_HARD_MAX_AGE_HOURS + 12)
    # No failed archive exists after the old success: this is a quiet database,
    # not evidence that the external disk is disconnected.
    result = backup_guard.status(_Conn(("on", old_success, None, 0, now)))

    assert result.state == "HEALTHY"
    assert result.writes_permitted is True
    assert result.bulk_writes_permitted is False


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
