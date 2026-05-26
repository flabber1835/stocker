"""
Cold-boot and position-state simulation tests.

Three scenarios, each run as a pure engine simulation (no DB or Docker):

A. Cold boot — Alpaca is empty (no positions, no portfolio run yet)
   Engine falls back to evaluate_all with empty portfolio.
   Expected: only entry and watch — no hold/at_risk/drift actions.

B. 4 positions "in the tank" — held at broker but prices crashed ~50%
   Actual weights are half of target; rankings are still healthy (rank ≤ entry_rank).
   Expected: buy_add for the 4 underweight tickers; rest of portfolio normal.

C. 4 positions low ranked — held at broker at target weight but rank has deteriorated
   C1: rank just outside exit zone but not confirmed (< confirmation_days) → at_risk
   C2: rank outside exit zone confirmed (≥ confirmation_days) → exit

For each scenario the test also verifies which tickers the LLM vetter *would*
evaluate. The vetter queries `rankings ORDER BY rank ASC LIMIT candidate_count`
and is completely independent of delta actions — it never "sees" at_risk/buy_add.
"""

from __future__ import annotations

import sys
import os
from datetime import date, timedelta
from typing import Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline/app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../_archive/delta-engine/app"))

from engine import evaluate_all, RankObservation, DeltaDecision


# ── Shared helpers ───────────────────────────────────────────────────────────

ENTRY_RANK = 20
EXIT_RANK = 30
CONFIRMATION_DAYS = 3
MAX_POSITIONS = 10
DRIFT_THRESHOLD = 0.02
VETTER_CANDIDATE_COUNT = 50  # default from strategy config


def _obs(rank: int, days: int = 3, base: date = date(2025, 1, 1)) -> list[RankObservation]:
    """Build `days` consecutive observations all at `rank`, most-recent first."""
    return [
        RankObservation(run_date=base + timedelta(days - 1 - i), rank=rank,
                        composite_score=round(1.0 / rank, 6))
        for i in range(days)
    ]


def _obs_mixed(good_days: int, bad_days: int,
               good_rank: int = 5, bad_rank: int = 35,
               base: date = date(2025, 1, 1)) -> list[RankObservation]:
    """Build history: `bad_days` recent bad ranks then `good_days` older good ranks."""
    result = []
    for i in range(bad_days):
        result.append(RankObservation(
            run_date=base + timedelta(good_days + bad_days - 1 - i),
            rank=bad_rank, composite_score=round(1.0 / bad_rank, 6)))
    for i in range(good_days):
        result.append(RankObservation(
            run_date=base + timedelta(good_days - 1 - i),
            rank=good_rank, composite_score=round(1.0 / good_rank, 6)))
    return result  # already most-recent first


def _vetter_would_see(universe: dict[str, list[RankObservation]],
                      candidate_count: int = VETTER_CANDIDATE_COUNT) -> list[str]:
    """
    Simulate which tickers the LLM vetter would evaluate.
    Vetter queries: SELECT ticker FROM rankings ORDER BY rank ASC LIMIT n
    where `rank` is from the most-recent observation (day 0).
    """
    ranked = sorted(
        ((ticker, obs[0].rank) for ticker, obs in universe.items()),
        key=lambda x: x[1],
    )
    return [t for t, _ in ranked[:candidate_count]]


# ── Scenario A: Cold boot (empty Alpaca) ─────────────────────────────────────

class TestColdBoot:
    """
    No existing portfolio, no live Alpaca positions.
    Engine receives empty current_portfolio and None for actual_weights.
    """

    @classmethod
    def _build_universe(cls) -> dict[str, list[RankObservation]]:
        # 8 tickers that confirm in entry zone (rank 1-8)
        # 5 tickers that confirm but will be watch (portfolio capped at 10)
        # Total 13 tickers; first 10 by iteration order enter, last 3 watch
        universe = {}
        for i, ticker in enumerate(["AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","AMD","AVGO","QCOM"]):
            universe[ticker] = _obs(rank=i+1)
        for i, ticker in enumerate(["ORCL","CRM","NOW"]):
            universe[ticker] = _obs(rank=i+1)  # excellent rank but portfolio will be full
        return universe

    def test_cold_boot_produces_only_entry_and_watch(self):
        universe = self._build_universe()
        decisions = evaluate_all(
            universe=universe,
            current_portfolio={},     # empty — no portfolio run yet
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
            actual_weights=None,
            drift_threshold=DRIFT_THRESHOLD,
        )
        actions = {d.action for d in decisions.values()}
        # Only entry and watch are valid when nothing is held
        assert actions <= {"entry", "watch"}, \
            f"Cold boot produced unexpected actions: {actions - {'entry', 'watch'}}"

    def test_cold_boot_fills_to_max_positions(self):
        universe = self._build_universe()
        decisions = evaluate_all(
            universe=universe, current_portfolio={},
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=None, drift_threshold=DRIFT_THRESHOLD,
        )
        entries = [d for d in decisions.values() if d.action == "entry"]
        assert len(entries) == MAX_POSITIONS, \
            f"Expected {MAX_POSITIONS} entries on cold boot, got {len(entries)}"

    def test_cold_boot_watch_when_over_capacity(self):
        universe = self._build_universe()
        decisions = evaluate_all(
            universe=universe, current_portfolio={},
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=None, drift_threshold=DRIFT_THRESHOLD,
        )
        watches = [d for d in decisions.values() if d.action == "watch"]
        # 13 tickers - 10 entries = 3 watches (ORCL, CRM, NOW)
        assert len(watches) == 3

    def test_cold_boot_no_hold_no_at_risk_no_drift(self):
        universe = self._build_universe()
        decisions = evaluate_all(
            universe=universe, current_portfolio={},
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=None, drift_threshold=DRIFT_THRESHOLD,
        )
        for d in decisions.values():
            assert d.action not in ("hold", "at_risk", "buy_add", "sell_trim", "exit"), \
                f"Cold boot produced {d.action} for {d.ticker} — impossible with empty portfolio"

    def test_cold_boot_insufficient_history_gives_watch(self):
        """With only 2 days of history, nothing should enter (needs 3 confirmation_days)."""
        universe = {t: _obs(rank=i+1, days=2)
                    for i, t in enumerate(["AAPL", "MSFT", "NVDA"])}
        decisions = evaluate_all(
            universe=universe, current_portfolio={},
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=None, drift_threshold=DRIFT_THRESHOLD,
        )
        assert all(d.action == "watch" for d in decisions.values()), \
            "With 2-day history and confirmation_days=3, all must be watch"

    def test_cold_boot_vetter_sees_all_entry_candidates(self):
        """On cold boot all entry candidates rank in the top 13 — vetter sees them all."""
        universe = self._build_universe()
        vetter_tickers = _vetter_would_see(universe)
        decisions = evaluate_all(
            universe=universe, current_portfolio={},
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
        )
        entry_tickers = {d.ticker for d in decisions.values() if d.action == "entry"}
        assert entry_tickers <= set(vetter_tickers), \
            "All entry candidates should be within the vetter's top-N window"


# ── Scenario B: 4 held positions "in the tank" (price crash) ─────────────────

class TestPositionsInTheTank:
    """
    4 tickers held at broker with target weight = 10% each.
    Their prices crashed ~50%, so actual_weight ≈ 5% each (underweight by ~5%).
    Their RANK is still healthy (rank ≤ entry_rank) — this is a price event, not
    a ranking deterioration. Expected: buy_add for all 4.
    """

    HELD = ["TANK1", "TANK2", "TANK3", "TANK4"]
    OTHER = ["STBL1", "STBL2", "STBL3", "STBL4", "STBL5", "STBL6"]

    @classmethod
    def _make(cls) -> tuple[dict, dict, dict]:
        universe: dict[str, list[RankObservation]] = {}
        # 4 crashed positions: rank still excellent (1-4)
        for i, t in enumerate(cls.HELD):
            universe[t] = _obs(rank=i + 1)
        # 6 stable positions filling remaining slots
        for i, t in enumerate(cls.OTHER):
            universe[t] = _obs(rank=i + 5)

        current_portfolio = {t: 0.10 for t in cls.HELD + cls.OTHER}  # all at 10%
        # Prices crashed: TANK tickers actual weight ≈ 5% (half target)
        actual_weights = {t: 0.05 for t in cls.HELD}
        actual_weights.update({t: 0.10 for t in cls.OTHER})  # stable tickers on target
        return universe, current_portfolio, actual_weights

    def test_tank_positions_get_buy_add(self):
        universe, portfolio, weights = self._make()
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=weights, drift_threshold=DRIFT_THRESHOLD,
        )
        for t in self.HELD:
            assert decisions[t].action == "buy_add", \
                f"{t} crashed 50% and still ranks well — expected buy_add, got {decisions[t].action}"

    def test_tank_positions_have_negative_drift(self):
        """buy_add decisions must have weight_drift < 0 (actual < target)."""
        universe, portfolio, weights = self._make()
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=weights, drift_threshold=DRIFT_THRESHOLD,
        )
        for t in self.HELD:
            d = decisions[t]
            assert d.weight_drift is not None
            assert d.weight_drift < 0, f"{t}: expected weight_drift < 0, got {d.weight_drift}"
            assert d.actual_weight == pytest.approx(0.05, abs=1e-7)
            assert d.weight_drift == pytest.approx(0.05 - 0.10, abs=1e-7)

    def test_stable_positions_hold(self):
        """Positions with no price drift remain hold."""
        universe, portfolio, weights = self._make()
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=weights, drift_threshold=DRIFT_THRESHOLD,
        )
        for t in self.OTHER:
            assert decisions[t].action == "hold", \
                f"{t} is on-target — expected hold, got {decisions[t].action}"

    def test_tank_positions_not_exited(self):
        """Price crash alone must never trigger exit — rank is still healthy."""
        universe, portfolio, weights = self._make()
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=weights, drift_threshold=DRIFT_THRESHOLD,
        )
        for t in self.HELD:
            assert decisions[t].action != "exit", \
                f"{t} ranked well but got exit — price crash must not trigger exit"

    def test_tank_positions_vetter_would_see_them(self):
        """TANK tickers rank 1-4 → vetter evaluates them (they're in the top 50)."""
        universe, _, _ = self._make()
        vetter_tickers = _vetter_would_see(universe, candidate_count=VETTER_CANDIDATE_COUNT)
        for t in self.HELD:
            assert t in vetter_tickers, \
                f"{t} ranks well but vetter would skip it — unexpected"

    def test_tank_without_live_weights_gives_hold(self):
        """If alpaca-sync hasn't run yet, actual_weights=None → no drift detection → hold."""
        universe, portfolio, _ = self._make()
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=None,  # sync not available
            drift_threshold=DRIFT_THRESHOLD,
        )
        for t in self.HELD:
            assert decisions[t].action == "hold", \
                f"Without live weights {t} should be hold, not {decisions[t].action}"


# ── Scenario C: 4 positions low ranked ───────────────────────────────────────

class TestLowRankedPositions:
    """
    4 tickers held at broker at target weight, but their rank has deteriorated.
    C1: rank > exit_rank for fewer than confirmation_days → at_risk
    C2: rank > exit_rank for exactly confirmation_days → exit

    Also verifies: vetter does NOT see these tickers (they rank past top-N).
    """

    LOW_RANKED = ["POOR1", "POOR2", "POOR3", "POOR4"]
    STABLE = ["STBL1", "STBL2", "STBL3", "STBL4", "STBL5", "STBL6"]

    @classmethod
    def _make(cls, bad_days: int) -> tuple[dict, dict, dict]:
        universe: dict[str, list[RankObservation]] = {}
        # Low-ranked: deteriorated to rank 40 (exit_rank=30) for `bad_days` days
        for i, t in enumerate(cls.LOW_RANKED):
            universe[t] = _obs_mixed(good_days=0, bad_days=bad_days,
                                      good_rank=5, bad_rank=40 + i)
        # Stable holdings: rank 1-6, fully healthy
        for i, t in enumerate(cls.STABLE):
            universe[t] = _obs(rank=i + 1)

        current_portfolio = {t: 0.10 for t in cls.LOW_RANKED + cls.STABLE}
        actual_weights = {t: 0.10 for t in cls.LOW_RANKED + cls.STABLE}  # on target
        return universe, current_portfolio, actual_weights

    # C1: insufficient confirmation days → at_risk

    def test_low_ranked_at_risk_when_unconfirmed(self):
        """2 bad days (< confirmation_days=3) → at_risk, not exit."""
        universe, portfolio, weights = self._make(bad_days=2)
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=weights, drift_threshold=DRIFT_THRESHOLD,
        )
        for t in self.LOW_RANKED:
            assert decisions[t].action == "at_risk", \
                f"{t}: 2 bad days → expected at_risk, got {decisions[t].action}"

    def test_at_risk_suppresses_drift_even_when_on_target(self):
        """at_risk tickers must not be tagged buy_add/sell_trim even if drift exists."""
        universe, portfolio, weights = self._make(bad_days=2)
        # Make low-ranked tickers underweight (as if prices also dropped)
        weights.update({t: 0.05 for t in self.LOW_RANKED})
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=weights, drift_threshold=DRIFT_THRESHOLD,
        )
        for t in self.LOW_RANKED:
            assert decisions[t].action == "at_risk", \
                f"{t}: at_risk must suppress buy_add even when underweight"

    # C2: confirmed exit

    def test_low_ranked_exit_when_confirmed(self):
        """3 bad days (= confirmation_days) → exit."""
        universe, portfolio, weights = self._make(bad_days=3)
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=weights, drift_threshold=DRIFT_THRESHOLD,
        )
        for t in self.LOW_RANKED:
            assert decisions[t].action == "exit", \
                f"{t}: 3 bad days → expected exit, got {decisions[t].action}"

    def test_exit_frees_slots_for_watch_tickers(self):
        """When 4 positions exit, remaining capacity should allow watches to enter."""
        universe, portfolio, weights = self._make(bad_days=3)
        # Add 4 watch candidates (great rank but portfolio currently full)
        for i, t in enumerate(["WATC1", "WATC2", "WATC3", "WATC4"]):
            universe[t] = _obs(rank=i + 1)
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=weights, drift_threshold=DRIFT_THRESHOLD,
        )
        # 4 exits → 4 free slots → WATC1-4 should enter
        entries = {d.ticker for d in decisions.values() if d.action == "entry"}
        expected_entries = {"WATC1", "WATC2", "WATC3", "WATC4"}
        assert expected_entries == entries, \
            f"After 4 exits expected {expected_entries} to enter, got {entries}"

    def test_stable_positions_hold_while_others_exit(self):
        universe, portfolio, weights = self._make(bad_days=3)
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=weights, drift_threshold=DRIFT_THRESHOLD,
        )
        for t in self.STABLE:
            assert decisions[t].action == "hold", \
                f"{t} is stable — expected hold while POOR* exit, got {decisions[t].action}"

    # Vetter behaviour for low-ranked tickers

    def test_vetter_does_not_see_low_ranked_positions(self):
        """
        Low-ranked positions (rank 40+) fall outside the vetter's top-N window
        when the universe is large enough. The vetter evaluates top-N by rank —
        it never learns about at_risk or exit; the portfolio-builder reads
        vetter_exclusions but the delta engine does not.

        We set candidate_count = len(STABLE) = 6 to model a real universe where
        thousands of tickers exist and only the top-6 are vetted.
        """
        universe, _, _ = self._make(bad_days=2)
        # candidate_count = number of stable tickers: vetter covers only the top 6
        vetter_tickers = _vetter_would_see(universe, candidate_count=len(self.STABLE))
        for t in self.LOW_RANKED:
            assert t not in vetter_tickers, \
                f"{t} ranks ~40 — outside the top-{len(self.STABLE)} vetter window"

    def test_vetter_sees_stable_tickers_not_at_risk_ones(self):
        """Stable tickers (rank 1-6) are in the vetter window; low-ranked ones are not."""
        universe, _, _ = self._make(bad_days=2)
        vetter_tickers = _vetter_would_see(universe, candidate_count=len(self.STABLE))
        for t in self.STABLE:
            assert t in vetter_tickers, \
                f"{t} ranks 1-6 but vetter would skip it"
        for t in self.LOW_RANKED:
            assert t not in vetter_tickers, \
                f"{t} ranks 40+ but vetter would evaluate it"

    def test_vetter_would_see_tank_tickers_that_still_rank_well(self):
        """
        Contrast: a position at_risk due to price crash but still ranking well
        IS visible to the vetter (good rank); one with bad rank is NOT.
        With only 2 tickers and candidate_count=1, only rank-1 is vetted.
        """
        tank_universe = {
            "PRICE_CRASH": _obs(rank=5),   # good rank, price crashed → buy_add
            "RANK_CRASH":  _obs(rank=45),  # bad rank, regardless of price → at_risk/exit
        }
        # Vetter picks top-1 only (simulating a cutoff below rank 45)
        vetter_tickers = _vetter_would_see(tank_universe, candidate_count=1)
        assert "PRICE_CRASH" in vetter_tickers, \
            "PRICE_CRASH ranks 5 — vetter should evaluate it"
        assert "RANK_CRASH" not in vetter_tickers, \
            "RANK_CRASH ranks 45 — vetter should not evaluate it"


# ── Edge cases across all three scenarios ────────────────────────────────────

class TestCrossScenarioEdgeCases:

    def test_mix_of_tank_and_low_ranked_in_same_portfolio(self):
        """
        2 tickers: price crashed (buy_add) + 2 tickers: rank crashed (at_risk).
        Ensure the two failure modes don't interfere.
        """
        universe = {
            "TANK1": _obs(rank=1),  # good rank, will get buy_add
            "TANK2": _obs(rank=2),
            "POOR1": _obs_mixed(good_days=0, bad_days=2, bad_rank=40),  # at_risk
            "POOR2": _obs_mixed(good_days=0, bad_days=2, bad_rank=41),
            "CORE1": _obs(rank=3),  # stable hold
            "CORE2": _obs(rank=4),
        }
        portfolio = {t: 0.10 for t in universe}
        weights = {
            "TANK1": 0.04, "TANK2": 0.04,  # underweight (crashed)
            "POOR1": 0.10, "POOR2": 0.10,  # on target (rank crash only)
            "CORE1": 0.10, "CORE2": 0.10,
        }
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
            actual_weights=weights, drift_threshold=DRIFT_THRESHOLD,
        )
        assert decisions["TANK1"].action == "buy_add"
        assert decisions["TANK2"].action == "buy_add"
        assert decisions["POOR1"].action == "at_risk"
        assert decisions["POOR2"].action == "at_risk"
        assert decisions["CORE1"].action == "hold"
        assert decisions["CORE2"].action == "hold"

    def test_cold_boot_with_one_day_history_gives_watch(self):
        """1 day of history — nothing can enter (confirmation_days=3)."""
        universe = {t: _obs(rank=i+1, days=1)
                    for i, t in enumerate(["AAPL", "MSFT", "NVDA"])}
        decisions = evaluate_all(
            universe=universe, current_portfolio={},
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
        )
        assert all(d.action == "watch" for d in decisions.values())

    def test_all_exits_clear_to_zero_portfolio(self):
        """Entire portfolio confirmed bad → all exit, final held count = 0."""
        universe = {
            f"BAD{i}": _obs_mixed(good_days=0, bad_days=3, bad_rank=40 + i)
            for i in range(6)
        }
        portfolio = {t: 0.10 for t in universe}
        decisions = evaluate_all(
            universe=universe, current_portfolio=portfolio,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS, max_positions=MAX_POSITIONS,
        )
        assert all(d.action == "exit" for d in decisions.values()), \
            "All 6 confirmed-bad tickers must exit"

    def test_portfolio_not_held_at_broker_gives_entry_intent(self):
        """
        Cold boot with a portfolio run already done (has target weights) but
        no broker positions yet — evaluate_target_vs_live path.
        live_positions is a set[str] of broker-held tickers.
        """
        from engine import evaluate_target_vs_live

        target = {"AAPL": 0.10, "MSFT": 0.10, "NVDA": 0.10}
        live: set[str] = set()  # broker has nothing yet

        universe = {
            "AAPL": _obs(rank=1),
            "MSFT": _obs(rank=2),
            "NVDA": _obs(rank=3),
        }
        decisions = evaluate_target_vs_live(
            target_portfolio=target,
            live_positions=live,
            universe=universe,
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        assert all(d.action == "entry" for d in decisions.values()), \
            "Tickers in target but not at broker should get entry intent"

    def test_broker_position_not_in_target_exits_immediately(self):
        """
        Broker has a position that the target portfolio no longer includes.

        Under Option A: the portfolio-builder has deliberately excluded this
        ticker from the target (e.g. it was bumped out by higher-ranked names,
        a sector cap, or a vetter exclusion). Buffer-zone protection only
        applies to in-target positions; not-in-target holdings exit
        immediately so the portfolio converges to the target.
        """
        from engine import evaluate_target_vs_live

        target = {"AAPL": 0.10}  # MSFT removed from target
        live: set[str] = {"AAPL", "MSFT"}  # broker still holds MSFT

        universe = {
            "AAPL": _obs(rank=1),
            "MSFT": _obs(rank=5),  # still ranks fine but excluded from target
        }
        decisions = evaluate_target_vs_live(
            target_portfolio=target,
            live_positions=live,
            universe=universe,
            entry_rank=ENTRY_RANK,
            exit_rank=EXIT_RANK,
            confirmation_days=CONFIRMATION_DAYS,
            max_positions=MAX_POSITIONS,
        )
        assert decisions["MSFT"].action == "exit", \
            f"MSFT held but not in target → exit, got {decisions['MSFT'].action}"
        assert "not in target portfolio" in decisions["MSFT"].reason
