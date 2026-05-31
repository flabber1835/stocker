"""Tests for the display-only 21-day drawdown indicator on the ranker.

Two guarantees:
  - the pure helper app.main._recent_drawdown matches the vetter's drawdown math
  - drawdown is NOT a scoring factor: it is absent from FACTORS, so rank_universe
    never scores on it and rank order is identical with or without the column.
"""
import pandas as pd

from app.main import _recent_drawdown
from app.rank import rank_universe, FACTORS


# ── pure helper ────────────────────────────────────────────────────────────────

def test_recent_drawdown_at_peak_is_zero():
    assert _recent_drawdown([100, 105, 110]) == 0.0


def test_recent_drawdown_below_peak():
    assert _recent_drawdown([100, 120, 90]) == 90 / 120 - 1.0


def test_recent_drawdown_window_limits_lookback():
    assert _recent_drawdown([100, 120, 90], window=2) == 90 / 120 - 1.0


def test_recent_drawdown_empty_and_nonpositive_none():
    assert _recent_drawdown([]) is None
    assert _recent_drawdown([0, 0]) is None


# ── drawdown is display-only: not a scoring factor ──────────────────────────────

def test_drawdown_not_in_factors():
    assert "drawdown_21d" not in FACTORS


def _strategy(monkeypatch_regime="bull_calm"):
    from types import SimpleNamespace
    weights = {f: 1.0 / len(FACTORS) for f in FACTORS}
    return SimpleNamespace(
        factor_weights={monkeypatch_regime: SimpleNamespace(model_dump=lambda: weights)},
        min_non_null_factors=1,
        required_factors=[],
        min_score_percentile=0.0,
    )


def test_rank_order_unaffected_by_drawdown_column():
    """Adding a drawdown_21d column must not change composite scores or rank order."""
    base = pd.DataFrame({
        "ticker": ["AAA", "BBB", "CCC"],
        "momentum":       [0.9, 0.5, 0.1],
        "quality":        [0.8, 0.5, 0.2],
        "value":          [0.7, 0.5, 0.3],
        "growth":         [0.6, 0.5, 0.4],
        "low_volatility": [0.5, 0.5, 0.5],
        "liquidity":      [0.9, 0.5, 0.1],
    })
    strat = _strategy()
    ranked_without = rank_universe(base, "bull_calm", strat)

    with_dd = base.copy()
    # A deep drawdown on the top-ranked name must NOT demote it.
    with_dd["drawdown_21d"] = [-0.40, -0.02, 0.0]
    ranked_with = rank_universe(with_dd, "bull_calm", strat)

    pd.testing.assert_series_equal(
        ranked_without["ticker"].reset_index(drop=True),
        ranked_with["ticker"].reset_index(drop=True),
    )
    pd.testing.assert_series_equal(
        ranked_without["composite_score"].reset_index(drop=True),
        ranked_with["composite_score"].reset_index(drop=True),
    )
    # AAA still ranks #1 despite its -40% drawdown.
    assert ranked_with.iloc[0]["ticker"] == "AAA"
