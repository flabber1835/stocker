"""Session boundaries are validated before any rolling or portfolio mutation."""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.feed import (
    Feed,
    FeedError,
    SecurityMeta,
    SecuritySeries,
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


@pytest.mark.parametrize('median5', [False, True])
def test_signal_window_compatibility_view_is_lazy_and_preserves_missing_close(median5):
    feed = Feed(meta())
    if median5:
        from stock_strategy_shared.wealth_core.median5 import fresh
        feed.median5_state = fresh()
    feed.advance('2024-01-02', [VendorBar(
        '2024-01-02', 'S1', 'T1', 10.0, 10.0, 1_000_000.0,
        signal_close=10.0)])
    normalized = feed.advance('2024-01-03', [VendorBar(
        '2024-01-03', 'S1', 'T1', None, None, 0.0)])

    assert 'signal_windows' not in vars(normalized)
    assert normalized.security_bars[0].closes == [10.0, None]
    windows = normalized.signal_windows
    assert windows == {'S1': [10.0]}
    assert normalized.signal_windows is windows
    windows['S1'].append(99.0)
    assert normalized.security_bars[0].closes == [10.0, None]
    assert feed.series['S1'].signal_closes == [10.0, None]


def test_current_window_feed_does_not_scan_compatibility_history_until_requested():
    from stock_strategy_shared.wealth_core.engine import SecurityBar
    from stock_strategy_shared.wealth_core.median5 import fresh

    scans = []

    class History(list):
        def __iter__(self):
            scans.append(True)
            return super().__iter__()

    feed = Feed(meta())
    feed.median5_state = fresh()
    feed.snapshot_security_bars = {'S1': SecurityBar(
        'S1', 'T1', 'P:1', History([7.0, None, 10.0]), raw_close=10.0)}
    normalized = feed.advance('2024-01-02', [VendorBar(
        '2024-01-02', 'S1', 'T1', 10.0, 10.0, 1_000_000.0,
        signal_close=10.0)])

    assert scans == []
    assert normalized.signal_windows == {'S1': [7.0, 10.0]}
    assert scans == [True]
    assert normalized.signal_windows == {'S1': [7.0, 10.0]}
    assert scans == [True]


def test_signal_window_remains_an_independent_trailing_list():
    series = SecuritySeries('S1', 'T1', 'P:1', signal_closes=[3.0, None, 4.0])
    window = series.signal_window(2)
    assert window == [None, 4.0]
    window[-1] = 99.0
    assert series.signal_closes == [3.0, None, 4.0]
