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


def siblings():
    return [complete_event(child_shares_per_parent="1/2", cash_in_lieu_price="30"),
            complete_event(child_ticker="CHILD2", child_security_id="P:CHILD2",
                           source_row_id="second-child", child_shares_per_parent="1/3",
                           cash_in_lieu_price="18")]


def sibling_bars():
    return bars() + [VendorBar("2026-08-11", "P:CHILD2", "CHILD2",
                              19.0, 18.0, 1_000_000)]


def assert_money(actual, expected):
    from decimal import Decimal
    assert abs(Decimal(str(actual)) - Decimal(str(expected))) < Decimal("0.00000001")


@pytest.mark.parametrize("shares", [2, 3, 105])
def test_multiple_children_independent_financial_oracle(shares):
    from decimal import Decimal
    from fractions import Fraction
    state, ledger = held_state(shares=shares), Ledger()
    before = deepcopy(state.to_dict())
    audit = apply_supported_entitlements(state, siblings(), bars=sibling_bars(),
                                        ledger=ledger, config=WealthCoreConfig())
    cash = Decimal("1000")
    expected_fees = Decimal(0)
    for index, (ratio, price, cil) in enumerate([(Fraction(1, 2), "31.90", "30"),
                                               (Fraction(1, 3), "18", "18")]):
        entitled = shares * ratio
        whole = entitled.numerator // entitled.denominator
        fraction = entitled - whole
        fee = Decimal(whole) * Decimal(price) / 1000
        payout = (Decimal(whole) * Decimal(price) - fee
                  + Decimal(fraction.numerator) / Decimal(fraction.denominator) * Decimal(cil))
        expected_fees += fee
        cash += payout
        assert audit[index]["whole_child_shares"] == whole
        assert audit[index]["fractional_child_shares"] == str(fraction)
        assert_money(audit[index]["cash_proceeds"], payout)
        assert_money(ledger.events[2 * index + 1].cash_after, cash)
        assert_money(ledger.events[2 * index + 1].fees, fee)
    assert_money(state.cash, cash)
    assert_money(sum(e.fees for e in ledger.events), expected_fees)
    scale = Decimal("37.55") / (Decimal("37.55") + Decimal("15.95") + Decimal("6"))
    assert_money(state.episodes[0].entry_split_adjusted_price, Decimal("65.98") * scale)
    assert_money(state.episodes[0].episode_peak_split_adjusted_close, Decimal(77) * scale)
    after = state.to_dict()
    assert after["slots"] == before["slots"]
    for key, value in before["episodes"]["0"].items():
        if key not in {"entry_split_adjusted_price", "episode_peak_split_adjusted_close", "source_lots"}:
            assert after["episodes"]["0"][key] == value
    assert len(state.episodes[0].source_lots) == 2
    assert [e.event_type for e in ledger.events] == [EventType.SPINOFF_RECEIPT,
        EventType.SPINOFF_LIQUIDATION] * 2
    assert_money(state.cash + shares * 38.86, cash + Decimal(shares) * Decimal("38.86"))


def test_multiple_children_round_each_at_holder_boundary():
    state, ledger = held_state(shares=1), Ledger()
    state.slots[1].occupied_by = "P:ADP"
    state.episodes[1] = replace(state.episodes[0], slot_id=1, current_shares=2,
                              initial_shares=2, source_lots=[])
    audit = apply_supported_entitlements(state, siblings(), bars=sibling_bars(),
                                        ledger=ledger, config=WealthCoreConfig())
    assert [(a["whole_child_shares"], a["fractional_child_shares"]) for a in audit] == [(1, "1/2"), (1, "0")]
    assert_money(state.cash, "1064.8501")
    assert state.episodes[0].entry_split_adjusted_price == state.episodes[1].entry_split_adjusted_price
    assert [state.episodes[i].current_shares for i in (0, 1)] == [1, 2]


def test_lvnta_two_share_fractional_entitlements():
    state, ledger = held_state(shares=2), Ledger()
    state.episodes[0].ticker = "LVNTA"
    events = [complete_event(parent_ticker="LVNTA", child_ticker=ticker,
              child_security_id="P:" + ticker, source_row_id=ticker,
              child_shares_per_parent=ratio, cash_in_lieu_price=price)
              for ticker, ratio, price in [("CHUBA", "1/10", "13.60"), ("CHUBK", "1/5", "13.51")]]
    opening = [replace(bars()[0], ticker="LVNTA")] + [
        VendorBar("2026-08-11", "P:" + ticker, ticker, price, price, 1000000)
        for ticker, price in [("CHUBA", 13.60), ("CHUBK", 13.51)]]
    audit = apply_supported_entitlements(state, events, bars=opening,
                                        ledger=ledger, config=WealthCoreConfig())
    assert [a["whole_child_shares"] for a in audit] == [0, 0]
    assert_money(audit[0]["cash_proceeds"], "2.72")
    assert_money(audit[1]["cash_proceeds"], "5.404")
    assert_money(state.cash, "1008.124")
    assert sum(e.fees for e in ledger.events) == 0
    assert state.episodes[0].current_shares == 2


@pytest.mark.parametrize("change", [{}, {"source_row_id": "different-source"},
    {"source_row_id": "different-source", "child_shares_per_parent": "2"},
    {"source_row_id": "different-source", "child_ticker": "CONFLICT"}])
def test_duplicate_child_refuses_even_with_distinct_source(change):
    state, ledger = held_state(), Ledger()
    before = deepcopy(state.to_dict())
    with pytest.raises(SpinoffTermsRequired, match="duplicate"):
        apply_supported_entitlements(state, [siblings()[0], replace(siblings()[0], **change)],
            bars=sibling_bars(), ledger=ledger, config=WealthCoreConfig())
    assert state.to_dict() == before
    assert not ledger.events


@pytest.mark.parametrize("change", [{"child_shares_per_parent": None},
    {"cash_in_lieu_price": None}, {"child_ticker": "WRONG"},
    {"child_security_id": "MISSING"}, {"policy": "UNKNOWN"}, {"session": "2026-08-12"}])
def test_invalid_later_sibling_is_atomic(change):
    state, ledger = held_state(shares=2), Ledger()
    ledger.post(session="2026-08-10", event_type=EventType.DIVIDEND_PAID,
                cash_before=999, cash_delta=1)
    before = deepcopy((state.to_dict(), ledger.to_dict()))
    with pytest.raises(SpinoffTermsRequired):
        apply_supported_entitlements(state, [siblings()[0], replace(siblings()[1], **change)],
            bars=sibling_bars(), ledger=ledger, config=WealthCoreConfig())
    assert (state.to_dict(), ledger.to_dict()) == before


@pytest.mark.parametrize("index", [0, 1, 2])
def test_ambiguous_opening_identity_refuses_atomically(index):
    state, ledger = held_state(), Ledger()
    before = deepcopy(state.to_dict())
    with pytest.raises(SpinoffTermsRequired, match="ambiguous"):
        apply_supported_entitlements(state, siblings(), bars=sibling_bars() + [sibling_bars()[index]],
            ledger=ledger, config=WealthCoreConfig())
    assert state.to_dict() == before
    assert not ledger.events


def test_sibling_order_and_serialized_restart_are_identical():
    outputs = []
    for events in (siblings(), list(reversed(siblings()))):
        state = PortfolioState.from_dict(json.loads(json.dumps(held_state(shares=3).to_dict())))
        ledger = Ledger.from_dict(json.loads(json.dumps(Ledger().to_dict())))
        audit = apply_supported_entitlements(state, events, bars=list(reversed(sibling_bars())),
            ledger=ledger, config=WealthCoreConfig())
        outputs.append(json.dumps((state.to_dict(), ledger.to_dict(), audit), sort_keys=True))
        assert PortfolioState.from_dict(json.loads(json.dumps(state.to_dict()))).to_dict() == state.to_dict()
        assert Ledger.from_dict(json.loads(json.dumps(ledger.to_dict()))).to_dict() == ledger.to_dict()
    assert outputs[0] == outputs[1]


def test_multiple_children_through_canonical_kernel_and_restart():
    from sentinel.core.production import SessionState
    from stock_strategy_shared.wealth_core.feed import SecurityMeta
    config, fresh = _fresh()
    opening = sibling_bars()
    meta = {b.security_id: SecurityMeta(b.security_id, b.ticker,
        category="Domestic Common Stock", permaticker=b.security_id, first_session="2026-08-10")
        for b in opening}
    initial = replace(_published(), meta=meta,
                      bars=[replace(b, session="2026-08-10") for b in opening])
    prior = _advance(fresh, initial, config)
    prior.wealth_core = held_state(shares=3).to_dict()
    before = deepcopy(prior.to_dict())
    published = replace(_published("2026-08-11"), meta=meta, bars=opening,
                        spinoff_distributions=tuple(siblings()))
    after = _advance(prior, published, config)
    restored = SessionState.from_dict(json.loads(json.dumps(prior.to_dict())))
    assert _advance(restored, published, config).to_dict() == after.to_dict()
    assert prior.to_dict() == before
    assert_money(after.wealth_core["cash"], "1064.8501")
    assert_money(after.shadow_nav_history[-1], "1181.4301")
    liquidations = [e for e in after.ledger["events"] if e["event_type"] == "SPINOFF_LIQUIDATION"]
    assert len(liquidations) == 2
    next_day = replace(published, session="2026-08-12", spinoff_distributions=(),
                       bars=[replace(b, session="2026-08-12") for b in opening],
                       **{k: getattr(_published("2026-08-12"), k) for k in
                          ("spy_closeadj", "spy_sessions", "spy_expected_sessions")})
    assert _advance(after, next_day, config).to_dict() == _advance(
        SessionState.from_dict(json.loads(json.dumps(after.to_dict()))), next_day, config).to_dict()
