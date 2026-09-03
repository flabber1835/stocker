from __future__ import annotations

import http.client
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as v2
from backtester.sec_http_transport_resilient_v4 import ResilientSecHttpTransport


def test_retries_incomplete_read_without_accepting_partial_bytes(tmp_path: Path):
    original = v2.SecHttpTransport.get
    calls = {"count": 0}

    def flaky(self, url):
        calls["count"] += 1
        if calls["count"] < 3:
            raise http.client.IncompleteRead(b"partial")
        data = b"complete-authoritative-source"
        return data, v2.HttpResult(url, 200, "cache", v2.sha256_bytes(data), len(data), 1, False, "2026-09-03T00:00:00Z")

    v2.SecHttpTransport.get = flaky
    try:
        transport = ResilientSecHttpTransport(tmp_path, min_interval=0.0, max_attempts=5)
        data, result = transport.get("https://www.sec.gov/example")
    finally:
        v2.SecHttpTransport.get = original

    assert data == b"complete-authoritative-source"
    assert result.status == 200
    assert calls["count"] == 3
    assert transport.counters["http_protocol_errors"] == 2
    assert transport.counters["http_protocol_retries"] == 2
    assert transport.counters["failures"] == 0


def test_fails_closed_after_protocol_retry_budget(tmp_path: Path):
    original = v2.SecHttpTransport.get

    def always_truncated(self, url):
        raise http.client.IncompleteRead(b"partial")

    v2.SecHttpTransport.get = always_truncated
    try:
        transport = ResilientSecHttpTransport(tmp_path, min_interval=0.0, max_attempts=2)
        try:
            transport.get("https://www.sec.gov/example")
        except v2.ReconstructionError as exc:
            assert "protocol retries" in str(exc)
        else:
            raise AssertionError("truncated body was accepted")
    finally:
        v2.SecHttpTransport.get = original

    assert transport.counters["http_protocol_errors"] == 2
    assert transport.counters["http_protocol_retries"] == 1
    assert transport.counters["failures"] == 1
