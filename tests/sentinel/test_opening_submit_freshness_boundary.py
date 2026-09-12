"""Final no-await freshness fence for exposure-increasing broker mutation."""
import asyncio
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.guarded import (
    ExecutionBrokerGuard, GuardedExecutionBroker, ManualExecutionGrant,
    PreTransportAuthorityRefused)
from sentinel.execution.simulator import SimulatedBroker
from sentinel.feed import calendar


class ClockedBroker(SimulatedBroker):
    async def market_clock(self):
        opened, closed = calendar.session_window(self.now.date())
        return SimpleNamespace(
            timestamp=self.now, is_open=opened <= self.now < closed,
            next_open=opened, next_close=closed)

    def _now(self):
        return self.now


class Guard:
    def __init__(self, inner, *, cross_deadline=False):
        self.inner = inner
        self.cross_deadline = cross_deadline

    async def before_read(self, grant, operation):
        return None

    async def after_read(self, grant, operation, result):
        return None

    async def before_mutation(self, grant, operation):
        if self.cross_deadline:
            opened, _closed = calendar.session_window(self.inner.now.date())
            self.inner.now = opened + timedelta(seconds=121)


def wrap(inner, *, cross_deadline=False):
    guard = Guard(inner, cross_deadline=cross_deadline)
    return GuardedExecutionBroker(
        inner=inner,
        grant=ManualExecutionGrant(
            confirm_paper_account="SIM-ACCOUNT",
            confirm_plan_id="sentinel-plan",
            confirm_effective_session=inner.now.date(),
            confirm_submit_paper_orders=True),
        guard=ExecutionBrokerGuard(
            before_read=guard.before_read,
            after_read=guard.after_read,
            before_mutation=guard.before_mutation))


def instrument():
    return BrokerInstrument("SEC-AAA", "AAA", "sim-asset-SEC-AAA")


def test_buy_inside_opening_freshness_reaches_transport():
    inner = ClockedBroker()
    opened, _closed = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(seconds=119)
    broker = wrap(inner)
    outcome = asyncio.run(broker.submit(
        client_key="fresh-buy", instrument=instrument(),
        side=Side.BUY, quantity=Decimal(1)))
    assert outcome.state.value == "ACKNOWLEDGED"
    assert "submit:fresh-buy" in inner.calls


def test_authority_latency_crossing_deadline_refuses_before_transport():
    inner = ClockedBroker()
    opened, _closed = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(seconds=119)
    broker = wrap(inner, cross_deadline=True)
    with pytest.raises(PreTransportAuthorityRefused, match="final next-open freshness"):
        asyncio.run(broker.submit(
            client_key="late-buy", instrument=instrument(),
            side=Side.BUY, quantity=Decimal(1)))
    assert "submit:late-buy" not in inner.calls


def test_late_sell_remains_risk_reducing_and_executable():
    inner = ClockedBroker()
    opened, _closed = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(hours=2)
    inner.seed_position(instrument(), "1")
    broker = wrap(inner)
    outcome = asyncio.run(broker.submit(
        client_key="late-sell", instrument=instrument(),
        side=Side.SELL, quantity=Decimal(1)))
    assert outcome.state.value == "ACKNOWLEDGED"
    assert "submit:late-sell" in inner.calls
