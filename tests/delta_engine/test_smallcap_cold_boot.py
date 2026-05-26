"""
Small-cap cold-boot simulation tests.

A common real-world scenario: Alpaca already holds tickers that were opened
before stocker was deployed, or were purchased under a different strategy.
These "orphan" broker positions must be handled gracefully by the delta engine:

  - On cold boot with no portfolio-builder run, every live broker position is
    carried as "held" (current_weight=0.0 sentinel) so the exit-zone logic
    applies.  The 0.0 sentinel is NOT a target weight, so no drift actions fire.
  - Positions that rank outside the exit zone (rank > exit_rank) accumulate
    bad-rank days. After confirmation_days consecutive bad days they emit
    "exit" signals. Before that they emit "at_risk".
  - Positions absent from the ranking universe (data gap) stay as "hold" —
    the system never force-exits something it can't rank.
  - Quality tickers that would normally enter are blocked as "watch" while
    broker count >= max_positions.  Capacity is restored as orphan exits are
    confirmed.

The key user scenario:

  60 small-cap orphan positions in Alpaca on cold boot.
  After 3 pipeline runs (= confirmation_days):
    • 60 exit signals generated
    • 30 quality entry signals generated (slots freed)
    • Portfolio converges from 60 small caps → 30 quality tickers

All tests run purely against the engine module — no database or Docker needed.
The pipeline service uses evaluate_all() in cold-start mode and
evaluate_target_vs_live() in normal mode; this suite tests both paths.

Parameter choices in this module:
  ENTRY_RANK = 30  — slightly relaxed (matches a wider quality pool of 30 tickers)
  EXIT_RANK  = 40  — matches the strategy.py default
  These differ from the narrower ENTRY_RANK=20 / EXIT_RANK=30 used in other
  test modules; both are legal strategy configurations.
"""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline/app"))

from engine import (
    evaluate_all,
    evaluate_target_vs_live,
    RankObservation,
    DeltaDecision,
)


# ── Module-wide parameters ────────────────────────────────────────────────────
# entry_rank=30 / exit_rank=40 gives a buffer zone of rank 31-40 and an
# entry zone of rank 1-30.  This lets 30 quality tickers all be entry-eligible
# while still having 40 rank-points of buffer-zone headroom.
ENTRY_RANK = 30
EXIT_RANK = 40
CONFIRMATION_DAYS = 3
MAX_POSITIONS = 30
ACCOUNT_VALUE = 500_000.0
BASE_DATE = date(2025, 1, 6)

# Boundary ranks used in scenario construction
POOR_RANK_START = EXIT_RANK + 5       # clearly outside exit zone: 45
BUFFER_RANK_START = ENTRY_RANK + 1    # in buffer zone (31-40): not entry, not exit yet


# ── Shared helpers ────────────────────────────────────────────────────────────

def _obs(rank: int, days: int = 3, start: date = BASE_DATE) -> list[RankObservation]:
    """Build `days` consecutive observations all at `rank`, most-recent first."""
    return [
        RankObservation(
            run_date=start + timedelta(days - 1 - i),
            rank=rank,
            composite_score=round(1.0 / rank, 6),
        )
        for i in range(days)
    ]


def _obs_trend(ranks: list[int], start: date = BASE_DATE) -> list[RankObservation]:
    """Build observations from a list of ranks, index 0 = most recent."""
    return [
        RankObservation(
            run_date=start + timedelta(len(ranks) - 1 - i),
            rank=r,
            composite_score=round(1.0 / r, 6),
        )
        for i, r in enumerate(ranks)
    ]


def _cold_portfolio(tickers: list[str]) -> dict[str, float]:
    """Replicate the pipeline service cold-start portfolio seed (weight=0.0 sentinel).

    The pipeline uses this when no portfolio-builder run exists:
        cold_start_portfolio = {t: 0.0 for t in live_positions_set}
    The 0.0 weight marks tickers as "held" (current_weight is not None) but
    suppresses drift actions (has_real_target requires current_weight > 0).
    """
    return {t: 0.0 for t in tickers}


def _quality(n: int) -> list[str]:
    return [f"QUAL{i:02d}" for i in range(1, n + 1)]


def _smallcaps(n: int, offset: int = 0) -> list[str]:
    return [f"SMCP{i:03d}" for i in range(1 + offset, n + 1 + offset)]


def _universe(
    quality_tickers: list[str],
    smallcap_tickers: list[str],
    days: int,
    smallcap_rank_start: int = POOR_RANK_START,
) -> dict[str, list[RankObservation]]:
    """Build a universe with quality tickers ranked 1..n and small caps ranked rank_start+."""
    u: dict[str, list[RankObservation]] = {}
    for i, t in enumerate(quality_tickers):
        u[t] = _obs(rank=i + 1, days=days)
    for i, t in enumerate(smallcap_tickers):
        u[t] = _obs(rank=smallcap_rank_start + i, days=days)
    return u


def _count(decisions: dict[str, DeltaDecision], action: str) -> int:
    return sum(1 for d in decisions.values() if d.action == action)


def _tickers(decisions: dict[str, DeltaDecision], action: str) -> set[str]:
    return {d.ticker for d in decisions.values() if d.action == action}


# ── Scenario A: Truly empty broker (baseline) ─────────────────────────────────

class TestColdBootEmptyBroker:
    """No Alpaca positions at all — baseline for comparison with orphan scenarios."""

    QUALITY = _quality(40)

    def _run(self) -> dict[str, DeltaDecision]:
        u = {t: _obs(rank=i + 1) for i, t in enumerate(self.QUALITY)}
        return evaluate_all(
            universe=u,
            current_portfolio={},
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )

    def test_empty_broker_fills_to_max_positions(self):
        d = self._run()
        entries = _count(d, "entry")
        assert entries == MAX_POSITIONS, (
            f"Empty broker should fill to max_positions={MAX_POSITIONS}, got {entries}"
        )

    def test_empty_broker_watches_tickers_beyond_capacity(self):
        d = self._run()
        watches = _count(d, "watch")
        assert watches == 10, (
            f"Tickers beyond capacity (40 - 30 = 10) should be watch, got {watches}"
        )

    def test_empty_broker_no_exit_hold_at_risk(self):
        d = self._run()
        for dec in d.values():
            assert dec.action not in ("exit", "hold", "at_risk"), (
                f"Empty broker should only produce entry/watch, got {dec.action} for {dec.ticker}"
            )

    def test_empty_broker_entry_current_weight_is_none(self):
        """
        evaluate_all with an empty portfolio returns current_weight=None for entries.
        In the real system, trade-executor sizes the order using the portfolio-builder's
        weight from portfolio_holdings, not from delta_intents.current_weight.
        evaluate_target_vs_live (normal mode) does carry the target weight — this test
        documents the difference between cold-start and normal entry mechanics.
        """
        d = self._run()
        for dec in d.values():
            if dec.action == "entry":
                assert dec.current_weight is None, (
                    f"{dec.ticker}: cold-boot entry current_weight should be None "
                    f"(portfolio-builder owns the weight), got {dec.current_weight}"
                )


# ── Scenario B: 10 pre-existing mixed-quality broker positions ────────────────

class TestColdBoot10MixedHoldings:
    """
    Broker holds 10 positions: 5 quality (rank ≤ entry_rank) and 5 small caps
    (rank outside exit zone).  Quality positions are held; small caps start the
    at_risk → exit progression while new quality tickers fill free slots.
    """

    QUALITY_HELD = [f"QHLD{i}" for i in range(1, 6)]    # rank 1-5 (excellent)
    SMALLCAP_HELD = [f"SMHLD{i}" for i in range(1, 6)]  # rank 45-49 (clearly outside zone)
    QUALITY_NEW = [f"QNEW{i:02d}" for i in range(1, 26)]  # rank 6-30 (entry-eligible)
    ALL_BROKER = QUALITY_HELD + SMALLCAP_HELD

    def _universe(self, bad_days: int) -> dict[str, list[RankObservation]]:
        u: dict[str, list[RankObservation]] = {}
        for i, t in enumerate(self.QUALITY_HELD):
            u[t] = _obs(rank=i + 1)              # rank 1-5, 3 days
        for i, t in enumerate(self.SMALLCAP_HELD):
            u[t] = _obs(rank=45 + i, days=bad_days)
        for i, t in enumerate(self.QUALITY_NEW):
            u[t] = _obs(rank=6 + i)              # rank 6-30, 3 days
        return u

    def _run(self, bad_days: int) -> dict[str, DeltaDecision]:
        return evaluate_all(
            universe=self._universe(bad_days),
            current_portfolio=_cold_portfolio(self.ALL_BROKER),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )

    def test_good_broker_positions_held(self):
        d = self._run(bad_days=1)
        for t in self.QUALITY_HELD:
            assert d[t].action == "hold", (
                f"{t} ranks well and is held at broker — expected hold, got {d[t].action}"
            )

    def test_poor_broker_positions_at_risk_day1(self):
        d = self._run(bad_days=1)
        for t in self.SMALLCAP_HELD:
            assert d[t].action == "at_risk", (
                f"{t} rank 45+ on day 1 — expected at_risk (1/{CONFIRMATION_DAYS}), "
                f"got {d[t].action}"
            )

    def test_poor_broker_positions_exit_day3(self):
        d = self._run(bad_days=3)
        for t in self.SMALLCAP_HELD:
            assert d[t].action == "exit", (
                f"{t} rank 45+ for 3 days — expected exit, got {d[t].action}"
            )

    def test_new_quality_tickers_enter_when_capacity_free(self):
        """10 broker positions < max_positions=30 → quality new tickers can enter."""
        d = self._run(bad_days=1)
        entries = _count(d, "entry")
        assert entries > 0, (
            "Quality new tickers (rank 6-30) should enter when portfolio has free slots"
        )
        # 10 held positions + 0 exits (day 1) → 20 free slots → 20 new entries
        assert entries == MAX_POSITIONS - len(self.ALL_BROKER), (
            f"Expected {MAX_POSITIONS - len(self.ALL_BROKER)} entries (free slots), "
            f"got {entries}"
        )

    def test_capacity_freed_by_exits_on_day3(self):
        """On day 3, 5 small caps exit → freed slots fill with more quality tickers."""
        d1 = self._run(bad_days=1)
        d3 = self._run(bad_days=3)
        assert _count(d1, "exit") == 0, "No exits on day 1"
        assert _count(d3, "exit") == 5, "5 small caps exit on day 3"

    def test_drift_suppressed_for_at_risk_positions(self):
        """at_risk tickers must NOT get buy_add even if underweight."""
        u = self._universe(bad_days=2)  # at_risk but not yet exit
        actual_weights = {t: 0.01 for t in self.SMALLCAP_HELD}  # severely underweight
        d = evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.ALL_BROKER),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
            actual_weights=actual_weights,
            drift_threshold=0.02,
        )
        for t in self.SMALLCAP_HELD:
            assert d[t].action == "at_risk", (
                f"{t}: at_risk must suppress buy_add even when severely underweight"
            )


# ── Scenario C: 30 small caps (exactly max_positions) ────────────────────────

class TestColdBoot30SmallCapsAtCapacity:
    """
    Broker holds exactly max_positions=30 small-cap positions.  All rank
    outside the exit zone.  Quality tickers are blocked as watch until capacity
    clears — which happens when all 30 confirm exit on day 3.
    """

    SMALLCAPS = _smallcaps(30)
    QUALITY = _quality(30)

    def _universe(self, days: int) -> dict[str, list[RankObservation]]:
        u: dict[str, list[RankObservation]] = {}
        for i, t in enumerate(self.SMALLCAPS):
            u[t] = _obs(rank=POOR_RANK_START + i, days=days)
        for i, t in enumerate(self.QUALITY):
            u[t] = _obs(rank=i + 1, days=days)
        return u

    def _run(self, days: int) -> dict[str, DeltaDecision]:
        return evaluate_all(
            universe=self._universe(days),
            current_portfolio=_cold_portfolio(self.SMALLCAPS),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )

    def test_quality_watch_when_at_capacity_day1(self):
        """30 small caps = max_positions → quality tickers cannot enter on day 1."""
        d = self._run(days=1)
        for t in self.QUALITY:
            assert d[t].action == "watch", (
                f"Day 1: {t} should be watch (at capacity), got {d[t].action}"
            )

    def test_all_smallcaps_at_risk_day1(self):
        d = self._run(days=1)
        for t in self.SMALLCAPS:
            assert d[t].action == "at_risk", (
                f"Day 1: {t} should be at_risk (1/{CONFIRMATION_DAYS}), got {d[t].action}"
            )

    def test_all_smallcaps_still_at_risk_day2(self):
        d = self._run(days=2)
        for t in self.SMALLCAPS:
            assert d[t].action == "at_risk", (
                f"Day 2: {t} should be at_risk (2/{CONFIRMATION_DAYS}), got {d[t].action}"
            )

    def test_all_smallcaps_exit_day3(self):
        d = self._run(days=3)
        for t in self.SMALLCAPS:
            assert d[t].action == "exit", (
                f"Day 3: {t} should be exit (3/{CONFIRMATION_DAYS} confirmed), "
                f"got {d[t].action}"
            )

    def test_quality_enters_when_capacity_freed_day3(self):
        """All 30 small caps exit → projected_base=0 → 30 quality tickers enter."""
        d = self._run(days=3)
        entries = _count(d, "entry")
        assert entries == MAX_POSITIONS, (
            f"Day 3: expected {MAX_POSITIONS} quality entries (all capacity freed), "
            f"got {entries}"
        )

    def test_quality_entries_are_top_ranked(self):
        d = self._run(days=3)
        entry_set = _tickers(d, "entry")
        assert entry_set == set(self.QUALITY), (
            f"Entries must be quality tickers, not small caps. Unexpected: "
            f"{entry_set - set(self.QUALITY)}"
        )

    def test_capacity_math_is_correct(self):
        """projected_base = len(cold_portfolio) - pending_exits = 30 - 30 = 0."""
        d = self._run(days=3)
        exits = _count(d, "exit")
        entries = _count(d, "entry")
        # Post-trade: 30 - 30 exits + 30 entries = 30 = max_positions ✓
        assert exits == 30 and entries == MAX_POSITIONS, (
            f"Capacity math: exits={exits}, entries={entries}"
        )


# ── Scenario D: 60 small caps — the main scenario ─────────────────────────────

class TestColdBoot60SmallCaps:
    """
    THE MAIN SCENARIO.

    Broker has 60 small-cap positions (2× max_positions=30) on cold boot.
    Universe has 30 quality tickers (rank 1-30) and 60 small caps (rank 45-104).

    Day-by-day progression:
      Day 1:  60 at_risk  | 30 watch (at_capacity)
      Day 2:  60 at_risk  | 30 watch
      Day 3:  60 exit     | 30 entry (capacity freed by exits)
      Day 4+: 30 hold     | 0 exit   (stable quality portfolio)
    """

    QUALITY = _quality(30)
    SMALLCAPS_A = _smallcaps(20, offset=0)    # rank 45-64   (near-outside)
    SMALLCAPS_B = _smallcaps(20, offset=20)   # rank 65-84   (clearly outside)
    SMALLCAPS_C = _smallcaps(20, offset=40)   # rank 85-104  (deeply outside)
    ALL_SMALLCAPS = SMALLCAPS_A + SMALLCAPS_B + SMALLCAPS_C

    def _universe(self, days: int) -> dict[str, list[RankObservation]]:
        u: dict[str, list[RankObservation]] = {}
        for i, t in enumerate(self.QUALITY):
            u[t] = _obs(rank=i + 1, days=days)
        for i, t in enumerate(self.SMALLCAPS_A):
            u[t] = _obs(rank=45 + i, days=days)
        for i, t in enumerate(self.SMALLCAPS_B):
            u[t] = _obs(rank=65 + i, days=days)
        for i, t in enumerate(self.SMALLCAPS_C):
            u[t] = _obs(rank=85 + i, days=days)
        return u

    def _run(self, days: int) -> dict[str, DeltaDecision]:
        return evaluate_all(
            universe=self._universe(days),
            current_portfolio=_cold_portfolio(self.ALL_SMALLCAPS),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )

    # ── Day 1 ─────────────────────────────────────────────────────────────────

    def test_day1_all_60_smallcaps_at_risk(self):
        d = self._run(days=1)
        for t in self.ALL_SMALLCAPS:
            assert d[t].action == "at_risk", (
                f"Day 1: {t} should be at_risk (1/3), got {d[t].action}"
            )

    def test_day1_quality_blocked_as_watch(self):
        """projected_base = 60 - 0 pending_exits = 60 > max_positions=30 → at_capacity."""
        d = self._run(days=1)
        for t in self.QUALITY:
            assert d[t].action == "watch", (
                f"Day 1: {t} must be watch — broker occupies 60 > {MAX_POSITIONS} slots, "
                f"got {d[t].action}"
            )

    def test_day1_no_entry_signals(self):
        d = self._run(days=1)
        assert _count(d, "entry") == 0, "Day 1: no entries while capacity is blocked"

    def test_day1_no_exit_signals(self):
        d = self._run(days=1)
        assert _count(d, "exit") == 0, "Day 1: no exits — only 1 bad day observed"

    def test_day1_at_risk_progress_is_one(self):
        """confirmation_days_met should be 1 on day 1 for all at_risk tickers."""
        d = self._run(days=1)
        for t in self.ALL_SMALLCAPS:
            assert d[t].confirmation_days_met == 1, (
                f"Day 1: {t} confirmation_days_met should be 1, got {d[t].confirmation_days_met}"
            )

    # ── Day 2 ─────────────────────────────────────────────────────────────────

    def test_day2_still_at_risk(self):
        d = self._run(days=2)
        for t in self.ALL_SMALLCAPS:
            assert d[t].action == "at_risk", (
                f"Day 2: {t} should still be at_risk (2/3), got {d[t].action}"
            )

    def test_day2_quality_still_watch(self):
        d = self._run(days=2)
        for t in self.QUALITY:
            assert d[t].action == "watch", (
                f"Day 2: {t} still at_capacity, got {d[t].action}"
            )

    def test_day2_at_risk_progress_is_two(self):
        d = self._run(days=2)
        for t in self.ALL_SMALLCAPS:
            assert d[t].confirmation_days_met == 2, (
                f"Day 2: {t} confirmation_days_met should be 2, "
                f"got {d[t].confirmation_days_met}"
            )

    # ── Day 3: the transition ─────────────────────────────────────────────────

    def test_day3_all_60_smallcaps_exit(self):
        d = self._run(days=3)
        exits = _tickers(d, "exit")
        assert exits == set(self.ALL_SMALLCAPS), (
            f"Day 3: all 60 small caps must exit. Missing exits: "
            f"{set(self.ALL_SMALLCAPS) - exits}"
        )

    def test_day3_exactly_max_positions_quality_enter(self):
        """projected_base = 60 - 60 = 0 → all 30 quality tickers can enter."""
        d = self._run(days=3)
        entries = _count(d, "entry")
        assert entries == MAX_POSITIONS, (
            f"Day 3: expected {MAX_POSITIONS} entries (capacity fully freed), got {entries}"
        )

    def test_day3_entries_are_all_quality_tickers(self):
        d = self._run(days=3)
        entry_set = _tickers(d, "entry")
        assert entry_set == set(self.QUALITY), (
            f"Day 3: entries must be exactly the quality tickers. "
            f"Got unexpected: {entry_set - set(self.QUALITY)}"
        )

    def test_day3_no_overlap_between_exit_and_entry(self):
        """A ticker cannot be both exit and entry."""
        d = self._run(days=3)
        exit_set = _tickers(d, "exit")
        entry_set = _tickers(d, "entry")
        assert not (exit_set & entry_set), (
            f"Impossible overlap between exit and entry: {exit_set & entry_set}"
        )

    def test_day3_exit_confidence_is_confirmed(self):
        """All exits must have confirmation_days_met == CONFIRMATION_DAYS."""
        d = self._run(days=3)
        for t in self.ALL_SMALLCAPS:
            assert d[t].confirmation_days_met == CONFIRMATION_DAYS, (
                f"Day 3 exit: {t} confirmation_days_met should be {CONFIRMATION_DAYS}, "
                f"got {d[t].confirmation_days_met}"
            )

    def test_day3_post_trade_portfolio_equals_max_positions(self):
        """After applying decisions: 60 - 60 exits + 30 entries = 30 = max_positions."""
        d = self._run(days=3)
        exits = _count(d, "exit")
        entries = _count(d, "entry")
        post_trade = 60 - exits + entries
        assert post_trade == MAX_POSITIONS, (
            f"Post-trade count should be {MAX_POSITIONS}, got {post_trade} "
            f"(exits={exits}, entries={entries})"
        )

    def test_day3_extra_capacity_gives_extra_entries(self):
        """If universe had 40 quality tickers, tickers 31-40 are watch (still at max)."""
        quality_40 = _quality(40)
        u: dict[str, list[RankObservation]] = {}
        for i, t in enumerate(quality_40):
            u[t] = _obs(rank=i + 1, days=3)
        for i, t in enumerate(self.ALL_SMALLCAPS):
            u[t] = _obs(rank=45 + i, days=3)
        d = evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.ALL_SMALLCAPS),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        entries = _count(d, "entry")
        watches_qual = [dec for dec in d.values()
                        if dec.action == "watch" and dec.ticker.startswith("QUAL")]
        assert entries == MAX_POSITIONS, (
            f"Should have exactly {MAX_POSITIONS} entries even with 40 quality tickers"
        )
        assert len(watches_qual) == 10, (
            f"10 quality tickers beyond capacity must be watch, got {len(watches_qual)}"
        )

    # ── Partial exit scenarios ────────────────────────────────────────────────

    def test_partial_exit_releases_proportional_capacity(self):
        """Only 20 of 60 small caps have 3 bad days; 40 still at_risk.
        projected_base = 60 - 20 = 40 > max_positions → quality still blocked.
        """
        u: dict[str, list[RankObservation]] = {}
        for i, t in enumerate(self.QUALITY):
            u[t] = _obs(rank=i + 1, days=3)
        # Smallcaps A: 3 bad days (confirm exit)
        for i, t in enumerate(self.SMALLCAPS_A):
            u[t] = _obs(rank=45 + i, days=3)
        # Smallcaps B+C: only 1 bad day (still at_risk)
        for i, t in enumerate(self.SMALLCAPS_B + self.SMALLCAPS_C):
            u[t] = _obs(rank=65 + i, days=1)

        d = evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.ALL_SMALLCAPS),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        assert _count(d, "exit") == 20, "Smallcaps A (20) confirmed exit"
        assert _count(d, "at_risk") == 40, "Smallcaps B+C (40) still at_risk"
        # projected_base = 60 - 20 = 40 > 30 → no entries
        assert _count(d, "entry") == 0, (
            "projected_base=40 > max_positions=30 → quality tickers still blocked"
        )

    def test_40_exits_enables_partial_entry(self):
        """40 of 60 exit → projected_base=20 → 10 quality entries (30 - 20 = 10 slots)."""
        u: dict[str, list[RankObservation]] = {}
        for i, t in enumerate(self.QUALITY):
            u[t] = _obs(rank=i + 1, days=3)
        # Smallcaps A+B (40): 3 bad days → exit
        for i, t in enumerate(self.SMALLCAPS_A + self.SMALLCAPS_B):
            u[t] = _obs(rank=45 + i, days=3)
        # Smallcaps C (20): 1 bad day → at_risk
        for i, t in enumerate(self.SMALLCAPS_C):
            u[t] = _obs(rank=85 + i, days=1)

        d = evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.ALL_SMALLCAPS),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        assert _count(d, "exit") == 40
        assert _count(d, "at_risk") == 20
        # projected_base = 60 - 40 = 20; free slots = 30 - 20 = 10
        assert _count(d, "entry") == 10, (
            f"40 exits free 10 slots (30 - 20 = 10), got {_count(d, 'entry')} entries"
        )


# ── Scenario E: 60 small caps with buffer-zone survivors ─────────────────────

class TestColdBoot60SmallCapsMixed:
    """
    Realistic scenario: not all orphan positions rank poorly.

    15 "good" small caps: rank 31-45 (in buffer zone ENTRY_RANK < rank ≤ EXIT_RANK).
      → These are held rather than exited — rank is within the safety zone.
    45 "poor" small caps: rank 41-85 (above EXIT_RANK=40).
      → These confirm exit after 3 days.
    30 quality tickers: rank 1-30.

    After 3 days: 45 exit, 15 hold, 15 quality enter (max_positions - 15 = 15 slots).
    """

    GOOD_SMCP = [f"GSMCP{i:02d}" for i in range(1, 16)]   # 15, rank 31-45 buffer zone
    POOR_SMCP = [f"PSMCP{i:03d}" for i in range(1, 46)]   # 45, rank 41-85 outside zone
    QUALITY = _quality(30)
    ALL_BROKER = GOOD_SMCP + POOR_SMCP

    def _universe(self, days: int) -> dict[str, list[RankObservation]]:
        u: dict[str, list[RankObservation]] = {}
        # GOOD_SMCP: ranks 26-40 — all ≤ EXIT_RANK=40 (buffer zone, some also in entry zone).
        # Formula: EXIT_RANK - 14 + i → 26, 27, ..., 40 for i=0..14.
        for i, t in enumerate(self.GOOD_SMCP):
            u[t] = _obs(rank=EXIT_RANK - 14 + i, days=days)   # rank 26-40, ≤ EXIT_RANK=40
        for i, t in enumerate(self.POOR_SMCP):
            u[t] = _obs(rank=EXIT_RANK + 1 + i, days=days)    # rank 41-85, > EXIT_RANK=40
        for i, t in enumerate(self.QUALITY):
            u[t] = _obs(rank=i + 1, days=days)
        return u

    def test_buffer_zone_smallcaps_held_not_exited(self):
        """15 small caps in buffer zone (rank 31-40 ≤ EXIT_RANK=40) must be hold."""
        u = self._universe(days=3)
        d = evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.ALL_BROKER),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        for t in self.GOOD_SMCP:
            assert d[t].action == "hold", (
                f"{t} rank ≤ EXIT_RANK={EXIT_RANK} (buffer zone) — expected hold, "
                f"got {d[t].action}"
            )

    def test_poor_smallcaps_exit_after_confirmation(self):
        """45 small caps rank > EXIT_RANK for 3 days → exit."""
        u = self._universe(days=3)
        d = evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.ALL_BROKER),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        for t in self.POOR_SMCP:
            assert d[t].action == "exit", (
                f"{t} rank > EXIT_RANK for 3 days — expected exit, got {d[t].action}"
            )

    def test_portfolio_converges_15_survivors_plus_15_quality(self):
        """
        projected_base = 60 - 45 = 15 (15 good small caps hold, not exiting).
        Free slots = MAX_POSITIONS - projected_base = 30 - 15 = 15.
        → 15 quality tickers enter.
        Post-trade: 15 holds + 15 entries = 30 = max_positions.
        """
        u = self._universe(days=3)
        d = evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.ALL_BROKER),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        exits = _count(d, "exit")
        holds = _count(d, "hold")
        entries = _count(d, "entry")
        assert exits == 45, f"Expected 45 exits (poor small caps), got {exits}"
        assert holds == 15, f"Expected 15 holds (buffer zone survivors), got {holds}"
        assert entries == MAX_POSITIONS - 15, (
            f"Expected {MAX_POSITIONS - 15} quality entries (15 free slots), got {entries}"
        )

    def test_buffer_zone_survivors_current_weight_is_zero_sentinel(self):
        """Buffer-zone holds must show current_weight=0.0 (cold-start sentinel, not target)."""
        u = self._universe(days=3)
        d = evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.ALL_BROKER),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        for t in self.GOOD_SMCP:
            assert d[t].current_weight == 0.0, (
                f"{t}: hold must have current_weight=0.0 (cold-start sentinel), "
                f"got {d[t].current_weight}"
            )


# ── Scenario F: Data gaps — broker positions absent from ranking universe ──────

class TestColdBootDataGaps:
    """
    60 small-cap broker positions but 20 are absent from the ranking universe
    (av-ingestor hasn't fetched price/fundamentals for these tickers yet, or
    they are OTC stocks not in the investable universe).

    Expected: absent tickers stay as "hold" with rank=9999, never force-exit.
    The 40 ranked small caps still confirm exit normally.
    Capacity freed: 40 exits (not 60) → only 10 quality entries (30-20=10 slots).
    """

    IN_UNIVERSE = _smallcaps(40)
    NOT_IN_UNIVERSE = [f"OTC{i:03d}" for i in range(1, 21)]
    ALL_BROKER = IN_UNIVERSE + NOT_IN_UNIVERSE
    QUALITY = _quality(30)

    def _universe(self, days: int) -> dict[str, list[RankObservation]]:
        u: dict[str, list[RankObservation]] = {}
        for i, t in enumerate(self.IN_UNIVERSE):
            u[t] = _obs(rank=POOR_RANK_START + i, days=days)
        for i, t in enumerate(self.QUALITY):
            u[t] = _obs(rank=i + 1, days=days)
        # NOT_IN_UNIVERSE intentionally absent from universe
        return u

    def _run(self, days: int) -> dict[str, DeltaDecision]:
        return evaluate_all(
            universe=self._universe(days),
            current_portfolio=_cold_portfolio(self.ALL_BROKER),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )

    def test_absent_tickers_held_not_force_exited(self):
        """Tickers absent from universe get 'hold', not 'exit'."""
        d = self._run(days=3)
        for t in self.NOT_IN_UNIVERSE:
            assert d[t].action == "hold", (
                f"{t} absent from universe — should hold awaiting data, got {d[t].action}"
            )

    def test_absent_tickers_have_rank_sentinel(self):
        """rank=9999 is the no-data sentinel for tickers absent from the universe."""
        d = self._run(days=3)
        for t in self.NOT_IN_UNIVERSE:
            assert d[t].rank == 9999, (
                f"{t}: absent ticker rank should be 9999, got {d[t].rank}"
            )

    def test_ranked_smallcaps_exit_normally(self):
        """The 40 small caps that ARE ranked still exit after 3 confirmation days."""
        d = self._run(days=3)
        for t in self.IN_UNIVERSE:
            assert d[t].action == "exit", (
                f"{t} in universe and rank > EXIT_RANK for 3 days — expected exit, "
                f"got {d[t].action}"
            )

    def test_data_gap_reduces_freed_capacity(self):
        """
        40 exits (in-universe only) free 10 slots (30 - 20 remaining = 10).
        20 absent tickers stay as hold, counting toward projected_base.
        """
        d = self._run(days=3)
        exits = _count(d, "exit")
        holds = _count(d, "hold")
        entries = _count(d, "entry")
        assert exits == 40, f"Expected 40 exits (in-universe small caps), got {exits}"
        assert holds == 20, f"Expected 20 holds (absent from universe), got {holds}"
        # projected_base = 60 - 40 = 20; free slots = 30 - 20 = 10
        assert entries == MAX_POSITIONS - 20, (
            f"Expected {MAX_POSITIONS - 20} entries (only 10 slots free), got {entries}"
        )

    def test_data_gap_heals_when_tickers_appear_in_universe(self):
        """If absent tickers gain ranking data with bad rank, they enter at_risk."""
        u = self._universe(days=1)
        # OTC tickers now appear in universe with poor rank
        for i, t in enumerate(self.NOT_IN_UNIVERSE):
            u[t] = _obs(rank=POOR_RANK_START + 50 + i, days=1)
        d = evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.ALL_BROKER),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        for t in self.NOT_IN_UNIVERSE:
            assert d[t].action == "at_risk", (
                f"{t} now ranked (poorly) — should be at_risk, got {d[t].action}"
            )


# ── Multi-day simulation: 60 small caps → 30 quality tickers ─────────────────

@dataclass
class _Position:
    ticker: str
    shares: float
    price: float

    @property
    def market_value(self) -> float:
        return self.shares * self.price

    def weight(self, account_value: float) -> float:
        return self.market_value / account_value if account_value > 0 else 0.0


@dataclass
class _Sim:
    """Minimal broker + portfolio-builder state for the multi-day simulation."""
    broker: dict[str, _Position] = field(default_factory=dict)
    target: dict[str, float] = field(default_factory=dict)  # portfolio-builder output
    pb_has_run: bool = False
    account_value: float = ACCOUNT_VALUE

    def live_weights(self) -> dict[str, float]:
        return {t: p.weight(self.account_value) for t, p in self.broker.items()}

    def apply(self, decisions: dict[str, DeltaDecision], prices: dict[str, float]) -> None:
        for d in decisions.values():
            price = prices.get(d.ticker, 100.0)
            if d.action == "entry" and d.ticker not in self.broker:
                target_w = (d.current_weight or 0.0)
                if target_w <= 0:
                    target_w = 1.0 / MAX_POSITIONS
                shares = (self.account_value * target_w) / price
                self.broker[d.ticker] = _Position(d.ticker, shares, price)
            elif d.action == "exit":
                self.broker.pop(d.ticker, None)
            elif d.ticker in self.broker:
                self.broker[d.ticker].price = price

        # Portfolio-builder fires after first successful day with entries.
        # It builds a target from the current broker holdings at equal weight.
        if not self.pb_has_run:
            has_entries = any(d.action == "entry" for d in decisions.values())
            if has_entries and self.broker:
                n = len(self.broker)
                w = 1.0 / max(n, 1)
                self.target = {t: w for t in self.broker}
                self.pb_has_run = True


class TestMultiDaySellDown60To30:
    """
    Full 10-day simulation: 60 small caps → 30 quality tickers.

    Models the two pipeline evaluation modes:
      Day 0-2:  cold_start (evaluate_all, weight=0.0 sentinel, no pb run yet)
      Day 3+:   target_vs_live (evaluate_target_vs_live, after portfolio-builder fires)

    Universe history grows by one observation each day so confirmation streaks
    accumulate naturally.  The portfolio converges to 30 quality holdings by day 3
    and stays stable through day 9.
    """

    QUALITY = _quality(30)
    SMALLCAPS = _smallcaps(60)
    DAYS = 10

    @classmethod
    def setup_class(cls):
        cls._log: list[dict] = []
        cls._run_simulation()

    @classmethod
    def _run_simulation(cls):
        sim = _Sim()
        # Seed broker with 60 small caps at $50/share
        for i, t in enumerate(cls.SMALLCAPS):
            sim.broker[t] = _Position(t, shares=500.0, price=50.0)

        prices_smcp = {t: 50.0 for t in cls.SMALLCAPS}
        prices_qual = {t: 100.0 for t in cls.QUALITY}
        prices = {**prices_smcp, **prices_qual}

        for day_idx in range(cls.DAYS):
            # Ranking history: 1 observation on day 0, 2 on day 1, etc.
            obs_days = day_idx + 1
            u = _universe(cls.QUALITY, cls.SMALLCAPS, obs_days)

            live_set = set(sim.broker.keys())

            if not sim.pb_has_run:
                # Cold-start mode: seed portfolio from live_positions (weight=0.0 sentinel)
                cold_portfolio = _cold_portfolio(list(live_set))
                decisions = evaluate_all(
                    universe=u,
                    current_portfolio=cold_portfolio,
                    entry_rank=ENTRY_RANK,
                    exit_rank=EXIT_RANK,
                    confirmation_days=CONFIRMATION_DAYS,
                    max_positions=MAX_POSITIONS,
                )
                mode = "cold_start"
            else:
                # Normal mode: target_vs_live diff
                decisions = evaluate_target_vs_live(
                    target_portfolio=sim.target,
                    live_positions=live_set,
                    universe=u,
                    entry_rank=ENTRY_RANK,
                    exit_rank=EXIT_RANK,
                    confirmation_days=CONFIRMATION_DAYS,
                    max_positions=MAX_POSITIONS,
                    actual_weights=sim.live_weights(),
                )
                mode = "target_vs_live"

            by_action: dict[str, list[str]] = {}
            for d in decisions.values():
                by_action.setdefault(d.action, []).append(d.ticker)

            cls._log.append({
                "day": day_idx,
                "mode": mode,
                "broker_before": len(sim.broker),   # snapshot before applying decisions
                "exits": len(by_action.get("exit", [])),
                "entries": len(by_action.get("entry", [])),
                "at_risks": len(by_action.get("at_risk", [])),
                "holds": len(by_action.get("hold", [])),
                "watches": len(by_action.get("watch", [])),
                "buy_adds": len(by_action.get("buy_add", [])),
                "sell_trims": len(by_action.get("sell_trim", [])),
                "exit_tickers": set(by_action.get("exit", [])),
                "entry_tickers": set(by_action.get("entry", [])),
            })

            sim.apply(decisions, prices)

        # Store final state for tests
        cls._final_broker = set(sim.broker.keys())
        cls._sim_pb_ran = sim.pb_has_run

    # ── Cold-start days (0 and 1) ─────────────────────────────────────────────

    def test_day0_mode_is_cold_start(self):
        assert self._log[0]["mode"] == "cold_start"

    def test_day0_60_at_risk(self):
        assert self._log[0]["at_risks"] == 60, (
            f"Day 0: expected 60 at_risk, got {self._log[0]['at_risks']}"
        )

    def test_day0_30_quality_watch(self):
        assert self._log[0]["watches"] == 30, (
            f"Day 0: expected 30 watches (quality blocked), got {self._log[0]['watches']}"
        )

    def test_day0_no_entries_no_exits(self):
        log = self._log[0]
        assert log["entries"] == 0, f"Day 0 must have no entries, got {log['entries']}"
        assert log["exits"] == 0, f"Day 0 must have no exits, got {log['exits']}"

    def test_day1_still_at_risk_building(self):
        assert self._log[1]["at_risks"] == 60, (
            f"Day 1: expected 60 at_risk (2/3 toward exit), got {self._log[1]['at_risks']}"
        )
        assert self._log[1]["exits"] == 0

    # ── Transition day (day 2 = 3rd observation = confirmation_days reached) ──

    def test_day2_all_60_confirm_exit(self):
        assert self._log[2]["exits"] == 60, (
            f"Day 2 (3rd observation): expected 60 exits, got {self._log[2]['exits']}"
        )

    def test_day2_quality_tickers_enter(self):
        assert self._log[2]["entries"] == MAX_POSITIONS, (
            f"Day 2: expected {MAX_POSITIONS} entries (capacity freed), "
            f"got {self._log[2]['entries']}"
        )

    def test_day2_exit_tickers_are_small_caps(self):
        assert self._log[2]["exit_tickers"] == set(self.SMALLCAPS), (
            f"Day 2 exits should be the 60 small caps"
        )

    def test_day2_entry_tickers_are_quality(self):
        assert self._log[2]["entry_tickers"] == set(self.QUALITY), (
            f"Day 2 entries should be the 30 quality tickers"
        )

    # ── Broker count trajectory ───────────────────────────────────────────────

    def test_broker_starts_at_60(self):
        assert self._log[0]["broker_before"] == 60

    def test_broker_transitions_to_max_positions_by_day3(self):
        """After day-2 decisions are applied: broker_before for day 3 = MAX_POSITIONS."""
        assert self._log[3]["broker_before"] == MAX_POSITIONS, (
            f"Day 3: broker should have {MAX_POSITIONS} positions after transition, "
            f"got {self._log[3]['broker_before']}"
        )

    def test_broker_stays_stable_after_transition(self):
        """Days 3-9 should all show broker_before == MAX_POSITIONS."""
        for log in self._log[3:]:
            assert log["broker_before"] == MAX_POSITIONS, (
                f"Day {log['day']}: broker count should be stable at {MAX_POSITIONS}, "
                f"got {log['broker_before']}"
            )

    # ── Mode transition ───────────────────────────────────────────────────────

    def test_mode_transitions_to_target_vs_live(self):
        """After portfolio-builder fires (after day-2 entries), mode switches."""
        modes = [log["mode"] for log in self._log]
        assert "target_vs_live" in modes, "Mode must switch to target_vs_live after pb run"
        # Mode switches on day 3 (the day after entries)
        assert modes[3] == "target_vs_live", (
            f"Day 3 mode should be target_vs_live, got {modes[3]}"
        )

    def test_portfolio_builder_ran(self):
        assert self._sim_pb_ran, "Portfolio-builder must have run during simulation"

    # ── Final state ───────────────────────────────────────────────────────────

    def test_final_portfolio_is_quality_only(self):
        """Final broker holds only quality tickers, no small caps remain."""
        assert self._final_broker == set(self.QUALITY), (
            f"Final portfolio should be exactly the 30 quality tickers. "
            f"Unexpected: {self._final_broker - set(self.QUALITY)}, "
            f"Missing: {set(self.QUALITY) - self._final_broker}"
        )

    def test_final_portfolio_size_is_max_positions(self):
        assert len(self._final_broker) == MAX_POSITIONS

    def test_stable_days_show_holds_not_exits(self):
        """Days 3-9: all broker positions held, no small-cap exits, no new entries."""
        for log in self._log[4:]:   # day 4+ is fully stable
            assert log["exits"] == 0, f"Day {log['day']}: unexpected exits"
            assert log["at_risks"] == 0, f"Day {log['day']}: unexpected at_risk"


# ── Fine-grained confirmation-day mechanics for 60 small caps ─────────────────

class TestConfirmationDayMechanics60SmallCaps:
    """
    Fine-grained verification of the 3-day confirmation streak for 60 small caps.
    Covers: exact boundary, progress counters, streak reset by one good day.
    """

    QUALITY = _quality(30)
    SMALLCAPS = _smallcaps(60)

    def _run(self, days: int) -> dict[str, DeltaDecision]:
        u = _universe(self.QUALITY, self.SMALLCAPS, days)
        return evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.SMALLCAPS),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )

    def test_exit_fires_at_exactly_confirmation_days(self):
        d2 = self._run(days=2)
        d3 = self._run(days=3)
        assert _count(d2, "exit") == 0, "No exits with only 2 days of bad ranking"
        assert _count(d3, "exit") == 60, "All 60 exit exactly at confirmation_days=3"

    def test_at_risk_progress_counters_day1_day2(self):
        """confirmation_days_met should increment each day."""
        d1 = self._run(days=1)
        d2 = self._run(days=2)
        for t in self.SMALLCAPS:
            assert d1[t].confirmation_days_met == 1, (
                f"Day 1: {t} confirmation_days_met should be 1"
            )
            assert d2[t].confirmation_days_met == 2, (
                f"Day 2: {t} confirmation_days_met should be 2"
            )

    def test_exit_confirmation_days_met_equals_3(self):
        d3 = self._run(days=3)
        for t in self.SMALLCAPS:
            assert d3[t].confirmation_days_met == CONFIRMATION_DAYS

    def test_streak_reset_by_one_buffer_day(self):
        """
        Pattern: bad, bad, buffer (rank in buffer zone), bad, bad
        The buffer day resets the streak — the most recent 3 days show only 2 bad.
        All small caps stay at_risk (2/3 toward exit).
        """
        bad_rank = EXIT_RANK + 10   # clearly outside zone
        buffer_rank = EXIT_RANK - 5  # inside buffer zone (≤ EXIT_RANK)
        # Most-recent first: bad, bad, buffer, bad, bad
        ranks = [bad_rank, bad_rank, buffer_rank, bad_rank, bad_rank]

        u: dict[str, list[RankObservation]] = {}
        for t in self.SMALLCAPS:
            u[t] = _obs_trend(ranks)
        for i, t in enumerate(self.QUALITY):
            u[t] = _obs(rank=i + 1, days=5)

        d = evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.SMALLCAPS),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        for t in self.SMALLCAPS:
            # Most recent 3: bad, bad, buffer → streak broken at position 2 → only 2 consecutive
            assert d[t].action == "at_risk", (
                f"{t}: one buffer day resets the streak — should be at_risk, "
                f"got {d[t].action}"
            )
            assert d[t].confirmation_days_met == 2, (
                f"{t}: 2 consecutive bad days at head after reset, "
                f"got confirmation_days_met={d[t].confirmation_days_met}"
            )

    def test_no_drift_actions_with_zero_sentinel_weight(self):
        """Cold-start weight=0.0 sentinel must never trigger buy_add/sell_trim."""
        u = _universe(self.QUALITY, self.SMALLCAPS, days=1)
        # Provide live weights showing small caps as severely underweight (would normally buy_add)
        actual_weights = {t: 0.001 for t in self.SMALLCAPS}
        d = evaluate_all(
            universe=u,
            current_portfolio=_cold_portfolio(self.SMALLCAPS),
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
            actual_weights=actual_weights,
            drift_threshold=0.02,
        )
        for t in self.SMALLCAPS:
            assert d[t].action not in ("buy_add", "sell_trim"), (
                f"{t}: cold-start sentinel weight=0.0 must suppress drift actions, "
                f"got {d[t].action}"
            )


# ── target_vs_live mode: orphan positions after portfolio-builder runs ─────────

class TestTargetVsLiveOrphanPositions:
    """
    After portfolio-builder runs, the delta engine uses evaluate_target_vs_live.

    Scenario: portfolio-builder built a target of 30 quality tickers, but the
    broker still holds 20 small caps from before the strategy was deployed
    (orphans — in live_positions but NOT in target_portfolio).

    This tests evaluate_target_vs_live's orphan handling: broker positions not
    in the target follow the same buffer-zone exit confirmation logic.
    """

    QUALITY_TARGET = _quality(30)
    ORPHAN_SMCPS = _smallcaps(20)

    def _run(self, smcp_days: int, smcp_rank: int = POOR_RANK_START) -> dict[str, DeltaDecision]:
        u: dict[str, list[RankObservation]] = {}
        for i, t in enumerate(self.QUALITY_TARGET):
            u[t] = _obs(rank=i + 1)
        # Use a fixed rank for ALL orphan tickers (no offset) so callers can precisely
        # control which zone all orphans land in without rank-overflow surprises.
        for t in self.ORPHAN_SMCPS:
            u[t] = _obs(rank=smcp_rank, days=smcp_days)

        target_portfolio = {t: 1.0 / MAX_POSITIONS for t in self.QUALITY_TARGET}
        live_positions = set(self.QUALITY_TARGET) | set(self.ORPHAN_SMCPS)

        return evaluate_target_vs_live(
            target_portfolio=target_portfolio,
            live_positions=live_positions,
            universe=u,
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )

    def test_target_tickers_held_get_hold(self):
        """Tickers in both target and broker get hold (or drift action if weights known)."""
        d = self._run(smcp_days=1)
        for t in self.QUALITY_TARGET:
            assert d[t].action in ("hold", "buy_add", "sell_trim"), (
                f"{t}: in target AND broker — expected hold/drift, got {d[t].action}"
            )

    def test_orphan_smallcaps_exit_on_day1(self):
        """Orphan broker positions exit immediately under Option A (non-empty target).

        Previously these were 'at_risk' on day 1 and 'exit' after confirmation_days.
        Option A: not-in-target = exit immediately, regardless of rank or duration.
        """
        d = self._run(smcp_days=1)
        for t in self.ORPHAN_SMCPS:
            assert d[t].action == "exit", (
                f"{t}: orphan with bad rank on day 1 → exit, got {d[t].action}"
            )

    def test_orphan_smallcaps_exit_on_day3(self):
        """Orphan positions exit (still expected after 3 days of bad rank)."""
        d = self._run(smcp_days=3)
        for t in self.ORPHAN_SMCPS:
            assert d[t].action == "exit", (
                f"{t}: orphan confirmed bad for 3 days — expected exit, got {d[t].action}"
            )

    def test_orphan_in_buffer_zone_exits_under_option_a(self):
        """Orphan with rank ≤ exit_rank still exits when target is non-empty.

        The buffer zone protects in-target positions only; an orphan with a good
        rank but no target slot is still excluded by portfolio-builder and gets
        an immediate exit.
        """
        buffer_rank = EXIT_RANK - 5   # within buffer zone
        d = self._run(smcp_days=3, smcp_rank=buffer_rank)
        for t in self.ORPHAN_SMCPS:
            assert d[t].action == "exit", (
                f"{t}: orphan not in target → exit (buffer zone irrelevant), got {d[t].action}"
            )

    def test_orphan_without_ranking_data_gets_hold(self):
        """Orphan absent from universe → hold (awaiting data, not force-exit)."""
        u: dict[str, list[RankObservation]] = {}
        for i, t in enumerate(self.QUALITY_TARGET):
            u[t] = _obs(rank=i + 1)
        # ORPHAN_SMCPS absent from universe

        target_portfolio = {t: 1.0 / MAX_POSITIONS for t in self.QUALITY_TARGET}
        live_positions = set(self.QUALITY_TARGET) | set(self.ORPHAN_SMCPS)

        d = evaluate_target_vs_live(
            target_portfolio=target_portfolio,
            live_positions=live_positions,
            universe=u,
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        for t in self.ORPHAN_SMCPS:
            assert d[t].action == "hold", (
                f"{t}: absent from universe — must hold awaiting data, not force-exit"
            )
