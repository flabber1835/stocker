"""Cooldown clocks begin after the session that creates them.

The exit session's close is age 0.  The following market-session closes are
ages 1 through 21, with both the slot and exited security blocked through age
20 and available after age 21.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.adapter import (
    PendingOrder,
    step_session,
    tradeability_only_bars,
)
from stock_strategy_shared.wealth_core.engine import (
    Operation,
    Reason,
    WealthCoreConfig,
)
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms


CFG = WealthCoreConfig()
STRATEGY_ID = "stocker_wealth_core_v1"
STRATEGY_VERSION = 1


def daily_bar(
        security_id: str = "S1",
        session: str = "d1",
        *,
        ticker: str | None = None,
        issuer_id: str | None = None,
        signal: float = 100.0,
        raw_open: float = 99.0,
        raw_close: float = 100.0,
        ) -> DailyBar:
    suffix = security_id[1:]
    return DailyBar(
        security_id=security_id,
        ticker=ticker or f"T{suffix}",
        issuer_id=issuer_id or f"I{suffix}",
        session=session,
        signal_close_split_adj_div_unadj=signal,
        raw_open=raw_open,
        raw_mark_close=raw_close,
        tradeable=True,
    )


def rising_window(n: int = 127, start: float = 100.0) -> list[float]:
    return [start + index for index in range(n)]


def seated_state(
        *,
        cash: float = 10_000.0,
        security_id: str = "S1",
        ticker: str | None = None,
        issuer_id: str | None = None,
        shares: int = 10,
        slot_id: int = 0,
        ) -> PortfolioState:
    suffix = security_id[1:]
    state = PortfolioState.fresh(cash)
    state.slots[slot_id].occupied_by = security_id
    state.episodes[slot_id] = HoldingEpisode(
        security_id,
        ticker or f"T{suffix}",
        issuer_id or f"I{suffix}",
        slot_id,
        "d0",
        "d0",
        100.0,
        100.0,
        shares,
        shares,
        100.0,
    )
    state.initialized = True
    return state


def run_session(
        state: PortfolioState,
        bars: list[DailyBar],
        *,
        session: str,
        pending: list[PendingOrder] | None = None,
        windows: dict[str, list[float]] | None = None,
        terminal_terms: list[TerminalTerms] | tuple[TerminalTerms, ...] = (),
        ledger: Ledger | None = None,
        last_known: dict[str, float] | None = None,
        ):
    queue = pending if pending is not None else []
    return step_session(
        session=session,
        state=state,
        bars=bars,
        pending=queue,
        ledger=ledger if ledger is not None else Ledger(),
        last_known=last_known if last_known is not None else {},
        cfg=CFG,
        strategy_id=STRATEGY_ID,
        strategy_version=STRATEGY_VERSION,
        security_bars=tradeability_only_bars(bars, windows),
        terminal_terms=terminal_terms,
    )


@pytest.mark.parametrize("exit_kind", ["pending", "terminal"])
def test_exit_close_is_age_zero_and_following_closes_are_ages_1_to_21(
        exit_kind: str) -> None:
    state = seated_state(cash=1_000.0)
    pending: list[PendingOrder] = []
    terminal_terms: list[TerminalTerms] = []
    bars: list[DailyBar] = []

    if exit_kind == "pending":
        pending.append(PendingOrder(
            Operation.CLOSE_POSITION,
            "S1",
            "T1",
            0,
            10,
            "d0",
            Reason.EXIT_TRAILING_STOP.value,
        ))
        bars = [daily_bar(session="exit")]
    else:
        terminal_terms.append(TerminalTerms(
            session="exit",
            security_id="S1",
            kind=TerminalKind.CASH_MERGER,
            cash_per_share=120.0,
            reference="test/cooldown-age-zero",
        ))

    result = run_session(
        state,
        bars,
        session="exit",
        pending=pending,
        windows={"S1": rising_window()},
        terminal_terms=terminal_terms,
    )

    assert 0 not in state.episodes
    assert state.slots[0].cooldown_sessions_elapsed == 0
    assert state.security_cooldowns == {"S1": 0}
    if exit_kind == "pending":
        assert result.fills[0]["operation"] == Operation.CLOSE_POSITION.value
    else:
        assert any(item.get("applied") for item in result.terminal_results)

    for age in range(1, 21):
        run_session(state, [], session=f"after-{age}", pending=pending)
        assert state.slots[0].cooldown_sessions_elapsed == age
        assert state.slots[0].in_cooldown
        assert state.security_cooldowns == {"S1": age}
        assert state.security_in_cooldown("S1")

    run_session(state, [], session="after-21", pending=pending)
    assert state.slots[0].cooldown_sessions_elapsed is None
    assert state.slots[0].ready
    assert "S1" not in state.security_cooldowns
    assert not state.security_in_cooldown("S1")


def test_pending_exit_resets_preexisting_security_cooldown_to_age_zero() -> None:
    state = seated_state(cash=1_000.0)
    state.security_cooldowns["S1"] = 3
    pending = [PendingOrder(
        Operation.CLOSE_POSITION,
        "S1",
        "T1",
        0,
        10,
        "d0",
        Reason.EXIT_TRAILING_STOP.value,
    )]

    run_session(
        state,
        [daily_bar(session="exit")],
        session="exit",
        pending=pending,
    )

    assert state.slots[0].cooldown_sessions_elapsed == 0
    assert state.security_cooldowns == {"S1": 0}


def test_terminal_exit_resets_preexisting_security_cooldown_to_age_zero() -> None:
    state = seated_state(cash=1_000.0)
    state.security_cooldowns["S1"] = 3

    run_session(
        state,
        [],
        session="exit",
        terminal_terms=[TerminalTerms(
            session="exit",
            security_id="S1",
            kind=TerminalKind.CASH_MERGER,
            cash_per_share=120.0,
            reference="test/preexisting-cooldown-cash-merger",
        )],
    )

    assert state.slots[0].cooldown_sessions_elapsed == 0
    assert state.security_cooldowns == {"S1": 0}


def test_continuing_conversion_ages_delivered_security_cooldown_normally() -> None:
    state = seated_state(cash=1_000.0)
    state.security_cooldowns["S2"] = 3

    run_session(
        state,
        [daily_bar("S2", session="conversion")],
        session="conversion",
        terminal_terms=[TerminalTerms(
            session="conversion",
            security_id="S1",
            kind=TerminalKind.CONVERSION,
            delivered_security_id="S2",
            delivered_ticker="T2",
            delivered_issuer_id="I2",
            exchange_ratio=1.0,
            reference="test/continuing-conversion-cooldown",
        )],
    )

    assert state.episodes[0].security_id == "S2"
    assert state.slots[0].cooldown_sessions_elapsed is None
    assert state.security_cooldowns == {"S2": 4}


def test_zero_share_conversion_resets_predecessor_cooldown_to_age_zero() -> None:
    state = seated_state(cash=1_000.0, shares=1)
    state.security_cooldowns["S1"] = 3

    result = run_session(
        state,
        [],
        session="conversion",
        terminal_terms=[TerminalTerms(
            session="conversion",
            security_id="S1",
            kind=TerminalKind.CONVERSION,
            delivered_security_id="S2",
            delivered_ticker="T2",
            delivered_issuer_id="I2",
            exchange_ratio=0.5,
            cash_in_lieu_price_per_delivered_share=100.0,
            reference="test/zero-share-conversion-cooldown",
        )],
    )

    applied = next(item for item in result.terminal_results
                   if item.get("applied"))
    assert applied["converted"] is False
    assert 0 not in state.episodes
    assert state.slots[0].cooldown_sessions_elapsed == 0
    assert state.security_cooldowns == {"S1": 0}


def test_mnst_omg_september_2006_cooldown_boundary() -> None:
    """MNST's 2006-08-08 exit blocks OMG through the 2006-09-06 close."""
    mnst = "530996274575880476"
    omg = "901890778211216620"
    state = seated_state(
        cash=0.0,
        security_id=mnst,
        ticker="MNST",
        issuer_id="SEC_CIK:1020416",
        shares=77_836,
        slot_id=5,
    )
    episode = state.episodes[5]
    episode.signal_date = "2006-01-03"
    episode.entry_date = "2006-01-04"
    episode.entry_raw_open = 5.0
    episode.entry_split_adjusted_price = 5.0
    episode.episode_peak_split_adjusted_close = 5.0

    for slot_id, slot in state.slots.items():
        if slot_id != 5:
            slot.reserve(
                f"BLOCKED-{slot_id}",
                f"BLOCKED-{slot_id}",
                f"BLOCKED-ISSUER-{slot_id}",
            )

    pending = [PendingOrder(
        Operation.CLOSE_POSITION,
        mnst,
        "MNST",
        5,
        77_836,
        "2006-08-07",
        Reason.EXIT_TRAILING_STOP.value,
    )]
    exit_bar = daily_bar(
        mnst,
        "2006-08-08",
        ticker="MNST",
        issuer_id="SEC_CIK:1020416",
        signal=2.455,
        raw_open=29.767958,
        raw_close=29.456,
    )
    run_session(
        state,
        [exit_bar],
        pending=pending,
        session="2006-08-08",
        windows={mnst: rising_window()},
    )
    assert state.slots[5].cooldown_sessions_elapsed == 0
    assert state.security_cooldowns[mnst] == 0

    strictly_after_exit = [
        "2006-08-09", "2006-08-10", "2006-08-11", "2006-08-14",
        "2006-08-15", "2006-08-16", "2006-08-17", "2006-08-18",
        "2006-08-21", "2006-08-22", "2006-08-23", "2006-08-24",
        "2006-08-25", "2006-08-28", "2006-08-29", "2006-08-30",
        "2006-08-31", "2006-09-01", "2006-09-05",
    ]
    for age, session in enumerate(strictly_after_exit, start=1):
        run_session(state, [], pending=pending, session=session)
        assert state.slots[5].cooldown_sessions_elapsed == age
        assert state.security_cooldowns[mnst] == age

    def omg_bar(session: str, raw_open: float, raw_close: float) -> DailyBar:
        return daily_bar(
            omg,
            session,
            ticker="OMG",
            issuer_id="SEC_CIK:899723",
            signal=raw_close,
            raw_open=raw_open,
            raw_close=raw_close,
        )

    sep6 = run_session(
        state,
        [omg_bar("2006-09-06", 41.50, 41.84)],
        pending=pending,
        session="2006-09-06",
        windows={omg: rising_window()},
    )
    assert state.slots[5].cooldown_sessions_elapsed == 20
    assert state.security_cooldowns[mnst] == 20
    assert not [
        operation
        for operation in sep6.decision.operations
        if operation.operation is Operation.OPEN_SLOT_POSITION
    ]
    assert pending == []

    sep7 = run_session(
        state,
        [omg_bar("2006-09-07", 41.67, 40.89)],
        pending=pending,
        session="2006-09-07",
        windows={omg: rising_window()},
    )
    assert state.slots[5].cooldown_sessions_elapsed is None
    assert mnst not in state.security_cooldowns
    opens = [
        operation
        for operation in sep7.decision.operations
        if operation.operation is Operation.OPEN_SLOT_POSITION
    ]
    assert [
        (operation.slot_id, operation.security_id) for operation in opens
    ] == [(5, omg)]
    assert [(order.slot_id, order.security_id) for order in pending] == [(5, omg)]
    assert not [fill for fill in sep7.fills if fill["security_id"] == omg]
