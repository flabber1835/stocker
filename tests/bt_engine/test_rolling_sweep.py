"""Phase 5b — rolling multi-window walk-forward + untouched holdout (pure math).

Window derivation must preserve the base window lengths, keep walk-forward
inside every window, carve the holdout out of the end, and return windows
oldest-first (window_idx chronological). Aggregation must be robust to error
legs (excluded from stats, reported as n_failed)."""
from datetime import date

import pytest

from app.sweep import (SweepWindows, aggregate_rolling, rolling_windows,
                       shift_months)


BASE = SweepWindows(tune_start=date(2015, 1, 1), tune_end=date(2021, 1, 1),
                    validate_start=date(2021, 1, 1), validate_end=date(2023, 1, 1))


# ── shift_months ──────────────────────────────────────────────────────────────

def test_shift_months_basic_and_year_boundary():
    assert shift_months(date(2026, 7, 15), -6) == date(2026, 1, 15)
    assert shift_months(date(2026, 1, 15), -1) == date(2025, 12, 15)
    assert shift_months(date(2025, 12, 15), 1) == date(2026, 1, 15)


def test_shift_months_day_clamping():
    assert shift_months(date(2026, 3, 31), -1) == date(2026, 2, 28)
    assert shift_months(date(2024, 3, 31), -1) == date(2024, 2, 29)   # leap year
    assert shift_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


# ── rolling window derivation ─────────────────────────────────────────────────

def test_windows_preserve_lengths_and_walk_forward():
    windows, holdout, err = rolling_windows(BASE, 3, 6, 0)
    assert err is None and holdout is None
    assert len(windows) == 3
    tune_len = BASE.tune_end - BASE.tune_start
    val_len = BASE.validate_end - BASE.validate_start
    for w in windows:
        assert w.tune_end - w.tune_start == tune_len
        assert w.validate_end - w.validate_start == val_len
        assert w.tune_end == w.validate_start          # walk-forward per window
        assert w.validate() is None


def test_windows_oldest_first_latest_anchored_at_validate_end():
    windows, _, err = rolling_windows(BASE, 3, 6, 0)
    assert err is None
    assert windows[-1].validate_end == BASE.validate_end
    ends = [w.validate_end for w in windows]
    assert ends == sorted(ends)                        # chronological
    assert windows[-2].validate_end == shift_months(BASE.validate_end, -6)
    assert windows[-3].validate_end == shift_months(BASE.validate_end, -12)


def test_holdout_carved_from_the_end_and_untouched_by_windows():
    windows, holdout, err = rolling_windows(BASE, 2, 6, 6)
    assert err is None
    assert holdout == (date(2022, 7, 1), date(2023, 1, 1))
    # no window may reach into the holdout
    assert all(w.validate_end <= holdout[0] for w in windows)
    assert windows[-1].validate_end == holdout[0]


def test_rejects_bad_specs():
    _, _, err = rolling_windows(BASE, 1, 6, 0)
    assert err is not None and "rolling_n_windows" in err
    _, _, err = rolling_windows(BASE, 2, 0, 0)
    assert err is not None and "step" in err
    # holdout swallowing the whole validate span
    _, _, err = rolling_windows(BASE, 2, 6, 25)
    assert err is not None and "holdout" in err


def test_zero_length_base_window_rejected():
    bad = SweepWindows(date(2020, 1, 1), date(2020, 1, 1),
                       date(2020, 1, 1), date(2021, 1, 1))
    _, _, err = rolling_windows(bad, 2, 6, 0)
    assert err is not None


# ── aggregation ───────────────────────────────────────────────────────────────

def _row(oos, ret=None, gap=0.1, error=None):
    # ret defaults to a monotone function of sharpe so return-ranking tests that
    # don't care about the exact number still get sensible values.
    return {"oos_sharpe": oos,
            "oos_return": ret if ret is not None else (oos * 0.1 if oos is not None else None),
            "overfit_gap": gap, "error_message": error}


def test_aggregate_median_worst_consistency():
    agg = aggregate_rolling([_row(1.0), _row(-0.5), _row(2.0)])
    assert agg["n_windows"] == 3 and agg["n_failed"] == 0
    assert agg["median_oos_sharpe"] == 1.0
    assert agg["worst_oos_sharpe"] == -0.5
    assert agg["consistency"] == pytest.approx(2 / 3, abs=1e-4)
    assert agg["mean_overfit_gap"] == pytest.approx(0.1)


def test_aggregate_ranks_on_return_not_sharpe():
    # median/worst OOS return are the ranking key now; assert they're computed
    agg = aggregate_rolling([_row(1.0, ret=0.30), _row(0.5, ret=-0.10),
                             _row(2.0, ret=0.50)])
    assert agg["median_oos_return"] == pytest.approx(0.30)
    assert agg["worst_oos_return"] == pytest.approx(-0.10)
    # sharpe still reported as a diagnostic
    assert agg["median_oos_sharpe"] == 1.0


def test_aggregate_excludes_error_legs_but_reports_them():
    agg = aggregate_rolling([_row(1.0, ret=0.2), _row(None, error="sim failed"),
                             _row(0.5, ret=0.4)])
    assert agg["n_windows"] == 3 and agg["n_failed"] == 1
    assert agg["median_oos_return"] == pytest.approx(0.3)
    assert agg["median_oos_sharpe"] == pytest.approx(0.75)
    assert agg["consistency"] == 1.0


def test_aggregate_all_errors_yields_null_stats():
    agg = aggregate_rolling([_row(None, error="x"), _row(None, error="y")])
    assert agg["n_failed"] == 2
    assert agg["median_oos_return"] is None
    assert agg["worst_oos_return"] is None
    assert agg["median_oos_sharpe"] is None
    assert agg["worst_oos_sharpe"] is None
    assert agg["consistency"] is None
