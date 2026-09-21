"""A spin-off's child value must never become a parent cash dividend."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.feed import VendorBar
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from sentinel.core.spinoffs import (
    LIQUIDATE_CHILD_AT_OPEN,
    SpinoffDistribution,
    SpinoffTermsRequired,
    apply_supported_entitlements,
    require_supported_entitlements,
)
from sentinel.feed.actions_map import dividends_from_actions
from sentinel.execution.reconcile import SAFE_NON_BOOK_ACTIONS
from test_production_state import _fresh, _advance, _published


def event(**kwargs):
    values = {
        "session": "2026-08-11", "parent_ticker": "ADP",
        "parent_security_id": "P:ADP", "child_ticker": "CDK",
        "child_security_id": "P:CDK", "source_row_id": "source-adp-cdk",
        "value_evidence": "10"}
    values.update(kwargs)
    return SpinoffDistribution(**values)


def complete_event(**kwargs):
    values = {"child_shares_per_parent": "1", "child_price": "31.5",
              "policy": LIQUIDATE_CHILD_AT_OPEN}
    values.update(kwargs)
    return event(**values)


def held_state(*, shares=105):
    state = PortfolioState.fresh(1_000)
    state.slots[0].occupied_by = "P:ADP"
    state.episodes[0] = HoldingEpisode(
        security_id="P:ADP", ticker="ADP", issuer_id="I:ADP", slot_id=0,
        signal_date="2025-01-01", entry_date="2025-01-02",
        entry_raw_open=65.98, entry_split_adjusted_price=65.98,
        initial_shares=shares, current_shares=shares,
        episode_peak_split_adjusted_close=77.0,
        source_lots=[])
    return state


def bars():
    return [
        VendorBar("2026-08-11", "P:ADP", "ADP", 38.86, 37.55, 1_000_000),
        VendorBar("2026-08-11", "P:CDK", "CDK", 31.50, 31.90, 1_000_000),
    ]


def test_adp_cdk_value_has_no_cash_authority_and_cash_distributions_remain_exact():
    from decimal import Decimal
    rows = [{"ticker": "ADP", "date": "2014-10-01", "action": "spinoffdividend", "value": "10"},
            {"ticker": "ADP", "date": "2014-10-01", "action": "dividend", "value": "0.1"},
            {"ticker": "ADP", "date": "2014-10-01", "action": "specialdividend", "value": "0.2"}]
    assert dividends_from_actions(rows, ["2014-10-01"]) == {("ADP", "2014-10-01"): Decimal("0.3")}
    assert "spinoffdividend" not in SAFE_NON_BOOK_ACTIONS


@pytest.mark.parametrize("distribution", [event(), event(child_shares_per_parent="1/3", child_price="30")])
def test_one_for_three_distribution_requires_reviewed_child_ownership(distribution):
    state = SimpleNamespace(wealth_core={"episodes": {"parent": {
        "security_id": "P:ADP", "ticker": "ADP", "current_shares": 300}}})
    original = deepcopy(state.wealth_core)
    with pytest.raises(SpinoffTermsRequired, match="CHILD_OWNERSHIP_REQUIRED"):
        require_supported_entitlements(state, [distribution])
    assert state.wealth_core == original


def test_complete_distribution_liquidates_child_and_rebases_parent_stop():
    state, ledger = held_state(), Ledger()
    audit = apply_supported_entitlements(
        state, [complete_event()], bars=bars(), ledger=ledger,
        config=WealthCoreConfig())

    scale = 37.55 / (37.55 + 31.90)
    expected = 1_000 + 105 * 31.90 * (1 - 0.001)
    assert state.cash == pytest.approx(expected)
    assert state.episodes[0].current_shares == 105
    assert state.episodes[0].entry_split_adjusted_price == pytest.approx(
        65.98 * scale)
    assert state.episodes[0].episode_peak_split_adjusted_close == pytest.approx(77 * scale)
    assert not state.episodes[0].stop_triggered(38.86)
    assert [row.event_type for row in ledger.events] == [
        EventType.SPINOFF_RECEIPT, EventType.SPINOFF_LIQUIDATION]
    assert audit[0]["whole_child_shares"] == 105
    assert audit[0]["gross_child_value"] == pytest.approx(3349.5)

    restored_state = PortfolioState.from_dict(
        json.loads(json.dumps(state.to_dict())))
    restored_ledger = Ledger.from_dict(
        json.loads(json.dumps(ledger.to_dict())))
    assert restored_state.to_dict() == state.to_dict()
    assert restored_ledger.to_dict() == ledger.to_dict()


def test_fractional_entitlements_round_once_at_holder_boundary():
    state, ledger = held_state(shares=1), Ledger()
    state.slots[1].occupied_by = "P:ADP"
    state.episodes[1] = replace(
        state.episodes[0], slot_id=1, source_lots=[])

    audit = apply_supported_entitlements(
        state, [complete_event(child_shares_per_parent="1/2")],
        bars=bars(), ledger=ledger, config=WealthCoreConfig())

    assert audit[0]["whole_child_shares"] == 1
    assert audit[0]["fractional_child_shares"] == "0"
    assert state.cash == pytest.approx(1_000 + 31.90 * (1 - 0.001))


def test_missing_fractional_cash_in_lieu_is_atomic():
    state, ledger = held_state(shares=1), Ledger()
    before = deepcopy(state.to_dict())
    with pytest.raises(SpinoffTermsRequired, match="cash-in-lieu"):
        apply_supported_entitlements(
            state, [complete_event(child_shares_per_parent="1/3")],
            bars=bars(), ledger=ledger, config=WealthCoreConfig())
    assert state.to_dict() == before
    assert not ledger.events


def test_held_ticker_with_unresolved_parent_identity_refuses_atomically():
    state, ledger = held_state(), Ledger()
    before = deepcopy(state.to_dict())
    with pytest.raises(SpinoffTermsRequired, match="identity is unresolved"):
        apply_supported_entitlements(
            state, [complete_event(parent_security_id=None)],
            bars=bars(), ledger=ledger, config=WealthCoreConfig())
    assert state.to_dict() == before
    assert not ledger.events


def test_canonical_kernel_checks_entitlement_before_any_accounting(monkeypatch):
    config, fresh = _fresh()
    prior = _advance(fresh, _published(), config)
    portfolio = PortfolioState.from_dict(prior.wealth_core)
    portfolio.slots[0].occupied_by = "P:ADP"
    portfolio.slots[0].release_reservation()
    portfolio.episodes[0] = held_state(shares=300).episodes[0]
    prior.wealth_core = portfolio.to_dict()
    reached = []
    monkeypatch.setattr("sentinel.core.kernel.plan_session", lambda **_: reached.append(True))
    published = replace(_published("2026-08-11"), spinoff_distributions=(event(),))
    with pytest.raises(SpinoffTermsRequired):
        _advance(prior, published, config)
    assert not reached


def test_unheld_parent_has_no_entitlement():
    require_supported_entitlements(SimpleNamespace(wealth_core={"episodes": {}}), [event()])
    state, ledger = PortfolioState.fresh(1_000), Ledger()
    assert apply_supported_entitlements(
        state, [event()], bars=bars(), ledger=ledger,
        config=WealthCoreConfig()) == ()
    assert state.cash == 1_000
    assert not ledger.events
