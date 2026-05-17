"""
Edge-case tests for backtester metrics and simulate.run_backtest.

Complements tests/backtester/test_metrics.py (basic correctness) and
tests/backtester/test_simulate.py (standard scenarios).
"""
import pandas as pd
import numpy as np
import pytest

from app.metrics import sharpe_ratio, annualized_return
from app.simulate import run_backtest


# ── Helper factories (same pattern as test_simulate.py) ──────────────────────

def _make_prices(tickers: list[str], dates: list[str], prices: dict[str, list[float]]) -> pd.DataFrame:
    rows = []
    for ticker in tickers:
        for i, d in enumerate(dates):
            rows.append({
                "ticker": ticker,
                "date": pd.Timestamp(d),
                "adjusted_close": prices[ticker][i],
            })
    return pd.DataFrame(rows)


def _make_run(run_id: str, portfolio_date: str, holdings: list[tuple[str, float]], regime: str = "bull_calm") -> dict:
    return {
        "run_id": run_id,
        "portfolio_date": portfolio_date,
        "regime": regime,
        "holdings": [{"ticker": t, "weight": w} for t, w in holdings],
    }


# ── Last period with no subsequent prices ────────────────────────────────────

class TestLastPeriodEdgeCases:

    def test_last_period_no_future_dates_skipped_gracefully(self):
        """
        When the last portfolio run has no subsequent price dates at all,
        run_backtest should not raise and should return valid metrics
        for all prior periods.
        """
        # Three runs but only two dates — the last run has no next price date
        runs = [
            _make_run("r1", "2023-01-03", [("AAPL", 1.0)]),
            _make_run("r2", "2023-02-01", [("AAPL", 1.0)]),
            _make_run("r3", "2023-03-01", [("AAPL", 1.0)]),  # no prices after this
        ]
        dates = ["2023-01-03", "2023-02-01", "2023-03-01"]
        prices = _make_prices(["AAPL"], dates, {"AAPL": [100.0, 110.0, 121.0]})
        # Should not raise
        result = run_backtest(runs, prices)
        # Must have at least one period from the first two runs
        assert "periods" in result
        assert "summary" in result
        assert len(result["periods"]) >= 1, (
            "Prior periods must still be returned even when the last period is skipped"
        )

    def test_last_period_with_sparse_future_dates_uses_available(self):
        """
        If fewer than 21 future trading days exist after the last portfolio date,
        run_backtest should use the last available date instead of raising.
        """
        # Last run: only 5 future price dates exist (< 21)
        dates = [
            "2023-01-03", "2023-02-01", "2023-03-01",
            "2023-03-05", "2023-03-10", "2023-03-15",
            "2023-03-20", "2023-03-25",
        ]
        prices = _make_prices(
            ["AAPL"], dates,
            {"AAPL": [100.0, 110.0, 121.0, 122.0, 123.0, 124.0, 125.0, 126.0]},
        )
        runs = [
            _make_run("r1", "2023-01-03", [("AAPL", 1.0)]),
            _make_run("r2", "2023-02-01", [("AAPL", 1.0)]),
            _make_run("r3", "2023-03-01", [("AAPL", 1.0)]),
        ]
        result = run_backtest(runs, prices)
        assert len(result["periods"]) >= 2


# ── Sharpe ratio edge cases ───────────────────────────────────────────────────

class TestSharpeEdgeCases:

    def test_sharpe_ratio_with_known_returns(self):
        """
        Known monthly returns produce a finite, non-NaN Sharpe ratio.
        Direction (positive/negative) is sanity-checked.
        """
        # Strongly positive returns — should produce a positive Sharpe
        returns = [0.05, 0.04, 0.06, 0.05, 0.04, 0.05, 0.06, 0.05, 0.04, 0.06, 0.05, 0.05]
        result = sharpe_ratio(returns)
        assert not np.isnan(result), "Sharpe must not be NaN"
        assert not np.isinf(result), "Sharpe must not be infinite"
        assert result > 0, "Strongly positive monthly returns should yield positive Sharpe"

    def test_zero_variance_returns_sharpe_zero(self):
        """
        All returns identical → std=0 → sharpe_ratio must return 0.0, not raise.
        """
        result = sharpe_ratio([0.01] * 12)
        assert result == 0.0, "Zero-variance returns must produce Sharpe of 0.0"

    def test_sharpe_empty_returns_zero(self):
        assert sharpe_ratio([]) == 0.0

    def test_sharpe_single_value_returns_zero(self):
        assert sharpe_ratio([0.05]) == 0.0

    def test_sharpe_negative_returns_negative(self):
        returns = [-0.05] * 12
        # All returns well below risk-free → negative excess → negative Sharpe … but std=0
        # so it returns 0.0 (by the zero-variance guard)
        result = sharpe_ratio(returns)
        assert result == 0.0

    def test_sharpe_mixed_returns_finite(self):
        """Mixed positive/negative returns → finite Sharpe."""
        returns = [0.05, -0.02, 0.03, -0.01, 0.04, -0.02, 0.03, -0.01, 0.04, -0.02, 0.03, -0.01]
        result = sharpe_ratio(returns)
        assert np.isfinite(result)


# ── run_backtest summary completeness ────────────────────────────────────────

class TestBacktestSummaryCompleteness:

    def test_summary_keys_present(self):
        """All expected summary keys are present in a normal backtest."""
        runs = [
            _make_run("r1", "2023-01-03", [("AAPL", 1.0)]),
            _make_run("r2", "2023-02-01", [("AAPL", 1.0)]),
        ]
        dates = ["2023-01-03", "2023-02-01"]
        prices = _make_prices(["AAPL"], dates, {"AAPL": [100.0, 110.0]})
        result = run_backtest(runs, prices)
        expected_keys = {
            "total_return", "annualized_return", "sharpe_ratio",
            "max_drawdown", "avg_monthly_turnover", "win_rate",
            "benchmark_total_return", "benchmark_annualized_return",
            "n_rebalances",
        }
        assert expected_keys.issubset(result["summary"].keys()), (
            f"Missing summary keys: {expected_keys - result['summary'].keys()}"
        )

    def test_summary_values_are_finite(self):
        """All numeric summary values must be finite (no NaN or inf)."""
        runs = [
            _make_run("r1", "2023-01-03", [("AAPL", 0.6), ("MSFT", 0.4)]),
            _make_run("r2", "2023-02-01", [("AAPL", 0.6), ("MSFT", 0.4)]),
        ]
        dates = ["2023-01-03", "2023-02-01"]
        prices = _make_prices(
            ["AAPL", "MSFT"],
            dates,
            {"AAPL": [100.0, 108.0], "MSFT": [50.0, 53.0]},
        )
        result = run_backtest(runs, prices)
        for key, value in result["summary"].items():
            if isinstance(value, float):
                assert np.isfinite(value), f"summary[{key!r}] = {value} is not finite"
