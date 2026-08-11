"""The mock Sharadar client must yield well-formed rows for SEP/SF1/TICKERS so the
backfill, the data-depth report, and the engine can run end-to-end before the real
Sharadar subscription is live (BT_MOCK_DATA / no SHARADAR_API_KEY)."""
import asyncio
import importlib

import pytest

import app.sharadar_client as client  # noqa: E402
from app.sharadar_adapter import map_sep_row, map_sf1_row, map_tickers_row  # noqa: E402


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    """Select the mode and RELOAD, rather than setting os.environ at import.

    The client reads its mode into MODULE CONSTANTS at import time, so the old
    module-level `os.environ["BT_MOCK_DATA"] = "true"` only worked while this
    file happened to be the first thing to import it. `test_data_mode.py` sorts
    earlier and reloads the module with the mode deleted; monkeypatch restores
    the environment afterwards but cannot restore the module, so in a
    whole-suite run these tests ran against the REAL client and issued outbound
    HTTPS requests to data.nasdaq.com — from the test suite, on every run, with
    an empty api_key. They passed in isolation the entire time.

    Reloading on the way out too, so this file cannot do to the next one what
    was being done to it.
    """
    monkeypatch.setenv("BT_DATA_MODE", "mock")
    importlib.reload(client)
    yield
    monkeypatch.undo()
    importlib.reload(client)


def _collect(table, **kw):
    async def run():
        return [r async for r in client.fetch_table(table, **kw)]
    return asyncio.run(run())


def test_is_mock_true_without_key():
    assert client.is_mock() is True


def test_mock_sep_rows_map_cleanly():
    rows = _collect("SEP")
    assert len(rows) > 100
    mapped = [map_sep_row(r) for r in rows]
    # every mapped row has a usable adjusted_close and the pipeline columns
    assert all(m["adjusted_close"] is not None for m in mapped)
    assert {"AAA", "BBB", "CCC", "SPY"}.issubset({m["ticker"] for m in mapped})
    assert all(set(m) >= {"ticker", "date", "adjusted_close", "close", "volume"} for m in mapped)


def test_mock_sf1_rows_map_with_datekey():
    rows = _collect("SF1")
    mapped = [map_sf1_row(r) for r in rows]
    assert all(m is not None for m in mapped)
    assert all(m["as_of_date"] for m in mapped)
    assert all(m["pe_ratio"] is not None for m in mapped)


def test_mock_tickers_filters_etf():
    rows = _collect("TICKERS")
    mapped = [map_tickers_row(r, "2023-01-01") for r in rows]
    kept = [m for m in mapped if m is not None]
    tickers = {m["ticker"] for m in kept}
    assert "SPY" not in tickers          # ETF excluded
    assert {"AAA", "BBB", "CCC"}.issubset(tickers)


def test_mock_sep_has_spy_for_benchmark_and_regime():
    rows = _collect("SEP")
    spy = [r for r in rows if r["ticker"] == "SPY"]
    assert len(spy) > 200   # enough for the 200-day regime SMA


# ── retry/backoff on transient failures (the "stuck at 25M" fragility) ─────────

def test_get_with_retry_retries_transient_then_succeeds(monkeypatch):
    """A 503 (retryable) is retried; a subsequent 200 succeeds. Backoff is
    zeroed so the test doesn't actually sleep."""
    import httpx
    from app import sharadar_client as sc
    monkeypatch.setattr(sc, "FETCH_BACKOFF_BASE", 0.0)

    calls = {"n": 0}

    class _Resp:
        def __init__(self, status):
            self.status_code = status
            self.request = httpx.Request("GET", "http://x")
            self.response = self
            self.headers = {}
        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("e", request=self.request, response=self)

    class _Client:
        async def get(self, url, params=None):
            calls["n"] += 1
            return _Resp(503 if calls["n"] < 3 else 200)

    resp = asyncio.run(sc._get_with_retry(_Client(), "http://x", {}))
    assert resp.status_code == 200 and calls["n"] == 3


def test_get_with_retry_does_not_retry_client_error(monkeypatch):
    """A 403 (auth/bad-request) fails fast — no retry storm on a real error."""
    import httpx
    from app import sharadar_client as sc
    monkeypatch.setattr(sc, "FETCH_BACKOFF_BASE", 0.0)
    calls = {"n": 0}

    class _Resp:
        status_code = 403
        def __init__(self):
            self.request = httpx.Request("GET", "http://x")
            self.response = self
        def raise_for_status(self):
            raise httpx.HTTPStatusError("403", request=self.request, response=self)

    class _Client:
        async def get(self, url, params=None):
            calls["n"] += 1
            return _Resp()

    import pytest
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(sc._get_with_retry(_Client(), "http://x", {}))
    assert calls["n"] == 1   # tried once, did not retry


def test_retry_delay_429_honors_retry_after_and_caps():
    from app.sharadar_client import _retry_delay, RATE_LIMIT_BACKOFF_CAP
    # 429 default: 60s × attempt number
    assert _retry_delay(0, 429, None) == 60.0
    assert _retry_delay(2, 429, None) == 180.0
    # Retry-After header wins when larger
    assert _retry_delay(0, 429, "300") == 300.0
    # capped
    assert _retry_delay(0, 429, "99999") == RATE_LIMIT_BACKOFF_CAP
    # non-429 keeps the fast generic backoff
    assert _retry_delay(0, 503, None) == 2.0
    assert _retry_delay(3, None, None) == 16.0
