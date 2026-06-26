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


# --- Phase 2b: write path now flows through the adapter (same seam) ---------


def _httpx_with_post(post_response):
    client = AsyncMock()
    client.post = AsyncMock(return_value=post_response)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    httpx_mock = MagicMock()
    httpx_mock.AsyncClient = MagicMock(return_value=cm)
    return httpx_mock, client


def _httpx_with_delete(delete_response):
    client = AsyncMock()
    client.delete = AsyncMock(return_value=delete_response)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    httpx_mock = MagicMock()
    httpx_mock.AsyncClient = MagicMock(return_value=cm)
    return httpx_mock, client


def test_submit_to_alpaca_goes_through_adapter():
    httpx_mock, client = _httpx_with_post(_resp({"id": "ord-1", "status": "accepted"}, 200))
    payload = {"symbol": "AAPL", "qty": "1", "side": "buy", "type": "market",
               "time_in_force": "day", "client_order_id": "row-9"}
    with patch.object(ex, "ALPACA_API_KEY", "k"), \
         patch.object(ex, "ALPACA_SECRET_KEY", "s"), \
         patch.object(ex, "httpx", httpx_mock):
        oid, status, err = asyncio.run(ex._submit_to_alpaca(payload))
    assert (oid, status, err) == ("ord-1", "accepted", None)
    # the exact payload (incl. client_order_id idempotency key) reached the broker
    assert client.post.await_args.kwargs["json"] == payload
    assert client.post.await_args.args[0].endswith("/v2/orders")


def test_submit_to_alpaca_non_2xx_returns_error_text():
    httpx_mock, _ = _httpx_with_post(_resp({}, 422))
    httpx_mock.AsyncClient.return_value.__aenter__.return_value.post.return_value.text = "rejected"
    with patch.object(ex, "ALPACA_API_KEY", "k"), \
         patch.object(ex, "ALPACA_SECRET_KEY", "s"), \
         patch.object(ex, "httpx", httpx_mock):
        oid, status, err = asyncio.run(ex._submit_to_alpaca({"symbol": "X"}))
    assert oid is None and status is None and err == "rejected"


def test_close_position_404_maps_to_sentinel_through_adapter():
    httpx_mock, _ = _httpx_with_delete(_resp({}, 404))
    with patch.object(ex, "ALPACA_API_KEY", "k"), \
         patch.object(ex, "ALPACA_SECRET_KEY", "s"), \
         patch.object(ex, "httpx", httpx_mock):
        oid, status, err = asyncio.run(ex._close_position_alpaca("AAPL"))
    assert oid is None and err is None
    assert status == ex._ALREADY_CLOSED_ALPACA_STATUS == "position_already_closed"
