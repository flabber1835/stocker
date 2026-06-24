"""Lock the broker-adapter `http_provider` seam in trade-executor.

The read helpers (_get_alpaca_clock / _get_alpaca_buying_power / _get_alpaca_order)
now delegate to the shared BrokerAdapter. The adapter routes transport through
`http_provider=lambda: te_main.httpx`, so the existing module-level mocking
(`patch.object(te_main, "httpx")`) must STILL intercept adapter calls — otherwise
the refactor would have silently moved the Alpaca calls out from under the tests.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import app.main as ex


def _httpx_with(get_response):
    """A fake httpx whose AsyncClient(...) async-context yields a client whose
    .get returns `get_response`."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=get_response)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    httpx_mock = MagicMock()
    httpx_mock.AsyncClient = MagicMock(return_value=cm)
    return httpx_mock, client


def _resp(payload, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json = MagicMock(return_value=payload)
    r.raise_for_status = MagicMock()
    return r


def test_buying_power_reads_through_adapter_with_module_httpx_patch():
    httpx_mock, client = _httpx_with(_resp({"buying_power": "12345.67", "equity": "1", "cash": "1"}))
    with patch.object(ex, "ALPACA_API_KEY", "k"), \
         patch.object(ex, "ALPACA_SECRET_KEY", "s"), \
         patch.object(ex, "httpx", httpx_mock):
        bp = asyncio.run(ex._get_alpaca_buying_power())
    assert bp == 12345.67
    # the call really went through the (patched) module httpx → adapter transport
    assert client.get.await_count == 1
    url = client.get.await_args.args[0]
    assert url.endswith("/v2/account")


def test_clock_reads_through_adapter_and_parses():
    httpx_mock, client = _httpx_with(_resp({
        "is_open": True,
        "next_open": "2026-06-01T09:30:00Z",
        "next_close": "2026-06-01T16:00:00Z",
    }))
    with patch.object(ex, "ALPACA_API_KEY", "k"), \
         patch.object(ex, "ALPACA_SECRET_KEY", "s"), \
         patch.object(ex, "httpx", httpx_mock):
        clock = asyncio.run(ex._get_alpaca_clock())
    assert clock["is_open"] is True
    assert clock["next_open"] is not None and clock["next_close"] is not None


def test_get_order_returns_none_on_non_200_through_adapter():
    httpx_mock, _ = _httpx_with(_resp({}, status_code=404))
    with patch.object(ex, "ALPACA_API_KEY", "k"), \
         patch.object(ex, "ALPACA_SECRET_KEY", "s"), \
         patch.object(ex, "httpx", httpx_mock):
        out = asyncio.run(ex._get_alpaca_order("missing-id"))
    assert out is None


def test_read_helpers_still_short_circuit_without_credentials():
    # No creds → must return None WITHOUT touching transport (adapter never built).
    with patch.object(ex, "ALPACA_API_KEY", ""), patch.object(ex, "ALPACA_SECRET_KEY", ""):
        assert asyncio.run(ex._get_alpaca_buying_power()) is None
        assert asyncio.run(ex._get_alpaca_clock()) is None
