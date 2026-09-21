"""Economic oracles for distributing cash out of a continuing stock episode."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D

import pytest

from tests.wealth_core.test_conversion_prior_basis import case, run_case


def mixed(*, cash=60, opening=40, closing=40, shares=10, ratio=1, lieu=None):
    state, feed, terms, bars = case()
    ep = state.episodes[0]
    ep.current_shares = ep.initial_shares = shares
    ep.entry_raw_open = 100
    ep.entry_split_adjusted_price = 200
    ep.episode_peak_split_adjusted_close = 240
    ep.market_sessions_held = 50
    ep.review_completed = True
    feed.series["BRL"].raw_closes[-1] = 100
    feed.series["BRL"].signal_closes[-1] = 200
    terms = replace(terms, cash_per_share=cash, exchange_ratio=ratio,
                    cash_in_lieu_price_per_delivered_share=lieu)
    return state, feed, terms, [replace(bars[0], raw_open=opening, raw_close=closing)]


def test_distribution_preserves_drawdown_without_resetting_peak_or_age():
    args = mixed()
    out = run_case(*args)
    ep = out.state.episodes[0]
    # $120 peak, $100 entry, $60 cash + $40 stock: keep 40% of each reference.
    # Delivered signal units are half raw units; source units are twice raw.
    assert ep.episode_peak_split_adjusted_close == pytest.approx(48*.5)
    assert ep.entry_split_adjusted_price == pytest.approx(40*.5)
    assert ep.entry_raw_open == pytest.approx(40)
    assert 20/ep.episode_peak_split_adjusted_close == pytest.approx(100/120)
    assert ep.market_sessions_held == 51 and ep.review_completed
    assert not ep.exit_pending
    assert out.state.cash == 10600
    assert out.sessions[0].resolved_equity == 11000


@pytest.mark.parametrize("cash,opening,closing,stop", [
    (30, 40, 40, True),  # package loses value: 70 / 120 < 70%
    (60, 40, 20, True),  # after distribution stock loses half; cash cannot shield it
    (80, 40, 40, False),  # package reaches the old peak
    (60, 50, 50, False),  # a real premium is retained, not normalized away
])
def test_real_losses_and_premiums_remain_visible(cash, opening, closing, stop):
    out = run_case(*mixed(cash=cash, opening=opening, closing=closing))
    ep = out.state.episodes[0]
    expected = D(120)*D(opening)/(D(cash)+D(opening))*D('.5')
    assert ep.episode_peak_split_adjusted_close == pytest.approx(max(float(expected), closing*.5))
    assert ep.exit_pending is stop


def test_fractional_cash_is_in_package_and_floor_happens_once_per_holder():
    state, feed, terms, bars = mixed(cash=10, opening=40, closing=40,
                                   shares=3, ratio=.5, lieu=40)
    # Two episodes own 1 and 2 source shares, not two separately rounded holders.
    ep = state.episodes[0]
    ep.current_shares = ep.initial_shares = 1
    second = deepcopy(ep)
    second.slot_id = 1
    second.current_shares = second.initial_shares = 2
    state.episodes[1] = second
    state.slots[1].occupied_by = "BRL"
    out = run_case(state, feed, terms, bars)
    # 1.5 gross -> 1 whole, $20 CIL + $30 cash; total package $90.
    assert sum(x.current_shares for x in out.state.episodes.values()) == 1
    assert out.state.cash == 10050
    assert out.sessions[0].resolved_equity == 10090
    for ep in out.state.episodes.values():
        assert ep.episode_peak_split_adjusted_close == pytest.approx(120*3*40/90*.5)


@pytest.mark.parametrize("opening", [None, 0, float('nan'), float('inf')])
def test_missing_opening_value_blocks_before_any_economic_mutation(opening):
    state, feed, terms, bars = mixed(opening=opening)
    out = run_case(state, feed, terms, bars)
    assert state.cash == 10000
    assert state.episodes[0].security_id == "BRL"
    assert state.episodes[0].current_shares == 10
    assert not out.ledger.events
    assert out.terminal_results[0]["reason"] == "MISSING_CONVERSION_OPENING_VALUE"


def test_a_current_close_cannot_repair_missing_opening_value():
    state, feed, terms, bars = mixed(opening=None)
    from stock_strategy_shared.wealth_core.feed import VendorBar
    bars.append(VendorBar(terms.session, "BRL", "BRL", 100, 100, 1000))
    out = run_case(state, feed, terms, bars)
    assert all(not x["applied"] for x in out.terminal_results)
    assert state.episodes[0].security_id == "BRL"
    assert state.cash == 10000


def test_all_cash_fraction_releases_without_delivered_open_or_basis():
    state, feed, terms, _ = mixed(shares=1, ratio=.5, lieu=40)
    out = run_case(state, feed, terms, [])
    assert not state.episodes
    assert state.cash == 10080
    assert out.terminal_results[0]["applied"]


def test_existing_exit_is_preserved_and_restart_is_identical():
    from sentinel.core.session import _feed_from_dict, _feed_to_dict
    state, feed, terms, bars = mixed()
    state.episodes[0].exit_pending = True
    state.episodes[0].exit_reason = "EXIT_TRAILING_STOP"
    restored = _feed_from_dict(_feed_to_dict(feed, {"BRL", "TEVA"}), feed.meta, feed.cfg)
    left = run_case(deepcopy(state), feed, terms, bars)
    right = run_case(deepcopy(state), restored, terms, bars)
    assert left.result_hash() == right.result_hash()
    assert left.state.episodes[0].exit_pending


def test_unrepresentable_reference_blocks_all_episodes_before_mutation():
    from stock_strategy_shared.wealth_core.terminal import apply_terminal
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
    state, _, terms, _ = mixed(cash=1, ratio=.5)
    second = deepcopy(state.episodes[0])
    second.slot_id = 1
    second.entry_raw_open = 1e308
    state.episodes[1] = second
    state.slots[1].occupied_by = "BRL"
    before = state.to_dict()
    ledger = Ledger()
    result = apply_terminal(state, terms, ledger=ledger, session=terms.session,
                            cfg=WealthCoreConfig(), source_signal_to_raw_scale=2,
                            delivered_signal_to_raw_scale=.5, delivered_raw_open=40)
    assert state.cash == before["cash"]
    assert all(ep.security_id == "BRL" for ep in state.episodes.values())
    assert result["reason"] == "INVALID_CONVERSION_REFERENCE_SCALE"
    assert state.to_dict() == {**before, "unresolved_terminals": {
        "BRL": "INVALID_CONVERSION_REFERENCE_SCALE"}}
    assert not ledger.events


def test_zero_cash_for_fraction_does_not_hide_the_lost_fraction():
    out = run_case(*mixed(cash=0, shares=3, ratio=.5, lieu=0))
    ep = out.state.episodes[0]
    assert ep.current_shares == 1
    assert out.state.cash == 10000
    # Full prior peak value is carried by the one remaining share; no cash was paid.
    assert ep.episode_peak_split_adjusted_close == pytest.approx(3*120*.5)
