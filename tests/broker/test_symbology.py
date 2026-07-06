"""Broker symbology translation (the PBR-A incident).

System form = Alpha Vantage hyphen (PBR-A, BRK-B); Alpaca uses dots (PBR.A).
The adapter translates at the transport boundary in BOTH directions so every
other service speaks only the system form: submit/close send the broker form,
position reads return the system form.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from stock_strategy_shared.broker.alpaca import AlpacaBrokerAdapter
from stock_strategy_shared.broker.base import BrokerAdapter


def _adapter(mock_client):
    httpx_mod = MagicMock()
    httpx_mod.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    httpx_mod.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=None)
    return AlpacaBrokerAdapter(api_key="k", secret_key="s",
                               http_provider=lambda: httpx_mod)


def test_translation_bijection():
    a = AlpacaBrokerAdapter(api_key="k", secret_key="s")
    for system, broker in (("PBR-A", "PBR.A"), ("BRK-B", "BRK.B"),
                           ("HEI-A", "HEI.A"), ("AAPL", "AAPL")):
        assert a.to_broker_symbol(system) == broker
        assert a.from_broker_symbol(broker) == system
    assert a.to_broker_symbol("") == "" and a.from_broker_symbol(None or "") == ""


def test_base_adapter_defaults_identity():
    # A future broker on AV symbology needs no override.
    assert BrokerAdapter.to_broker_symbol(MagicMock(), "PBR-A") == "PBR-A"
    assert BrokerAdapter.from_broker_symbol(MagicMock(), "PBR-A") == "PBR-A"


@pytest.mark.asyncio
async def test_submit_order_translates_symbol():
    client = MagicMock()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"id": "o1", "status": "accepted"}
    client.post = AsyncMock(return_value=resp)
    a = _adapter(client)
    payload = {"symbol": "PBR-A", "qty": "10", "side": "buy",
               "type": "market", "time_in_force": "day"}
    oid, status, err = await a.submit_order(payload)
    assert err is None and oid == "o1"
    sent = client.post.call_args.kwargs["json"]
    assert sent["symbol"] == "PBR.A"          # broker form on the wire
    assert payload["symbol"] == "PBR-A"       # caller's dict not mutated


@pytest.mark.asyncio
async def test_close_position_translates_url():
    client = MagicMock()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"id": "o2", "status": "accepted"}
    client.delete = AsyncMock(return_value=resp)
    a = _adapter(client)
    await a.close_position("PBR-A")
    url = client.delete.call_args.args[0]
    assert url.endswith("/v2/positions/PBR.A")


@pytest.mark.asyncio
async def test_get_positions_returns_system_form():
    client = MagicMock()
    resp = MagicMock(status_code=200)
    resp.json.return_value = [{"symbol": "PBR.A", "qty": "5", "side": "long"}]
    resp.raise_for_status = MagicMock()
    client.get = AsyncMock(return_value=resp)
    a = _adapter(client)
    positions = await a.get_positions()
    assert positions[0].ticker == "PBR-A"
