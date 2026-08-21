from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from sentinel.config import SentinelConfig, build_execution_broker
from sentinel.execution.alpaca import MalformedBrokerPayload
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.states import CommandState
from tests.sentinel.test_issue_183_alpaca_hardening import (
    Httpx,
    INSTRUMENT,
    PAPER,
    Response,
    full_order,
    run,
)


def _broker(http):
    return AssetIdAlpacaExecutionBroker(
        api_key="k",
        secret_key="s",
        base_url=PAPER,
        resolve_security_id=lambda symbol, _as_of=None: f"SEC-{symbol}",
        http_provider=lambda: http,
    )


def test_submit_addresses_the_durable_asset_id_not_the_ticker():
    http = Httpx(post=Response(full_order(), 200))
    broker = _broker(http)

    outcome = run(
        broker.submit(
            client_key="key-1",
            instrument=INSTRUMENT,
            side=Side.BUY,
            quantity=Decimal(2),
        )
    )

    assert outcome.state is CommandState.ACKNOWLEDGED
    posts = [call for call in http.calls if call[0] == "POST"]
    assert len(posts) == 1
    assert posts[0][2]["symbol"] == "asset-aapl"
    assert posts[0][2]["symbol"] != "AAPL"


def test_submit_without_stable_asset_id_refuses_before_transport():
    http = Httpx(post=Response(full_order(), 200))
    broker = _broker(http)
    unresolved = BrokerInstrument(
        security_id="SEC-AAPL",
        symbol="AAPL",
        broker_id=None,
    )

    with pytest.raises(MalformedBrokerPayload, match="durable broker asset id"):
        run(
            broker.submit(
                client_key="key-1",
                instrument=unresolved,
                side=Side.SELL,
                quantity=Decimal(2),
            )
        )

    assert http.calls == []


def test_submit_acknowledgement_must_return_the_same_asset_id():
    http = Httpx(
        post=Response(full_order(asset_id="different-alpaca-asset"), 200)
    )
    broker = _broker(http)

    with pytest.raises(MalformedBrokerPayload, match="stable asset id"):
        run(
            broker.submit(
                client_key="key-1",
                instrument=INSTRUMENT,
                side=Side.BUY,
                quantity=Decimal(2),
            )
        )


def test_production_builder_selects_asset_id_bound_adapter():
    cfg = SentinelConfig(
        alpaca_key="paper-key",
        alpaca_secret="paper-secret",
        base_url=PAPER,
        state_dir=Path("/tmp/sentinel-test"),
        max_cycles=40,
        poll_seconds=5.0,
    )

    broker = build_execution_broker(
        cfg,
        resolve_security_id=lambda symbol, _as_of=None: f"SEC-{symbol}",
    )

    assert isinstance(broker, AssetIdAlpacaExecutionBroker)



def test_execution_certificate_identity_names_asset_id_transport():
    from sentinel.authority import execution_config_identity

    identity = execution_config_identity(paper_base_url=PAPER)
    assert identity["adapter"] == (
        "sentinel.execution.alpaca_asset_id.AssetIdAlpacaExecutionBroker")
