from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sentinel import dual_plan_authority
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerInstrument,
    BrokerObservation,
    BrokerOrder,
    BrokerPosition,
    Completeness,
    Side,
)
from sentinel.execution.states import CommandState


NOW = datetime(2026, 8, 26, 23, 50, tzinfo=timezone.utc)
IDENTITY = BrokerAccountIdentity(broker="alpaca", account_id="paper-1")
INSTRUMENT = BrokerInstrument(
    security_id="perm-1", symbol="ABC", broker_id="asset-1")


def _observation(*, positions=(), orders=(), completeness=Completeness.COMPLETE):
    return BrokerObservation(
        observed_at=NOW,
        started_at=NOW,
        terminal_recovery_through=NOW,
        completeness=completeness,
        account_identity=IDENTITY,
        positions=tuple(positions),
        orders=tuple(orders),
    )


def _order(state=CommandState.ACKNOWLEDGED, *, replaced=False):
    return BrokerOrder(
        broker_order_id="order-1",
        client_key="sntl-key",
        instrument=INSTRUMENT,
        side=Side.BUY,
        state=state,
        quantity=Decimal("10"),
        filled_quantity=(Decimal("10") if state is CommandState.FILLED
                         else Decimal("0")),
        filled_average_price=(Decimal("12") if state is CommandState.FILLED
                              else None),
        submitted_at=NOW,
        external_replacement=replaced,
    )


def test_flat_complete_observation_is_valid_first_segment_sizing_input():
    dual_plan_authority._require_flat_regenesis_observation(_observation())


def test_first_post_gap_sizing_refuses_predecessor_position():
    with pytest.raises(
            dual_plan_authority.DualPlanAuthorityRefused,
            match="flat broker account"):
        dual_plan_authority._require_flat_regenesis_observation(
            _observation(positions=[BrokerPosition(
                instrument=INSTRUMENT, quantity=Decimal("10"))]))


def test_first_post_gap_sizing_refuses_working_broker_order():
    with pytest.raises(
            dual_plan_authority.DualPlanAuthorityRefused,
            match="working broker order"):
        dual_plan_authority._require_flat_regenesis_observation(
            _observation(orders=[_order()]))


def test_first_post_gap_sizing_refuses_external_replacement_even_if_terminal():
    with pytest.raises(
            dual_plan_authority.DualPlanAuthorityRefused,
            match="externally replaced"):
        dual_plan_authority._require_flat_regenesis_observation(
            _observation(orders=[_order(CommandState.CANCELLED, replaced=True)]))


def test_flat_sizing_scope_is_task_local_and_restored():
    assert dual_plan_authority.regenesis_flat_sizing_required() is False
    with dual_plan_authority.regenesis_flat_sizing_scope(True):
        assert dual_plan_authority.regenesis_flat_sizing_required() is True
        with dual_plan_authority.regenesis_flat_sizing_scope(False):
            assert dual_plan_authority.regenesis_flat_sizing_required() is False
        assert dual_plan_authority.regenesis_flat_sizing_required() is True
    assert dual_plan_authority.regenesis_flat_sizing_required() is False
