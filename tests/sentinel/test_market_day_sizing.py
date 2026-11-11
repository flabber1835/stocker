"""Canonical sizing and compatibility of the explicit PAPER market projection."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from sentinel.execution import market_buy_sizing, target_reprojection
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.opening_prices import OpeningPriceUnavailability, RegularQuotes
from tests.v5.test_opening import base, case, prices


def _quotes(state, plan, *, ask="50", missing=()):
    opening = prices(state, plan, price=ask)
    asks = {sid: price for sid, price in opening.prices.items() if sid not in missing}
    return RegularQuotes(
        session=opening.session, opening_at=opening.opening_at, observed_at=opening.observed_at,
        prices=asks, symbols=opening.symbols, broker_ids=opening.broker_ids,
        bids={sid: price - Decimal("0.01") for sid, price in asks.items()},
        quoted_at={sid: opening.observed_at - timedelta(seconds=1) for sid in asks},
    )


def test_whole_share_projection_binds_original_quote_buffer_and_priority():
    state, plan = case(entries=2)
    before = state.state_hash
    quotes = _quotes(state, plan)
    result = market_buy_sizing.resolve(
        state, plan, base(state, plan), quotes, MarketBuyPolicy(), retained_targets=None)
    assert result.target_basket == {"SEC-AAA": Decimal(98), "SEC-BBB": Decimal(98)}
    assert market_buy_sizing.original_prices(result) == quotes
    assert market_buy_sizing.entry_budget(result, "SEC-AAA") == 5000
    assert market_buy_sizing.validate_projection(result, plan=plan) == MarketBuyPolicy()
    assert state.state_hash == before
    assert target_reprojection._decode(
        result.payload(), plan_id=plan.plan_id, session=plan.effective_session) == result

    changed = replace(result, target_basket={**result.target_basket, "SEC-AAA": Decimal(99)})
    with pytest.raises(target_reprojection.TargetProjectionRefused, match="quote allocation"):
        market_buy_sizing.validate_projection(changed, plan=plan)


def test_missing_quote_is_pending_and_saved_targets_survive():
    state, plan = case(entries=2)
    quotes = _quotes(state, plan, missing={"SEC-AAA"})
    projection = base(state, plan)
    result = market_buy_sizing.resolve(
        state, plan, projection, quotes, MarketBuyPolicy(), retained_targets=None)
    assert result.target_basket == {"SEC-AAA": Decimal(0), "SEC-BBB": Decimal(98)}
    assert market_buy_sizing.unavailable_opening_intents(result) == {"SEC-AAA": "PRICE_PENDING"}

    held = market_buy_sizing.resolve(
        state, plan, projection, quotes, MarketBuyPolicy(), retained_targets={"SEC-AAA": Decimal(31)})
    assert held.target_basket["SEC-AAA"] == 31
    assert market_buy_sizing.entry_budget(held, "SEC-AAA") is None


def test_unavailable_quote_keeps_an_explicit_unresolved_entry():
    state, plan = case()
    unavailable = OpeningPriceUnavailability(plan.effective_session, "opening window closed", {}, {})
    result = market_buy_sizing.resolve(
        state, plan, base(state, plan), unavailable, MarketBuyPolicy(), retained_targets=None)
    assert result.target_basket == {"SEC-AAA": Decimal(0)}
    assert market_buy_sizing.original_prices(result) == unavailable
    assert market_buy_sizing.unavailable_opening_intents(result) == {"SEC-AAA": "PRICE_PENDING"}


def test_fixed_targets_keep_unit_projection_and_policy_drift_refuses(monkeypatch):
    monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY", raising=False)
    state, plan = case(entries=0)
    projection = base(state, plan)
    result = market_buy_sizing.resolve(
        state, plan, projection, None, MarketBuyPolicy(), retained_targets=None)
    assert result == projection
    assert market_buy_sizing.original_prices(result) is None
    assert market_buy_sizing.validate_projection(result, plan=plan) == MarketBuyPolicy()
    with pytest.raises(target_reprojection.TargetProjectionRefused, match="current policy"):
        market_buy_sizing.validate_projection(result, require_current_policy=True, plan=plan)
