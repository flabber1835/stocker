import pandas as pd
import numpy as np
import pytest
from app.simulate import run_backtest


def _make_prices(tickers: list[str], dates: list[str], prices: dict[str, list[float]]) -> pd.DataFrame:
    """Build a long-format price DataFrame."""
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


# ── basic correctness ──────────────────────────────────────────────────────────

def test_empty_runs():
    result = run_backtest([], pd.DataFrame(columns=["ticker", "date", "adjusted_close"]))
    assert result == {"summary": {}, "periods": []}


def test_single_period_return():
    # AAPL: 100 → 110 = 10% return, weight 1.0
    runs = [
        _make_run("r1", "2023-01-03", [("AAPL", 1.0)]),
        _make_run("r2", "2023-02-01", [("AAPL", 1.0)]),
    ]
    dates = ["2023-01-03", "2023-02-01"]
    prices = _make_prices(["AAPL"], dates, {"AAPL": [100.0, 110.0]})
    result = run_backtest(runs, prices)
    assert len(result["periods"]) >= 1
    period = result["periods"][0]
    np.testing.assert_allclose(period["portfolio_return"], 0.10, rtol=1e-4)


def test_benchmark_comparison():
    runs = [
        _make_run("r1", "2023-01-03", [("AAPL", 1.0)]),
        _make_run("r2", "2023-02-01", [("AAPL", 1.0)]),
    ]
    dates = ["2023-01-03", "2023-02-01"]
    prices = _make_prices(["AAPL", "SPY"], dates, {"AAPL": [100.0, 110.0], "SPY": [400.0, 420.0]})
    result = run_backtest(runs, prices)
    period = result["periods"][0]
    np.testing.assert_allclose(period["benchmark_return"], 0.05, rtol=1e-4)
    np.testing.assert_allclose(period["excess_return"], 0.05, rtol=1e-4)


def test_compounding():
    # Two periods: 10% each → total = 1.1*1.1 - 1 = 0.21
    runs = [
        _make_run("r1", "2023-01-03", [("AAPL", 1.0)]),
        _make_run("r2", "2023-02-01", [("AAPL", 1.0)]),
        _make_run("r3", "2023-03-01", [("AAPL", 1.0)]),
    ]
    dates = ["2023-01-03", "2023-02-01", "2023-03-01"]
    prices = _make_prices(["AAPL"], dates, {"AAPL": [100.0, 110.0, 121.0]})
    result = run_backtest(runs, prices)
    summary = result["summary"]
    np.testing.assert_allclose(summary["total_return"], 0.21, rtol=1e-3)


def test_tx_cost_reduces_return():
    # AAPL 100→110 (10%), SPY static. With full turnover and 100 bps cost → net < 0.10
    runs = [
        _make_run("r1", "2023-01-03", [("AAPL", 1.0)]),
        _make_run("r2", "2023-02-01", [("MSFT", 1.0)]),  # full replacement
        _make_run("r3", "2023-03-01", [("MSFT", 1.0)]),
    ]
    dates = ["2023-01-03", "2023-02-01", "2023-03-01"]
    prices = _make_prices(
        ["AAPL", "MSFT"],
        dates,
        {"AAPL": [100.0, 110.0, 110.0], "MSFT": [50.0, 50.0, 55.0]},
    )
    result_no_cost = run_backtest(runs, prices, tx_cost_bps=0)
    result_with_cost = run_backtest(runs, prices, tx_cost_bps=100)

    r_no = result_no_cost["periods"][0]["portfolio_return"]
    r_with = result_with_cost["periods"][0]["portfolio_return"]
    assert r_with < r_no


def test_turnover_tracked():
    # Full portfolio replacement between periods → turnover = 1.0
    runs = [
        _make_run("r1", "2023-01-03", [("AAPL", 1.0)]),
        _make_run("r2", "2023-02-01", [("MSFT", 1.0)]),
        _make_run("r3", "2023-03-01", [("MSFT", 1.0)]),
    ]
    dates = ["2023-01-03", "2023-02-01", "2023-03-01"]
    prices = _make_prices(
        ["AAPL", "MSFT"],
        dates,
        {"AAPL": [100.0, 100.0, 100.0], "MSFT": [100.0, 100.0, 100.0]},
    )
    result = run_backtest(runs, prices)
    # Second period (index 1) is where the full swap happens
    assert result["periods"][1]["turnover"] == pytest.approx(1.0, abs=1e-4)


def test_missing_price_handling():
    # AAPL has prices, NVDA is absent from prices → NVDA excluded, n_holdings=1
    runs = [
        _make_run("r1", "2023-01-03", [("AAPL", 0.5), ("NVDA", 0.5)]),
        _make_run("r2", "2023-02-01", [("AAPL", 1.0)]),
    ]
    dates = ["2023-01-03", "2023-02-01"]
    prices = _make_prices(["AAPL"], dates, {"AAPL": [100.0, 110.0]})
    result = run_backtest(runs, prices)
    assert result["periods"][0]["n_holdings"] == 1


def test_determinism():
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
    result1 = run_backtest(runs, prices)
    result2 = run_backtest(runs, prices)
    assert result1["summary"] == result2["summary"]
    assert result1["periods"] == result2["periods"]


def test_regime_preserved():
    runs = [
        _make_run("r1", "2023-01-03", [("AAPL", 1.0)], regime="bear_stress"),
        _make_run("r2", "2023-02-01", [("AAPL", 1.0)], regime="bear_stress"),
    ]
    dates = ["2023-01-03", "2023-02-01"]
    prices = _make_prices(["AAPL"], dates, {"AAPL": [100.0, 95.0]})
    result = run_backtest(runs, prices)
    assert result["periods"][0]["regime"] == "bear_stress"
