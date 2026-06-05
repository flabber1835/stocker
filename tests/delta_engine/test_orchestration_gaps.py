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

# Engine lives in the pipeline service (delta-engine was consolidated into it in
# Phase 7). Import the LIVE copy — do not fall back to the _archive snapshot.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline/app"))

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
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        assert decisions["AAPL"].action == "hold", \
            "Orphan ticker ranking well should be held, not exited"

    def test_empty_target_never_force_exits_even_on_bad_rank(self):
        """An EMPTY target is a degraded build (builder failed / filtered all), NOT a
        'sell everything' signal. With the rank buffer retired, a held name is HELD
        regardless of rank until a non-empty target appears — rank can never force an
        exit on an empty build."""
        decisions = evaluate_target_vs_live(
            target_portfolio={},
            live_positions={"AAPL"},
            universe={"AAPL": _obs(rank=400)},  # awful rank
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        assert decisions["AAPL"].action == "hold", \
            "Empty target must hold all positions (degraded build), never force-exit on rank"

    def test_empty_target_missing_from_universe_gives_hold_not_exit(self):
        """Orphan ticker absent from universe (e.g. data gap) → hold with 'awaiting data'."""
        decisions = evaluate_target_vs_live(
            target_portfolio={},
            live_positions={"AAPL"},
            universe={},  # AAPL not in universe at all
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        assert decisions["AAPL"].action == "hold", \
            "Orphan ticker absent from universe should be held (awaiting data), not force-exited"

    def test_non_empty_target_skipped_well_ranked_live_ticker_at_risk_first_build(self):
        """
        portfolio-builder built a partial target (3 of 4 live tickers). The 4th
        live ticker (GOOGL, rank 4) is an orphan. On its first orphaned build (no
        build history) it is at_risk, not a snap exit — even though well-ranked,
        the target is binding and it will exit once the orphan window is met.
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
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        assert decisions["GOOGL"].action == "at_risk", \
            "GOOGL orphan on first build → at_risk (will exit once orphan window met)"
        assert decisions["AAPL"].action == "hold"
        assert decisions["MSFT"].action == "hold"
        assert decisions["NVDA"].action == "hold"

    def test_non_empty_target_skipped_orphan_exits_when_confirmed_across_builds(self):
        """Orphan absent from the target for confirmation_days builds → exit
        (regardless of rank)."""
        target = {"AAPL": 0.10}
        live = {"AAPL", "JUNK"}
        universe = {
            "AAPL": _obs(rank=1),
            "JUNK": _obs(rank=50),
        }
        hist = [{"AAPL"}] * CONF  # JUNK absent from the target for CONF builds
        decisions = evaluate_target_vs_live(
            target_portfolio=target,
            live_positions=live,
            universe=universe,
            confirmation_days=CONF, max_positions=MAX_POS,
            target_history=hist,
        )
        assert decisions["JUNK"].action == "exit", \
            "JUNK orphaned for CONF builds → should exit"

    def test_non_empty_target_skipped_bad_ranked_live_ticker_at_risk_when_not_confirmed(self):
        """Orphan ticker outside exit zone but not yet confirmed → at_risk."""
        target = {"AAPL": 0.10}
        live = {"AAPL", "JUNK"}
        universe = {
            "AAPL": _obs(rank=1),
            # Only 2 days of bad rank (confirmation_days=3 not met)
            "JUNK": [
                RankObservation(run_date=date(2025, 1, 3), rank=50, composite_score=0.02),
                RankObservation(run_date=date(2025, 1, 2), rank=50, composite_score=0.02),
                RankObservation(run_date=date(2025, 1, 1), rank=5,  composite_score=0.20),
            ],
        }
        decisions = evaluate_target_vs_live(
            target_portfolio=target,
            live_positions=live,
            universe=universe,
            confirmation_days=CONF, max_positions=MAX_POS,
        )
        assert decisions["JUNK"].action == "at_risk", \
            "JUNK rank > exit_rank but not confirmed — should be at_risk"


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
