from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_source_membership_probe as probe


def test_probe_get_filters_and_pagination_exclude_unreviewed_output_fields():
    calls = []

    class Source:
        def open(self, url, *, timeout):
            calls.append((urlsplit(url), timeout))
            return io.BytesIO(json.dumps({
                "datatable": {"columns": [{"name": "ticker"}, {"name": "private"}],
                              "data": [["CYCN", "not-an-output-field"]]},
                "meta": {"next_cursor_id": "page2" if len(calls) == 1 else None},
            }).encode())

    result = probe.fetch_rows("SEP", {"ticker": "CYCN,KRSA", "date.gte": "2026-09-01",
                                      "date.lte": "2026-09-11"}, "secret", opener=Source())
    assert len(result["rows"]) == len(result["page_sha256"]) == 2
    assert "private" not in result["rows"][0]
    for url, timeout in calls:
        assert url.scheme == "https" and url.hostname == "data.nasdaq.com"
        assert url.path == "/api/v3/datatables/SHARADAR/SEP.json"
        assert parse_qs(url.query)["date.gte"] == ["2026-09-01"]
        assert parse_qs(url.query)["ticker"] == ["CYCN,KRSA"]
        assert timeout == 30
    assert parse_qs(calls[-1][0].query)["qopts.cursor_id"] == ["page2"]


@pytest.mark.parametrize("failure", ["network", "oversize", "pagination"])
def test_probe_is_bounded_and_does_not_expose_credentials(monkeypatch, failure):
    monkeypatch.setattr(probe, "MAX_BYTES", 500)

    class Source:
        def open(self, url, *, timeout):
            if failure == "network":
                raise RuntimeError(url)
            if failure == "oversize":
                return io.BytesIO(b"x" * 501)
            return io.BytesIO(json.dumps({
                "datatable": {"columns": [], "data": []},
                "meta": {"next_cursor_id": "again"},
            }).encode())

    with pytest.raises(probe.ProbeRefused) as caught:
        probe.fetch_rows("SEP", {}, "private-key", opener=Source())
    assert "private-key" not in str(caught.value)


def test_probe_rejects_unbounded_requests_and_redirects():
    with pytest.raises(SystemExit):
        probe.arguments(["--from", "2020-01-01", "--to", "2026-01-01", "--tickers", "CYCN"])
    with pytest.raises(probe.ProbeRefused):
        probe.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere/")


def test_operator_probe_captures_both_action_directions_without_exposing_key(monkeypatch, capsys):
    import sentinel_env
    calls = []
    monkeypatch.setattr(sentinel_env, "load", lambda *a, **k: {"SHARADAR_API_KEY": "private-test-key"})

    def fetch(table, params, key):
        assert key == "private-test-key"
        calls.append((table, params))
        return {"rows": [], "page_sha256": ["a" * 64]}

    monkeypatch.setattr(probe, "fetch_rows", fetch)
    assert probe.main(["--from", "2026-09-01", "--to", "2026-09-11",
                       "--tickers", "CYCN,KRSA,PHGE,HLSQ"]) == 0
    output = capsys.readouterr().out
    assert "private-test-key" not in output
    result = json.loads(output)
    assert result["authority"] == "DIAGNOSTIC_ONLY_NOT_A_STABLE_PUBLICATION"
    for field in ("ticker", "contraticker"):
        assert result["actions_by_" + field]["page_sha256"] == ["a" * 64]
        assert ("ACTIONS", {field: "CYCN,KRSA,PHGE,HLSQ", "date.gte": "2026-09-01",
                            "date.lte": "2026-09-11"}) in calls
