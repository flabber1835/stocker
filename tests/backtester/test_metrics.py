import numpy as np
import pytest
from app.metrics import annualized_return, sharpe_ratio, max_drawdown, turnover


# ── annualized_return ──────────────────────────────────────────────────────────

def test_annualized_return_1yr():
    result = annualized_return(0.10, 252)
    np.testing.assert_allclose(result, 0.10, rtol=1e-4)


def test_annualized_return_6mo():
    # 5% over 126 days should annualise to ~10%
    result = annualized_return(0.05, 126)
    np.testing.assert_allclose(result, (1.05 ** 2) - 1, rtol=1e-4)


def test_annualized_return_zero_days():
    assert annualized_return(0.10, 0) == 0.0


def test_annualized_return_negative():
    result = annualized_return(-0.20, 252)
    np.testing.assert_allclose(result, -0.20, rtol=1e-4)


# ── sharpe_ratio ───────────────────────────────────────────────────────────────

def test_sharpe_all_positive():
    # Varying but consistently positive returns well above risk-free → Sharpe > 0
    result = sharpe_ratio([0.03, 0.04, 0.02, 0.05, 0.03, 0.04, 0.02, 0.03, 0.04, 0.05, 0.03, 0.04])
    assert result > 0


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
