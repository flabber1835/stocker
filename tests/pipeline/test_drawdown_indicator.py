"""Tests for the display-only 21-day drawdown indicator on the ranker.

Three guarantees:
  - the pure helper app.main._recent_drawdown matches the vetter's drawdown math
  - _drawdown_map_from_rows builds the right {ticker: drawdown} map from DB rows
    (this is the code path the ranked_tickers forward-reference regression broke;
    a direct test now exercises it)
  - drawdown is NOT a scoring factor: it is absent from FACTORS, so rank_universe
    never scores on it and rank order is identical with or without the column.
"""
from types import SimpleNamespace

import pandas as pd

from app.main import _recent_drawdown, _drawdown_map_from_rows
from app.rank import rank_universe, FACTORS


def _row(ticker, close):
    return SimpleNamespace(ticker=ticker, adjusted_close=close)


# ── _drawdown_map_from_rows (the extracted DB-block logic) ──────────────────────

def test_drawdown_map_groups_by_ticker_in_order():
    # AAA: peak 120 then 90 → -25%; BBB: flat → 0.0
    rows = [
        _row("AAA", 100), _row("AAA", 120), _row("AAA", 90),
        _row("BBB", 50), _row("BBB", 50),
    ]
    # baseline_window=0 → pure peak-to-now (this test checks grouping, not the
    # round-trip baseline logic, which is covered in tests/shared/test_drawdown_baseline).
    m = _drawdown_map_from_rows(rows, window=21, baseline_window=0)
    assert m["AAA"] == 90 / 120 - 1.0
    assert m["BBB"] == 0.0


def test_drawdown_map_skips_null_closes():
    rows = [_row("AAA", None), _row("AAA", 100), _row("AAA", 80)]
    m = _drawdown_map_from_rows(rows, window=21, baseline_window=0)
    assert m["AAA"] == 80 / 100 - 1.0


def test_drawdown_map_omits_ticker_with_no_usable_data():
    rows = [_row("ZZZ", None), _row("ZZZ", 0)]
    m = _drawdown_map_from_rows(rows, window=21)
    assert "ZZZ" not in m


def test_drawdown_map_empty_rows():
    assert _drawdown_map_from_rows([], window=21) == {}


def test_drawdown_map_window_truncation():
    # window=2 ignores the leading 100 → peak 120, last 90
    rows = [_row("AAA", 100), _row("AAA", 120), _row("AAA", 90)]
    assert _drawdown_map_from_rows(rows, window=2, baseline_window=0)["AAA"] == 90 / 120 - 1.0


# ── pure helper ────────────────────────────────────────────────────────────────

def test_recent_drawdown_at_peak_is_zero():
    assert _recent_drawdown([100, 105, 110]) == 0.0


def test_recent_drawdown_below_peak():
    assert _recent_drawdown([100, 120, 90], baseline_window=0) == 90 / 120 - 1.0


def test_recent_drawdown_window_limits_lookback():
    assert _recent_drawdown([100, 120, 90], window=2, baseline_window=0) == 90 / 120 - 1.0


def test_recent_drawdown_empty_and_nonpositive_none():
    assert _recent_drawdown([]) is None
    assert _recent_drawdown([0, 0]) is None


# ── drawdown is display-only: not a scoring factor ──────────────────────────────

def test_drawdown_not_in_factors():
    assert "drawdown_21d" not in FACTORS


def _strategy(monkeypatch_regime="bull_calm"):
    from types import SimpleNamespace
    weights = {f: 1.0 / len(FACTORS) for f in FACTORS}
    wv = SimpleNamespace(model_dump=lambda: weights)
    return SimpleNamespace(
        factor_weights={monkeypatch_regime: wv},
        # rank_universe resolves weights via effective_factor_weights(regime); mirror
        # the real resolver (regime rotation on → per-regime vector) for the mock.
        effective_factor_weights=lambda regime: wv,
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
