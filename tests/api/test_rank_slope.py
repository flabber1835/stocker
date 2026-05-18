"""
Unit tests for _linear_slope — the rank-trend computation used by /rankings.

The function mirrors what the SQL REGR_SLOPE(rank, row_number) query does.
x indices are always 0, 1, 2, ... (equally-spaced integers) regardless of
the wall-clock gap between ranking runs, so weekends, holidays, and missed
runs are all treated identically: each recorded run is one step.

Negative slope  → rank is improving (moving toward #1)  → green ▲
Positive slope  → rank is worsening (moving toward #N)  → red ▼
slope near 0    → stable                                 → no arrow
None            → fewer than 2 data points               → no arrow
"""
import pytest
from app.main import _linear_slope


# ── Basic correctness ─────────────────────────────────────────────────────────

def test_single_point_returns_none():
    assert _linear_slope([42]) is None


def test_empty_returns_none():
    assert _linear_slope([]) is None


def test_two_points_improving():
    # rank went from 20 → 10: improving, slope should be negative
    slope = _linear_slope([20, 10])
    assert slope is not None
    assert slope < 0


def test_two_points_worsening():
    # rank went from 10 → 20: worsening, slope should be positive
    slope = _linear_slope([10, 20])
    assert slope is not None
    assert slope > 0


def test_five_points_steadily_improving():
    # Rank drops by 10 each run: [50, 40, 30, 20, 10]
    slope = _linear_slope([50, 40, 30, 20, 10])
    assert slope == pytest.approx(-10.0)


def test_five_points_steadily_worsening():
    slope = _linear_slope([10, 20, 30, 40, 50])
    assert slope == pytest.approx(10.0)


def test_flat_rank_slope_is_zero():
    # Rank unchanged across all 5 runs → slope = 0
    slope = _linear_slope([25, 25, 25, 25, 25])
    assert slope == pytest.approx(0.0)


def test_exact_slope_two_points():
    # x=[0,1], y=[100, 60] → slope = (60-100)/(1-0) = -40
    slope = _linear_slope([100, 60])
    assert slope == pytest.approx(-40.0)


def test_exact_slope_three_points():
    # x=[0,1,2], y=[30, 20, 10]
    # mx=1, my=20; num=(0-1)(30-20)+(1-1)(20-20)+(2-1)(10-20) = -10+0-10 = -20
    # den=(0-1)^2+(1-1)^2+(2-1)^2 = 1+0+1 = 2; slope = -10
    slope = _linear_slope([30, 20, 10])
    assert slope == pytest.approx(-10.0)


# ── Noisy / non-monotone trends ───────────────────────────────────────────────

def test_noisy_improving_trend():
    # Overall drift downward even with noise
    slope = _linear_slope([50, 45, 52, 38, 30])
    assert slope is not None
    assert slope < 0


def test_noisy_worsening_trend():
    slope = _linear_slope([10, 12, 8, 18, 25])
    assert slope is not None
    assert slope > 0


def test_v_shape_net_flat():
    # Goes down then comes back up — net slope should be near 0
    slope = _linear_slope([20, 10, 5, 10, 20])
    assert slope is not None
    assert abs(slope) < 1.0


# ── Date gap handling: weekends and missed runs ───────────────────────────────

def test_weekend_gap_treated_as_single_step():
    """
    Rankings only exist on trading days. A gap spanning a weekend (Fri → Mon)
    is identical to any other consecutive-run gap — the x index increments by 1.
    Slope over [Mon, Wed, Fri, Mon, Wed] is the same as [0, 1, 2, 3, 4].
    """
    # These ranks represent Mon/Wed/Fri/Mon/Wed — two weekends skipped
    # x is always [0,1,2,3,4] not calendar-day distance
    slope_with_weekend_gaps = _linear_slope([50, 45, 40, 35, 30])
    slope_consecutive       = _linear_slope([50, 45, 40, 35, 30])
    assert slope_with_weekend_gaps == pytest.approx(slope_consecutive)


def test_missed_run_gap_treated_as_single_step():
    """
    If the pipeline didn't run on a given day (outage, holiday), the next
    successful run becomes x+1, not x+gap_days. A 3-day gap and a 1-day gap
    are both just 'next step'.
    """
    # 4 runs instead of 5 due to one missed day — still computes a valid slope
    slope = _linear_slope([40, 30, 20, 10])  # 4 points; steady improvement
    assert slope == pytest.approx(-10.0)


def test_large_date_gap_same_as_adjacent_step():
    """
    A two-week stale gap between run N-1 and run N doesn't inflate the slope.
    The function sees two points: the previous run and the latest run.
    The slope is based on rank change / 1 step, not rank change / calendar days.
    """
    # Old rank 80, after 2-week gap rank is 30 — 50-position jump in 1 step
    slope = _linear_slope([80, 30])
    assert slope == pytest.approx(-50.0)


# ── Stale data: old runs still contribute ─────────────────────────────────────

def test_stale_data_slope_still_computed():
    """
    There is no age cutoff: even if the last 5 runs span 3 weeks instead of 5
    days, the slope is still computed. The caller decides how to interpret it.
    """
    slope = _linear_slope([60, 55, 50, 45, 40])
    assert slope is not None
    assert slope < 0


def test_only_two_stale_runs_returns_slope():
    # Minimum viable case: last 2 runs, even if weeks apart
    slope = _linear_slope([100, 50])
    assert slope == pytest.approx(-50.0)


# ── New / disappearing tickers ────────────────────────────────────────────────

def test_new_ticker_one_run_returns_none():
    """
    A ticker that just entered the universe only has 1 ranking data point.
    Slope must be None — no arrow shown.
    """
    assert _linear_slope([15]) is None


def test_ticker_reappears_after_absence():
    """
    If a ticker was absent for several runs and reappears, we only see it in
    the runs where it was ranked. Two data points → valid slope.
    """
    slope = _linear_slope([200, 80])  # was rank 200, now rank 80
    assert slope is not None
    assert slope < 0


# ── Boundary: threshold used by dashboard (|slope| >= 1) ─────────────────────

def test_slope_below_threshold_is_noise():
    # Moved < 1 rank/day on average: [10, 10, 11, 10, 10] — barely any trend
    slope = _linear_slope([10, 10, 11, 10, 10])
    assert slope is not None
    assert abs(slope) < 1.0  # dashboard shows no arrow


def test_slope_above_threshold_is_signal():
    # Moved ~5 ranks/day over 5 days: [50, 45, 40, 35, 30]
    slope = _linear_slope([50, 45, 40, 35, 30])
    assert slope is not None
    assert abs(slope) >= 1.0  # dashboard shows ▲


def test_slope_exactly_one_boundary():
    # Exact slope of -1: [4, 3, 2, 1, 0] — right at threshold
    slope = _linear_slope([4, 3, 2, 1, 0])
    assert slope == pytest.approx(-1.0)
