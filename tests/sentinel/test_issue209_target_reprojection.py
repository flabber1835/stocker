"""Issue #209: corporate actions change share units, not plan intent."""
from datetime import date
from decimal import Decimal

import pytest

from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.target_reprojection import (
    TargetProjectionRefused, project_target)


def plan(*, basket=None):
    return ExecutionPlan(
        plan_id="sentinel-issue-209", decision_session=date(2026, 8, 20),
        effective_session=date(2026, 8, 21), target_exposure=Decimal("1"),
        target_basket=basket or {"SEC-A": Decimal("10")},
        rollout_mode="PINNED_1_00", rollout_version=1)


def test_forward_split_reexpresses_units_without_mutating_plan():
    original = plan()

    projected = project_target(
        original, through_session=original.effective_session,
        action_multipliers={"SEC-A": Decimal("2")},
        action_evidence=({
            "security_id": "SEC-A", "session": "2026-08-21",
            "action": "split", "value": "2", "source_row_id": "action-1",
        },))

    assert original.target_basket == {"SEC-A": Decimal("10")}
    assert projected.plan_id == original.plan_id
    assert projected.plan_fingerprint == original.fingerprint()
    assert projected.target_basket == {"SEC-A": Decimal("20")}
    assert projected.action_multipliers == {"SEC-A": Decimal("2")}
    assert projected.action_evidence[0]["source_row_id"] == "action-1"
    assert projected.payload()["projection_fingerprint"] == \
        projected.fingerprint()


def test_exact_reverse_split_is_supported_for_whole_share_adapter():
    projected = project_target(
        plan(), through_session=date(2026, 8, 21),
        action_multipliers={"SEC-A": Decimal("0.1")})

    assert projected.target_basket == {"SEC-A": Decimal("1.0")}


def test_fractional_reverse_split_refuses_instead_of_rounding():
    with pytest.raises(TargetProjectionRefused, match="not a multiple"):
        project_target(
            plan(basket={"SEC-A": Decimal("3")}),
            through_session=date(2026, 8, 21),
            action_multipliers={"SEC-A": Decimal("0.1")},
            minimum_quantity_increment=Decimal("1"))


def test_fractional_reverse_split_uses_broker_certified_increment_exactly():
    projected = project_target(
        plan(basket={"SEC-A": Decimal("3")}),
        through_session=date(2026, 8, 21),
        action_multipliers={"SEC-A": Decimal("0.1")},
        minimum_quantity_increment=Decimal("0.000000001"))

    assert projected.target_basket == {"SEC-A": Decimal("0.3")}


@pytest.mark.parametrize("ratio", [Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_invalid_scalar_terms_refuse(ratio):
    with pytest.raises(TargetProjectionRefused):
        project_target(
            plan(), through_session=date(2026, 8, 21),
            action_multipliers={"SEC-A": ratio})


def test_scalar_action_cannot_introduce_a_security():
    with pytest.raises(TargetProjectionRefused, match="outside the plan"):
        project_target(
            plan(), through_session=date(2026, 8, 21),
            action_multipliers={"SPINOFF": Decimal("1")})
