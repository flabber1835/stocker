"""Executor-level regression for issue #180 working-order identity coverage."""
from datetime import datetime, timezone
from decimal import Decimal

from sentinel.execution import commands as C
from sentinel.execution.executor import _execution_universe
from sentinel.execution.contract import (
    BrokerInstrument, BrokerObservation, BrokerOrder, Completeness, Side)
from sentinel.execution.states import CommandState


def test_executor_universe_includes_working_order_only_security():
    instrument = BrokerInstrument(
        security_id="ORDER-ONLY", symbol="OLD", broker_id="asset-old")
    order = BrokerOrder(
        broker_order_id="broker-1", client_key=None, instrument=instrument,
        side=Side.BUY, state=CommandState.ACKNOWLEDGED,
        quantity=Decimal("7"), filled_quantity=Decimal(0))
    observation = BrokerObservation(
        observed_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
        orders=(order,), positions=(), completeness=Completeness.COMPLETE)

    assert _execution_universe({}, observation) == {"ORDER-ONLY"}

    delta = C.compute_delta(
        security_id="ORDER-ONLY", desired=Decimal(0), observation=observation)
    assert delta.remaining == Decimal("-7")
    assert delta.conflicting_orders == (order,)
