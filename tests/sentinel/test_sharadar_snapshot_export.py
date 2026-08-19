from __future__ import annotations

import io
import zipfile

import pytest

from sentinel.feed import snapshot_export


class _Response:
    def __init__(self, *, status=200, payload=None, content=b"", headers=None):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            exc = RuntimeError(f"HTTP {self.status_code}")
            exc.response = self
            raise exc


def _zip_csv(name: str, header: str, rows: list[list[str]]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        body = header + "\n" + "\n".join(",".join(row) for row in rows) + "\n"
        archive.writestr(name, body)
    return out.getvalue()


def _zip_actions(rows: list[list[str]]) -> bytes:
    return _zip_csv(
        "SHARADAR_ACTIONS.csv",
        "date,action,ticker,name,value,contraticker,contraname", rows)


def _zip_tickers(rows: list[list[str]]) -> bytes:
    return _zip_csv("SHARADAR_TICKERS.csv", "table,permaticker,ticker", rows)


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)


class _Http:
    class TimeoutException(Exception):
        pass

    class TransportError(Exception):
        pass

    def __init__(self, responses):
        self.client = _Client(responses)

    def Client(self, timeout=None):
        return self.client


def _status(*, state="fresh", link="https://example.com/snapshot.zip?api_key=secret",
            snapshot="2026-08-19T22:00:00Z",
            refreshed="2026-08-19T21:59:00Z"):
    return {
        "datatable_bulk_download": {
            "file": {
                "link": link,
                "status": state,
                "data_snapshot_time": snapshot,
            },
            "datatable": {"last_refreshed_time": refreshed},
        }
    }


def test_complete_actions_accepts_fresh_snapshot_after_latest_refresh(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit-test-key")
    blob = _zip_actions([
        ["2026-08-18", "dividend", "AAA", "AAA INC", "0.25", "", ""],
        ["2026-08-18", "split", "BBB", "BBB INC", "2", "", ""],
    ])
    http = _Http([
        _Response(payload=_status()),
        _Response(content=blob),
    ])
    rows, evidence = snapshot_export.fetch_complete_actions(
        through="2026-08-19", http=http, sleep=lambda _n: None,
        max_polls=1)
    assert len(rows) == 2
    assert rows[0]["ticker"] == "AAA"
    assert rows[0]["contraticker"] is None
    assert evidence["authority"] == "nasdaq-data-link-table-export/v1"
    assert evidence["source_rows"] == 2
    assert "link" not in evidence


def test_official_utc_timestamp_spelling_is_accepted():
    assert snapshot_export._aware_iso(
        "2026-08-19 22:00:00 UTC", field="snapshot").isoformat() == \
        "2026-08-19T22:00:00+00:00"


def test_complete_actions_waits_for_vendor_generated_fresh_file(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit-test-key")
    sleeps = []
    blob = _zip_actions([
        ["2026-08-18", "delisted", "AAA", "AAA INC", "", "", ""],
    ])
    http = _Http([
        _Response(payload=_status(state="creating", link=None)),
        _Response(payload=_status(state="fresh")),
        _Response(content=blob),
    ])
    rows, _evidence = snapshot_export.fetch_complete_actions(
        through="2026-08-19", http=http, sleep=sleeps.append,
        poll_seconds=3, max_polls=2)
    assert len(rows) == 1
    assert sleeps == [3]


def test_fresh_snapshot_older_than_table_refresh_is_refused(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit-test-key")
    http = _Http([
        _Response(payload=_status(
            snapshot="2026-08-19T21:58:00Z",
            refreshed="2026-08-19T21:59:00Z")),
    ])
    with pytest.raises(snapshot_export.SharadarSnapshotExportError,
                       match="before the table's last refresh"):
        snapshot_export.fetch_complete_actions(
            through="2026-08-19", http=http, sleep=lambda _n: None,
            max_polls=1)


def test_export_csv_schema_and_zip_are_fail_closed(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit-test-key")
    bad_zip = io.BytesIO()
    with zipfile.ZipFile(bad_zip, "w") as archive:
        archive.writestr("bad.csv", "date,action,ticker\n2026-08-18,dividend,AAA\n")
    http = _Http([
        _Response(payload=_status()),
        _Response(content=bad_zip.getvalue()),
    ])
    with pytest.raises(snapshot_export.SharadarSnapshotExportError,
                       match="lacks required column"):
        snapshot_export.fetch_complete_actions(
            through="2026-08-19", http=http, sleep=lambda _n: None,
            max_polls=1)


def test_non_https_export_link_is_refused_without_rendering_secret(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit-test-key")
    http = _Http([
        _Response(payload=_status(
            link="http://example.com/snapshot.zip?api_key=do-not-print")),
    ])
    with pytest.raises(snapshot_export.SharadarSnapshotExportError) as caught:
        snapshot_export.fetch_complete_actions(
            through="2026-08-19", http=http, sleep=lambda _n: None,
            max_polls=1)
    assert "do-not-print" not in str(caught.value)


def test_complete_ticker_export_returns_only_sep_identity_keys(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit-test-key")
    http = _Http([
        _Response(payload=_status()),
        _Response(content=_zip_tickers([
            ["SEP", "P1", "AAA"],
            ["SEP", "P2", "BBB"],
            ["SF1", "P1", "AAA"],
        ])),
    ])
    keys, evidence = snapshot_export.fetch_complete_ticker_keys(
        http=http, sleep=lambda _n: None, max_polls=1)
    assert keys == {("P1", "AAA"), ("P2", "BBB")}
    assert evidence["sep_identity_keys"] == 2


def test_paginated_ticker_keyset_must_exactly_match_fresh_export():
    rows = [
        {"table": "SEP", "permaticker": "P1", "ticker": "AAA"},
    ]
    with pytest.raises(snapshot_export.SharadarSnapshotExportError,
                       match="missing_from_pages"):
        snapshot_export.assert_complete_ticker_keys(
            rows, {("P1", "AAA"), ("P2", "BBB")})

    snapshot_export.assert_complete_ticker_keys(rows, {("P1", "AAA")})
