from __future__ import annotations

import pytest

from sentinel.feed import sharadar, snapshot_export


class _Response:
    status_code = 200
    headers = {}
    content = b"zip-bytes"

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self):
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return _Response()


class _Http:
    class TimeoutException(Exception):
        pass

    class TransportError(Exception):
        pass


def test_explicit_insecure_test_base_allows_same_origin_export(monkeypatch):
    monkeypatch.setattr(
        sharadar, "NDL_BASE",
        "http://172.18.0.1:18080/api/v3/datatables/SHARADAR")
    monkeypatch.setattr(sharadar, "ALLOW_INSECURE_BASE_URL", True)
    client = _Client()

    body = snapshot_export._safe_download(
        client,
        "http://172.18.0.1:18080/exports/TICKERS.zip?token=secret",
        http=_Http, sleep=lambda _seconds: None, now=None)

    assert body == b"zip-bytes"
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "link",
    (
        "http://172.18.0.2:18080/exports/TICKERS.zip",
        "http://172.18.0.1:18081/exports/TICKERS.zip",
    ),
)
def test_insecure_export_must_match_configured_provider_origin(monkeypatch, link):
    monkeypatch.setattr(
        sharadar, "NDL_BASE",
        "http://172.18.0.1:18080/api/v3/datatables/SHARADAR")
    monkeypatch.setattr(sharadar, "ALLOW_INSECURE_BASE_URL", True)
    client = _Client()

    with pytest.raises(
            snapshot_export.SharadarSnapshotExportError,
            match="non-HTTPS"):
        snapshot_export._safe_download(
            client, link, http=_Http, sleep=lambda _seconds: None, now=None)

    assert client.calls == []


def test_http_export_remains_refused_when_test_flag_is_off(monkeypatch):
    monkeypatch.setattr(
        sharadar, "NDL_BASE",
        "http://172.18.0.1:18080/api/v3/datatables/SHARADAR")
    monkeypatch.setattr(sharadar, "ALLOW_INSECURE_BASE_URL", False)
    client = _Client()

    with pytest.raises(
            snapshot_export.SharadarSnapshotExportError,
            match="non-HTTPS"):
        snapshot_export._safe_download(
            client,
            "http://172.18.0.1:18080/exports/TICKERS.zip",
            http=_Http, sleep=lambda _seconds: None, now=None)

    assert client.calls == []
