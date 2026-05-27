"""
Tests for the MAX(date)-based universe filter and probation re-probing.

The earlier streak-based approach (consecutive_empty_days,
quarantined_until) was replaced in migration 0007. Universe filtering
now uses the same empirical signal as the per-ticker skip check:
`MAX(date) IN daily_prices < spy_max` means AV had no row for today
the last time we asked. Re-probing happens via a rotation cohort that
re-admits ~1/N of the dropped tickers each fetch-universe run.

The helpers under test:
  - app.main._filter_stale_max_date
  - app.main._pick_probation_cohort
"""
from datetime import date, timedelta

import pytest

from app.main import (
    _filter_stale_max_date,
    _pick_probation_cohort,
)


TODAY = date(2026, 5, 27)
YESTERDAY = TODAY - timedelta(days=1)


# ── _filter_stale_max_date ───────────────────────────────────────────────────


def _row(ticker: str, **extra) -> dict:
    return {"ticker": ticker, "name": f"{ticker} Inc", **extra}


class TestFilterStaleMaxDate:

    def test_cold_start_keeps_everything_when_spy_max_is_none(self):
        """spy_max=None means daily_prices is empty — first ingest must keep all."""
        rows = [_row("AAPL"), _row("MSFT")]
        kept, dropped = _filter_stale_max_date(rows, ticker_latest={}, spy_max=None)
        assert kept == rows
        assert dropped == []

    def test_cold_start_keeps_everything_when_ticker_latest_empty(self):
        """Empty ticker_latest dict (no daily_prices rows yet) → keep all."""
        rows = [_row("AAPL"), _row("MSFT")]
        kept, dropped = _filter_stale_max_date(rows, ticker_latest={}, spy_max=TODAY)
        assert kept == rows
        assert dropped == []

    def test_all_up_to_date_kept(self):
        """Every ticker has today's bar → all kept, none dropped."""
        rows = [_row("AAPL"), _row("MSFT"), _row("GOOG")]
        latest = {"AAPL": TODAY, "MSFT": TODAY, "GOOG": TODAY}
        kept, dropped = _filter_stale_max_date(rows, latest, TODAY)
        assert {r["ticker"] for r in kept} == {"AAPL", "MSFT", "GOOG"}
        assert dropped == []

    def test_one_day_behind_dropped(self):
        """MAX(date) one day behind spy_max → dropped."""
        rows = [_row("LAG")]
        latest = {"LAG": YESTERDAY}
        kept, dropped = _filter_stale_max_date(rows, latest, TODAY)
        assert kept == []
        assert dropped == ["LAG"]

    def test_far_behind_dropped(self):
        """Months behind → dropped (no special handling, same code path)."""
        rows = [_row("DEAD")]
        latest = {"DEAD": TODAY - timedelta(days=90)}
        kept, dropped = _filter_stale_max_date(rows, latest, TODAY)
        assert kept == []
        assert dropped == ["DEAD"]

    def test_unknown_ticker_dropped(self):
        """A ticker with no daily_prices entry at all (latest is None)
        is treated as stale — it has never produced data, so the
        universe filter excludes it for now. The probation cohort
        will pick it up later if AV starts returning data."""
        rows = [_row("NEWLY")]
        latest = {"AAPL": TODAY}  # NEWLY absent
        kept, dropped = _filter_stale_max_date(rows, latest, TODAY)
        assert kept == []
        assert dropped == ["NEWLY"]

    def test_mixed_partitions_correctly(self):
        rows = [_row("CURRENT"), _row("STALE"), _row("ALSO_CURRENT"), _row("VERY_STALE")]
        latest = {
            "CURRENT": TODAY,
            "STALE": TODAY - timedelta(days=2),
            "ALSO_CURRENT": TODAY,
            "VERY_STALE": TODAY - timedelta(days=400),
        }
        kept, dropped = _filter_stale_max_date(rows, latest, TODAY)
        assert {r["ticker"] for r in kept} == {"CURRENT", "ALSO_CURRENT"}
        assert set(dropped) == {"STALE", "VERY_STALE"}

    def test_preserves_row_metadata(self):
        """The kept list returns the original row dicts unchanged."""
        rows = [_row("AAPL", sector="Tech", exchange="NASDAQ")]
        latest = {"AAPL": TODAY}
        kept, _ = _filter_stale_max_date(rows, latest, TODAY)
        assert kept == [{"ticker": "AAPL", "name": "AAPL Inc",
                         "sector": "Tech", "exchange": "NASDAQ"}]

    def test_accepts_bare_string_tickers(self):
        """Symmetry: accepts ['AAPL', 'MSFT'] as well as dict rows."""
        rows = ["AAPL", "STALE", "MSFT"]
        latest = {"AAPL": TODAY, "STALE": YESTERDAY, "MSFT": TODAY}
        kept, dropped = _filter_stale_max_date(rows, latest, TODAY)
        assert kept == ["AAPL", "MSFT"]
        assert dropped == ["STALE"]

    def test_row_with_no_ticker_field_is_passed_through(self):
        """Malformed row (no ticker key) is kept rather than crashing —
        the snapshot save path will reject it later if invalid."""
        rows = [{"weird": "shape"}, _row("AAPL")]
        latest = {"AAPL": TODAY}
        kept, dropped = _filter_stale_max_date(rows, latest, TODAY)
        # The malformed row got `t = None` and falls into the "no ticker" pass-through
        assert any(r.get("weird") == "shape" for r in kept)
        assert any(r.get("ticker") == "AAPL" for r in kept)
        assert dropped == []

    def test_empty_input(self):
        kept, dropped = _filter_stale_max_date([], {"AAPL": TODAY}, TODAY)
        assert kept == []
        assert dropped == []


# ── _pick_probation_cohort ──────────────────────────────────────────────────


class TestPickProbationCohort:

    def test_empty_input_returns_empty(self):
        assert _pick_probation_cohort([], {}, TODAY, 30) == []

    def test_rotation_days_zero_returns_empty(self):
        """rotation_days=0 disables the probation system entirely."""
        assert _pick_probation_cohort(["A", "B", "C"], {}, TODAY, 0) == []

    def test_rotation_days_negative_returns_empty(self):
        assert _pick_probation_cohort(["A", "B", "C"], {}, TODAY, -1) == []

    def test_cohort_size_is_ceil_division(self):
        """30 stale, rotation 30 → ceil(30/30) = 1 picked."""
        stale = [f"T{i:02d}" for i in range(30)]
        picked = _pick_probation_cohort(stale, {}, TODAY, 30)
        assert len(picked) == 1

    def test_cohort_size_rounds_up(self):
        """31 stale, rotation 30 → ceil(31/30) = 2 picked."""
        stale = [f"T{i:02d}" for i in range(31)]
        picked = _pick_probation_cohort(stale, {}, TODAY, 30)
        assert len(picked) == 2

    def test_cohort_size_caps_at_pool_size(self):
        """5 stale, rotation 30 → ceil(5/30) = 1 picked (not 0)."""
        stale = ["A", "B", "C", "D", "E"]
        picked = _pick_probation_cohort(stale, {}, TODAY, 30)
        assert len(picked) == 1

    def test_smaller_rotation_picks_more(self):
        """30 stale, rotation 3 → ceil(30/3) = 10 picked."""
        stale = [f"T{i:02d}" for i in range(30)]
        picked = _pick_probation_cohort(stale, {}, TODAY, 3)
        assert len(picked) == 10

    def test_oldest_consulted_picked_first(self):
        """The ticker with the earliest last_consulted_date is at the front
        of the cohort."""
        stale = ["RECENT", "OLD", "MIDDLE"]
        state = {
            "RECENT": {"last_consulted_date": TODAY},
            "OLD":    {"last_consulted_date": TODAY - timedelta(days=60)},
            "MIDDLE": {"last_consulted_date": TODAY - timedelta(days=10)},
        }
        # Force the full pool into the cohort
        picked = _pick_probation_cohort(stale, state, TODAY, rotation_days=1)
        assert picked == ["OLD", "MIDDLE", "RECENT"]

    def test_unconsulted_tickers_treated_as_oldest(self):
        """A ticker missing from fetch_state ranks earlier than any
        consulted one, so brand-new stale names get probed first."""
        stale = ["KNOWN", "UNKNOWN"]
        state = {"KNOWN": {"last_consulted_date": TODAY - timedelta(days=5)}}
        picked = _pick_probation_cohort(stale, state, TODAY, rotation_days=1)
        # UNKNOWN has no state row → treated as EPOCH (1900-01-01) → comes first
        assert picked == ["UNKNOWN", "KNOWN"]

    def test_state_with_null_date_treated_as_oldest(self):
        """state present but last_consulted_date is None → oldest."""
        stale = ["A", "B"]
        state = {
            "A": {"last_consulted_date": TODAY - timedelta(days=2)},
            "B": {"last_consulted_date": None},
        }
        picked = _pick_probation_cohort(stale, state, TODAY, rotation_days=1)
        assert picked == ["B", "A"]

    def test_deterministic_tie_break_by_ticker(self):
        """Ties on last_consulted_date are broken by ticker alphabetical
        order so re-runs are reproducible."""
        stale = ["ZZZ", "AAA", "MMM"]
        state = {t: {"last_consulted_date": TODAY - timedelta(days=10)} for t in stale}
        picked = _pick_probation_cohort(stale, state, TODAY, rotation_days=1)
        assert picked == ["AAA", "MMM", "ZZZ"]

    def test_rotation_covers_pool_over_n_runs(self):
        """Over `rotation_days` simulated runs the whole pool gets probed
        at least once. Models the system at steady state: every run, the
        oldest 1/N gets probed and updates last_consulted_date to today,
        sending it to the back of the queue."""
        pool = [f"T{i:03d}" for i in range(60)]
        # All unconsulted at start.
        state: dict = {}
        probed: set = set()
        simulated_today = TODAY
        for _ in range(30):
            cohort = _pick_probation_cohort(pool, state, simulated_today, 30)
            for t in cohort:
                state[t] = {"last_consulted_date": simulated_today}
                probed.add(t)
            simulated_today += timedelta(days=1)
        assert probed == set(pool), "Every stale ticker should have been probed within 30 runs"


# ── Behaviour under the live decision path ──────────────────────────────────


class TestEndToEndDecisions:
    """
    Combine the two helpers to simulate one fetch-universe -> fetch-data
    cycle. The point is to lock in:
       - stale tickers don't get re-fetched immediately
       - the rotation cohort eventually probes everyone
       - a successful probe re-admits the ticker to the universe
    """

    def test_resumer_reenters_after_one_successful_probe(self):
        """A halted-then-resumed ticker rejoins as soon as its probation
        slot lands and AV returns fresh data."""
        # Day 0: TICKER is stale.
        latest = {"AAPL": TODAY, "TICKER": TODAY - timedelta(days=20)}
        rows = [_row("AAPL"), _row("TICKER")]
        kept, dropped = _filter_stale_max_date(rows, latest, TODAY)
        assert dropped == ["TICKER"]

        # Probation picks it (the only one stale).
        probation = _pick_probation_cohort(dropped, {}, TODAY, 30)
        assert probation == ["TICKER"]

        # fetch-data calls AV for TICKER, AV returns today's bar → latest
        # updates to TODAY in daily_prices.
        latest_after = {"AAPL": TODAY, "TICKER": TODAY}

        # Next fetch-universe sees it as up-to-date again.
        kept_next, dropped_next = _filter_stale_max_date(rows, latest_after, TODAY)
        assert dropped_next == []
        assert {r["ticker"] for r in kept_next} == {"AAPL", "TICKER"}

    def test_persistent_dead_ticker_keeps_getting_dropped(self):
        """A truly dead ticker (AV keeps returning empty) gets re-probed
        but each cycle still produces 0 new rows, so it stays out of the
        primary universe."""
        rows = [_row("AAPL"), _row("DEAD")]
        state: dict = {}
        for day_offset in range(3):
            sim_today = TODAY + timedelta(days=day_offset)
            # Healthy ticker advances with sim_today; DEAD never updates.
            latest = {"AAPL": sim_today, "DEAD": TODAY - timedelta(days=50)}
            kept, dropped = _filter_stale_max_date(rows, latest, sim_today)
            assert dropped == ["DEAD"]
            probation = _pick_probation_cohort(dropped, state, sim_today, 30)
            assert probation == ["DEAD"]
            # Probe happens but AV returns nothing → daily_prices unchanged →
            # MAX(date) for DEAD is unchanged.
            state["DEAD"] = {"last_consulted_date": sim_today}
        # After 3 days DEAD still stale; last_consulted_date is current so
        # it would be picked LAST among any larger pool.
        assert state["DEAD"]["last_consulted_date"] == TODAY + timedelta(days=2)
