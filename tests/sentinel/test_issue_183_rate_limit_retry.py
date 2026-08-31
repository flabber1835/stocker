"""Rate-limit retry semantics for issue #183."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from sentinel.execution import recovery
from sentinel.execution.alpaca import RetryableCommandOutcome
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerExactOrderLookup, BrokerInstrument,
    BrokerObservation, CommandOutcome, Completeness, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState as S


UTC = timezone.utc
INSTRUMENT = BrokerInstrument(
    security_id="SEC-AAPL", symbol="AAPL", broker_id="asset-aapl")
DEPLOYMENT = DeploymentIdentity("test", "alpaca", "PA-1", 1)


def run(coro):
    return asyncio.run(coro)


def command():
    identity = CommandIdentity(
        deployment=DEPLOYMENT, plan_id="plan-rate-limit",
        security_id=INSTRUMENT.security_id)
    return Command(
        identity=identity, instrument=INSTRUMENT, side=Side.BUY,
        quantity=Decimal(2), state=S.SEND_PENDING)


class AbsentThenAcceptBroker:
    def __init__(self):
        self.submitted_keys = []
        self.lookups = 0
        self.observations = 0

    async def submit(self, *, client_key, instrument, side, quantity):
        self.submitted_keys.append(client_key)
        if len(self.submitted_keys) == 1:
            return RetryableCommandOutcome(
                state=S.UNKNOWN, retry_after_seconds=Decimal(0),
                detail="HTTP 429")
        return CommandOutcome(
            state=S.ACKNOWLEDGED, broker_order_id="order-retry",
            detail="accepted")

    async def find_by_client_key(self, _client_key):
        self.lookups += 1
        now = datetime.now(UTC)
        account = BrokerAccountIdentity("alpaca", "PA-1")
        return BrokerExactOrderLookup(
            client_key=_client_key, request_started_at=now,
            request_completed_at=now, identity_before=account,
            identity_after=account, order=None)

    async def observe(self):
        self.observations += 1
        return BrokerObservation(
            observed_at=datetime.now(UTC), orders=(), positions=(),
            completeness=Completeness.COMPLETE,
            account_identity=BrokerAccountIdentity("alpaca", "PA-1"))


def test_429_absence_retries_once_under_the_exact_same_durable_key():
    pending = command()
    broker = AbsentThenAcceptBroker()

    result = run(recovery.dispatch(broker, pending))

    assert result.state is S.ACKNOWLEDGED
    assert result.broker_order_id == "order-retry"
    assert broker.submitted_keys == [pending.client_key, pending.client_key]
    # Lookup before the COMPLETE absence proof, and once more after backoff.
    assert broker.lookups == 2
    assert broker.observations == 1


class LongBackoffBroker(AbsentThenAcceptBroker):
    async def submit(self, *, client_key, instrument, side, quantity):
        self.submitted_keys.append(client_key)
        return RetryableCommandOutcome(
            state=S.UNKNOWN, retry_after_seconds=Decimal(30),
            detail="HTTP 429")


def test_long_429_backoff_stays_unknown_without_a_second_post():
    pending = command()
    broker = LongBackoffBroker()

    result = run(recovery.dispatch(broker, pending))

    assert result.state is S.UNKNOWN
    assert broker.submitted_keys == [pending.client_key]
    assert broker.lookups == 0
    assert broker.observations == 0
