"""Audit forward windows: measured in SESSIONS, pooled at a FIXED horizon.

Two defects this pins, both found by reading the W30 report's own "data gaps":

1. The cutoff subtracted CALENDAR days while the code claimed "N days of
   prices". On a weekend review the two coincide; a mid-week review landed the
   cutoff on the prior Friday and scored ~3 sessions while the packet reported
   `fwd_window_days: 7`. A section whose job is honest evidence was overstating
   its own sample.

2. The audit anchored ONE build and started over every week, so the
   selected/cap_blocked/out_ranked comparison could never accumulate — hence
   "cap_blocked>selected remains a single window" in report after report.

The pure helpers are tested directly (the DB-backed path has its own
integration coverage in test_packet_integration.py).
"""
from datetime import date, timedelta

import pytest

from app.packet import (classify_candidates, horizon_bounds, pool_outcome_stats,
                        session_cutoff)


def _sessions(n: int, start=date(2026, 6, 1)) -> list[date]:
    """n consecutive WEEKDAY sessions — a calendar with real weekend gaps, which
    is the whole point: a calendar-day cutoff and a session cutoff only differ
    when weekends fall inside the window."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


# ── session_cutoff ───────────────────────────────────────────────────────────

class TestSessionCutoff:
    def test_cutoff_leaves_exactly_the_horizon_of_sessions_after_it(self):
        s = _sessions(30)
        cut = session_cutoff(s, 5)
        assert s.index(cut) == len(s) - 6          # 5 full sessions follow it
        assert len(s) - 1 - s.index(cut) == 5

    def test_horizon_zero_is_the_latest_session(self):
        s = _sessions(10)
        assert session_cutoff(s, 0) == s[-1]

    def test_none_when_history_is_shorter_than_the_horizon(self):
        assert session_cutoff(_sessions(3), 5) is None
        assert session_cutoff([], 5) is None

    def test_differs_from_a_calendar_cutoff_across_a_weekend(self):
        """THE bug. Latest session Wednesday: 5 CALENDAR days back is the prior
        Friday, which leaves only 3 sessions — the calendar cutoff admits a
        build the session cutoff correctly refuses."""
        s = _sessions(30)
        while s[-1].weekday() != 2:               # land on a Wednesday
            s = s[:-1]
        session_cut = session_cutoff(s, 5)
        calendar_cut = s[-1] - timedelta(days=5)
        assert calendar_cut > session_cut, (
            "calendar cutoff is not looser here — the fixture no longer "
            "reproduces the mid-week weekend case this test exists for")
        sessions_after_calendar = sum(1 for d in s if d > calendar_cut)
        assert sessions_after_calendar < 5        # the overstatement, quantified
        assert sum(1 for d in s if d > session_cut) == 5


# ── horizon_bounds ───────────────────────────────────────────────────────────

class TestHorizonBounds:
    def test_window_is_exactly_horizon_sessions_wide(self):
        s = _sessions(30)
        base, end = horizon_bounds(s, s[10], 5)
        assert base == s[10] and end == s[15]

    def test_anchor_on_a_non_session_snaps_back_to_the_last_session(self):
        """A build dated on a weekend/holiday must anchor on the prior session,
        not silently shift the window forward."""
        s = _sessions(30)
        fri = next(d for d in s if d.weekday() == 4)
        sat = fri + timedelta(days=1)
        assert horizon_bounds(s, sat, 3) == horizon_bounds(s, fri, 3)

    def test_none_when_the_window_would_run_past_available_data(self):
        """A PARTIAL window must never be scored as a full one — that is what
        makes pooled averages measure elapsed time instead of selection."""
        s = _sessions(30)
        assert horizon_bounds(s, s[-2], 5) is None
        assert horizon_bounds(s, s[-6], 5) is not None      # exactly reaches

    def test_none_before_the_start_of_history(self):
        s = _sessions(10)
        assert horizon_bounds(s, s[0] - timedelta(days=30), 3) is None


# ── pool_outcome_stats ───────────────────────────────────────────────────────

def _build(sel: list[float], cap: list[float]) -> dict:
    return {"returns": {"selected": sel, "cap_blocked": cap}}


class TestPoolOutcomeStats:
    def test_pools_observations_across_builds_not_averages_of_averages(self):
        """A build with 1 name must not carry the same weight as one with 3."""
        out = pool_outcome_stats([_build([0.10], []), _build([0.0, 0.0, 0.0], [])])
        assert out["by_outcome"]["selected"]["n"] == 4
        assert out["by_outcome"]["selected"]["avg_fwd_return"] == pytest.approx(0.025)

    def test_counts_the_windows_in_which_cap_blocked_beat_selected(self):
        """The statistic that answers the construction question. One window is
        an anecdote; this is what makes '6 of 8' expressible."""
        builds = [_build([0.01], [0.05]),      # cap wins
                  _build([0.02], [0.09]),      # cap wins
                  _build([0.04], [0.01])]      # selected wins
        cb = pool_outcome_stats(builds)["cap_blocked_vs_selected"]
        assert cb["windows_compared"] == 3
        assert cb["windows_beating_selected"] == 2
        assert cb["avg_spread_vs_selected"] == pytest.approx(
            ((0.05 - 0.01) + (0.09 - 0.02) + (0.01 - 0.04)) / 3, abs=5e-5)  # 4dp

    def test_a_window_missing_either_side_is_not_counted(self):
        """No cap_blocked names that day means no comparison — counting it as a
        'selected win' would bias the consistency test toward the builder."""
        cb = pool_outcome_stats([_build([0.01], []),
                                 _build([0.01], [0.05])])["cap_blocked_vs_selected"]
        assert cb["windows_compared"] == 1
        assert cb["windows_beating_selected"] == 1

    def test_empty_input_is_reported_as_absent_not_zero(self):
        """None means 'no evidence'; 0.0 would read as 'measured, no edge'."""
        out = pool_outcome_stats([])
        assert out["by_outcome"]["selected"]["avg_fwd_return"] is None
        assert out["by_outcome"]["selected"]["n"] == 0
        assert out["cap_blocked_vs_selected"]["windows_compared"] == 0
        assert out["cap_blocked_vs_selected"]["avg_spread_vs_selected"] is None

    def test_classification_feeds_the_pool_unchanged(self):
        """The pooled layer must not re-interpret classify_candidates: same
        four classes, same meanings."""
        audit = classify_candidates(
            [{"ticker": "A", "rank": 1}, {"ticker": "B", "rank": 2},
             {"ticker": "C", "rank": 3}, {"ticker": "D", "rank": 99}],
            selected={"A", "C"}, excluded={"B": "drawdown"}, worst_selected_rank=3)
        by = {a["ticker"]: a["outcome"] for a in audit}
        assert by == {"A": "selected", "B": "vetter_excluded",
                      "C": "selected", "D": "out_ranked"}
        out = pool_outcome_stats([{"returns": {"selected": [0.01],
                                               "vetter_excluded": [-0.05],
                                               "out_ranked": [0.02]}}])
        assert set(out["by_outcome"]) == {"selected", "cap_blocked",
                                          "vetter_excluded", "out_ranked"}
        assert out["by_outcome"]["vetter_excluded"]["avg_fwd_return"] == pytest.approx(-0.05)
