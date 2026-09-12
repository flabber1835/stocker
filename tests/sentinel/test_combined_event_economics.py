"""Whole-event accounting through production normalization and session kernel."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
import json

import pytest

from sentinel.controller.machine import Controller
from sentinel.core.kernel import advance_session
from sentinel.core.production import PublishedSession, SessionState
from sentinel.feed import actions_map, calendar, corporate_action_authority as CAA, sharadar
from sentinel.feed.domains import RawPriceDomainUnavailable, normalise_sep_rows
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.engine import Operation
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.sharadar_domains import raw_dividend_per_share
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms
from tests.sentinel.test_corporate_action_cash_adjudication import (
    EVENT_DAY, RATIO, tri_vendor,
)
from tests.sentinel.test_production_state import _fresh


PRE, NEXT = "2026-05-01", "2026-05-05"
OLD_SHARES = 1000
EXPECTED_CASH = Decimal("1435.518000")


def normalized_tri(*, rebase=1, cash="1.36"):
    fetch = tri_vendor(rebase=rebase, cash=cash)
    rows = [r for r in fetch(sharadar.SEP) if r["date"] >= PRE]
    days = sorted(r["date"] for r in rows)
    source = fetch(sharadar.ACTIONS)
    splits, ambiguous = actions_map.split_rows_from_actions(source, days)
    assert not ambiguous
    resolution = CAA.resolve_dividends(source, days)
    result = list(normalise_sep_rows(
        rows, resolve_identity=lambda *_: "TRI", authoritative_splits=splits,
        dividends=resolution.dividends))
    return [replace(row, vendor=replace(row.vendor, signal_close=row.close_signal)) for row in result]


def published(day, bars, *, version=7):
    meta = {b.security_id: SecurityMeta(
        b.security_id, b.ticker, category="Domestic Common Stock",
        permaticker=b.security_id, first_session=PRE) for b in bars}
    spy_days = calendar.previous_sessions(day, 41)
    return PublishedSession(
        session=day, data_version=version, bars=bars, meta=meta,
        sectors={sid: "Industrials" for sid in meta},
        spy_sessions=spy_days, spy_expected_sessions=spy_days,
        spy_closeadj=[100. + i * .1 for i in range(len(spy_days))])


def advance(state, value, config):
    return advance_session(state, value, controller_config=config,
                           strategy_identity=state.strategy_identity)


def held_seed(bars, *, champion=True, shares=OLD_SHARES, cash=100.):
    if champion:
        config, identity = production_strategy()
        state = SessionState.fresh(starting_cash=100000., controller=Controller(config),
                                   strategy_identity=identity)
    else:
        config, state = _fresh()
    state = advance(state, published(PRE, bars), config)
    portfolio = PortfolioState.from_dict(state.wealth_core)
    portfolio.cash = cash
    portfolio.initialized = True
    first = bars[0]
    portfolio.slots[0].occupied_by = first.security_id
    portfolio.episodes[0] = HoldingEpisode(
        first.security_id, first.ticker, "P:" + first.security_id, 0,
        PRE, PRE, first.raw_open, (first.signal_close if champion else first.raw_close), shares, shares,
        (first.signal_close if champion else first.raw_close))
    state.wealth_core = portfolio.to_dict()
    return config, state


@pytest.mark.parametrize("champion", [False, True])
@pytest.mark.parametrize("cash", ["1.36", "1.435518"])
@pytest.mark.parametrize("rebase", [1, 5, Decimal("0.5")])
def test_combined_event_conserves_old_share_cash_through_kernel_and_restart(
        champion, cash, rebase):
    normalized = normalized_tri(rebase=rebase, cash=cash)
    prior_bar, event_bar = normalized[0].vendor, normalized[1].vendor
    assert event_bar.split_ratio == float(RATIO)
    assert event_bar.dividend_per_share == float(Fraction(1435518, 984560))
    config, seed = held_seed([prior_bar], champion=champion)
    prior = deepcopy(seed.to_dict())
    uninterrupted = advance(seed, published(EVENT_DAY, [event_bar]), config)
    restarted = advance(SessionState.from_dict(json.loads(json.dumps(prior))),
                        published(EVENT_DAY, [event_bar]), config)
    assert uninterrupted.to_dict() == restarted.to_dict()
    assert seed.to_dict() == prior
    book = PortfolioState.from_dict(uninterrupted.wealth_core)
    ledger = Ledger.from_dict(uninterrupted.ledger)
    assert book.episodes[0].current_shares == 984.56
    assert ledger.receivable_total() == pytest.approx(float(EXPECTED_CASH), abs=1e-10)
    assert book.cash == 100.
    expected_nav = Decimal(100) + Decimal("984.56") * Decimal(99) + EXPECTED_CASH
    assert uninterrupted.last_evidence["wealth_core"]["resolved_open_equity"] == \
        pytest.approx(float(expected_nav), abs=1e-9)
    # The next opening receives cash exactly once; the claim survives restart.
    next_bar = next(b.vendor for b in normalized if b.vendor.session == NEXT)
    resumed = SessionState.from_dict(json.loads(json.dumps(uninterrupted.to_dict())))
    settled = advance(resumed, published(NEXT, [next_bar]), config)
    assert settled.wealth_core["cash"] == pytest.approx(1535.518, abs=1e-10)
    assert Ledger.from_dict(settled.ledger).receivable_total() == 0
    assert sum(e.event_type is EventType.DIVIDEND_PAID
               for e in Ledger.from_dict(settled.ledger).events) == 1
    with pytest.raises(ValueError, match="advance strictly"):
        advance(settled, published(NEXT, [next_bar], version=8), config)


def test_equivalent_later_adjustments_preserve_cash_holdings_and_controller():
    runs = []
    for factor in (1, 5, Decimal("0.5")):
        bars = normalized_tri(rebase=factor)
        config, state = held_seed([bars[0].vendor])
        for row in bars[1:]:
            state = advance(state, published(row.vendor.session, [row.vendor]), config)
        book = PortfolioState.from_dict(state.wealth_core)
        runs.append((book.cash, {sid: (ep.security_id, ep.current_shares)
                                 for sid, ep in book.episodes.items()},
                     state.ledger, state.pending, state.controller, state.shadow_nav_history))
    assert runs[0] == runs[1] == runs[2]


@pytest.mark.parametrize("exit_at_event", [False, True])
def test_cash_entitlement_follows_prior_holding_and_funds_next_open_sizing(exit_at_event):
    bars = normalized_tri()
    extra = VendorBar(PRE, "BUY", "BUY", 10., 10., 1000000., signal_close=10.)
    config, seed = held_seed([bars[0].vendor, extra])
    if exit_at_event:
        seed.pending = [PendingOrder(Operation.CLOSE_POSITION, "TRI", "TRI", 0,
                                     OLD_SHARES, PRE, "EXIT").to_dict()]
    after = advance(seed, published(EVENT_DAY, [bars[1].vendor,
                     replace(extra, session=EVENT_DAY)]), config)
    assert Ledger.from_dict(after.ledger).receivable_total() == pytest.approx(1435.518)
    if exit_at_event:
        assert not after.wealth_core["episodes"]
        sales = [e for e in Ledger.from_dict(after.ledger).events if e.event_type is EventType.SELL]
        assert sales[0].shares_delta == -984.56
    book = PortfolioState.from_dict(after.wealth_core)
    book.slots[1].reserve("BUY", "BUY", "P:BUY")
    after.wealth_core = book.to_dict()
    after.pending = [PendingOrder(Operation.OPEN_SLOT_POSITION, "BUY", "BUY", 1,
                                  0, EVENT_DAY, "ENTRY", intended_dollars=2000.).to_dict()]
    nxt = next(row.vendor for row in bars if row.vendor.session == NEXT)
    settled = advance(SessionState.from_dict(json.loads(json.dumps(after.to_dict()))),
                      published(NEXT, [nxt, replace(extra, session=NEXT)]), config)
    buy = [e for e in Ledger.from_dict(settled.ledger).events if e.event_type is EventType.BUY][-1]
    assert buy.shares_delta == (199 if exit_at_event else 153)


def test_opening_entry_receives_no_old_share_distribution():
    bars = normalized_tri()
    config, seed = held_seed([bars[0].vendor])
    book = PortfolioState.from_dict(seed.wealth_core)
    book.episodes.clear()
    book.slots[0].occupied_by = None
    book.slots[0].reserve("TRI", "TRI", "P:TRI")
    book.cash = 100000.
    seed.wealth_core = book.to_dict()
    seed.pending = [PendingOrder(Operation.OPEN_SLOT_POSITION, "TRI", "TRI", 0,
                                  0, PRE, "ENTRY", intended_dollars=5000.).to_dict()]
    after = advance(seed, published(EVENT_DAY, [bars[1].vendor]), config)
    assert Ledger.from_dict(after.ledger).receivable_total() == 0
    assert after.wealth_core["episodes"]["0"]["current_shares"] == 50


def test_basis_contract_refuses_missing_or_wrong_consolidation():
    fetch = tri_vendor()
    rows = [r for r in fetch(sharadar.SEP) if r["date"] == EVENT_DAY]
    resolution = CAA.resolve_dividends(fetch(sharadar.ACTIONS), [EVENT_DAY])
    with pytest.raises(RawPriceDomainUnavailable, match="split_ratio"):
        list(normalise_sep_rows(rows, dividends=resolution.dividends))
    distribution = resolution.dividends[("TRI", EVENT_DAY)]
    assert raw_dividend_per_share(100, 100, distribution, split_ratio=2) is None


def test_production_kernel_opening_witness_is_invariant_to_terminal_close():
    results = []
    for close in (1., 10.):
        prior = VendorBar(PRE, "TERM", "TERM", 10., 10., 1000000.)
        config, state = held_seed([prior], champion=False, shares=100, cash=100.)
        book = PortfolioState.from_dict(state.wealth_core)
        book.sessions_since_valid_mark["TERM"] = 11
        state.wealth_core = book.to_dict()
        value = replace(published(EVENT_DAY, [replace(prior, session=EVENT_DAY,
                                raw_open=5., raw_close=close)]),
                        terminal_events=[TerminalTerms(EVENT_DAY, "TERM", TerminalKind.CASH_MERGER)])
        result = advance(SessionState.from_dict(json.loads(json.dumps(state.to_dict()))), value, config)
        results.append(result.last_evidence["wealth_core"]["resolved_open_equity"])
        assert result.wealth_core["cash"] == 600.
        assert not result.wealth_core["episodes"]
    assert results == [600., 600.]
