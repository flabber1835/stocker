"""Independent entitlement and price-domain oracles for a delisted predecessor."""
from copy import deepcopy
from decimal import Decimal

import pytest

from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.run import run_sessions
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms


def case():
    meta = {s: SecurityMeta(s, s, permaticker=s) for s in ("BRL", "TEVA")}
    feed = Feed(meta)
    feed.warmup(["2008-12-22"], {"2008-12-22": [
        VendorBar("2008-12-22", "BRL", "BRL", 65.8, 65.8, 1000, split_ratio=2),
        VendorBar("2008-12-22", "TEVA", "TEVA", 41.82, 41.82, 1000, split_ratio=.5)]})
    state = PortfolioState.fresh(10000)
    state.initialized = True
    state.slots[0].occupied_by = "BRL"
    state.episodes[0] = HoldingEpisode(
        "BRL", "BRL", meta["BRL"].issuer_key()[0], 0, "2008-12-01", "2008-12-01",
        65.8, 131.6, 70, 70, 131.6)
    terms = TerminalTerms(
        session="2008-12-23", security_id="BRL", kind=TerminalKind.CASH_PLUS_STOCK,
        cash_per_share=39.9, delivered_security_id="TEVA", delivered_ticker="TEVA",
        delivered_issuer_id=meta["TEVA"].issuer_key()[0], exchange_ratio=.6272,
        cash_in_lieu_price_per_delivered_share=41.82)
    bars = [VendorBar("2008-12-23", "TEVA", "TEVA", 41.99, 42.11, 1000)]
    return state, feed, terms, bars


def run_case(state, feed, terms, bars):
    return run_sessions(sessions=[terms.session], bars_by_session={terms.session: bars},
                        meta=feed.meta, starting_cash=10000, state=state, feed=feed,
                        terminal_events=[terms])


def test_absent_predecessor_uses_owned_basis_and_exact_cash_share_oracle():
    state, feed, terms, bars = case()
    out = run_case(state, feed, terms, bars)
    ep = state.episodes[0]
    quantity = Decimal(70) * Decimal("0.6272")
    shares = int(quantity)
    cash = Decimal(70) * Decimal("39.90") + (quantity-shares) * Decimal("41.82")
    assert ep.security_id == "TEVA"
    assert ep.current_shares == shares == 43
    assert state.cash == pytest.approx(float(Decimal(10000)+cash))
    assert ep.episode_peak_split_adjusted_close == pytest.approx(131.6/.6272*.5/2)
    assert out.sessions[0].resolved_open_equity == pytest.approx(float(10000+cash)+43*42.11)
    assert out.sessions[0].resolved_equity == pytest.approx(float(10000+cash)+43*41.99)
    assert out.terminal_results[0]["source_signal_basis"]["session"] == "2008-12-22"


@pytest.mark.parametrize("fault", ["missing", "stale", "wrong_id", "wrong_date",
                                    "zero", "nan", "infinite", "unaligned", "anchor"])
def test_unusable_prior_basis_never_settles(fault):
    state, feed, terms, bars = case()
    series = feed.series["BRL"]
    if fault == "missing":
        del feed.series["BRL"]
    elif fault == "stale":
        feed.warmup(["2008-12-23"], {})
        from dataclasses import replace
        terms = replace(terms, session="2008-12-24")
        bars = [replace(bars[0], session=terms.session)]
    elif fault == "wrong_id":
        series.security_id = "OTHER"
    elif fault == "wrong_date":
        series.sessions[-1] = "2008-12-19"
    elif fault == "unaligned":
        series.raw_closes = []
    elif fault == "anchor":
        series.signal_basis_anchor = ["2008-12-22", 65.8, 65.8]
    else:
        series.signal_closes[-1] = {"zero": 0, "nan": float("nan"), "infinite": float("inf")}[fault]
    out = run_case(state, feed, terms, bars)
    assert state.episodes[0].security_id == "BRL"
    assert state.episodes[0].current_shares == 70
    assert state.cash == 10000
    assert out.terminal_results[0]["reason"] == "MISSING_CONVERSION_SIGNAL_BASIS"
    assert out.sessions[0].resolved_equity is None


def test_present_invalid_source_bar_cannot_use_prior_basis():
    state, feed, terms, bars = case()
    bars.append(VendorBar(terms.session, "BRL", "BRL", None, None, 1000))
    out = run_case(state, feed, terms, bars)
    assert out.terminal_results[0]["reason"] == "MISSING_CONVERSION_SIGNAL_BASIS"


def test_missing_delivered_open_remains_unresolved():
    from dataclasses import replace
    state, feed, terms, bars = case()
    out = run_case(state, feed, terms, [replace(bars[0], raw_open=None)])
    assert state.episodes[0].security_id == "TEVA"
    assert out.sessions[0].resolved_open_equity is None
    assert out.sessions[0].open_unresolved_security_ids == ("TEVA",)


def test_missing_delivered_basis_never_uses_its_prior_observation():
    state, feed, terms, _ = case()
    out = run_case(state, feed, terms, [])
    assert state.cash == 10000
    assert state.episodes[0].security_id == "BRL"
    assert out.terminal_results[0]["reason"] == "MISSING_CONVERSION_SIGNAL_BASIS"


def test_current_source_split_takes_precedence_over_prior_basis():
    state, feed, terms, bars = case()
    bars.append(VendorBar(terms.session, "BRL", "BRL", 32.9, 32.9, 1000, split_ratio=2))
    out = run_case(state, feed, terms, bars)
    ep = state.episodes[0]
    assert ep.current_shares == int(Decimal(140)*Decimal("0.6272")) == 87
    assert ep.episode_peak_split_adjusted_close == pytest.approx(131.6/.6272*.5/4)
    assert "source_signal_basis" not in out.terminal_results[0]


def test_publication_rebase_preserves_owned_prior_basis():
    state, feed, terms, bars = case()
    source = feed.series["BRL"]
    source.signal_basis_anchor = ["2008-12-22", 65.8, 131.6]
    source.reconcile_signal_basis(VendorBar(
        "2008-12-22", "BRL", "BRL", 65.8, 65.8, 1000, signal_close=13.16))
    assert feed.prior_conversion_basis("BRL")["signal_to_raw_scale"] == 2
    out = run_case(state, feed, terms, bars)
    assert out.state.episodes[0].security_id == "TEVA"


def test_incompatible_publication_anchor_still_refuses():
    from stock_strategy_shared.wealth_core.feed import FeedError
    _, feed, _, _ = case()
    with pytest.raises(FeedError, match="incomplete or revised"):
        feed.series["BRL"].reconcile_signal_basis(VendorBar(
            "2008-12-22", "BRL", "BRL", 60, 60, 1000, signal_close=13.16))


def test_retained_feed_serialization_preserves_conversion():
    from sentinel.core.session import _feed_from_dict, _feed_to_dict
    state, feed, terms, bars = case()
    restored = _feed_from_dict(_feed_to_dict(feed, {"BRL", "TEVA"}), feed.meta, feed.cfg)
    left = run_case(deepcopy(state), feed, terms, bars)
    right = run_case(deepcopy(state), restored, terms, bars)
    assert left.result_hash() == right.result_hash()
    assert right.state.episodes[0].security_id == "TEVA"
