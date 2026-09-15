import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_go_feed_progress as progress


def test_valid_events_are_bounded_and_preserve_final_failure():
    value = {"stage": "actions_export", "status": "working", "rows": 123,
             "elapsed_ms": 15}
    line = progress.PREFIX + json.dumps(value)
    assert progress.parse(line) == value
    final = dict(value, status="failed")
    events = progress.collect((line + "\n") * 600 + progress.PREFIX + json.dumps(final))
    assert len(events) == 512
    assert events[-1] == final


def test_unsafe_progress_is_rejected():
    valid = {"stage": "actions_export", "status": "completed", "rows": 1,
             "elapsed_ms": 0}
    for bad in [dict(valid, url="https://secret"), dict(valid, stage="api_key=secret"),
                dict(valid, rows=True), dict(valid, elapsed_ms=-1),
                dict(valid, status=["completed"]), {"error": "secret"}]:
        assert progress.parse(progress.PREFIX + json.dumps(bad)) is None


def test_refresh_metadata_has_only_valid_utc_timestamps():
    value = {"stage": "actions_export", "status": "observed", "rows": 100,
             "elapsed_ms": 0, "refreshed_at": "2026-09-07T21:00:00+00:00",
             "snapshot_at": "2026-09-07T21:01:00+00:00"}
    assert progress.parse(progress.PREFIX + json.dumps(value)) == value
    for stamp in ("api_key=secret", "2026-99-07T21:01:00+00:00", [], None):
        assert progress.parse(progress.PREFIX + json.dumps(
            dict(value, refreshed_at=stamp))) is None


def test_source_progress_reports_dates_partition_and_snapshot():
    event = {"stage": "source_download", "status": "observed", "rows": 12345,
             "elapsed_ms": 50, "table": "SEP", "date_from": "2026-08-01",
             "date_to": "2026-08-19", "part": 4, "parts": 15,
             "refreshed_at": "2026-08-19T21:59:00+00:00", "snapshot_at": "2026-08-19T22:00:00+00:00"}
    assert progress.parse(progress.PREFIX + json.dumps(event)) == event
    rendered = progress.describe(event)
    assert "SEP 2026-08-01..2026-08-19 partition 4/15" in rendered
    assert "12,345 rows" in rendered and "refreshed" in rendered and "snapshot" in rendered
    for bad in [dict(event, table=[]), dict(event, date_from="api_key=secret"),
                dict(event, part=True), dict(event, parts=0), dict(event, date_to="2026-99-01")]:
        assert progress.parse(progress.PREFIX + json.dumps(bad)) is None


def test_cdc_status_reports_both_market_and_vendor_update_windows():
    event = {"stage": "source_replay", "status": "started", "rows": 0,
             "elapsed_ms": 0, "table": "SEP", "date_from": "2025-07-01",
             "date_to": "2026-09-14", "updated_from": "2026-09-12",
             "updated_to": "2026-09-15", "reason": "LOCAL_CURSOR_MISSING"}
    assert progress.parse(progress.PREFIX + json.dumps(event)) == event
    assert "updated 2026-09-12..2026-09-15" in progress.describe(event)
    for bad in (dict(event, reason="password=secret"), dict(event, updated_to=[]),
                dict(event, updated_from="2026-02-30")):
        assert progress.parse(progress.PREFIX + json.dumps(bad)) is None
