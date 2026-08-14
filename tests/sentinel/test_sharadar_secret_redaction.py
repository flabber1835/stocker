"""A sentinel API key never reaches any operator-visible diagnostic surface."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sentinel.feed import sharadar  # noqa: E402

SECRET = "SENTINEL-SECRET-must-never-render"


class _HttpStatusError(Exception):
    def __init__(self, response, secret):
        self.response = response
        super().__init__(f"HTTP {response.status_code} for ?api_key={secret}")


class _Response:
    headers = {}

    def __init__(self, status, secret):
        self.status_code = status
        self._secret = secret

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _HttpStatusError(self, self._secret)

    def json(self):
        return {"datatable": {"columns": [], "data": []},
                "meta": {"next_cursor_id": None}}


class _Http:
    class TimeoutException(Exception):
        pass

    class TransportError(Exception):
        pass

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        outer = self

        class Client:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def get(self, url, params):
                # Reproduce httpx's URL-bearing INFO diagnostic exactly where
                # the authenticated request is made.
                logging.getLogger("httpx").info(
                    "HTTP Request: GET %s?api_key=%s", url, params["api_key"])
                outcome = outer.outcomes.pop(0)
                if outcome == "transport":
                    raise outer.TransportError(
                        f"transport failed for ?api_key={params['api_key']}")
                return _Response(int(outcome), params["api_key"])

        self.Client = Client


@pytest.mark.parametrize(("outcomes", "raises"), [
    pytest.param([200], False, id="success"),
    pytest.param([500, 200], False, id="retry-then-success"),
    pytest.param([400], True, id="4xx"),
    pytest.param([500] * sharadar.FETCH_MAX_RETRIES, True, id="5xx"),
    pytest.param(["transport"] * sharadar.FETCH_MAX_RETRIES, True,
                 id="transport"),
])
def test_secret_absent_from_stdout_stderr_logs_and_exception(
        monkeypatch, capsys, caplog, outcomes, raises):
    monkeypatch.setenv("SHARADAR_API_KEY", SECRET)
    caplog.set_level(logging.DEBUG)
    http = _Http(outcomes)
    rendered_exception = ""
    if raises:
        with pytest.raises(sharadar.SharadarRequestError) as caught:
            list(sharadar.fetch_table(
                sharadar.SEP, {"date.gte": "2026-01-01"}, http=http,
                sleep=lambda _seconds: None))
        rendered_exception = repr(caught.value) + str(caught.value)
    else:
        assert list(sharadar.fetch_table(
            sharadar.SEP, {"date.gte": "2026-01-01"}, http=http,
            sleep=lambda _seconds: None)) == []

    captured = capsys.readouterr()
    log_surface = "\n".join(
        record.getMessage() + repr(record.args) + repr(record.exc_info)
        for record in caplog.records)
    surfaces = captured.out + captured.err + log_surface + rendered_exception
    assert SECRET not in surfaces


def test_verbose_logging_still_cannot_reenable_url_disclosure(
        monkeypatch, caplog):
    monkeypatch.setenv("SHARADAR_API_KEY", SECRET)
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    with caplog.at_level(logging.DEBUG):
        list(sharadar.fetch_table(
            sharadar.SFP, {"ticker": "SPY"}, http=_Http([200]),
            sleep=lambda _seconds: None))
    assert SECRET not in "\n".join(
        record.getMessage() + repr(record.args) for record in caplog.records)
