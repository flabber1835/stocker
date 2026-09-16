from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
from types import SimpleNamespace

import pytest

from sentinel.feed import (
    operational_source as source, snapshot_export as export, sharadar,
    authority, publication, ingest, outage_recovery, maintenance_impl,
)
from tests.sentinel.test_sharadar_snapshot_export import _Http, _Response, _status


def install_source(monkeypatch, *, changed=False):
    calls = []
    refresh = datetime(2026, 8, 19, 22, tzinfo=timezone.utc)
    def probe(table, *, params=None):
        calls.append(("probe", table, dict(params or {})))
        stamp = refresh + (timedelta(seconds=1) if changed and any(c[0] == "download" for c in calls) else timedelta())
        return export.ExportSnapshot(table, dict(params or {}), "https://unit.invalid/file", stamp, stamp)
    def download(snapshot, *, required):
        calls.append(("download", snapshot.table, snapshot.params))
        if snapshot.table == sharadar.SEP:
            day = source.calendar.sessions_in_range(snapshot.params["date.gte"], snapshot.params["date.lte"])[-1]
            rows = [{"date": day, "ticker": "TEST", "lastupdated": "2026-08-19",
                     "open": "10", "close": "10", "closeunadj": "10", "volume": "100"}]
        elif snapshot.table == sharadar.ACTIONS:
            rows = [{"date": "2000-01-03", "action": "renamefrom", "ticker": "TEST", "name": "Test",
                     "value": "0", "contraticker": "OLD", "contraname": "Old"}]
        else:
            rows = [{"table": "SEP", "ticker": "TEST", "permaticker": "1"}]
        return rows, {"authority": "nasdaq-data-link-table-export/v1", "table": snapshot.table,
                      "file_status": "fresh", "last_refreshed_time": refresh.isoformat(),
                      "data_snapshot_time": refresh.isoformat(), "file_sha256": "a" * 64,
                      "source_rows": len(rows), "window": snapshot.params}
    monkeypatch.setattr(export, "probe_snapshot", probe)
    monkeypatch.setattr(export, "download_snapshot", download)
    return calls


def test_window_is_exactly_300_sessions_and_requirement_is_independent():
    start, end = source.price_window("2026-09-14")
    sessions = source.calendar.sessions_in_range(start, end)
    assert len(sessions) == 300
    assert sessions[-1] == "2026-09-14"


def test_capture_predecessors_resolve_renames_and_reused_tickers_at_source_date():
    capture = source.OperationalCapture("2026-08-18", "2026-08-20")
    try:
        capture.loaded = True
        rows = [dict(ticker="REUSE", date="2026-08-18", close="5", closeunadj="10"),
                dict(ticker="REUSE", date="2026-08-19", close="20", closeunadj="20"),
                dict(ticker="RENAMED", date="2026-08-20", close="6", closeunadj="12")]
        capture.db.executemany("INSERT INTO source VALUES (?,?,?,?,?,?)", [
            (sharadar.SEP, r["date"], "", r["ticker"], "", json.dumps(r)) for r in reversed(rows)])

        def resolve(ticker, day):
            return "OLD-ID" if ticker == "RENAMED" or day == "2026-08-18" else "NEW-ID"

        assert capture.previous_observations("2026-08-20", resolve_identity=resolve) == {
            "OLD-ID": (5.0, 10.0), "NEW-ID": (20.0, 20.0)}
        assert capture.previous_observations(capture.start, resolve_identity=resolve) == {}
    finally:
        capture.close()


def test_same_capture_predecessor_does_not_hide_real_split_disagreement():
    from sentinel.feed import actions_map, domains
    capture = source.OperationalCapture("2026-08-18", "2026-08-19")
    try:
        capture.loaded = True
        prior = dict(ticker="AAA", date=capture.start, close="50", closeunadj="100")
        capture.db.execute("INSERT INTO source VALUES (?,?,?,?,?,?)",
                           (sharadar.SEP, capture.start, "", "AAA", "", json.dumps(prior)))
        report = domains.NormalisationReport()
        row = dict(ticker="AAA", date=capture.end, close="50", closeunadj="50", open="50", volume="100")
        bars = list(domains.normalise_sep_rows([row], report=report,
            resolve_identity=lambda *args: "SID",
            prior_observations=capture.previous_observations(capture.end, resolve_identity=lambda *args: "SID"),
            authoritative_splits={("AAA", capture.end): 3}))
        assert bars[0].vendor.split_ratio == 1
        assert report.split_dispositions[("AAA", capture.end)]["disposition"] == actions_map.SPLIT_UNRESOLVED
        assert report.derived_splits_unsnapped[("AAA", capture.end)] == 2
    finally:
        capture.close()


def test_larger_startup_requirement_refuses(monkeypatch):
    from sentinel.feed import operational_coherence
    monkeypatch.setattr(operational_coherence, "OPERATIONAL_HISTORY_SESSIONS", 301)
    with pytest.raises(source.OperationalAcquisitionRefused, match="startup requires"):
        source.price_window("2026-09-14")


@pytest.mark.parametrize("status", ["creating", "regenerating"])
def test_diagnostic_probe_reports_pending_without_polling_or_download(monkeypatch, status):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit-key")
    http = _Http([_Response(payload=_status(state=status))])
    with pytest.raises(export.ExportPending, match="status=" + status):
        export.probe_snapshot(sharadar.SEP, params=sharadar.date_params("2026-08-18", "2026-08-19"),
                              http=http, sleep=lambda *a: pytest.fail("export probe cannot poll"))
    assert len(http.client.calls) == 1


def test_bounded_recovery_includes_stable_local_key_and_value_drift():
    for failure in (outage_recovery.sep_reconciliation.SepKeysetDrift,
                    outage_recovery.sep_reconciliation.SepValueDrift):
        assert failure in outage_recovery._RECOVERABLE_LOCAL_STATE


@pytest.mark.parametrize("table", [sharadar.ACTIONS, sharadar.TICKERS, sharadar.SEP])
def test_preflight_refuses_before_any_file_download(monkeypatch, table):
    calls = install_source(monkeypatch)
    original = export.probe_snapshot
    def unavailable(selected, **kwargs):
        if selected == table:
            raise export.SharadarSnapshotExportError("status=creating")
        return original(selected, **kwargs)
    monkeypatch.setattr(export, "probe_snapshot", unavailable)
    with pytest.raises(export.SharadarSnapshotExportError, match="creating"):
        with source.acquisition("2026-08-18", "2026-08-19"):
            pytest.fail("acquisition must refuse")
    assert not any(c[0] == "download" for c in calls)
    assert source.current() is None


def test_repeated_sep_and_cdc_proofs_download_once(monkeypatch):
    calls = install_source(monkeypatch)
    monkeypatch.setattr(sharadar.DEFAULT_SOURCE, "fetch_table",
                        lambda *a, **k: pytest.fail("no paginated fallback"))
    with source.acquisition("2026-08-18", "2026-08-19") as capture:
        params = sharadar.date_params(capture.start, capture.end)
        first = list(sharadar.fetch_table(sharadar.SEP, params))
        first[0]["close"] = "99"
        second = list(sharadar.fetch_table(sharadar.SEP, params))
        assert second[0]["close"] == "10"
        assert list(sharadar.fetch_table(sharadar.SEP, {"lastupdated.gte": "2026-08-19", "lastupdated.lte": "2026-08-19"})) == second
        rows, evidence = export.fetch_complete_sep(start="2026-08-19", end="2026-08-19")
        assert rows == second
        assert evidence["file_sha256"] == "a" * 64
        assert list(sharadar.fetch_table(sharadar.ACTIONS, {"date.gte": "1900-01-01", "date.lte": capture.end}))[0]["date"] == "2000-01-03"
        assert len(list(sharadar.fetch_table(sharadar.ACTIONS, {"action": "renamefrom,rename"}))) == 1
        assert not list(sharadar.fetch_table(sharadar.ACTIONS, {"action": "split"}))
        capture.corroborate()
    assert len([c for c in calls if c[:2] == ("download", "SEP")]) == 1
    assert source.current() is None


def test_changed_generation_refuses_capture_and_closes_resources(monkeypatch):
    install_source(monkeypatch, changed=True)
    with pytest.raises(authority.VendorPublicationUnstable, match="refresh changed"):
        with source.acquisition("2026-08-18", "2026-08-19") as capture:
            capture.acquire()
    assert source.current() is None


def test_monthly_exports_are_each_downloaded_once_across_all_replays(monkeypatch):
    calls = install_source(monkeypatch)
    original = export.download_snapshot
    def partition(snapshot, **kwargs):
        rows, evidence = original(snapshot, **kwargs)
        if snapshot.table == sharadar.SEP:
            rows[0]["date"] = source.calendar.sessions_in_range(
                snapshot.params["date.gte"], snapshot.params["date.lte"])[0]
        return rows, evidence
    monkeypatch.setattr(export, "download_snapshot", partition)
    start, end = source.price_window("2026-09-14")
    with source.acquisition(start, end) as capture:
        first = list(sharadar.fetch_table(sharadar.SEP, sharadar.date_params(start, end)))
        assert list(sharadar.fetch_table(sharadar.SEP, sharadar.date_params(start, end))) == first
        recent, evidence = export.fetch_complete_sep(start="2026-08-01", end=end)
        assert recent and all("2026-08-01" <= r["date"] <= end for r in recent)
        assert len(capture.evidence) == len(capture.snapshots)
        assert evidence["parts"]
    downloads = [c for c in calls if c[:2] == ("download", sharadar.SEP)]
    assert len(downloads) == len(list(source._months(start, end)))
    assert all(start <= c[2]["date.gte"] <= c[2]["date.lte"] <= end for c in downloads)


def test_mixed_sep_partition_refresh_refuses_before_download(monkeypatch):
    calls = install_source(monkeypatch)
    original = export.probe_snapshot
    def mixed(table, *, params=None):
        result = original(table, params=params)
        if table == sharadar.SEP and params["date.gte"].startswith("2026-09"):
            result = export.ExportSnapshot(table, result.params, result.link,
                                           result.snapshot + timedelta(seconds=1),
                                           result.refreshed + timedelta(seconds=1))
        return result
    monkeypatch.setattr(export, "probe_snapshot", mixed)
    with pytest.raises(authority.VendorPublicationUnstable, match="crossed a table refresh"):
        with source.acquisition("2026-08-18", "2026-09-14"):
            pytest.fail("mixed generation cannot acquire")
    assert not any(c[0] == "download" for c in calls)


def test_outside_window_refuses_before_acquisition(monkeypatch):
    calls = install_source(monkeypatch)
    with source.acquisition("2026-08-18", "2026-08-19") as capture:
        with pytest.raises(source.OperationalAcquisitionRefused, match="allowed"):
            list(capture.fetch_rows(sharadar.SEP, {"date.gte": "2006-01-01", "date.lte": capture.end}))
    assert not any(c[0] == "download" for c in calls)


def test_source_partitions_never_cross_price_cap():
    start, end = source.price_window("2026-09-14")
    partitions = list(source._months(start, end))
    assert partitions[0][0] == start and partitions[-1][1] == end
    assert sum(len(source.calendar.sessions_in_range(lo, hi)) for lo, hi in partitions) == 300


def test_direct_capture_cannot_bypass_300_session_cap():
    sessions = source.calendar.previous_sessions("2026-09-14", 301)
    with pytest.raises(source.OperationalAcquisitionRefused, match="1..300"):
        source.OperationalCapture(sessions[0], sessions[-1])


def test_non_session_source_row_refuses_before_private_staging(monkeypatch):
    install_source(monkeypatch)
    original = export.download_snapshot
    def weekend(snapshot, **kwargs):
        rows, evidence = original(snapshot, **kwargs)
        if snapshot.table == sharadar.SEP:
            rows[0]["date"] = "2026-08-22"
        return rows, evidence
    monkeypatch.setattr(export, "download_snapshot", weekend)
    from sentinel.feed.session_envelope import SourceSessionEnvelopeViolation
    with source.acquisition("2026-08-18", "2026-08-24") as capture:
        with pytest.raises(SourceSessionEnvelopeViolation):
            capture.acquire()
        assert capture.db.execute("SELECT count(*) FROM source WHERE table_code='SEP'").fetchone()[0] == 0


def test_daily_wrapper_keeps_injected_sources_offline(monkeypatch):
    calls = []
    fetch = lambda *a, **k: []
    monkeypatch.setattr(ingest, "_daily", lambda *a, **k: calls.append(k) or "done")
    assert ingest.daily(object(), fetch=fetch, today="2026-09-14") == "done"
    assert calls[0]["fetch"] is fetch


def test_production_daily_establishes_a_bounded_capture(monkeypatch):
    install_source(monkeypatch)
    monkeypatch.setattr(publication, "operational_boundary",
                        lambda *a, **k: SimpleNamespace(start="2026-01-01"))
    monkeypatch.setattr(ingest, "_daily", lambda *a, **k: (source.current().start, source.current().end))
    assert ingest.daily(object(), today="2026-09-14") == source.price_window("2026-09-14")
    assert source.current() is None


@pytest.mark.parametrize("visible", [None, "2006-01-03"])
def test_cold_or_expired_feed_uses_bounded_seed_without_daily(monkeypatch, visible):
    from contextlib import nullcontext
    seeded = []
    monkeypatch.setattr(source, "acquisition", lambda *a, **k: nullcontext())
    monkeypatch.setattr(outage_recovery.store, "latest_visible_session",
                        lambda c: "2026-09-14" if seeded else visible)
    monkeypatch.setattr(publication, "operational_boundary", lambda *a, **k: SimpleNamespace(start="2026-01-01"))
    monkeypatch.setattr(publication, "assert_operationally_coherent", lambda *a, **k: None)
    monkeypatch.setattr(publication, "chain_gaps", lambda *a: [])
    monkeypatch.setattr(outage_recovery.backup_guard, "require_writes_permitted", lambda *a, **k: None)
    monkeypatch.setattr(outage_recovery.backup_guard, "require_bulk_writes_permitted", lambda *a, **k: None)
    monkeypatch.setattr(ingest, "seed", lambda *a, **k: seeded.append(k))
    monkeypatch.setattr(ingest, "daily", lambda *a, **k: pytest.fail("out-of-window daily download"))
    result = outage_recovery.catch_up(object(), target_session="2026-09-14")
    start, end = source.price_window(result.target_session)
    assert seeded == [{"date_from": start, "date_to": end}]
    assert result.mode == ("BOUNDED_INITIAL_SEED" if visible is None else "BOUNDED_RESEED")


def test_daily_uses_existing_capture_and_maintenance_bounds(monkeypatch):
    install_source(monkeypatch)
    monkeypatch.setattr(ingest, "_daily", lambda *a, **k: source.current())
    with source.acquisition("2026-08-18", "2026-08-19") as capture:
        assert ingest.daily(object(), today=capture.end) is capture
        assert maintenance_impl._retained_market_bounds(object()) == (capture.start, capture.end)


def test_old_persisted_cursor_refuses_before_source_contact(monkeypatch):
    monkeypatch.setattr(outage_recovery.store, "latest_visible_session", lambda c: "2026-08-19")
    monkeypatch.setattr(outage_recovery.backup_guard, "require_writes_permitted", lambda *a, **k: None)
    monkeypatch.setattr(publication, "operational_boundary", lambda *a, **k: SimpleNamespace(start="2006-01-03"))
    monkeypatch.setattr(export, "probe_snapshot", lambda *a, **k: pytest.fail("source contact before cursor refusal"))
    with pytest.raises(source.OperationalAcquisitionRefused, match="2006-01-03"):
        outage_recovery.catch_up(object(), target_session="2026-09-14")
