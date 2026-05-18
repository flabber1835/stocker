import numpy as np
import pytest
from app.metrics import annualized_return, sharpe_ratio, max_drawdown, turnover


# ── annualized_return ──────────────────────────────────────────────────────────

def test_annualized_return_1yr():
    # 10% over 365 calendar days → exactly 10% annualised
    result = annualized_return(0.10, 365)
    np.testing.assert_allclose(result, 0.10, rtol=1e-3)


def test_annualized_return_6mo():
    # 5% over ~182 calendar days should annualise to ~10%
    result = annualized_return(0.05, 182)
    np.testing.assert_allclose(result, (1.05 ** 2) - 1, rtol=1e-2)


def test_annualized_return_zero_days():
    assert annualized_return(0.10, 0) == 0.0


def test_annualized_return_negative():
    # -20% over 365 calendar days → exactly -20% annualised
    result = annualized_return(-0.20, 365)
    np.testing.assert_allclose(result, -0.20, rtol=1e-3)


# ── sharpe_ratio ───────────────────────────────────────────────────────────────

def test_sharpe_all_positive():
    # Varying but consistently positive returns well above risk-free → Sharpe > 0
    result = sharpe_ratio([0.03, 0.04, 0.02, 0.05, 0.03, 0.04, 0.02, 0.03, 0.04, 0.05, 0.03, 0.04])
    assert result > 0


def test_sharpe_periods_per_year_scales_result():
    # Same returns, different frequency assumption: daily (252) vs monthly (12)
    # Daily Sharpe should be sqrt(252/12) ≈ 4.58× larger than monthly Sharpe.
    # Use rf_annual=0 so both Sharpes are positive and the ratio is exactly
    # sqrt(periods_per_year_daily / periods_per_year_monthly).
    returns = [0.01, 0.03] * 12  # alternating → non-zero std, well above rf=0
    s_monthly = sharpe_ratio(returns, rf_annual=0.0, periods_per_year=12)
    s_daily   = sharpe_ratio(returns, rf_annual=0.0, periods_per_year=252)
    assert s_daily > s_monthly
    import math
    assert abs(s_daily / s_monthly - math.sqrt(252 / 12)) < 0.001


def test_sharpe_default_is_monthly():
    # Default periods_per_year=12 should match explicit monthly call
    returns = [0.02, 0.03, -0.01, 0.04, 0.02, 0.01, 0.03, 0.02, -0.01, 0.03, 0.02, 0.01]
    assert sharpe_ratio(returns) == pytest.approx(sharpe_ratio(returns, periods_per_year=12))


def test_sharpe_all_negative():
    # Consistently negative returns below risk-free → Sharpe < 0
    result = sharpe_ratio([-0.03, -0.02, -0.04, -0.03, -0.05, -0.02, -0.04, -0.03, -0.02, -0.04, -0.03, -0.05])
    assert result < 0


def test_sharpe_zero_std():
    # All returns identical → std=0 → returns 0.0, no exception
    result = sharpe_ratio([0.01] * 12)
    assert result == 0.0


def test_sharpe_single_value():
    # Less than 2 values → 0.0
    assert sharpe_ratio([0.05]) == 0.0


def test_sharpe_empty():
    assert sharpe_ratio([]) == 0.0


# ── max_drawdown ───────────────────────────────────────────────────────────────

def test_max_drawdown_flat():
    assert max_drawdown([1.0, 1.0, 1.0, 1.0]) == 0.0


def test_max_drawdown_50pct_drop():
    result = max_drawdown([1.0, 0.5])
    np.testing.assert_allclose(result, -0.5, rtol=1e-6)


def test_max_drawdown_recovery():
    # peak=1.2 at index 2, then drops to 0.6 → drawdown = 0.6/1.2 - 1 = -0.5
    result = max_drawdown([1.0, 0.8, 1.2, 0.6])
    np.testing.assert_allclose(result, -0.5, rtol=1e-6)


def test_max_drawdown_always_rising():
    result = max_drawdown([1.0, 1.1, 1.2, 1.3])
    assert result == 0.0


def test_max_drawdown_single():
    assert max_drawdown([1.0]) == 0.0


# ── turnover ──────────────────────────────────────────────────────────────────

def test_turnover_identical():
    w = {"AAPL": 0.5, "MSFT": 0.5}
    assert turnover(w, w) == 0.0


def test_turnover_full_replacement():
    # {A:1.0} → {B:1.0}: |0-1|+|1-0| = 2, /2 = 1.0
    result = turnover({"A": 1.0}, {"B": 1.0})
    np.testing.assert_allclose(result, 1.0, rtol=1e-6)


def test_turnover_partial():
    # prev={A:0.6, B:0.4}, curr={A:0.4, C:0.6}
    # |0.4-0.6| + |0-0.4| + |0.6-0| = 0.2 + 0.4 + 0.6 = 1.2, /2 = 0.6
    result = turnover({"A": 0.6, "B": 0.4}, {"A": 0.4, "C": 0.6})
    np.testing.assert_allclose(result, 0.6, rtol=1e-6)


def test_turnover_empty_prev():
    result = turnover({}, {"A": 0.5, "B": 0.5})
    np.testing.assert_allclose(result, 0.5, rtol=1e-6)


def test_turnover_empty_both():
    assert turnover({}, {}) == 0.0
