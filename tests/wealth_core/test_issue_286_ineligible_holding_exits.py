"""Regression coverage for issue #286: eligibility cannot erase exit evidence."""
from __future__ import annotations

from stock_strategy_shared.wealth_core.adapter import step_session
from stock_strategy_shared.wealth_core.engine import (
    Operation,
    Reason,
    WealthCoreConfig,
)
from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import (
    REVIEW_AGE_SESSIONS,
    HoldingEpisode,
    PortfolioState,
)

CFG = WealthCoreConfig()
SID, VER = "stocker_wealth_core_v1", 1


def _meta() -> SecurityMeta:
    return SecurityMeta(
        security_id="S1",
        ticker="T1",
        category="Domestic Common Stock",
        permaticker="1",
        first_session="S000",
    )


def _feed_and_session(*, current_close: float | None,
                      current_volume: float = 1.0,
                      previous_last_close: float = 100.0):
    feed = Feed({"S1": _meta()})
    warm_sessions = [f"S{i:03d}" for i in range(126)]
    warm_bars = {}
    for i, session in enumerate(warm_sessions):
        close = previous_last_close if i == len(warm_sessions) - 1 else 100.0
        warm_bars[session] = [VendorBar(
            session=session,
            security_id="S1",
            ticker="T1",
            raw_close=close,
            raw_open=close,
            volume=1_000_000.0,
        )]
    feed.warmup(warm_sessions, warm_bars)
    norm = feed.advance("S126", [VendorBar(
        session="S126",
        security_id="S1",
        ticker="T1",
        raw_close=current_close,
        raw_open=current_close,
        volume=current_volume,
    )])
    return feed, norm


def _held(*, peak: float = 100.0, entry: float = 100.0,
          age: int = 5) -> PortfolioState:
    state = PortfolioState.fresh(10_000.0)
    state.slots[0].occupied_by = "S1"
    state.episodes[0] = HoldingEpisode(
        security_id="S1",
        ticker="T1",
        issuer_id="P:1",
        slot_id=0,
        signal_date="S000",
        entry_date="S001",
        entry_raw_open=entry,
        entry_split_adjusted_price=entry,
        initial_shares=10,
        current_shares=10,
        episode_peak_split_adjusted_close=peak,
        market_sessions_held=age,
    )
    state.initialized = True
    return state


def _step(state: PortfolioState, norm, *, last_known=None):
    return step_session(
        session="S126",
        state=state,
        bars=norm.bars,
        pending=[],
        ledger=Ledger(),
        last_known={} if last_known is None else dict(last_known),
        cfg=CFG,
        strategy_id=SID,
        strategy_version=VER,
        security_bars=norm.security_bars,
    )


def _closes(result):
    return [op for op in result.decision.operations
            if op.operation is Operation.CLOSE_POSITION]


def test_ineligible_held_security_keeps_current_close_and_trailing_stop_fires():
    _, norm = _feed_and_session(current_close=69.0, current_volume=1.0)

    assert norm.eligibility["S1"].eligible is False
    assert norm.security_bars[0].closes[-1] == 69.0

    result = _step(_held(peak=100.0), norm, last_known={"S1": 100.0})
    closes = _closes(result)
    assert len(closes) == 1
    assert closes[0].reason is Reason.EXIT_TRAILING_STOP
    assert closes[0].detail["close"] == 69.0


def test_ineligible_held_security_above_stop_remains_held():
    _, norm = _feed_and_session(current_close=80.0, current_volume=1.0)

    assert norm.eligibility["S1"].eligible is False
    assert norm.security_bars[0].closes[-1] == 80.0
    assert _closes(_step(_held(peak=100.0), norm)) == []


def test_ineligible_held_security_still_gets_one_time_review_with_current_close():
    _, norm = _feed_and_session(current_close=90.0, current_volume=1.0)
    state = _held(
        peak=100.0,
        entry=100.0,
        age=REVIEW_AGE_SESSIONS - 1,
    )

    result = _step(state, norm)
    closes = _closes(result)
    assert len(closes) == 1
    assert closes[0].reason is Reason.EXIT_REVIEW_WEAKNESS
    assert closes[0].detail["close"] == 90.0
    assert closes[0].detail["underwater"] is True
    assert closes[0].detail["qualified"] is False


def test_missing_current_close_is_not_compacted_into_a_stale_stop_price():
    _, norm = _feed_and_session(
        current_close=None,
        current_volume=0.0,
        previous_last_close=69.0,
    )

    assert norm.eligibility["S1"].eligible is False
    assert norm.signal_windows["S1"][-1] == 69.0
    assert norm.security_bars[0].closes[-1] is None

    result = _step(_held(peak=100.0), norm, last_known={"S1": 69.0})
    assert _closes(result) == []


def test_unheld_ineligible_security_remains_excluded_from_admission():
    _, norm = _feed_and_session(current_close=100.0, current_volume=1.0)
    state = PortfolioState.fresh(100_000.0)

    result = _step(state, norm)
    assert norm.eligibility["S1"].eligible is False
    assert not [op for op in result.decision.operations
                if op.operation is Operation.OPEN_SLOT_POSITION]
