from datetime import datetime, timezone

import pytest

from sentinel.feed import acquisition_work as work, operational_source as source
from sentinel.feed import snapshot_export as export, sharadar
from tests.sentinel.test_bounded_operational_feed import install_source
from tests.sentinel.test_sharadar_snapshot_export import _Http, _Response, _status, _zip_tickers


def snapshot():
    stamp = datetime(2026, 8, 19, 22, tzinfo=timezone.utc)
    return export.ExportSnapshot("TICKERS", {}, "https://unit.invalid/expired", stamp, stamp)


def fresh(**kwargs):
    return _Response(payload=_status(refreshed="2026-08-19T22:00:00Z", **kwargs))


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
    from sentinel.shadow_worker import _sharadar_availability
    monkeypatch.setattr(work, "SLICE_SECONDS", 1)
    def pending(table, *, params=None):
        raise export.ExportPending(table, "regenerating", params)
    monkeypatch.setattr(export, "probe_snapshot", pending)
    with pytest.raises(export.ExportPending) as error:
        with source.acquisition("2026-08-18", "2026-08-19", download=True):
            pytest.fail("pending source cannot be consumed")
    assert _sharadar_availability(error.value)
    assert isinstance(classify_dependency_failure(error.value), TransientInfrastructureFailure)
    assert source.current() is None


def test_download_renews_expired_link_and_restart_reuses_verified_bytes(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit")
    blob = _zip_tickers([["SEP", "1", "AAA"]])
    http = _Http([fresh(), _Response(status=403), fresh(), _Response(content=blob)])
    rows, evidence = export.download_snapshot(snapshot(), required={"ticker"}, http=http)
    assert len(http.client.calls) == 4
    offline = _Http([])
    again, proof = export.download_snapshot(snapshot(), required={"ticker"}, http=offline)
    assert again == rows and proof == evidence
    assert not offline.client.calls
    assert "api_key" not in str(list(work.cache_root().iterdir()))
    assert "link" not in proof


def test_corrupt_cache_redownloads_instead_of_replaying(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit")
    blob = _zip_tickers([["SEP", "1", "AAA"]])
    first = _Http([fresh(), _Response(content=blob)])
    export.download_snapshot(snapshot(), required={"ticker"}, http=first)
    path = next(work.cache_root().glob("*.zip"))
    path.write_bytes(b"corrupt")
    retry = _Http([fresh(), _Response(content=blob)])
    rows, _ = export.download_snapshot(snapshot(), required={"ticker"}, http=retry)
    assert rows[0]["ticker"] == "AAA" and len(retry.client.calls) == 2


def test_link_renewal_may_not_switch_generation(monkeypatch):
    from sentinel.feed.authority import VendorPublicationUnstable
    monkeypatch.setenv("SHARADAR_API_KEY", "unit")
    http = _Http([_Response(payload=_status(snapshot="2026-08-20T22:00:00Z",
                                           refreshed="2026-08-20T22:00:00Z")),
                  _Response(content=_zip_tickers([["SEP", "1", "AAA"]]))])
    with pytest.raises(VendorPublicationUnstable):
        export.download_snapshot(snapshot(), required={"ticker"}, http=http)
    assert len(http.client.calls) == 1 and not list(work.cache_root().glob("*.zip"))


def test_retry_after_survives_restart_and_classification(monkeypatch):
    from sentinel.automation_runtime import classify_dependency_failure
    with pytest.raises(sharadar.SharadarRetryDeferred) as error:
        sharadar.retry_delay(0, 429, "3600")
    mapped = classify_dependency_failure(error.value)
    assert mapped.retry_after_seconds == 3600
    with pytest.raises(sharadar.SharadarRetryDeferred) as cooldown:
        work.check_cooldown()
    assert 3590 < cooldown.value.delay <= 3600


def test_http_backoff_cannot_overrun_acquisition_slice(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit")
    monkeypatch.setattr(work, "SLICE_SECONDS", 1)
    http = _Http([_Response(status=503, headers={"Retry-After": "50"})])
    with work.budget(), pytest.raises(sharadar.SharadarRetryDeferred):
        export.probe_snapshot("SEP", http=http,
                              sleep=lambda _: pytest.fail("deadline must yield before sleeping"))
    assert len(http.client.calls) == 1


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
        raise sharadar.SharadarRetryDeferred(3600)
    monkeypatch.setattr(outage_recovery, "catch_up", deferred)
    with pytest.raises(sharadar.SharadarRetryDeferred):
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
            assert work.request_options()["timeout"] == 10
        assert work.remaining() == 10


def test_snapshot_transport_exhaustion_remains_shadow_availability(monkeypatch):
    from sentinel.shadow_worker import _sharadar_availability
    monkeypatch.setattr(sharadar, "FETCH_MAX_RETRIES", 1)
    http = _Http([_Response(status=503)])
    with pytest.raises(sharadar.SharadarRequestError) as failure:
        export._safe_download(http.client, "https://unit.invalid/file", http=http,
                              sleep=lambda _: None, now=None)
    assert _sharadar_availability(failure.value)


def test_expired_export_url_is_renewed_without_changing_provider_generation():
    import httpx
    from research.sharadar_replay.provider import Provider
    from research.sharadar_replay.scenarios import FIRST, step
    clock = [0.0]
    provider = Provider(clock=lambda: clock[0], link_lifetime=1800)
    provider.advance(step("expiry", FIRST))
    request = httpx.Request("GET", sharadar.NDL_BASE + "/SEP.json", params={"qopts.export": "true"})
    first = provider(request).json()["datatable_bulk_download"]
    clock[0] = 1801
    assert provider(httpx.Request("GET", first["file"]["link"])).status_code == 403
    second = provider(request).json()["datatable_bulk_download"]
    assert second["file"]["link"] != first["file"]["link"]
    assert second["datatable"] == first["datatable"]
    assert provider(httpx.Request("GET", second["file"]["link"])).status_code == 200


def test_completed_download_survives_a_new_process(monkeypatch, tmp_path):
    import os
    import subprocess
    import sys
    root = tmp_path / "source-cache-v1"
    root.mkdir()
    monkeypatch.setattr(work, "cache_root", lambda: root)
    monkeypatch.setenv("SHARADAR_API_KEY", "unit")
    export.download_snapshot(snapshot(), required={"ticker"},
        http=_Http([fresh(), _Response(content=_zip_tickers([["SEP", "1", "AAA"]]))]))
    code = """
from tests.sentinel.test_source_acquisition_lifecycle import snapshot
from tests.sentinel.test_sharadar_snapshot_export import _Http
from sentinel.feed import snapshot_export
rows, proof = snapshot_export.download_snapshot(snapshot(), required={'ticker'}, http=_Http([]))
assert rows[0]['ticker'] == 'AAA'
print('verified cache reused without network')
"""
    completed = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
        text=True, timeout=30, env={**os.environ, "SENTINEL_STATE_DIR": str(tmp_path)})
    assert completed.returncode == 0, completed.stderr
    assert "verified cache reused without network" in completed.stdout
