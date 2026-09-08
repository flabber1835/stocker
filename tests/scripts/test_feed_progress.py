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
