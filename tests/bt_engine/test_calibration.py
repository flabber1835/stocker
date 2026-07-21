"""Score-calibration diagnostics (closed-loop item 3, pure math) + the sim
summary wiring: a dataset where score ordering perfectly predicts forward
returns must produce a monotone decile curve; a shuffled one must not."""
from datetime import date, timedelta

import pytest

from app.calibration import (aggregate_calibration, decile_forward_returns,
                             sample_evenly)


def _scores(n=50):
    # ticker T00 best score … T49 worst
    return {f"T{i:02d}": float(n - i) for i in range(n)}


def test_perfectly_predictive_scores_yield_monotone_deciles():
    scores = _scores()
    base = {t: 100.0 for t in scores}
    # forward return decreases with worse score: best +25% … worst −24%
    fwd = {f"T{i:02d}": 100.0 * (1.25 - 0.01 * i) for i in range(50)}
    rows = decile_forward_returns(scores, base, fwd)
    assert len(rows) == 10
    avgs = [r["avg_fwd"] for r in rows]
    assert all(a > b for a, b in zip(avgs, avgs[1:]))     # strictly monotone
    agg = aggregate_calibration([rows], 20)
    assert agg["monotone_fraction"] == 1.0
    assert agg["top_minus_bottom"] == pytest.approx(avgs[0] - avgs[-1], abs=1e-6)
    assert agg["n_dates"] == 1


def test_uninformative_scores_yield_flat_curve():
    scores = _scores()
    base = {t: 100.0 for t in scores}
    fwd = {t: 105.0 for t in scores}                      # +5% for everyone
    agg = aggregate_calibration([decile_forward_returns(scores, base, fwd)], 20)
    assert agg["top_minus_bottom"] == pytest.approx(0.0, abs=1e-9)
    assert all(d["avg_fwd"] == pytest.approx(0.05) for d in agg["deciles"])


def test_missing_prices_skipped_not_averaged_as_zero():
    scores = _scores(20)
    base = {t: 100.0 for t in scores}
    fwd = {t: 110.0 for t in scores}
    del fwd["T00"]                                        # best name delisted mid-horizon
    rows = decile_forward_returns(scores, base, fwd)
    assert sum(r["n"] for r in rows) == 19
    assert rows[0]["avg_fwd"] == pytest.approx(0.10)      # not dragged toward 0


def test_too_few_names_returns_empty():
    assert decile_forward_returns(_scores(5), {}, {}) == []
    assert aggregate_calibration([[], []], 20) is None


def test_aggregate_averages_across_dates():
    scores = _scores()
    base = {t: 100.0 for t in scores}
    up = {t: 110.0 for t in scores}
    down = {t: 90.0 for t in scores}
    agg = aggregate_calibration([
        decile_forward_returns(scores, base, up),
        decile_forward_returns(scores, base, down)], 20)
    assert agg["n_dates"] == 2
    assert all(d["avg_fwd"] == pytest.approx(0.0, abs=1e-9) for d in agg["deciles"])


def test_sample_evenly_keeps_ends_and_is_deterministic():
    items = list(range(100))
    s = sample_evenly(items, 12)
    assert len(s) == 12 and s[0] == 0 and s[-1] == 99
    assert s == sample_evenly(items, 12)
    assert sample_evenly([1, 2], 12) == [1, 2]
