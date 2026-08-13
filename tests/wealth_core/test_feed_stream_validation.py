"""Session boundaries are validated before any rolling or portfolio mutation."""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.feed import (
    Feed,
    FeedError,
    SecurityMeta,
    VendorBar,
)
from stock_strategy_shared.wealth_core.run import run_sessions
from stock_strategy_shared.wealth_core.state import PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms


def meta():
    return {"S1": SecurityMeta("S1", "T1", permaticker="1")}


def vendor(session: str, *, close: float = 10.0):
    return VendorBar(session, "S1", "T1", close, close, 1_000_000.0)


@pytest.mark.parametrize("sessions", [
    ["2024-01-02", "2024-01-02"],
    ["2024-01-03", "2024-01-02"],
])
def test_warmup_refuses_duplicate_or_out_of_order_sessions_before_mutation(sessions):
    feed = Feed(meta())
    with pytest.raises(FeedError, match="strictly increasing"):
        feed.warmup(sessions, {})
    assert feed.series == {}
    assert feed._session_index == -1


def test_warmup_refuses_a_bar_from_the_wrong_session_before_mutation():
    feed = Feed(meta())
    with pytest.raises(FeedError, match="session boundary"):
        feed.warmup(
            ["2024-01-02"],
            {"2024-01-02": [vendor("2024-01-03")]})
    assert feed.series == {} and feed._session_index == -1


def test_warmup_refuses_duplicate_security_bars_before_applying_split_twice():
    feed = Feed(meta())
    bars = [vendor("2024-01-02"), vendor("2024-01-02", close=11.0)]
    with pytest.raises(FeedError, match="duplicate bar"):
        feed.warmup(["2024-01-02"], {"2024-01-02": bars})
    assert feed.series == {} and feed._session_index == -1


def test_advance_refuses_replaying_or_reversing_an_applied_session():
    feed = Feed(meta())
    feed.advance("2024-01-03", [vendor("2024-01-03")])
    with pytest.raises(FeedError, match="duplicate"):
        feed.advance("2024-01-03", [vendor("2024-01-03")])
    with pytest.raises(FeedError, match="out of order"):
        feed.advance("2024-01-02", [vendor("2024-01-02")])
    assert feed.series["S1"].sessions == ["2024-01-03"]


def test_run_refuses_bad_stream_before_mutating_canonical_state():
    state = PortfolioState.fresh(1_000.0)
    before = state.to_dict()
    with pytest.raises(FeedError, match="duplicate"):
        run_sessions(
            sessions=["2024-01-02", "2024-01-02"],
            bars_by_session={}, meta=meta(), starting_cash=1_000.0,
            state=state)
    assert state.to_dict() == before


def test_run_refuses_duplicate_terminal_application_before_state_mutation():
    state = PortfolioState.fresh(1_000.0)
    before = state.to_dict()
    event = TerminalTerms(
        session="2024-01-02", security_id="S1",
        kind=TerminalKind.WRITE_OFF, reference="test/duplicate")
    with pytest.raises(ValueError, match="duplicate terminal event"):
        run_sessions(
            sessions=["2024-01-02"], bars_by_session={}, meta=meta(),
            starting_cash=1_000.0, state=state,
            terminal_events=[event, event])
    assert state.to_dict() == before
