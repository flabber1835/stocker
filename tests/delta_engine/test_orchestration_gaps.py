"""
Tests for the three orchestration gaps not caught by prior unit tests:

1. evaluate_target_vs_live with empty target_portfolio + non-empty live_positions
   → all live positions become orphans → all tagged 'hold' (not entry, not exit).
   This is what the dashboard shows when portfolio-builder runs but produces 0 holdings.

2. The API /delta/latest ordering: scheduler-triggered delta must be preferred
   over the embedded pipeline delta, even if it started earlier.
   (Tests the ORDER BY preference logic, not the HTTP layer.)

3. evaluate_target_vs_live with non-empty target + empty live (true cold boot
   post-portfolio-builder) → all target tickers get 'entry'.
"""

from datetime import date, timedelta
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline/app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../_archive/delta-engine/app"))

from engine import evaluate_target_vs_live, evaluate_all, RankObservation


# ── helpers ──────────────────────────────────────────────────────────────────

def _obs(rank: int, days: int = 3, base: date = date(2025, 1, 1)) -> list[RankObservation]:
    return [
        RankObservation(run_date=base + timedelta(days - 1 - i), rank=rank,
                        composite_score=round(1.0 / rank, 6))
        for i in range(days)
    ]


ENTRY_RANK = 20
EXIT_RANK = 30
CONF = 3
MAX_POS = 15


# ── Gap 1: empty target_portfolio + live positions ────────────────────────────

class TestEmptyTargetPortfolio:
    """
    Reproduces the symptom: portfolio-builder ran but produced 0 holdings.
    target_portfolio = {} but live_positions has 4 broker tickers.
    All 4 become orphan tickers in evaluate_target_vs_live.
    """

    LIVE = {"AAPL", "MSFT", "NVDA", "GOOGL"}
    UNIVERSE = {
        "AAPL": _obs(rank=1),
        "MSFT": _obs(rank=2),
        "NVDA": _obs(rank=3),
        "GOOGL": _obs(rank=4),
    }

    def test_empty_target_with_live_positions_gives_hold_not_entry(self):
        """
        This is the bug scenario: target_portfolio={} means no entries are generated.
        Live positions become orphans and get hold/at_risk/exit based on rank only.
        """
        decisions = evaluate_target_vs_live(
            target_portfolio={},
            live_positions=self.LIVE,
            universe=self.UNIVERSE,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        for ticker in self.LIVE:
            assert decisions[ticker].action in ("hold", "at_risk"), \
                f"{ticker}: empty target → expected hold/at_risk, got {decisions[ticker].action}"
        # Crucially: no entries are generated because target_portfolio is empty
        entries = [d for d in decisions.values() if d.action == "entry"]
        assert len(entries) == 0, \
            "Empty target_portfolio must produce 0 entries — this is the portfolio-builder-empty bug"

    def test_empty_target_with_well_ranked_live_gives_hold(self):
        """Orphan tickers ranking well (< exit_rank) must be tagged hold, not exit."""
        decisions = evaluate_target_vs_live(
            target_portfolio={},
            live_positions={"AAPL"},
            universe={"AAPL": _obs(rank=5)},
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        assert decisions["AAPL"].action == "hold", \
            "Orphan ticker ranking well should be held, not exited"

    def test_empty_target_with_bad_ranked_live_gives_exit_when_confirmed(self):
        """Orphan tickers with confirmed bad rank (> exit_rank × confirmation_days) → exit."""
        decisions = evaluate_target_vs_live(
            target_portfolio={},
            live_positions={"AAPL"},
            universe={"AAPL": _obs(rank=40)},
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        assert decisions["AAPL"].action == "exit", \
            "Orphan ticker with confirmed bad rank should be exited"

    def test_empty_target_missing_from_universe_gives_hold_not_exit(self):
        """Orphan ticker absent from universe (e.g. data gap) → hold with 'awaiting data'."""
        decisions = evaluate_target_vs_live(
            target_portfolio={},
            live_positions={"AAPL"},
            universe={},  # AAPL not in universe at all
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        assert decisions["AAPL"].action == "hold", \
            "Orphan ticker absent from universe should be held (awaiting data), not force-exited"

    def test_non_empty_target_skipped_live_ticker_exits_under_option_a(self):
        """
        portfolio-builder built a partial target (3 of 4 live tickers).
        The 4th live ticker is an orphan → exit under Option A, regardless of rank.
        The 3 target tickers are in both target and live → hold (already held).
        """
        target = {"AAPL": 0.10, "MSFT": 0.10, "NVDA": 0.10}
        live = {"AAPL", "MSFT", "NVDA", "GOOGL"}
        universe = {
            "AAPL": _obs(rank=1),
            "MSFT": _obs(rank=2),
            "NVDA": _obs(rank=3),
            "GOOGL": _obs(rank=4),
        }
        decisions = evaluate_target_vs_live(
            target_portfolio=target,
            live_positions=live,
            universe=universe,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        assert decisions["GOOGL"].action == "exit", \
            "GOOGL is live but not in target (orphan) — must exit immediately"
        assert decisions["AAPL"].action == "hold"
        assert decisions["MSFT"].action == "hold"
        assert decisions["NVDA"].action == "hold"


# ── Gap 2: cold boot post-portfolio-builder ───────────────────────────────────

class TestColdBootPostPortfolioBuilder:
    """
    The scheduler sequence is:
      1. pipeline /jobs/run (factors + rank + embedded delta)
      2. portfolio-builder /jobs/build
      3. pipeline /jobs/delta (standalone delta, triggered_by='scheduler')

    After step 2, portfolio_holdings has N tickers. The standalone delta (step 3)
    calls evaluate_target_vs_live with those N tickers in target but none held at
    broker yet (alpaca-sync hasn't filled them). All N must get 'entry'.
    """

    def test_target_tickers_not_yet_at_broker_get_entry(self):
        """Core behaviour: portfolio-builder built target, broker has nothing yet."""
        target = {"AAPL": 0.10, "MSFT": 0.10, "NVDA": 0.10}
        live: set[str] = set()
        universe = {
            "AAPL": _obs(rank=1),
            "MSFT": _obs(rank=2),
            "NVDA": _obs(rank=3),
        }
        decisions = evaluate_target_vs_live(
            target_portfolio=target,
            live_positions=live,
            universe=universe,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        for ticker in target:
            assert decisions[ticker].action == "entry", \
                f"{ticker}: in target but not at broker → must be entry, got {decisions[ticker].action}"

    def test_entry_carries_target_weight_for_sizing(self):
        """Entry decisions must carry current_weight = target weight for trade-executor sizing."""
        target = {"AAPL": 0.083}
        decisions = evaluate_target_vs_live(
            target_portfolio=target,
            live_positions=set(),
            universe={"AAPL": _obs(rank=5)},
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        assert decisions["AAPL"].current_weight == pytest.approx(0.083, abs=1e-7), \
            "Entry intent must carry target weight so trade-executor can size the order"

    def test_partial_fill_target_not_yet_held_are_entries(self):
        """
        After day 1 of execution: 2 of 5 target tickers filled. The other 3 remain
        as 'entry' until the broker executes them.
        """
        target = {"AAPL": 0.10, "MSFT": 0.10, "NVDA": 0.10, "GOOGL": 0.10, "AMZN": 0.10}
        live: set[str] = {"AAPL", "MSFT"}  # 2 already filled
        universe = {t: _obs(rank=i+1) for i, t in enumerate(target)}
        decisions = evaluate_target_vs_live(
            target_portfolio=target,
            live_positions=live,
            universe=universe,
            entry_rank=ENTRY_RANK, exit_rank=EXIT_RANK,
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        assert decisions["AAPL"].action == "hold"
        assert decisions["MSFT"].action == "hold"
        assert decisions["NVDA"].action == "entry"
        assert decisions["GOOGL"].action == "entry"
        assert decisions["AMZN"].action == "entry"


# ── Gap 3: delta ordering preference (scheduler over pipeline) ────────────────

class TestDeltaRunOrdering:
    """
    Verifies the ORDER BY logic used in the API /delta/latest query:
      ORDER BY CASE WHEN triggered_by = 'scheduler' THEN 0 ELSE 1 END, started_at DESC

    We simulate this ordering in Python to confirm it selects the scheduler-triggered
    run even when it's older than an embedded pipeline run.
    """

    def _select_preferred_run(self, runs: list[dict]) -> dict:
        """Simulate the SQL ORDER BY used in the API."""
        return sorted(
            runs,
            key=lambda r: (0 if r["triggered_by"] == "scheduler" else 1, -r["started_at"]),
        )[0]

    def test_scheduler_delta_preferred_over_newer_pipeline_delta(self):
        """Scheduler-triggered delta wins even if an embedded delta ran more recently."""
        runs = [
            {"triggered_by": "pipeline",  "started_at": 300},  # most recent
            {"triggered_by": "scheduler", "started_at": 200},  # older but preferred
        ]
        preferred = self._select_preferred_run(runs)
        assert preferred["triggered_by"] == "scheduler", \
            "API must return the scheduler-triggered delta, not the most-recently-started one"

    def test_most_recent_scheduler_selected_when_multiple(self):
        """When multiple scheduler runs exist, the most recent one is returned."""
        runs = [
            {"triggered_by": "scheduler", "started_at": 100},
            {"triggered_by": "scheduler", "started_at": 200},  # newer scheduler run
            {"triggered_by": "pipeline",  "started_at": 300},
        ]
        preferred = self._select_preferred_run(runs)
        assert preferred["triggered_by"] == "scheduler"
        assert preferred["started_at"] == 200

    def test_pipeline_delta_is_fallback_when_no_scheduler_run_exists(self):
        """If no scheduler-triggered delta exists, fall back to the pipeline delta."""
        runs = [
            {"triggered_by": "pipeline", "started_at": 100},
            {"triggered_by": "pipeline", "started_at": 200},
        ]
        preferred = self._select_preferred_run(runs)
        assert preferred["triggered_by"] == "pipeline"
        assert preferred["started_at"] == 200

    def test_single_pipeline_run_is_returned(self):
        """On first boot (only embedded delta exists), that run is returned."""
        runs = [{"triggered_by": "pipeline", "started_at": 100}]
        preferred = self._select_preferred_run(runs)
        assert preferred["triggered_by"] == "pipeline"
