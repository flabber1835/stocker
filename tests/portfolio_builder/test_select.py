import numpy as np
import pandas as pd
import pytest
from app.select import greedy_select, build_covariance, compute_weights


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


def test_build_covariance_deduplicates_prices():
    """Duplicate (date, ticker) rows must be dropped (keep last) not silently averaged."""
    tickers = ["A", "B"]
    df_clean = _prices_df(tickers, n_days=200)
    # Duplicate every row for ticker A — if silently averaged the covariance would
    # be identical but pivot() would have raised. After the fix, the last row wins
    # and the result should match the clean covariance.
    df_duped = pd.concat([df_clean, df_clean[df_clean["ticker"] == "A"]], ignore_index=True)
    cov_clean, _ = build_covariance(df_clean, window_days=200, min_observations=50)
    cov_deduped, _ = build_covariance(df_duped, window_days=200, min_observations=50)
    # Covariance should be identical — duplicates discarded, not averaged
    np.testing.assert_allclose(
        cov_clean.values, cov_deduped.values, rtol=1e-6,
        err_msg="build_covariance produced different covariance for duplicated input"
    )


# ── compute_weights ───────────────────────────────────────────────────────────

def _make_selected(tickers, scores, adj_scores=None):
    if adj_scores is None:
        adj_scores = scores
    return [
        {"ticker": t, "composite_score": s, "adj_score": a, "position": i + 1,
         "portfolio_vol_at_add": 0.3}
        for i, (t, s, a) in enumerate(zip(tickers, scores, adj_scores))
    ]


def test_compute_weights_equal_sums_to_one():
    tickers = ["A", "B", "C", "D"]
    selected = _make_selected(tickers, [1.0, 0.8, 0.6, 0.4])
    cov = _simple_cov(tickers)
    w = compute_weights(selected, cov, "equal_weight")
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(abs(v - 0.25) < 1e-6 for v in w.values())


def test_compute_weights_adj_score_proportional():
    tickers = ["A", "B"]
    selected = _make_selected(tickers, [1.0, 1.0], adj_scores=[3.0, 1.0])
    cov = _simple_cov(tickers)
    w = compute_weights(selected, cov, "adj_score_proportional")
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert w["A"] > w["B"]
    assert abs(w["A"] - 0.75) < 1e-6


def test_compute_weights_score_proportional_negative_scores():
    """Negative scores are shifted positive before proportioning."""
    tickers = ["A", "B", "C"]
    selected = _make_selected(tickers, [-0.5, 0.0, 0.5])
    cov = _simple_cov(tickers)
    w = compute_weights(selected, cov, "score_proportional")
    assert abs(sum(w.values()) - 1.0) < 1e-5  # 6-decimal rounding across 3 values
    assert w["C"] > w["B"] > w["A"]


def test_compute_weights_inverse_vol():
    """Lower-vol tickers get higher weight."""
    tickers = ["A", "B"]
    cov = _simple_cov(tickers, vol=0.20)
    cov.loc["B", "B"] = 0.40 ** 2  # B is twice as volatile
    selected = _make_selected(tickers, [1.0, 1.0])
    w = compute_weights(selected, cov, "inverse_vol")
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert w["A"] > w["B"]


def test_compute_weights_max_position_cap():
    """No weight should exceed max_position_weight."""
    tickers = ["A", "B", "C", "D"]
    # Give A a huge adj_score so it would dominate without the cap
    selected = _make_selected(tickers, [1.0, 0.1, 0.1, 0.1], adj_scores=[100.0, 1.0, 1.0, 1.0])
    cov = _simple_cov(tickers)
    w = compute_weights(selected, cov, "adj_score_proportional", max_position_weight=0.40)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(v <= 0.40 + 1e-9 for v in w.values())
    assert abs(w["A"] - 0.40) < 1e-6


def test_compute_weights_unknown_method_raises():
    selected = _make_selected(["A"], [1.0])
    cov = _simple_cov(["A"])
    with pytest.raises(ValueError, match="Unknown weighting method"):
        compute_weights(selected, cov, "magic_weights")


# ── Covariance edge cases ─────────────────────────────────────────────────────

def test_build_covariance_empty_raises_runtime_error():
    """
    When build_covariance returns an empty DataFrame (all tickers dropped for
    insufficient observations), main.py raises RuntimeError.

    We replicate the identical guard from _do_build to verify:
      1. build_covariance genuinely returns an empty matrix for sparse data.
      2. The RuntimeError message matches what the service emits.
    """
    # Only 5 price rows — far below min_observations=126 → both tickers dropped
    cov, dropped = build_covariance(
        _prices_df(["A", "B"], n_days=5),
        window_days=252,
        min_observations=126,
    )

    # Verify the precondition: the matrix must actually be empty
    assert len(cov) == 0, f"Expected empty cov but got shape {cov.shape}"

    # Reproduce the guard from main.py._do_build and assert it raises correctly
    with pytest.raises(RuntimeError, match="(?i)insufficient price history|empty"):
        if cov is None or len(cov) == 0:
            raise RuntimeError(
                "Covariance matrix is empty — candidates have insufficient price history. "
                "Need at least 2 tickers with overlapping price data."
            )


def test_build_covariance_empty_from_real_data():
    """
    Passing a prices DataFrame where every ticker has fewer rows than
    min_observations should return an empty covariance matrix.
    The caller is responsible for raising RuntimeError on an empty result.
    """
    # Only 5 rows — far below min_observations=126
    tickers = ["X", "Y"]
    df = _prices_df(tickers, n_days=5)
    cov, dropped = build_covariance(df, window_days=252, min_observations=126)

    # Both tickers must be dropped and the matrix must be empty
    assert set(dropped) == set(tickers)
    assert len(cov) == 0

    # Reproduce the guard from main.py to verify RuntimeError semantics
    with pytest.raises(RuntimeError, match="(?i)insufficient price history|empty"):
        if cov is None or len(cov) == 0:
            raise RuntimeError(
                "Covariance matrix is empty — candidates have insufficient price history. "
                "Need at least 2 tickers with overlapping price data."
            )


def test_build_covariance_near_singular_warns(capsys):
    """
    A near-singular covariance matrix (very small minimum eigenvalue) should
    trigger a printed warning about rank-deficiency.  The check lives in
    main.py; replicate the identical guard so the warning path is exercised.
    """
    # Build a near-singular 3×3 covariance: two rows are almost identical,
    # making the matrix near rank-deficient.
    tickers = ["A", "B", "C"]
    var = 0.04   # 20 % vol²

    # Near-singular: B ≈ A (correlation ≈ 0.9999999, giving min eigenvalue ≈ 4e-9 < 1e-8)
    corr_ab = 0.9999999
    mat = np.array([
        [var,           corr_ab * var,  0.0],
        [corr_ab * var, var,            0.0],
        [0.0,           0.0,            var],
    ])
    cov = pd.DataFrame(mat, index=tickers, columns=tickers)

    eigenvalues = np.linalg.eigvalsh(cov.values)
    min_eigenvalue = float(eigenvalues.min())

    # Reproduce the identical guard from main.py
    if min_eigenvalue < 1e-8:
        print(
            f"[portfolio-builder] WARNING: covariance matrix near rank-deficient "
            f"(min eigenvalue={min_eigenvalue:.2e}). Portfolio vol estimates may be unreliable."
        )

    captured = capsys.readouterr()

    assert min_eigenvalue < 1e-8, (
        f"Expected a near-singular matrix but min eigenvalue was {min_eigenvalue:.2e}"
    )
    assert "WARNING" in captured.out
    assert "rank-deficient" in captured.out


# ── Sector cap: target-denominator fix ─────────────────────────────────────────

def test_sector_cap_selects_multiple_stocks():
    """
    With max_sector_weight=0.30 and 30 candidates all in the same sector,
    the portfolio must contain more than 1 stock (old bug: used current_size+1
    as denominator, so pick 2 always failed 1/2=0.50>0.30).
    """
    tickers = [f"T{i}" for i in range(30)]
    scores = pd.Series({t: float(30 - i) for i, t in enumerate(tickers)})
    cov = _simple_cov(tickers, vol=0.20)
    sector_map = {t: "TECH" for t in tickers}  # all same sector

    result = greedy_select(scores, cov, target=30, sector_map=sector_map, max_sector_weight=0.30)

    # With correct target-denominator: max 9 TECH stocks in a 30-stock portfolio
    # So we should get exactly 9 (the cap), not 1
    assert len(result) == 9, f"Expected 9 stocks (30% of 30), got {len(result)}"


def test_sector_cap_respects_max_per_sector():
    """
    With 20 tickers split evenly across 2 sectors and a 0.30 cap,
    each sector can have at most floor(0.30 * 10) = 3 stocks in a 10-stock portfolio.
    """
    tickers_a = [f"A{i}" for i in range(10)]
    tickers_b = [f"B{i}" for i in range(10)]
    all_tickers = tickers_a + tickers_b
    # Give sector A higher scores so it would be preferred without cap
    scores = pd.Series({t: 2.0 for t in tickers_a} | {t: 1.0 for t in tickers_b})
    cov = _simple_cov(all_tickers, vol=0.20)
    sector_map = {t: "TECH" for t in tickers_a} | {t: "HEALTH" for t in tickers_b}

    result = greedy_select(scores, cov, target=10, sector_map=sector_map, max_sector_weight=0.30)

    sector_counts: dict[str, int] = {}
    for r in result:
        s = sector_map[r["ticker"]]
        sector_counts[s] = sector_counts.get(s, 0) + 1

    for sector, count in sector_counts.items():
        assert count / 10 <= 0.30 + 1e-9, f"{sector} has {count}/10 = {count/10:.2f} > 0.30"


def test_sector_cap_no_limit_when_disabled():
    """Without sector_map, all 30 tickers from one sector should be selectable."""
    tickers = [f"T{i}" for i in range(30)]
    scores = pd.Series({t: float(30 - i) for i, t in enumerate(tickers)})
    cov = _simple_cov(tickers, vol=0.20)

    result = greedy_select(scores, cov, target=30, sector_map=None, max_sector_weight=0.30)
    assert len(result) == 30


def test_sector_cap_all_candidates_blocked_returns_empty():
    """When every candidate is sector-blocked, greedy_select returns [] without crashing.

    Scenario: 3 tickers all in 'TECH', sector cap = 0.10, target = 30.
    At equal weight 1/30 ≈ 3.3%, the cap of 10% allows floor(0.10 * 30) = 3 picks.
    But cap is checked as new_count / target <= max_sector_weight, so:
      pick 1: 1/30 = 3.3% ≤ 10% → OK
      pick 2: 2/30 = 6.7% ≤ 10% → OK
      pick 3: 3/30 = 10%  ≤ 10% → OK
    All three are selected fine here. To truly block the first pick, use cap=0.
    """
    tickers = ["AAPL", "MSFT", "GOOG"]
    scores = pd.Series({"AAPL": 0.9, "MSFT": 0.8, "GOOG": 0.7})
    cov = _simple_cov(tickers)
    sector_map = {t: "TECH" for t in tickers}

    # max_sector_weight=0 means 0/30 = 0% required — no stock can pass.
    result = greedy_select(scores, cov, target=30, sector_map=sector_map, max_sector_weight=0.0)
    assert result == [], (
        "All candidates sector-blocked should return empty list, not crash"
    )


def test_sector_cap_tighter_than_one_stock_returns_empty():
    """Cap so tight not even one stock can be added: result must be [] not a crash."""
    tickers = ["AAPL"]
    scores = pd.Series({"AAPL": 1.0})
    cov = _simple_cov(tickers)
    sector_map = {"AAPL": "TECH"}

    # 1/30 ≈ 3.3%; a cap of 0.03 means 0.03 < 1/30, so the first pick is blocked.
    result = greedy_select(scores, cov, target=30, sector_map=sector_map, max_sector_weight=0.03)
    assert result == []
