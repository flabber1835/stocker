from __future__ import annotations

import http.client
import json
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base
from backtester import run_historical_metadata_web_shard_v2_resilient as resilient


def _result(url: str, data: bytes) -> base.HttpResult:
    return base.HttpResult(url, 200, "cache", base.sha256_bytes(data), len(data), 1, False, "now")


def test_incomplete_read_is_retried(monkeypatch, tmp_path: Path):
    calls = {"n": 0}

    def fake_get(self, url):
        calls["n"] += 1
        self.counters["attempts"] += 1
        if calls["n"] == 1:
            raise http.client.IncompleteRead(b"partial")
        data = b'{"ok": true}'
        self.counters["successes"] += 1
        self.counters["status_200"] += 1
        return data, _result(url, data)

    monkeypatch.setattr(base.SecHttpTransport, "get", fake_get)
    monkeypatch.setattr(resilient.time, "sleep", lambda _: None)
    client = resilient.ResilientSecHttpTransport(tmp_path, max_attempts=3)
    data, result = client.get("https://data.sec.gov/submissions/CIK0000000001.json")

    assert data == b'{"ok": true}'
    assert result.status == 200
    assert calls["n"] == 2
    assert client.counters["retries"] == 1
    assert client.counters["transport_errors"] == 1
    assert client.counters["failures"] == 0


def test_invalid_cached_json_is_discarded_and_refetched(monkeypatch, tmp_path: Path):
    calls = {"n": 0}
    url = "https://data.sec.gov/submissions/CIK0000000002.json"

    def fake_get(self, requested_url):
        calls["n"] += 1
        self.counters["attempts"] += 1
        data = b'{"broken":' if calls["n"] == 1 else b'{"fixed": true}'
        self._cache_path(requested_url).write_bytes(data)
        self.counters["successes"] += 1
        self.counters["status_200"] += 1
        return data, _result(requested_url, data)

    monkeypatch.setattr(base.SecHttpTransport, "get", fake_get)
    monkeypatch.setattr(resilient.time, "sleep", lambda _: None)
    client = resilient.ResilientSecHttpTransport(tmp_path, max_attempts=3)
    data, _ = client.get(url)

    assert json.loads(data) == {"fixed": True}
    assert calls["n"] == 2
    assert client.counters["retries"] == 1
    assert client.counters["transport_errors"] == 1
    assert client.counters["successes"] == 1
    assert client.counters["status_200"] == 1


def test_empty_200_body_is_retried(monkeypatch, tmp_path: Path):
    calls = {"n": 0}

    def fake_get(self, url):
        calls["n"] += 1
        self.counters["attempts"] += 1
        data = b"" if calls["n"] == 1 else b"filing"
        self.counters["successes"] += 1
        self.counters["status_200"] += 1
        return data, _result(url, data)

    monkeypatch.setattr(base.SecHttpTransport, "get", fake_get)
    monkeypatch.setattr(resilient.time, "sleep", lambda _: None)
    client = resilient.ResilientSecHttpTransport(tmp_path, max_attempts=3)
    data, _ = client.get("https://www.sec.gov/Archives/edgar/data/1/a.txt")

    assert data == b"filing"
    assert calls["n"] == 2
    assert client.counters["retries"] == 1


def test_live_progress_writes_step_summary_and_annotation(monkeypatch, tmp_path: Path, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    original_print = resilient.builtins.print
    try:
        resilient._install_live_github_progress()
        print("[PROGRESS] shard=07 ciks=50/100 pct=50.0% http_attempts=300 successes=299 retries=1 failures=0")
    finally:
        resilient.builtins.print = original_print

    text = summary.read_text(encoding="utf-8")
    assert "Shard 07: 50.0% (50/100 CIKs)" in text
    captured = capsys.readouterr().out
    assert "::notice title=SEC metadata live progress::Shard 07: 50.0%" in captured
