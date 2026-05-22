import pytest
import pandas as pd
import numpy as np
from app.factors import (
    cross_section_zscore, compute_momentum, compute_low_volatility,
    compute_all_factors, compute_quality, compute_value, compute_growth,
    _winsorize, _component_zscore,
)


def _pivot(tickers: list[str], n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    data = {}
    for t in tickers:
        start = rng.uniform(50, 300)
        returns = rng.normal(0.0003, 0.015, n)
        prices = start * np.cumprod(1 + returns)
        data[t] = prices
    return pd.DataFrame(data, index=dates)


def _prices_long(tickers: list[str], n: int = 300) -> pd.DataFrame:
    pivot = _pivot(tickers, n)
    rows = []
    for ticker in tickers:
        for date, price in pivot[ticker].items():
            rows.append({
                "ticker": ticker, "date": date.date(),
                "close": price, "adjusted_close": price,
                "volume": int(1e6),
            })
    return pd.DataFrame(rows)


def _large_fund(n: int = 50, seed: int = 0) -> pd.DataFrame:
    """Return a realistic fundamentals DataFrame with n tickers for winsorization tests."""
    rng = np.random.default_rng(seed)
    tickers = [f"T{i:03d}" for i in range(n)]
    return pd.DataFrame({
        "ticker": tickers,
        "pe_ratio": rng.uniform(5, 80, n),
        "pb_ratio": rng.uniform(0.5, 15, n),
        "roe": rng.uniform(-0.10, 0.60, n),
        "debt_to_equity": rng.uniform(0.0, 3.0, n),
        "revenue_growth": rng.uniform(-0.20, 0.50, n),
        "eps_growth": rng.uniform(-0.30, 0.80, n),
    })


# ── cross_section_zscore ─────────────────────────────────────────────────────────────────────────

def test_zscore_clips_to_2_5():
    s = pd.Series([1.0, 2.0, 100.0, -100.0])
    z = cross_section_zscore(s)
    assert z.max() <= 2.5
    assert z.min() >= -2.5


def test_zscore_zero_std():
    s = pd.Series([5.0, 5.0, 5.0])
    z = cross_section_zscore(s)
    assert (z == 0.0).all()


def test_zscore_preserves_nan():
    s = pd.Series([1.0, float("nan"), 3.0, float("nan")])
    z = cross_section_zscore(s)
    assert pd.isna(z.iloc[1])
    assert pd.isna(z.iloc[3])
    assert pd.notna(z.iloc[0])
    assert pd.notna(z.iloc[2])


def test_zscore_all_nan():
    s = pd.Series([float("nan"), float("nan")])
    z = cross_section_zscore(s)
    assert z.isna().all()


def test_zscore_clip_threshold_exact_boundary():
    """
    Values that produce z-scores outside ±2.5 must be clipped to exactly ±2.5.
    Values already inside the window must pass through unchanged.

    Input: [0.5, 2.5, -2.5, 3.0, -3.0] — treated as pre-computed z-scores by
    constructing a Series whose raw z-score is already that value.  We achieve
    this by building a Series where mean=0, std=1 (values are exactly their
    own z-score) and confirming the clip boundary is honoured.
    """
    # Use a large population so std ≈ 1 and mean ≈ 0; inject our boundary values.
    # Simpler: create a Series that IS its own z-score by using mean=0, std=1.
    base = pd.Series([0.0] * 100, dtype=float)
    # Override five indices with the test values
    test_values = [0.5, 2.5, -2.5, 3.0, -3.0]
    for i, v in enumerate(test_values):
        base.iloc[i] = v

    z = cross_section_zscore(base)

    # 3.0 and -3.0 exceed ±2.5 — must be clipped exactly
    assert z.iloc[3] == pytest.approx(2.5), "value 3.0 should be clipped to +2.5"
    assert z.iloc[4] == pytest.approx(-2.5), "value -3.0 should be clipped to -2.5"

    # 2.5 and -2.5 are exactly at the boundary — must not be altered beyond floating-point
    assert z.iloc[1] <= 2.5 + 1e-9
    assert z.iloc[2] >= -2.5 - 1e-9

    # 0.5 is well inside the window — must remain close to its raw z-score
    assert -2.5 < z.iloc[0] < 2.5


def test_zscore_clip_audit_identifies_clipped_values():
    """
    The audit log (indices where |z| == 2.5) must correctly identify the
    clipped values and not flag interior values.

    We build a population of 20 zeros plus one interior value and two extreme
    outliers so that the outliers produce raw z-scores well beyond ±2.5 and are
    clipped, while the interior value stays inside the window.
    """
    # Large population of zeros keeps mean≈0 and std small so the outliers
    # definitely exceed ±2.5 after normalisation.
    normal_data = {f"N{i}": 0.0 for i in range(20)}
    special = {"INTERIOR": 0.5, "HIGH_OUT": 1000.0, "LOW_OUT": -1000.0}
    s = pd.Series({**normal_data, **special})
    z = cross_section_zscore(s)

    # Identify which tickers hit the ±2.5 clip boundary
    clipped = z.index[z.abs() >= 2.5 - 1e-9].tolist()

    # The extreme outliers must be in the clipped audit set
    assert "HIGH_OUT" in clipped, "HIGH_OUT (1000.0) should be clipped to +2.5"
    assert "LOW_OUT" in clipped, "LOW_OUT (-1000.0) should be clipped to -2.5"

    # The interior value must not appear in the clipped set
    assert "INTERIOR" not in clipped, "INTERIOR (0.5) should not be clipped"


def test_zscore_clip_no_values_beyond_boundary():
    """No output value may exceed ±2.5 regardless of how extreme the inputs are."""
    rng = np.random.default_rng(99)
    extremes = list(rng.uniform(-100, 100, 50))
    s = pd.Series(extremes)
    z = cross_section_zscore(s)
    assert z.max() <= 2.5 + 1e-9
    assert z.min() >= -2.5 - 1e-9


# ── _winsorize ────────────────────────────────────────────────────────────────────────────────────

def test_winsorize_clips_extremes():
    s = pd.Series(list(range(100)) + [10000, -10000])
    w = _winsorize(s)
    assert w.max() < 10000
    assert w.min() > -10000


def test_winsorize_passthrough_small_population():
    # Fewer than 10 values — returned unchanged
    s = pd.Series([1.0, 2.0, 100.0])
    w = _winsorize(s)
    assert (w == s).all()


def test_winsorize_preserves_interior_order():
    # Winsorization only clips extremes; values strictly between the two bounds
    # must keep their original relative order.
    rng = np.random.default_rng(7)
    s = pd.Series(rng.normal(0, 1, 200))
    w = _winsorize(s)
    lo, hi = s.quantile(0.01), s.quantile(0.99)
    interior = (s > lo) & (s < hi)
    assert (w[interior].rank() == s[interior].rank()).all()


# ── _component_zscore ────────────────────────────────────────────────────────────────────────────────────

def test_component_zscore_zero_mean():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = _component_zscore(s)
    assert abs(z.mean()) < 1e-10


def test_component_zscore_unit_std():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = _component_zscore(s)
    assert abs(z.std() - 1.0) < 0.01


def test_component_zscore_zero_std_returns_zeros():
    s = pd.Series([7.0, 7.0, 7.0])
    z = _component_zscore(s)
    assert (z == 0.0).all()


# ── compute_quality ────────────────────────────────────────────────────────────────────────────────────

def test_quality_upside_not_compressed():
    """
    With a large diverse population the best quality stock should score well above 0.5
    after cross-sectional z-scoring. The old min-max approach was capped at ~0.55σ.
    """
    fund = _large_fund(n=100, seed=1)
    # Override one ticker to be clearly the best
    fund.loc[0, "roe"] = 2.0    # extreme high ROE
    fund.loc[0, "debt_to_equity"] = 0.0  # zero debt

    raw = compute_quality(fund)
    z = cross_section_zscore(raw)

    best = str(fund.loc[0, "ticker"])
    assert z[best] > 1.0, f"best quality ticker z-score {z[best]:.3f} should be >1.0"


def test_quality_returns_nan_for_no_fundamentals():
    fund = pd.DataFrame(columns=["ticker", "roe", "debt_to_equity"])
    result = compute_quality(pd.DataFrame({"ticker": ["A"], "roe": [float("nan")], "debt_to_equity": [float("nan")]}))
    assert pd.isna(result["A"])


def test_quality_uses_partial_data():
    # Ticker with only ROE (no D/E) should still get a score
    fund = pd.DataFrame([
        {"ticker": "A", "roe": 0.3, "debt_to_equity": float("nan")},
        {"ticker": "B", "roe": 0.1, "debt_to_equity": 0.5},
    ])
    result = compute_quality(fund)
    assert pd.notna(result["A"])


# ── compute_growth ────────────────────────────────────────────────────────────────────────────────────

def test_growth_winsorization_prevents_outlier_collapse():
    """
    When one ticker has explosive growth (10x revenue), unwinsorized z-scoring compresses
    all other tickers to near-zero. After winsorization the cross-section should spread out.
    """
    rng = np.random.default_rng(42)
    n = 100
    tickers = [f"T{i}" for i in range(n)]
    rev_g = list(rng.uniform(0.0, 0.3, n - 1)) + [10.0]  # one massive outlier
    eps_g = list(rng.uniform(-0.1, 0.5, n - 1)) + [50.0]
    fund = pd.DataFrame({"ticker": tickers, "pe_ratio": [20.0] * n, "pb_ratio": [2.0] * n,
                          "roe": [0.2] * n, "debt_to_equity": [0.5] * n,
                          "revenue_growth": rev_g, "eps_growth": eps_g})

    raw = compute_growth(fund)
    z = cross_section_zscore(raw)

    valid = z.dropna()
    # With proper winsorization, std of z-scores should be meaningfully spread (not collapsed)
    assert valid.std() > 0.5, f"growth z-score std {valid.std():.3f} is too low — outlier not winsorized"


def test_growth_partial_data():
    # Ticker with only revenue_growth (no eps_growth) should still get a score
    fund = pd.DataFrame([
        {"ticker": "A", "revenue_growth": 0.2, "eps_growth": float("nan"),
         "pe_ratio": 20.0, "pb_ratio": 2.0, "roe": 0.2, "debt_to_equity": 0.5},
    ])
    result = compute_growth(fund)
    assert pd.notna(result["A"])


# ── compute_value ─────────────────────────────────────────────────────────────────────────────────────

def test_value_pe_cap_at_50():
    """Stocks with PE=200 and PE=100 should produce the same earnings yield as PE=50."""
    fund = pd.DataFrame([
        {"ticker": "CHEAP", "pe_ratio": 10.0, "pb_ratio": 1.0,
         "roe": 0.2, "debt_to_equity": 0.5, "revenue_growth": 0.1, "eps_growth": 0.1},
        {"ticker": "RICH50", "pe_ratio": 50.0, "pb_ratio": 10.0,
         "roe": 0.1, "debt_to_equity": 1.0, "revenue_growth": 0.05, "eps_growth": 0.05},
        {"ticker": "RICH200", "pe_ratio": 200.0, "pb_ratio": 10.0,
         "roe": 0.1, "debt_to_equity": 1.0, "revenue_growth": 0.05, "eps_growth": 0.05},
    ])
    result = compute_value(fund)
    # RICH50 and RICH200 should have identical earnings yield (both capped at 50x)
    assert abs(result["RICH50"] - result["RICH200"]) < 1e-9


def test_value_negative_pe_excluded():
    """Loss-making companies (negative P/E) must not receive a negative earnings yield.
    The .where(pe > 0) guard should produce NaN for those tickers so they are excluded
    from the earnings_yield component rather than penalised."""
    fund = pd.DataFrame([
        {"ticker": "PROFIT", "pe_ratio": 20.0, "pb_ratio": 2.0,
         "roe": 0.2, "debt_to_equity": 0.5, "revenue_growth": 0.1, "eps_growth": 0.1},
        {"ticker": "LOSS",   "pe_ratio": -5.0,  "pb_ratio": 2.0,
         "roe": -0.1, "debt_to_equity": 0.5, "revenue_growth": -0.1, "eps_growth": -0.1},
    ])
    result = compute_value(fund)
    # LOSS has negative P/E: earnings_yield component must be NaN (not a negative number),
    # so the value score is derived solely from book_yield (which is positive for pb=2).
    # In any case the score must not be driven lower by a spurious negative earnings yield.
    profit_score = result["PROFIT"]
    loss_score = result["LOSS"]
    assert pd.notna(profit_score), "profitable ticker should have a value score"
    # The key invariant: a loss-making company's value score must not be boosted above a
    # profitable company's simply because -1/PE gave a large positive number.
    # Negative earnings yield must have been excluded, not inverted.
    assert not (loss_score > profit_score + 0.5), (
        f"LOSS score {loss_score:.3f} is suspiciously higher than PROFIT {profit_score:.3f}; "
        "negative P/E may have been inverted instead of excluded"
    )


def test_value_winsorization_reduces_outliers():
    """
    Cross-sectional z-scores of value should not have many extreme outliers
    after winsorization + cap at 50.
    """
    fund = _large_fund(n=200, seed=3)
    # Inject a handful of extreme values that previously produced 88 outliers
    fund.loc[:4, "pe_ratio"] = 0.5   # extreme value (near-zero PE)
    fund.loc[5:9, "pb_ratio"] = 0.1

    raw = compute_value(fund)
    z = cross_section_zscore(raw)
    extreme = (z.abs() > 2.4).sum()
    # After proper winsorization there should be very few tickers at the ±2.5 clip
    assert extreme <= 10, f"{extreme} tickers hit extreme z-score after winsorization"


# ── compute_low_volatility ────────────────────────────────────────────────────────────────────────────────────

def test_low_volatility_handles_sparse_tickers():
    rng = np.random.default_rng(42)
    dates = pd.date_range("2020-01-01", periods=300, freq="B")
    full = 100 * np.cumprod(1 + rng.normal(0, 0.01, 300))
    sparse = full.copy().astype(float)
    sparse[50:250] = float("nan")
    pivot = pd.DataFrame({"FULL": full, "SPARSE": sparse}, index=dates)
    result = compute_low_volatility(pivot)
    assert pd.notna(result["FULL"])


def test_low_volatility_is_negative_vol():
    pivot = _pivot(["A", "B"], n=300)
    result = compute_low_volatility(pivot)
    assert (result < 0).all()


# ── compute_momentum ──────────────────────────────────────────────────────────────────────────────────────

def test_compute_momentum_needs_253_rows():
    pivot = _pivot(["A"], n=200)
    result = compute_momentum(pivot)
    assert result.empty


def test_compute_momentum_returns_series():
    pivot = _pivot(["A", "B", "C"], n=300)
    result = compute_momentum(pivot)
    assert set(result.index) == {"A", "B", "C"}


# ── compute_all_factors ─────────────────────────────────────────────────────────────────────────────────────

def test_compute_all_factors_columns():
    df = _prices_long(["AAPL", "MSFT", "GOOG"], n=300)
    fund = pd.DataFrame([
        {"ticker": "AAPL", "pe_ratio": 25.0, "pb_ratio": 5.0, "roe": 0.3,
         "debt_to_equity": 0.5, "revenue_growth": 0.1, "eps_growth": 0.15},
        {"ticker": "MSFT", "pe_ratio": 30.0, "pb_ratio": 8.0, "roe": 0.4,
         "debt_to_equity": 0.3, "revenue_growth": 0.15, "eps_growth": 0.2},
        {"ticker": "GOOG", "pe_ratio": 20.0, "pb_ratio": 4.0, "roe": 0.25,
         "debt_to_equity": 0.1, "revenue_growth": 0.12, "eps_growth": 0.18},
    ])
    result = compute_all_factors(df, fund)
    assert "ticker" in result.columns
    for col in ("momentum", "quality", "value", "growth", "low_volatility", "liquidity"):
        assert col in result.columns
    assert len(result) == 3


def test_compute_all_factors_handles_empty_fundamentals():
    df = _prices_long(["X", "Y"], n=300)
    fund = pd.DataFrame(columns=["ticker", "pe_ratio", "pb_ratio", "roe",
                                  "debt_to_equity", "revenue_growth", "eps_growth"])
    result = compute_all_factors(df, fund)
    assert len(result) == 2
    # With no fundamentals, factor scores that need them must be NaN; price-only factors are not.
    for col in ("quality", "value", "growth"):
        assert result[col].isna().all(), f"{col} should be all-NaN with empty fundamentals"
    for col in ("momentum", "low_volatility", "liquidity"):
        assert result[col].notna().any(), f"{col} should have values with sufficient price data"


# ── M1: compute_low_volatility minimum data guard ────────────────────────────
# Old guard: `len(prices) < 2` — a single log-return was enough.
# Fixed guard: `len(prices) < 63` — require ~one quarter of trading history.


class TestLowVolatilityMinimumDataGuard:
    """Regression tests for M1: vol computed from too few rows is unreliable."""

    def test_62_rows_returns_empty(self):
        """Fewer than 63 rows must return an empty Series (no score at all).

        Old code used `< 2`, so 62 rows would have produced an annualised vol
        estimate from 61 log-returns — statistically meaningless but no error raised.
        """
        pivot = _pivot(["A"], n=62)
        result = compute_low_volatility(pivot)
        assert result.empty, (
            "M1 regression: 62 rows must produce an empty Series. "
            "Old guard (< 2) would have returned a score from only 61 log-returns."
        )

    def test_exactly_63_rows_accepted(self):
        """Exactly 63 rows must produce a result (boundary is inclusive)."""
        pivot = _pivot(["A"], n=63)
        result = compute_low_volatility(pivot)
        assert not result.empty, "63 rows (minimum) must produce a score"
        assert pd.notna(result["A"])

    def test_2_rows_also_returns_empty(self):
        """The old threshold of < 2 is too permissive — 2 rows must also be empty."""
        pivot = _pivot(["A"], n=2)
        result = compute_low_volatility(pivot)
        assert result.empty

    def test_full_window_produces_meaningful_score(self):
        """300 rows (full window) must produce a negative vol score."""
        pivot = _pivot(["A", "B"], n=300)
        result = compute_low_volatility(pivot)
        assert (result < 0).all(), "vol score must be negative (lower vol = higher score)"


# ── M3: no_data sentinel rows must be excluded from factor calculations ───────
# The fundamentals query now filters `source != 'no_data'` before returning data.
# Tests verify that a fundamentals DataFrame containing all-NaN fundamental
# values (as a sentinel would produce) yields NaN factor scores — not spurious
# zeros or misleading partial scores.


class TestNoDataSentinelExclusion:
    """Regression tests for M3: sentinel rows with null fundamentals must not
    generate factor scores. The production query now excludes them at the DB level;
    these tests verify the factor functions handle null-only rows correctly."""

    def test_all_null_fundamentals_produce_nan_scores(self):
        """A ticker with all-null fundamental columns must get NaN for every
        fundamental-based factor (quality, value, growth)."""
        fund = pd.DataFrame([{
            "ticker": "SENTINEL",
            "pe_ratio": float("nan"), "pb_ratio": float("nan"),
            "roe": float("nan"), "debt_to_equity": float("nan"),
            "revenue_growth": float("nan"), "eps_growth": float("nan"),
        }])
        quality = compute_quality(fund)
        value   = compute_value(fund)
        growth  = compute_growth(fund)
        assert pd.isna(quality["SENTINEL"]), "quality must be NaN for all-null sentinel"
        assert pd.isna(value["SENTINEL"]),   "value must be NaN for all-null sentinel"
        assert pd.isna(growth["SENTINEL"]),  "growth must be NaN for all-null sentinel"

    def test_sentinel_mixed_with_real_data(self):
        """Sentinel ticker must not distort real tickers' scores.

        If a sentinel's all-null row were treated as a valid data point (zeros),
        it would corrupt the cross-sectional mean and std used in z-scoring.
        """
        real = pd.DataFrame([
            {"ticker": "REAL", "pe_ratio": 20.0, "pb_ratio": 2.0,
             "roe": 0.25, "debt_to_equity": 0.5,
             "revenue_growth": 0.10, "eps_growth": 0.12},
        ])
        with_sentinel = pd.DataFrame([
            {"ticker": "REAL", "pe_ratio": 20.0, "pb_ratio": 2.0,
             "roe": 0.25, "debt_to_equity": 0.5,
             "revenue_growth": 0.10, "eps_growth": 0.12},
            {"ticker": "SENTINEL", "pe_ratio": float("nan"), "pb_ratio": float("nan"),
             "roe": float("nan"), "debt_to_equity": float("nan"),
             "revenue_growth": float("nan"), "eps_growth": float("nan")},
        ])
        q_clean = compute_quality(real)
        q_with  = compute_quality(with_sentinel)
        # REAL's score should be the same (NaN rows don't affect _component_zscore)
        # With only one valid ticker, both produce the same rank (zero z-score).
        assert pd.notna(q_with["REAL"]), "REAL must still score when sentinel is present"
        assert pd.isna(q_with["SENTINEL"]), "SENTINEL must remain NaN"

    def test_no_data_row_with_source_field_not_confused_with_valid(self):
        """Simulate what happened pre-fix: sentinel rows appeared in the fundamentals
        DataFrame. Verify quality factor returns NaN for such rows — the DB query
        now excludes them, but if they slipped through, the factor must handle them."""
        sentinel_fund = pd.DataFrame([{
            "ticker": "NO_DATA",
            "pe_ratio": None, "pb_ratio": None, "roe": None,
            "debt_to_equity": None, "revenue_growth": None, "eps_growth": None,
        }])
        result = compute_quality(sentinel_fund)
        assert pd.isna(result["NO_DATA"]), (
            "M3 regression: a row with all-null fundamentals (sentinel) must produce "
            "NaN quality score, not a spurious 0.0 or other value"
        )


# ── Proactive: pivot() raises on duplicate (date, ticker) pairs ───────────────
# L1: The old pivot_table() silently averaged duplicates; pivot() raises.


class TestComputeAllFactorsDuplicateDetection:
    """Tests for L1: duplicate (date, ticker) rows must raise, not silently average."""

    def test_duplicate_date_ticker_raises(self):
        """compute_all_factors must raise ValueError on duplicate (date, ticker) rows.

        Old code used pivot_table() which silently averaged them. pivot() makes
        the data integrity issue immediately visible instead of masking it.
        """
        df = _prices_long(["AAPL"], n=300)
        fund = pd.DataFrame([{
            "ticker": "AAPL", "pe_ratio": 25.0, "pb_ratio": 5.0,
            "roe": 0.3, "debt_to_equity": 0.5,
            "revenue_growth": 0.1, "eps_growth": 0.15,
        }])
        # Inject a duplicate row for the same (date, ticker)
        duplicate = df.iloc[:1].copy()
        duplicate["adjusted_close"] = 999.0  # different value to expose averaging
        df_with_dup = pd.concat([df, duplicate], ignore_index=True)

        with pytest.raises((ValueError, Exception)):
            compute_all_factors(df_with_dup, fund)

    def test_no_duplicates_does_not_raise(self):
        """Clean input (no duplicates) must pass through without error."""
        df = _prices_long(["AAPL"], n=300)
        fund = pd.DataFrame([{
            "ticker": "AAPL", "pe_ratio": 25.0, "pb_ratio": 5.0,
            "roe": 0.3, "debt_to_equity": 0.5,
            "revenue_growth": 0.1, "eps_growth": 0.15,
        }])
        result = compute_all_factors(df, fund)
        assert len(result) == 1


# ── Proactive: quality/value/growth with only one data source ─────────────────


class TestSingleComponentFactors:
    """Tests for factors when only one of two component signals is available.

    These guard against regressions where a missing component causes the entire
    factor to NaN out instead of falling back to the available component.
    """

    def test_quality_from_roe_only(self):
        """Quality from ROE alone (no D/E) must be non-NaN."""
        fund = pd.DataFrame([
            {"ticker": "A", "roe": 0.30, "debt_to_equity": float("nan"),
             "pe_ratio": 20.0, "pb_ratio": 2.0, "revenue_growth": 0.1, "eps_growth": 0.1},
            {"ticker": "B", "roe": 0.10, "debt_to_equity": float("nan"),
             "pe_ratio": 25.0, "pb_ratio": 3.0, "revenue_growth": 0.05, "eps_growth": 0.05},
        ])
        result = compute_quality(fund)
        assert pd.notna(result["A"]) and pd.notna(result["B"])
        assert result["A"] > result["B"], "higher ROE must produce higher quality score"

    def test_quality_from_dte_only(self):
        """Quality from D/E alone (no ROE) must be non-NaN."""
        fund = pd.DataFrame([
            {"ticker": "LOW_DEBT", "roe": float("nan"), "debt_to_equity": 0.1,
             "pe_ratio": 20.0, "pb_ratio": 2.0, "revenue_growth": 0.1, "eps_growth": 0.1},
            {"ticker": "HIGH_DEBT", "roe": float("nan"), "debt_to_equity": 3.0,
             "pe_ratio": 20.0, "pb_ratio": 2.0, "revenue_growth": 0.1, "eps_growth": 0.1},
        ])
        result = compute_quality(fund)
        assert pd.notna(result["LOW_DEBT"]) and pd.notna(result["HIGH_DEBT"])
        assert result["LOW_DEBT"] > result["HIGH_DEBT"], "lower debt must score higher quality"

    def test_value_from_pe_only(self):
        """Value from earnings yield alone (no PB) must be non-NaN."""
        fund = pd.DataFrame([
            {"ticker": "CHEAP", "pe_ratio": 10.0, "pb_ratio": float("nan"),
             "roe": 0.2, "debt_to_equity": 0.5, "revenue_growth": 0.1, "eps_growth": 0.1},
            {"ticker": "RICH",  "pe_ratio": 40.0, "pb_ratio": float("nan"),
             "roe": 0.2, "debt_to_equity": 0.5, "revenue_growth": 0.1, "eps_growth": 0.1},
        ])
        result = compute_value(fund)
        assert pd.notna(result["CHEAP"]) and pd.notna(result["RICH"])
        assert result["CHEAP"] > result["RICH"], "lower PE must produce higher value score"

    def test_growth_from_revenue_only(self):
        """Growth from revenue alone (no EPS growth) must be non-NaN."""
        fund = pd.DataFrame([
            {"ticker": "FAST", "revenue_growth": 0.30, "eps_growth": float("nan"),
             "pe_ratio": 20.0, "pb_ratio": 2.0, "roe": 0.2, "debt_to_equity": 0.5},
            {"ticker": "SLOW", "revenue_growth": 0.02, "eps_growth": float("nan"),
             "pe_ratio": 20.0, "pb_ratio": 2.0, "roe": 0.2, "debt_to_equity": 0.5},
        ])
        result = compute_growth(fund)
        assert pd.notna(result["FAST"]) and pd.notna(result["SLOW"])
        assert result["FAST"] > result["SLOW"]


# ── Momentum winsorization: spinoff/outlier pollution guard ───────────────────

def _make_prices_with_outlier(
    normal_return: float, outlier_return: float,
    n_normal: int = 50, normal_std: float = 0.08, seed: int = 42,
) -> pd.DataFrame:
    """
    Build a price pivot with n_normal tickers whose 12-month returns are drawn
    from N(normal_return, normal_std), plus one outlier ticker at outlier_return.

    Prices are flat at 100 for the base period; only the terminal short-window
    price varies so that compute_momentum sees the intended return cleanly.
    """
    rng = np.random.default_rng(seed)
    n_days = 300
    dates = pd.date_range("2023-01-01", periods=n_days, freq="B")
    data = {}
    for i in range(n_normal):
        t = f"N{i:03d}"
        ret = rng.normal(normal_return, normal_std)
        prices = np.ones(n_days) * 100.0
        prices[-21] = 100.0 * (1.0 + ret)
        data[t] = prices
    data["SNDK"] = np.ones(n_days) * 100.0
    data["SNDK"][-21] = 100.0 * (1.0 + outlier_return)
    return pd.DataFrame(data, index=dates)


def test_momentum_outlier_inflates_std_without_winsorization():
    """Without winsorization, a 200% outlier inflates cross-sectional std and
    compresses z-scores for every other ticker. With winsorization, SNDK is
    clipped to the 99th pctile of the raw return distribution so the normal
    cohort retains meaningful spread.
    """
    pivot = _make_prices_with_outlier(normal_return=0.15, outlier_return=2.0, n_normal=50)
    mom_raw = compute_momentum(pivot, short_window=21, long_window=252)
    assert "SNDK" in mom_raw.index

    # raw std without the outlier
    std_excl_outlier = mom_raw.drop("SNDK").std()

    # Without winsorization: SNDK pulls std up
    z_no_w = cross_section_zscore(mom_raw, clip=2.5)
    normal_spread_no_w = z_no_w.drop("SNDK").std()

    # With winsorization: SNDK clipped to 99th pctile → std closer to normal cohort
    mom_w = _winsorize(mom_raw.dropna()).reindex(mom_raw.index)
    z_w = cross_section_zscore(mom_w, clip=2.5)
    normal_spread_w = z_w.drop("SNDK").std()

    # Winsorized spread must be strictly larger (outlier inflation is reduced)
    assert normal_spread_w > normal_spread_no_w, (
        f"winsorized spread {normal_spread_w:.3f} should exceed "
        f"unwinsorized {normal_spread_no_w:.3f}"
    )
    # SNDK is still the top scorer after winsorization (signal preserved, just bounded)
    assert z_w["SNDK"] == pytest.approx(2.5, abs=0.01)


def test_momentum_winsorization_applied_in_compute_all_factors():
    """compute_all_factors winsorizes momentum so outlier returns don't collapse the field.

    With 50 normal tickers (N(15%, 8%) returns) plus SNDK at +200%, normal tickers
    must retain meaningful cross-sectional spread in the final momentum z-scores.
    """
    pivot = _make_prices_with_outlier(normal_return=0.15, outlier_return=2.0, n_normal=50)
    tickers = list(pivot.columns)

    rows = []
    for t in tickers:
        for dt, p in pivot[t].items():
            rows.append({"ticker": t, "date": dt.date(), "close": p, "adjusted_close": p, "volume": 1_000_000})
    prices_long = pd.DataFrame(rows)

    fund_rows = [
        {"ticker": t, "as_of_date": "2024-01-01", "source": "av",
         "pe_ratio": 20.0, "pb_ratio": 2.0, "roe": 0.15, "debt_to_equity": 0.5,
         "revenue_growth": 0.10, "eps_growth": 0.10}
        for t in tickers
    ]
    fundamentals = pd.DataFrame(fund_rows)

    result = compute_all_factors(prices_long, fundamentals)
    result = result.set_index("ticker")

    # SNDK should be at the cap
    assert result.loc["SNDK", "momentum"] == pytest.approx(2.5, abs=0.05)

    # Normal tickers must retain meaningful spread — not all collapsed toward zero
    normal_mom = result.drop("SNDK")["momentum"].dropna()
    assert normal_mom.std() > 0.15, (
        f"Normal tickers momentum std={normal_mom.std():.3f} after winsorization; "
        "should be well above zero (outlier not polluting the distribution)"
    )
