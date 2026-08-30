"""Issue #209: corporate actions change share units, not plan intent."""
from datetime import date
from decimal import Decimal

import pytest

from sentinel import paper
from sentinel.paper import targets as paper_targets
from sentinel.execution.reconcile import CorporateActionEvent, CorpusActionLookup
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.target_reprojection import (
    TargetProjectionRefused, project_target)
from stock_strategy_shared.wealth_core.adapter import (
    PendingOrder, step_session, tradeability_only_bars)
from stock_strategy_shared.wealth_core.engine import Operation, WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import PortfolioState


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


def test_fractional_held_entitlement_uses_broker_certified_increment_exactly():
    projected = project_target(
        plan(basket={"SEC-A": Decimal("3")}),
        through_session=date(2026, 8, 21),
        action_multipliers={"SEC-A": Decimal("0.1")},
        minimum_quantity_increment=Decimal("0.000000001"))

    assert projected.target_basket == {"SEC-A": Decimal("0.3")}
    assert projected.cancelled_pending_opens == {}


def _pending_split_evidence(ratio="0.1"):
    return ({
        "security_id": "SEC-A", "session": "2026-08-21",
        "action": "split", "value": ratio, "source_row_id": "action-pending",
        "canonical_multiplier": ratio,
        "split_disposition": "provider_oriented_multiplier",
    },)


def test_fractional_pending_open_is_cancelled_even_for_fractional_broker():
    projected = project_target(
        plan(basket={"SEC-A": Decimal("3")}),
        through_session=date(2026, 8, 21),
        action_multipliers={"SEC-A": Decimal("0.1")},
        action_evidence=_pending_split_evidence(),
        canonical_target_shares={"SEC-A": Decimal("3")},
        pending_open_shares={"SEC-A": (Decimal("3"),)},
        minimum_quantity_increment=Decimal("0.000000001"))

    assert projected.target_basket == {"SEC-A": Decimal("0.0")}
    assert projected.cancelled_pending_opens == {
        "SEC-A": (Decimal("3"),)}


def test_cancelled_pending_open_removes_the_account_sized_target():
    """Canonical shares identify intent; plan shares can be NAV-scaled."""
    projected = project_target(
        plan(basket={"SEC-A": Decimal("37")}),
        through_session=date(2026, 8, 21),
        action_multipliers={"SEC-A": Decimal("0.1")},
        action_evidence=_pending_split_evidence(),
        canonical_target_shares={"SEC-A": Decimal("3")},
        pending_open_shares={"SEC-A": (Decimal("3"),)},
        minimum_quantity_increment=Decimal("0.000000001"))

    assert projected.target_basket == {"SEC-A": Decimal("0.0")}
    assert projected.cancelled_pending_opens == {
        "SEC-A": (Decimal("3"),)}


def test_integral_pending_open_survives_the_same_reverse_split():
    projected = project_target(
        plan(basket={"SEC-A": Decimal("10")}),
        through_session=date(2026, 8, 21),
        action_multipliers={"SEC-A": Decimal("0.1")},
        action_evidence=_pending_split_evidence(),
        canonical_target_shares={"SEC-A": Decimal("10")},
        pending_open_shares={"SEC-A": (Decimal("10"),)},
        minimum_quantity_increment=Decimal("0.000000001"))

    assert projected.target_basket == {"SEC-A": Decimal("1.0")}
    assert projected.cancelled_pending_opens == {}


def test_intermediate_fraction_cannot_be_resurrected_by_later_split():
    evidence = (
        {
            "security_id": "SEC-A", "session": "2026-08-21",
            "action": "split", "value": "0.5", "source_row_id": "first",
            "canonical_multiplier": "0.5",
        },
        {
            "security_id": "SEC-A", "session": "2026-08-24",
            "action": "split", "value": "2", "source_row_id": "second",
            "canonical_multiplier": "2",
        },
    )
    projected = project_target(
        plan(basket={"SEC-A": Decimal("3")}),
        through_session=date(2026, 8, 24),
        action_multipliers={"SEC-A": Decimal("1.0")},
        action_evidence=evidence,
        canonical_target_shares={"SEC-A": Decimal("3")},
        pending_open_shares={"SEC-A": (Decimal("3"),)},
        minimum_quantity_increment=Decimal("0.000000001"))

    assert projected.target_basket == {"SEC-A": Decimal("0.0")}
    assert projected.cancelled_pending_opens == {
        "SEC-A": (Decimal("3"),)}


def test_evidenced_net_one_sequence_remains_bound_during_finalization():
    first = date(2026, 8, 21)
    second = date(2026, 8, 24)
    lookup = CorpusActionLookup(
        start=date(2026, 8, 20),
        events={"SEC-A": (
            (first, Decimal("0.5")),
            (second, Decimal("2")),
        )},
        scalar_events=(
            CorporateActionEvent(
                security_id="SEC-A", ticker="AAA", session=first,
                action="split", value="0.5", contraticker=None,
                source_row_id="first", reason="accepted",
                canonical_multiplier=Decimal("0.5")),
            CorporateActionEvent(
                security_id="SEC-A", ticker="AAA", session=second,
                action="split", value="2", contraticker=None,
                source_row_id="second", reason="accepted",
                canonical_multiplier=Decimal("2")),
        ))

    assert paper_targets._target_action_multipliers(  # noqa: SLF001
        plan(basket={"SEC-A": Decimal("3")}), lookup) == {
            "SEC-A": Decimal("1.0")}


def test_pending_open_mixed_with_held_quantity_refuses_decomposition():
    with pytest.raises(TargetProjectionRefused, match="mixed with held/close"):
        project_target(
            plan(basket={"SEC-A": Decimal("8")}),
            through_session=date(2026, 8, 21),
            action_multipliers={"SEC-A": Decimal("0.5")},
            action_evidence=_pending_split_evidence("0.5"),
            canonical_target_shares={"SEC-A": Decimal("8")},
            pending_open_shares={"SEC-A": (Decimal("3"),)},
            held_shares={"SEC-A": Decimal("5")},
            minimum_quantity_increment=Decimal("0.000000001"))


def test_projection_matches_canonical_pending_open_cancellation_end_to_end():
    """The former breach: Core cancels 3 -> .3 while execution bought .3."""
    state = PortfolioState.fresh(1_000)
    state.reserve_slot(0, "SEC-A", "AAA", "issuer-a")
    pending = [PendingOrder(
        operation=Operation.OPEN_SLOT_POSITION,
        security_id="SEC-A", ticker="AAA", slot_id=0, shares=3,
        signal_session="2026-08-20", reason="ENTRY")]
    bar = DailyBar(
        security_id="SEC-A", ticker="AAA", issuer_id="issuer-a",
        session="2026-08-21", signal_close_split_adj_div_unadj=100,
        raw_open=1_000, raw_mark_close=1_000, tradeable=True,
        split_ratio=0.1)
    canonical = step_session(
        session="2026-08-21", state=state, bars=[bar], pending=pending,
        ledger=Ledger(), last_known={}, cfg=WealthCoreConfig(),
        strategy_id="stocker_wealth_core_v1", strategy_version=1,
        security_bars=tradeability_only_bars([bar], None))

    assert pending == []
    assert state.episodes == {}
    assert [item["reason"] for item in canonical.cancelled] == [
        "INEXPRESSIBLE_FRACTIONAL_ENTRY"]

    projected = project_target(
        plan(basket={"SEC-A": Decimal("3")}),
        through_session=date(2026, 8, 21),
        action_multipliers={"SEC-A": Decimal("0.1")},
        action_evidence=_pending_split_evidence(),
        canonical_target_shares={"SEC-A": Decimal("3")},
        pending_open_shares={"SEC-A": (Decimal("3"),)},
        minimum_quantity_increment=Decimal("0.000000001"))
    assert projected.target_basket["SEC-A"] == 0


def _direct_reverse_split_evidence():
    return ({
        "security_id": "SEC-A", "session": "2026-08-21",
        "action": "split", "value": "0.03333", "source_row_id": "action-30",
        "canonical_multiplier": "0.03333333333333333",
        "split_disposition": "published_canonical_equity_ratio",
        "canonical_numerator": 1, "canonical_denominator": 30,
    },)


def test_repeating_reverse_ratio_reconstructs_exact_increment_from_evidence():
    projected = project_target(
        plan(basket={"SEC-A": Decimal("300")}),
        through_session=date(2026, 8, 21),
        action_multipliers={
            "SEC-A": Decimal("0.03333333333333333")},
        action_evidence=_direct_reverse_split_evidence(),
        minimum_quantity_increment=Decimal("1"))

    assert projected.target_basket == {"SEC-A": Decimal("10")}


def test_repeating_reverse_ratio_never_rounds_a_fractional_entitlement():
    with pytest.raises(TargetProjectionRefused, match="not a multiple"):
        project_target(
            plan(basket={"SEC-A": Decimal("301")}),
            through_session=date(2026, 8, 21),
            action_multipliers={
                "SEC-A": Decimal("0.03333333333333333")},
            action_evidence=_direct_reverse_split_evidence(),
            minimum_quantity_increment=Decimal("1"))


def test_repeating_reverse_ratio_without_structured_evidence_still_refuses():
    with pytest.raises(TargetProjectionRefused, match="not a multiple"):
        project_target(
            plan(basket={"SEC-A": Decimal("300")}),
            through_session=date(2026, 8, 21),
            action_multipliers={
                "SEC-A": Decimal("0.03333333333333333")},
            minimum_quantity_increment=Decimal("1"))


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
