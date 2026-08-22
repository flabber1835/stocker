import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sentinel.execution.alpaca import AlpacaExecutionBroker, MalformedBrokerPayload
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerCapabilities, BrokerObservation, Completeness,
)
from sentinel.execution.reconcile import ReconciliationResult


PAPER = "https://paper-api.alpaca.markets"


def _broker():
    return AlpacaExecutionBroker(
        api_key="k", secret_key="s", base_url=PAPER,
        resolve_security_id=lambda symbol, _as_of=None: symbol,
        http_provider=lambda: None)


def test_alpaca_observation_refuses_a_b_a_account_flip():
    broker = _broker()
    identities = iter([
        BrokerAccountIdentity("alpaca", "A"),
        BrokerAccountIdentity("alpaca", "B"),
        BrokerAccountIdentity("alpaca", "A"),
        BrokerAccountIdentity("alpaca", "A"),
        BrokerAccountIdentity("alpaca", "A"),
    ])

    async def identity():
        return next(identities)

    async def open_orders():
        return [], True

    async def positions():
        return []

    broker.identify_account = identity
    broker._list_open_orders = open_orders  # noqa: SLF001
    broker._list_positions = positions  # noqa: SLF001

    with pytest.raises(MalformedBrokerPayload, match="changed during"):
        asyncio.run(broker._observe_snapshot())  # noqa: SLF001


def test_stable_alpaca_observation_carries_account_identity():
    broker = _broker()
    account = BrokerAccountIdentity("alpaca", "A")

    async def identity():
        return account

    async def open_orders():
        return [], True

    async def positions():
        return []

    broker.identify_account = identity
    broker._list_open_orders = open_orders  # noqa: SLF001
    broker._list_positions = positions  # noqa: SLF001
    observed = asyncio.run(broker._observe_snapshot())  # noqa: SLF001
    assert observed.completeness is Completeness.COMPLETE
    assert observed.account_identity == account
    assert broker.capabilities.account_bound_observation is True
