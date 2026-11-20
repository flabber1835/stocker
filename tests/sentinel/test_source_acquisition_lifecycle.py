from datetime import datetime, timezone
import hashlib

import pytest

from sentinel.feed import acquisition_work as work, archive_tables, operational_source as source, provider_budget
from sentinel.feed import snapshot_export as export
from tests.sentinel.test_bounded_operational_feed import install_source
from tests.support.table_export import _zip_tickers


def snapshot():
    stamp = datetime(2026, 8, 19, 22, tzinfo=timezone.utc)
    return export.ExportSnapshot("TICKERS", {}, "unused", stamp, stamp)


def stage(blob, root=None):
    path = (root or work.cache_root()) / (work.file_key(snapshot()) + ".zip")
    path.write_bytes(blob)
    path.with_suffix(".sha256").write_text(hashlib.sha256(blob).hexdigest())
    return path


def test_historical_archive_is_explicit_and_corrupt_bytes_are_preserved():
    with pytest.raises(archive_tables.CaptureRequired):
        export.download_snapshot(snapshot(), required={"ticker"})
    path = stage(_zip_tickers([["SEP", "1", "AAA"]]))
    before = path.read_bytes()
    rows, proof = export.download_snapshot(snapshot(), required={"ticker"})
    assert rows[0]["ticker"] == "AAA" and proof["file_sha256"] == hashlib.sha256(before).hexdigest()
    changed = _zip_tickers([["SEP", "9", "WRONG"]])
    path.write_bytes(changed)
    with pytest.raises(archive_tables.CaptureRequired):
        export.download_snapshot(snapshot(), required={"ticker"})
    assert path.read_bytes() == changed


def test_verified_capture_survives_a_new_process(tmp_path):
    import os
    import subprocess
    import sys
    root = tmp_path / "source-cache-v1"
    root.mkdir()
    stage(_zip_tickers([["SEP", "1", "AAA"]]), root)
    code = """from tests.sentinel.test_source_acquisition_lifecycle import snapshot
from sentinel.feed import snapshot_export
rows, proof = snapshot_export.download_snapshot(snapshot(), required={'ticker'})
assert rows[0]['ticker'] == 'AAA'
"""
    checked = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
        text=True, timeout=30, env={**os.environ, "SENTINEL_STATE_DIR": str(tmp_path)})
    assert checked.returncode == 0, checked.stderr


def test_pending_jobs_all_requested_then_polled_without_download(monkeypatch):
    calls = install_source(monkeypatch)
    real_probe = export.probe_snapshot
    seen = set()
    def probe(table, *, params=None):
        key = (table, str(params))
        if key not in seen:
            seen.add(key)
            calls.append(("pending", table, params))
            raise export.ExportPending(table, "creating", params)
        return real_probe(table, params=params)
    sleeps = []
    def pause(seconds):
        assert len(seen) == 3
        assert not any(c[0] == "download" for c in calls)
        sleeps.append(seconds)
    monkeypatch.setattr(export, "probe_snapshot", probe)
    monkeypatch.setattr(work, "pause", pause)
    with source.acquisition("2026-08-18", "2026-08-19", download=True) as captured:
        assert captured.loaded
    assert len(sleeps) == 1
    assert len([c for c in calls if c[0] == "download"]) == 3


def test_pending_budget_yields_availability_not_integrity_failure(monkeypatch):
    from sentinel.automation_runtime import classify_dependency_failure
    from sentinel.automation.model import TransientInfrastructureFailure
    from sentinel.shadow_worker import _availability_failure
    from sentinel.feed.alpaca_transport import AlpacaTransportUnavailable
    monkeypatch.setattr(work, "SLICE_SECONDS", 1)
    def pending(table, *, params=None):
        raise export.ExportPending(table, "regenerating", params)
    monkeypatch.setattr(export, "probe_snapshot", pending)
    with pytest.raises(export.ExportPending) as error:
        with source.acquisition("2026-08-18", "2026-08-19", download=True):
            pytest.fail("pending source cannot be consumed")
    assert not _availability_failure(error.value)
    assert _availability_failure(AlpacaTransportUnavailable("market data unavailable"))
    assert isinstance(classify_dependency_failure(error.value), TransientInfrastructureFailure)
    assert source.current() is None


def test_go_retries_fixed_target_without_remigrating_or_changing_window(monkeypatch):
    from sentinel.feed import outage_recovery
    from types import SimpleNamespace
    calls, waits, rollbacks = [], [], []
    def catch_up(conn, **kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            raise export.ExportPending("SEP", "creating", {})
        return "complete"
    monkeypatch.setattr(outage_recovery, "catch_up", catch_up)
    assert outage_recovery.catch_up_waiting(
        SimpleNamespace(rollback=lambda: rollbacks.append(True)),
        target_session="2026-08-19", sleep=waits.append) == "complete"
    assert len(rollbacks) == len(waits) == 2
    assert calls == [calls[0]] * 3


def test_go_wait_budget_never_shortens_retry_after(monkeypatch):
    from sentinel.feed import outage_recovery
    from types import SimpleNamespace
    def deferred(*args, **kwargs):
        raise archive_tables.RetryDeferred(3600)
    monkeypatch.setattr(outage_recovery, "catch_up", deferred)
    with pytest.raises(archive_tables.RetryDeferred):
        outage_recovery.catch_up_waiting(SimpleNamespace(rollback=lambda: None),
            target_session="2026-08-19", wait_seconds=60,
            sleep=lambda _: pytest.fail("must not shorten provider wait"))


def test_corroboration_and_metadata_budgets_cannot_extend_parent_deadline(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(work.time, "monotonic", lambda: clock[0])
    with work.budget(seconds=20):
        clock[0] += 10
        with work.budget(seconds=60):
            assert work.remaining() == 10
            assert provider_budget.remaining() == 10
        assert work.remaining() == 10
