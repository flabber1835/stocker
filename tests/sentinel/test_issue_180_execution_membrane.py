"""Regression tests for issue #180 execution-membrane invariants."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from sentinel.execution import commands as C
from sentinel.execution.contract import (
    BrokerInstrument,
    BrokerObservation,
    BrokerPosition,
    Completeness,
    Side,
)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.projection import project


NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)
INSTR = BrokerInstrument(
    security_id="SEC-AAA", symbol="AAA", broker_id="asset-a")
DEPLOY = DeploymentIdentity(
    deployment_id="sentinel-test", broker="alpaca",
    broker_account_id="paper-123", takeover_epoch=1)
IDENT = CommandIdentity(
    deployment=DEPLOY, plan_id="plan-1", security_id="SEC-AAA", revision=0)


def _observation(*positions):
    return BrokerObservation(
        observed_at=NOW, positions=tuple(positions), orders=(),
        completeness=Completeness.COMPLETE)


@pytest.mark.parametrize(
    "bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_execution_plan_rejects_nonfinite_target_quantities(bad):
    with pytest.raises(ValueError, match="must be finite"):
        ExecutionPlan(
            plan_id="plan-1", decision_session=date(2026, 8, 11),
            effective_session=date(2026, 8, 12),
            target_exposure=Decimal(1), target_basket={"SEC-AAA": bad},
            account_nav=Decimal(100), account_cash=Decimal(100),
            cash_residual=Decimal(0))


@pytest.mark.parametrize(
    "bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_command_rejects_nonfinite_quantities(bad):
    with pytest.raises(ValueError, match="finite and positive"):
        C.Command(
            identity=IDENT, instrument=INSTR, side=Side.BUY, quantity=bad)


@pytest.mark.parametrize(
    "bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_compute_delta_rejects_nonfinite_desired_quantities(bad):
    with pytest.raises(ValueError, match="desired quantity must be finite"):
        C.compute_delta(
            security_id="SEC-AAA", desired=bad, observation=_observation())


def test_compute_delta_rejects_nonfinite_or_nonpositive_increment():
    for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal(0), Decimal(-1)):
        with pytest.raises(ValueError, match="finite and positive"):
            C.compute_delta(
                security_id="SEC-AAA", desired=Decimal(0),
                observation=_observation(), min_increment=bad)


def test_observation_rejects_duplicate_permanent_position_identity():
    first = BrokerPosition(instrument=INSTR, quantity=Decimal(1))
    renamed_transport = BrokerPosition(
        instrument=BrokerInstrument(
            security_id="SEC-AAA", symbol="AAA2", broker_id="asset-b"),
        quantity=Decimal(2))

    with pytest.raises(ValueError, match="permanent position identity"):
        _observation(first, renamed_transport)


def test_defensive_projection_uses_the_same_fractional_lot_as_core():
    sized = project(
        shadow_weights={}, exposure=Decimal(0), nav=Decimal(100),
        marks={"SENTINEL:BIL": Decimal(3)},
        defensive_security="SENTINEL:BIL", defensive_weight=Decimal(1),
        lot=Decimal("0.25"))

    assert sized.defensive_quantity == Decimal("33.25")
    assert sized.cash_residual == Decimal("0.25")
