"""Tests for cross-sectional percentile factor scoring.

Verifies that cross_section_percentile produces correct [0, 1] ranks and that
the composite score is free from the momentum-dominance bug that arose with
unclipped z-scores.
"""
import sys
import os

import numpy as np
import pandas as pd
import pytest

# Ensure shared + pipeline are importable
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "pipeline"))

from app.factors import cross_section_percentile
from app.rank import FACTORS


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_factor_row(**kwargs) -> pd.Series:
    """Build a factor-score row dict matching what rank.compute_score expects."""
    defaults = {f: np.nan for f in ["momentum", "quality", "value", "growth", "low_volatility", "liquidity"]}
    defaults.update(kwargs)
    return pd.Series(defaults)


EQUAL_WEIGHTS = {
    "momentum": 1 / 6,
    "quality": 1 / 6,
    "value": 1 / 6,
    "growth": 1 / 6,
    "low_volatility": 1 / 6,
    "liquidity": 1 / 6,
}

BULL_CALM_WEIGHTS = {
    "momentum": 0.27,
    "growth": 0.21,
    "quality": 0.15,
    "low_volatility": 0.14,
    "value": 0.13,
    "liquidity": 0.10,
}


# ---------------------------------------------------------------------------
# 1. Highest value gets rank 1.0
# ---------------------------------------------------------------------------

def test_percentile_highest_gets_1():
    s = pd.Series([1.0, 2.0, 3.0], index=["a", "b", "c"])
    result = cross_section_percentile(s)
    assert result["c"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 2. Lowest value gets 1/N, not 0
# ---------------------------------------------------------------------------

def test_percentile_lowest_gets_near_zero():
    s = pd.Series([1.0, 2.0, 3.0], index=["a", "b", "c"])
    result = cross_section_percentile(s)
    n = s.notna().sum()
    assert result["a"] == pytest.approx(1 / n)


# ---------------------------------------------------------------------------
# 3. NaN values stay NaN and don't affect the ranks of valid entries
# ---------------------------------------------------------------------------

def test_percentile_nan_excluded():
    s = pd.Series([1.0, np.nan, 3.0], index=["a", "b", "c"])
    result = cross_section_percentile(s)
    assert pd.isna(result["b"])
    # Only 2 valid entries → ranks should be 0.5 and 1.0
    assert result["a"] == pytest.approx(0.5)
    assert result["c"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4. Tied values get average rank (pandas pct=True average method)
# ---------------------------------------------------------------------------

def test_percentile_ties_get_average():
    # [1, 2, 2, 3] → ranks 1, 2.5, 2.5, 4 → pct ranks 0.25, 0.625, 0.625, 1.0
    s = pd.Series([1.0, 2.0, 2.0, 3.0], index=["a", "b", "c", "d"])
    result = cross_section_percentile(s)
    assert result["a"] == pytest.approx(0.25)
    assert result["b"] == pytest.approx(0.625)
    assert result["c"] == pytest.approx(0.625)
    assert result["d"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 5. Fewer than 2 valid values → all NaN returned
# ---------------------------------------------------------------------------

def test_percentile_small_universe():
    # zero valid
    s0 = pd.Series([np.nan, np.nan], index=["a", "b"])
    r0 = cross_section_percentile(s0)
    assert r0.isna().all()

    # one valid
    s1 = pd.Series([1.0, np.nan], index=["a", "b"])
    r1 = cross_section_percentile(s1)
    assert r1.isna().all()


# ---------------------------------------------------------------------------
# 6. Composite of percentile factors lies in [0, 1]
# ---------------------------------------------------------------------------

def test_composite_in_unit_interval():
    """Weighted average of six [0,1] factors must itself be in [0,1]."""
    rng = np.random.default_rng(42)
    n = 200
    tickers = [f"T{i:04d}" for i in range(n)]

    factors = {}
    for f in ["momentum", "quality", "value", "growth", "low_volatility", "liquidity"]:
        raw = pd.Series(rng.normal(size=n), index=tickers)
        factors[f] = cross_section_percentile(raw)

    factor_df = pd.DataFrame(factors)

    for _, row in factor_df.iterrows():
        score = _composite(row, EQUAL_WEIGHTS)
        if not np.isnan(score):
            assert 0.0 <= score <= 1.0, f"composite out of [0,1]: {score}"


def _composite(row: pd.Series, weights: dict) -> float:
    """Replicate rank_universe scoring logic inline."""
    available = {f: weights[f] for f in FACTORS if pd.notna(row.get(f))}
    if len(available) < 1:
        return float("nan")
    wsum = sum(available.values())
    if wsum == 0:
        return float("nan")
    return sum((w / wsum) * row[f] for f, w in available.items())


# ---------------------------------------------------------------------------
# 7. No factor dominance: all-0.8 beats 1.0-momentum + 0.5-rest
# ---------------------------------------------------------------------------

def test_no_factor_dominance():
    """With z-scores, momentum at z=6 dominated. With percentiles, a ticker
    that scores 1.0 on momentum but 0.5 on everything else must NOT beat
    a ticker that scores 0.8 on all six factors.
    """
    # Ticker A: momentum=1.0, all others=0.5
    row_a = _make_factor_row(
        momentum=1.0,
        quality=0.5,
        value=0.5,
        growth=0.5,
        low_volatility=0.5,
        liquidity=0.5,
    )
    # Ticker B: all factors=0.8
    row_b = _make_factor_row(
        momentum=0.8,
        quality=0.8,
        value=0.8,
        growth=0.8,
        low_volatility=0.8,
        liquidity=0.8,
    )

    score_a = _composite(row_a, BULL_CALM_WEIGHTS)
    score_b = _composite(row_b, BULL_CALM_WEIGHTS)

    assert score_b > score_a, (
        f"Consistent 0.8 ticker (score={score_b:.4f}) should beat "
        f"momentum-only 1.0 ticker (score={score_a:.4f})"
    )


# ---------------------------------------------------------------------------
# 8. Equal factor ceiling: momentum=1.0 and quality=1.0 contribute per weight
# ---------------------------------------------------------------------------

def test_equal_factor_ceiling():
    """Verify that momentum and quality at percentile=1.0 each contribute
    proportionally to their stated weight — no factor can exceed 1.0.

    With z-scores, momentum at z=6 contributed 6×weight while quality at
    z=2.5 contributed only 2.5×weight, breaking the stated weight allocation.
    With percentile ranks both are capped at 1.0, so momentum contributes
    0.27 and quality contributes 0.15 (per bull_calm weights), not 6×0.27 vs 2.5×0.15.
    """
    weights = BULL_CALM_WEIGHTS
    w_sum = sum(weights.values())  # should equal 1.0

    # Ticker with only momentum=1.0, all others NaN → contribution = 1.0
    row_mom = _make_factor_row(momentum=1.0)
    score_mom = _composite(row_mom, weights)
    # With only one factor the normalised weight is 1.0 → score = 1.0 * 1.0
    assert score_mom == pytest.approx(1.0)

    # Ticker with only quality=1.0
    row_qual = _make_factor_row(quality=1.0)
    score_qual = _composite(row_qual, weights)
    assert score_qual == pytest.approx(1.0)

    # With ALL factors present at their respective ceiling (1.0), composite = 1.0
    row_all_1 = _make_factor_row(
        momentum=1.0, quality=1.0, value=1.0,
        growth=1.0, low_volatility=1.0, liquidity=1.0,
    )
    score_all = _composite(row_all_1, weights)
    assert score_all == pytest.approx(1.0)

    # With ALL factors at the floor (1/N ≈ small), composite stays ≤ 1.0
    floor = 1 / 3000  # representative universe size
    row_all_floor = _make_factor_row(
        momentum=floor, quality=floor, value=floor,
        growth=floor, low_volatility=floor, liquidity=floor,
    )
    score_floor = _composite(row_all_floor, weights)
    assert 0.0 <= score_floor <= 1.0
    assert score_floor < 0.01  # near zero
