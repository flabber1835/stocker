import numpy as np
import pandas as pd
import pytest
from app.select import greedy_select, build_covariance


def _simple_cov(tickers: list[str], vol: float = 0.20, corr: float = 0.0) -> pd.DataFrame:
    """Diagonal covariance (annualised) with optional uniform off-diagonal correlation."""
    n = len(tickers)
    var = vol ** 2
    mat = np.full((n, n), corr * var)
    np.fill_diagonal(mat, var)
    return pd.DataFrame(mat, index=tickers, columns=tickers)


def _prices_df(tickers: list[str], n_days: int = 300, seed: int = 0) -> pd.DataFrame:
    """Long-format price DataFrame suitable for build_covariance."""
    rng = np.random.default_rng(seed)
    rows = []
    base_date = pd.Timestamp("2022-01-03")
    for t in tickers:
        price = 100.0
        for i in range(n_days):
            price *= 1 + rng.normal(0.0003, 0.015)
            rows.append({"ticker": t, "date": base_date + pd.Timedelta(days=i), "adjusted_close": price})
    return pd.DataFrame(rows)


# ── greedy_select ──────────────────────────────────────────────────────────────────────────────

def test_greedy_select_returns_target_count():
    tickers = [f"T{i}" for i in range(50)]
    scores = pd.Series({t: float(i) for i, t in enumerate(tickers)})
    cov = _simple_cov(tickers, vol=0.20)
    result = greedy_select(scores, cov, target=10)
    assert len(result) == 10


def test_greedy_select_fewer_candidates_than_target():
    tickers = ["A", "B", "C"]
    scores = pd.Series({"A": 1.0, "B": 0.8, "C": 0.5})
    cov = _simple_cov(tickers, vol=0.20)
    result = greedy_select(scores, cov, target=10)
    assert len(result) == 3


def test_greedy_select_positions_are_sequential():
    tickers = [f"T{i}" for i in range(20)]
    scores = pd.Series({t: float(i) for i, t in enumerate(tickers)})
    cov = _simple_cov(tickers, vol=0.20)
    result = greedy_select(scores, cov, target=10)
    positions = [r["position"] for r in result]
    assert positions == list(range(1, 11))


def test_greedy_select_no_duplicate_tickers():
    tickers = [f"T{i}" for i in range(30)]
    scores = pd.Series({t: float(i) for i, t in enumerate(tickers)})
    cov = _simple_cov(tickers, vol=0.20)
    result = greedy_select(scores, cov, target=20)
    selected = [r["ticker"] for r in result]
    assert len(selected) == len(set(selected))


def test_greedy_select_first_pick_is_highest_score():
    """First pick should be the ticker with the highest score (no correlation context yet)."""
    tickers = ["LOW", "MID", "HIGH"]
    scores = pd.Series({"LOW": 0.1, "MID": 0.5, "HIGH": 2.0})
    cov = _simple_cov(tickers, vol=0.20)
    result = greedy_select(scores, cov, target=3)
    assert result[0]["ticker"] == "HIGH"


def test_greedy_select_negative_scores_handled():
    """Negative z-scores must not flip ranking — shift makes all scores positive."""
    tickers = ["A", "B", "C", "D"]
    scores = pd.Series({"A": -2.0, "B": -1.0, "C": 0.5, "D": 1.5})
    cov = _simple_cov(tickers, vol=0.20)
    result = greedy_select(scores, cov, target=4)
    # Should complete without error and return all 4
    assert len(result) == 4
    # Highest composite score picks first
    assert result[0]["ticker"] == "D"


def test_greedy_select_prefers_uncorrelated_candidates():
    """
    Given two candidates with equal scores, the algorithm should prefer the one
    that keeps portfolio vol lower (i.e., less correlated with the current portfolio).
    """
    # Portfolio already holds T0. T1 is highly correlated with T0; T2 is not.
    # Scores: T1 = T2 = 1.0 (equal), so correlation is the tiebreaker.
    tickers = ["T0", "T1", "T2"]
    scores = pd.Series({"T0": 2.0, "T1": 1.0, "T2": 1.0})

    # Build cov: T0–T1 highly correlated (0.8), T0–T2 uncorrelated (0.0)
    vol = 0.20
    var = vol ** 2
    mat = np.array([
        [var,       0.8 * var, 0.0 * var],
        [0.8 * var, var,       0.0],
        [0.0 * var, 0.0,       var],
    ])
    cov = pd.DataFrame(mat, index=tickers, columns=tickers)

    result = greedy_select(scores, cov, target=3)
    # T0 is first (highest score). Next should be T2 (lower corr with T0 → lower port vol → higher adj score)
    assert result[0]["ticker"] == "T0"
    assert result[1]["ticker"] == "T2"
    assert result[2]["ticker"] == "T1"


def test_greedy_select_result_fields():
    tickers = ["A", "B", "C"]
    scores = pd.Series({"A": 1.0, "B": 0.8, "C": 0.6})
    cov = _simple_cov(tickers, vol=0.20)
    result = greedy_select(scores, cov, target=3)
    for item in result:
        assert "ticker" in item
        assert "position" in item
        assert "composite_score" in item
        assert "adj_score" in item
        assert "portfolio_vol_at_add" in item
        assert item["portfolio_vol_at_add"] > 0


def test_greedy_select_single_candidate():
    scores = pd.Series({"ONLY": 1.5})
    cov = _simple_cov(["ONLY"], vol=0.25)
    result = greedy_select(scores, cov, target=5)
    assert len(result) == 1
    assert result[0]["ticker"] == "ONLY"
    assert result[0]["position"] == 1


# ── build_covariance ─────────────────────────────────────────────────────────────────────────────

def test_build_covariance_shape():
    tickers = ["A", "B", "C"]
    df = _prices_df(tickers, n_days=300)
    cov, dropped = build_covariance(df, window_days=252)
    assert cov.shape == (3, 3)
    assert list(cov.index) == tickers
    assert list(cov.columns) == tickers
    assert dropped == []


def test_build_covariance_positive_diagonal():
    tickers = ["A", "B", "C", "D"]
    df = _prices_df(tickers, n_days=300)
    cov, _ = build_covariance(df, window_days=252)
    for t in tickers:
        assert cov.loc[t, t] > 0, f"variance for {t} is not positive"


def test_build_covariance_symmetric():
    tickers = ["A", "B", "C"]
    df = _prices_df(tickers, n_days=300)
    cov, _ = build_covariance(df, window_days=252)
    np.testing.assert_allclose(cov.values, cov.values.T, atol=1e-10)


def test_build_covariance_window_truncation():
    """With window_days=50, only the last 50 rows of returns should be used."""
    tickers = ["A", "B"]
    df = _prices_df(tickers, n_days=300)
    cov_full, _ = build_covariance(df, window_days=252, min_observations=20)
    cov_short, _ = build_covariance(df, window_days=50, min_observations=20)
    # Variances should differ since they use different history windows
    assert cov_full.loc["A", "A"] != cov_short.loc["A", "A"]


def test_build_covariance_no_nan():
    tickers = ["A", "B", "C"]
    df = _prices_df(tickers, n_days=300)
    cov, _ = build_covariance(df, window_days=252)
    assert not cov.isnull().any().any()


def test_build_covariance_drops_sparse_tickers():
    """Tickers with fewer observations than min_observations are excluded."""
    tickers = ["A", "B", "C"]
    df_full = _prices_df(tickers, n_days=300)
    # Give "C" only 50 observations by keeping just the last 50 rows for it
    df_c_sparse = df_full[df_full["ticker"] == "C"].tail(50)
    df = pd.concat([df_full[df_full["ticker"] != "C"], df_c_sparse])
    cov, dropped = build_covariance(df, window_days=252, min_observations=126)
    assert "C" in dropped
    assert "C" not in cov.index


def test_build_covariance_shrinkage_reduces_off_diagonal():
    """Shrinkage should pull off-diagonal elements toward zero."""
    tickers = ["A", "B"]
    df = _prices_df(tickers, n_days=300)
    cov_raw, _ = build_covariance(df, window_days=252, shrinkage=0.0)
    cov_shrunk, _ = build_covariance(df, window_days=252, shrinkage=0.5)
    # Off-diagonal should be smaller in magnitude after shrinkage
    assert abs(cov_shrunk.loc["A", "B"]) < abs(cov_raw.loc["A", "B"])
    # Diagonal should be unchanged (shrinkage toward diagonal keeps variances)
    np.testing.assert_allclose(cov_raw.loc["A", "A"], cov_shrunk.loc["A", "A"], rtol=1e-6)
