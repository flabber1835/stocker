"""Physical PostgreSQL witness: terminal facts do not depend on load start."""
import json

import pytest

from sentinel.core import terminal as T
from sentinel.feed import calendar, publication as P, store as S
from sentinel.feed.domains import NormalisedBar
from stock_strategy_shared.wealth_core.feed import VendorBar
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState
from tests.sentinel.test_terminal_identity import pg, conn, action, universe, load
from tests.wealth_core.test_conversion_entitlements import book


def price(conn, ticker, session):
    S.write_bars(conn, [NormalisedBar(close_signal=100., vendor=VendorBar(
        session=session, security_id=f"P:{ticker}", ticker=ticker, raw_close=100.,
        raw_open=100., volume=1e6, split_ratio=1., dividend_per_share=0.))])
    conn.commit()


@pytest.mark.parametrize("raw_day,effective", [("2024-12-30", "2024-12-30"),
                                                ("2024-12-28", "2024-12-30")])
@pytest.mark.parametrize("renamed", [False, True])
def test_historical_holder_receives_daily_terminal_without_event_day_price(conn, raw_day, effective, renamed):
    price(conn, "OLD", "2024-12-27")
    price(conn, "KEEP", effective)
    ticker = "RENAMED" if renamed else "OLD"
    from sentinel.feed.universe import write_universe
    write_universe(conn, [dict(permaticker='P:OLD', ticker=ticker,
                               firstpricedate='2000-01-01', relatedtickers='OLD RENAMED'),
                          dict(permaticker='P:KEEP', ticker='KEEP', firstpricedate=effective)],
                   effective)
    action(conn, ticker, raw_day, act="acquisitionby")
    from sentinel.core.production import MIN_CLOSES, load_published_session
    spy_days = calendar.previous_sessions(effective, MIN_CLOSES)
    S.write_spy_total_return(conn, [dict(ticker='SPY', date=day, closeadj=500.)
                                   for day in spy_days])
    S.write_defensive_bars(conn, [dict(ticker='BIL', date=day, open=90., close=90.,
                                     closeadj=90., closeunadj=90.) for day in spy_days[-2:]])
    P.publish(conn, window_start="2024-12-27", window_end=effective)
    daily = load(conn, start=effective, end=effective)
    broad = load(conn, start="2024-12-27", end=effective)
    assert daily.events == broad.events and len(daily.events) == 1
    assert daily.events[0].security_id == "P:OLD"
    assert daily.conservation_holds() and daily.normalized_stream_holds()
    assert not daily.unresolved and not daily.excluded
    published = load_published_session(conn, effective, known_feed_security_ids=('P:OLD',))
    assert list(published.terminal_events) == daily.events

    state, ledger = book([100]), Ledger()
    state.episodes[0].security_id = "P:OLD"
    state.slots[0].occupied_by = "P:OLD"
    state.last_valid_mark_session["P:OLD"] = "2024-12-27"
    from stock_strategy_shared.wealth_core.adapter import step_session
    from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
    marks = {"P:OLD": 100.}
    for index, day in enumerate(calendar.sessions_in_range(effective, "2025-02-03")):
        step_session(session=day, state=state, bars=[], pending=[], ledger=ledger,
            last_known=marks, cfg=WealthCoreConfig(), strategy_id="stocker_wealth_core_v1",
            strategy_version=1, security_bars=[], terminal_terms=daily.events if index == 0 else ())
        if index == 0:
            assert "P:OLD" in state.terminal_pending_terms
        state = PortfolioState.from_dict(json.loads(json.dumps(state.to_dict())))
        ledger = Ledger.from_dict(json.loads(json.dumps(ledger.to_dict())))
    assert state.cash == 20_000. and not state.episodes
    assert not any(e.detail.get("settlement_source") == "ZERO_ORPHAN" for e in ledger.events)


def test_unresolved_prior_ticker_blocks_even_when_another_security_prints(conn):
    price(conn, "OLD", "2024-12-27")
    price(conn, "KEEP", "2024-12-30")
    action(conn, "OLD", "2024-12-30", act="acquisitionby")
    daily = load(conn, start="2024-12-30", end="2024-12-30")
    assert len(daily.unresolved) == 1
    assert daily.unresolved[0].ticker == "OLD"
    assert not daily.excluded
