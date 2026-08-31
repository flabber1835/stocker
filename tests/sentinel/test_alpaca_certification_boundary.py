"""Falsifiers for Alpaca's stable-asset mutation certification boundary."""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from sentinel.execution.alpaca import (
    FinancialGradeAlpacaExecutionBroker,
    HardenedAlpacaExecutionBroker,
    MalformedBrokerPayload,
    OriginalAlpaca,
)
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.certification import (
    _IMPLEMENTATIONS,
    AdapterNotCertified,
    certify_adapter,
    require_certified_adapter,
)
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.guarded import BrokerAuthorityRefused
from sentinel.execution.states import CommandState
from tests.sentinel.test_issue_183_alpaca_hardening import (
    Httpx,
    Response,
    full_order,
)


SAFE_ALPACA_ADAPTERS = (
    FinancialGradeAlpacaExecutionBroker,
    AssetIdAlpacaExecutionBroker,
)
SAFE_ALPACA_IMPLEMENTATIONS = frozenset(
    f"{adapter_type.__module__}.{adapter_type.__qualname__}"
    for adapter_type in SAFE_ALPACA_ADAPTERS
)
INSTRUMENT = BrokerInstrument(
    security_id="SEC-AAPL", symbol="AAPL", broker_id="asset-aapl")


def _broker(adapter_type, http=None):
    return adapter_type(
        api_key="test",
        secret_key="test",
        base_url="https://paper-api.alpaca.markets",
        resolve_security_id=lambda symbol, _as_of=None: f"SEC-{symbol}",
        http_provider=(lambda: http) if http is not None else None,
    )


def test_alpaca_certification_allowlist_is_closed_to_asset_id_submitters() -> None:
    assert _IMPLEMENTATIONS["alpaca"] == SAFE_ALPACA_IMPLEMENTATIONS


@pytest.mark.parametrize(
    "adapter_type",
    [OriginalAlpaca, HardenedAlpacaExecutionBroker],
    ids=["original-ticker-submit", "hardened-ticker-submit"],
)
def test_ticker_addressed_alpaca_variants_cannot_claim_certification(
    adapter_type,
) -> None:
    broker = _broker(adapter_type)

    with pytest.raises(AdapterNotCertified, match="cannot claim.*alpaca"):
        certify_adapter(broker, name="alpaca", mode="ALPACA_PAPER")

    with pytest.raises(AdapterNotCertified, match="composition-issued"):
        require_certified_adapter(broker, expected="alpaca")


@pytest.mark.parametrize(
    "adapter_type",
    SAFE_ALPACA_ADAPTERS,
    ids=["financial-grade-asset-id-submit", "asset-id-overlay"],
)
def test_every_certified_alpaca_variant_submits_by_stable_asset_id(
    adapter_type,
) -> None:
    http = Httpx(post=Response(full_order(), 200))
    broker = _broker(adapter_type, http)

    identity = certify_adapter(
        broker, name="alpaca", mode="ALPACA_PAPER")
    outcome = asyncio.run(broker.submit(
        client_key="key-1", instrument=INSTRUMENT,
        side=Side.BUY, quantity=Decimal("2")))

    assert identity.implementation == (
        f"{adapter_type.__module__}.{adapter_type.__qualname__}")
    assert "instrument_identity" in identity.capabilities
    assert "pre_submit_instrument_revalidation" in identity.capabilities
    assert require_certified_adapter(broker, expected="alpaca") is identity
    assert outcome.state is CommandState.ACKNOWLEDGED
    posts = [call for call in http.calls if call[0] == "POST"]
    assert len(posts) == 1
    assert posts[0][2]["symbol"] == "asset-aapl"
    assert posts[0][2]["symbol"] != "AAPL"


@pytest.mark.parametrize(
    "adapter_type",
    SAFE_ALPACA_ADAPTERS,
    ids=["financial-grade-asset-id-submit", "asset-id-overlay"],
)
def test_every_certified_alpaca_variant_refuses_missing_asset_id_before_transport(
    adapter_type,
) -> None:
    http = Httpx(post=Response(full_order(), 200))
    broker = _broker(adapter_type, http)
    instrument = BrokerInstrument(
        security_id="SEC-AAPL", symbol="AAPL", broker_id=None)

    with pytest.raises(
        (BrokerAuthorityRefused, MalformedBrokerPayload),
        match=r"durable broker asset[_ ]id",
    ):
        asyncio.run(broker.submit(
            client_key="key-1", instrument=instrument,
            side=Side.SELL, quantity=Decimal("2")))

    assert http.calls == []
