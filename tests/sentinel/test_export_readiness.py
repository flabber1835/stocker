"""Small provider schedules exercise the production preflight sweep."""
from datetime import datetime, timezone

import pytest

from sentinel.feed import export_readiness as exports, snapshot_export as source
from sentinel.feed import rolling_source, authority, sharadar
from sentinel.feed.rolling_contract import FormationWindow


@pytest.mark.parametrize("pending", [{0}, {1}, {0, 2}, set()])
def test_all_exports_requested_before_pending_is_returned(monkeypatch, capsys, pending):
    requests = [("ACTIONS", {}), ("TICKERS", {}), ("SEP", {"date.gte": "2025-03-25"})]
    calls = []
    def probe(table, *, params):
        index = len(calls)
        calls.append((table, params))
        if index in pending:
            raise source.ExportPending(table, "creating", params)
        return table
    monkeypatch.setattr(source, "probe_snapshot", probe)
    if pending:
        with pytest.raises(source.ExportPending):
            exports.probe_all(requests)
        from scripts.sentinel_go_feed_progress import collect
        events = collect(capsys.readouterr().err)
        assert events[-1]["ready"] == 3 - len(pending)
        assert events[-1]["parts"] == 3
    else:
        assert exports.probe_all(requests) == ["ACTIONS", "TICKERS", "SEP"]
    assert calls == requests


@pytest.mark.parametrize("error", [ValueError("bad response"),
                                  sharadar.SharadarRetryDeferred(90, 429)])
def test_fatal_or_throttled_request_stops_sweep(monkeypatch, error):
    calls = []
    def probe(table, *, params):
        calls.append(table)
        raise error
    monkeypatch.setattr(source, "probe_snapshot", probe)
    with pytest.raises(type(error)):
        exports.probe_all([("ACTIONS", {}), ("TICKERS", {})])
    assert calls == ["ACTIONS"]


def test_formation_preflight_requests_all_months_and_rejects_mixed_refresh(monkeypatch):
    window = FormationWindow.through("2026-09-25")
    monkeypatch.setattr(rolling_source.calendar, "latest_closed_session", lambda: str(window.end))
    capture = rolling_source.SharadarSource(window)
    calls = []
    pending = True
    def probe(table, *, params):
        calls.append((table, params))
        if pending:
            raise source.ExportPending(table, "creating", params)
        day = 26 if table != "SEP" or params["date.gte"] == str(window.start) else 27
        stamp = datetime(2026, 9, day, tzinfo=timezone.utc)
        return source.ExportSnapshot(table, params, "private", stamp, stamp)
    monkeypatch.setattr(source, "probe_snapshot", probe)
    with pytest.raises(source.ExportPending):
        capture.preflight()
    assert calls[0][0] == "ACTIONS" and calls[1][0] == "TICKERS"
    assert calls[2][1]["date.gte"] == str(window.start)
    assert calls[-1][1]["date.lte"] == str(window.end)
    assert len(calls) == 21
    pending = False
    with pytest.raises(authority.VendorPublicationUnstable, match="refresh"):
        capture.preflight()
