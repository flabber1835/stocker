"""Regression tests for the backtester-only production cooldown overlay.

These tests execute the exact pinned production adapter after the diagnostic
workflow applies ``backtester/production_cooldown_age_zero.patch``.  They do not
alter or import strategy code from the research implementation.
"""
from __future__ import annotations

import unittest

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

CFG = WealthCoreConfig()
STRATEGY_ID = "stocker_wealth_core_v1"
STRATEGY_VERSION = 1


def daily_bar(
        security_id: str = "S1",
        session: str = "d1",
        *,
        signal: float = 100.0,
        raw_open: float = 99.0,
        raw_close: float = 100.0,
        ) -> DailyBar:
    return DailyBar(
        security_id=security_id,
        ticker=f"T{security_id[1:]}",
        issuer_id=f"I{security_id[1:]}",
        session=session,
        signal_close_split_adj_div_unadj=signal,
        raw_open=raw_open,
        raw_mark_close=raw_close,
        tradeable=True,
    )


def rising_window(n: int = 127, start: float = 100.0) -> list[float]:
    return [start + i for i in range(n)]


def seated_state(
        *, cash: float = 10_000.0, security_id: str = "S1",
        shares: int = 10, slot_id: int = 0,
        ) -> PortfolioState:
    state = PortfolioState.fresh(cash)
    state.slots[slot_id].occupied_by = security_id
    state.episodes[slot_id] = HoldingEpisode(
        security_id,
        f"T{security_id[1:]}",
        f"I{security_id[1:]}",
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


class ProductionCooldownAgeZeroTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = Ledger()
        self.last_known: dict[str, float] = {}

    def step(
            self,
            state: PortfolioState,
            bars: list[DailyBar],
            *,
            session: str,
            pending: list[PendingOrder] | None = None,
            windows: dict[str, list[float]] | None = None,
            terminal_terms: list | tuple = (),
            ):
        queue = pending if pending is not None else []
        return step_session(
            session=session,
            state=state,
            bars=bars,
            pending=queue,
            ledger=self.ledger,
            last_known=self.last_known,
            cfg=CFG,
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            security_bars=tradeability_only_bars(bars, windows),
            terminal_terms=terminal_terms,
        )

    def test_pending_exit_creates_age_zero_cooldowns(self) -> None:
        state = seated_state()
        pending = [PendingOrder(
            Operation.CLOSE_POSITION,
            "S1",
            "T1",
            0,
            10,
            "d0",
            Reason.EXIT_TRAILING_STOP.value,
        )]

        result = self.step(
            state,
            [daily_bar("S1", "d1")],
            session="d1",
            pending=pending,
            windows={"S1": rising_window()},
        )

        self.assertEqual(result.fills[0]["operation"],
                         Operation.CLOSE_POSITION.value)
        self.assertEqual(state.slots[0].cooldown_sessions_elapsed, 0)
        self.assertEqual(state.security_cooldowns["S1"], 0)

    def test_terminal_exit_creates_age_zero_cooldowns(self) -> None:
        from stock_strategy_shared.wealth_core.terminal import (
            TerminalKind,
            TerminalTerms,
        )

        state = seated_state(cash=1_000.0)
        terms = TerminalTerms(
            session="d1",
            security_id="S1",
            kind=TerminalKind.CASH_MERGER,
            cash_per_share=120.0,
            reference="backtester/cooldown-age-zero",
        )

        self.step(state, [], session="d1", terminal_terms=[terms])

        self.assertNotIn(0, state.episodes)
        self.assertEqual(state.slots[0].cooldown_sessions_elapsed, 0)
        self.assertEqual(state.security_cooldowns["S1"], 0)

    def test_mnst_omg_september_2006_boundary(self) -> None:
        """Reproduce the first strict-PIT research/production divergence.

        MNST exits at the 2006-08-08 open. Slot 5 remains blocked through the
        2006-09-06 close and may queue OMG only after the 2006-09-07 close.
        """
        mnst = "530996274575880476"
        omg = "901890778211216620"
        state = PortfolioState.fresh(0.0)
        state.slots[5].occupied_by = mnst
        state.episodes[5] = HoldingEpisode(
            mnst,
            "MNST",
            "SEC_CIK:1020416",
            5,
            "2006-01-03",
            "2006-01-04",
            5.0,
            5.0,
            77_836,
            77_836,
            5.0,
        )
        state.initialized = True
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
        exit_bar = DailyBar(
            security_id=mnst,
            ticker="MNST",
            issuer_id="SEC_CIK:1020416",
            session="2006-08-08",
            signal_close_split_adj_div_unadj=2.455,
            raw_open=29.767958,
            raw_mark_close=29.456,
            tradeable=True,
        )
        self.step(
            state,
            [exit_bar],
            pending=pending,
            session="2006-08-08",
            windows={mnst: rising_window()},
        )
        self.assertEqual(state.slots[5].cooldown_sessions_elapsed, 0)
        self.assertEqual(state.security_cooldowns[mnst], 0)

        strictly_after_exit = [
            "2006-08-09", "2006-08-10", "2006-08-11", "2006-08-14",
            "2006-08-15", "2006-08-16", "2006-08-17", "2006-08-18",
            "2006-08-21", "2006-08-22", "2006-08-23", "2006-08-24",
            "2006-08-25", "2006-08-28", "2006-08-29", "2006-08-30",
            "2006-08-31", "2006-09-01", "2006-09-05",
        ]
        for age, session in enumerate(strictly_after_exit, start=1):
            self.step(state, [], pending=pending, session=session)
            self.assertEqual(state.slots[5].cooldown_sessions_elapsed, age)
            self.assertEqual(state.security_cooldowns[mnst], age)

        def omg_bar(session: str, raw_open: float, raw_close: float) -> DailyBar:
            return DailyBar(
                security_id=omg,
                ticker="OMG",
                issuer_id="SEC_CIK:899723",
                session=session,
                signal_close_split_adj_div_unadj=raw_close,
                raw_open=raw_open,
                raw_mark_close=raw_close,
                tradeable=True,
            )

        sep6 = self.step(
            state,
            [omg_bar("2006-09-06", 41.50, 41.84)],
            pending=pending,
            session="2006-09-06",
            windows={omg: rising_window()},
        )
        self.assertEqual(state.slots[5].cooldown_sessions_elapsed, 20)
        self.assertEqual(state.security_cooldowns[mnst], 20)
        self.assertFalse([
            operation
            for operation in sep6.decision.operations
            if operation.operation is Operation.OPEN_SLOT_POSITION
        ])
        self.assertEqual(pending, [])

        sep7 = self.step(
            state,
            [omg_bar("2006-09-07", 41.67, 40.89)],
            pending=pending,
            session="2006-09-07",
            windows={omg: rising_window()},
        )
        self.assertIsNone(state.slots[5].cooldown_sessions_elapsed)
        self.assertNotIn(mnst, state.security_cooldowns)
        opens = [
            operation
            for operation in sep7.decision.operations
            if operation.operation is Operation.OPEN_SLOT_POSITION
        ]
        self.assertEqual(
            [(operation.slot_id, operation.security_id) for operation in opens],
            [(5, omg)],
        )
        self.assertEqual(
            [(order.slot_id, order.security_id) for order in pending],
            [(5, omg)],
        )
        self.assertFalse([
            fill for fill in sep7.fills if fill["security_id"] == omg
        ])


if __name__ == "__main__":
    unittest.main()
