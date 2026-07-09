import pandas as pd
import numpy as np
import pytest
from app.simulate import run_backtest


def _make_prices(tickers: list[str], dates: list[str], prices: dict[str, list[float]]) -> pd.DataFrame:
    """Build a long-format price DataFrame.

    The simulator fills at t+1 (the first close STRICTLY AFTER a rebalance date —
    no same-close look-ahead), so for each rebalance date we also emit the NEXT
    calendar day carrying the SAME price. Entry/exit then land on those +1 days at
    the rebalance-date price, preserving each fixture's intended period return
    while exercising the correct (non-look-ahead) fill path.
    """
    rows = []
    for ticker in tickers:
        for i, d in enumerate(dates):
            ts = pd.Timestamp(d)
            px = prices[ticker][i]
            rows.append({"ticker": ticker, "date": ts, "adjusted_close": px})
            rows.append({"ticker": ticker, "date": ts + pd.Timedelta(days=1), "adjusted_close": px})
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
    result = run_backtest(runs, prices, tx_cost_bps=0)
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
    result = run_backtest(runs, prices, tx_cost_bps=0)
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
    result = run_backtest(runs, prices, tx_cost_bps=0)
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
    # AAPL has prices, NVDA is absent → NVDA is KEPT at 0% return in the full-weight
    # denominator (G3 de-bias: a missing name must not boost survivors). So both
    # names count as holdings, but only AAPL is 'priced'. AAPL +10% at weight 0.5,
    # NVDA 0% at weight 0.5 → port return ≈ 5% (not 10% as the old survivor-renorm
    # would have inflated it).
    runs = [
        _make_run("r1", "2023-01-03", [("AAPL", 0.5), ("NVDA", 0.5)]),
        _make_run("r2", "2023-02-01", [("AAPL", 1.0)]),
    ]
    dates = ["2023-01-03", "2023-02-01"]
    prices = _make_prices(["AAPL"], dates, {"AAPL": [100.0, 110.0]})
    result = run_backtest(runs, prices, tx_cost_bps=0)
    p = result["periods"][0]
    assert p["n_holdings"] == 2 and p["n_priced"] == 1
    np.testing.assert_allclose(p["portfolio_return"], 0.05, rtol=1e-4)


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


# ── G3 de-bias + G5 distribution stats ────────────────────────────────────────

def test_next_close_fill_no_lookahead():
    # Ranking formed on 2023-01-03 close (price 100); a same-close fill would buy
    # at 100 that day. The correct fill is the NEXT close. Give a jump on the day
    # AFTER the rebalance to prove entry uses t+1, not t.
    runs = [
        _make_run("r1", "2023-01-03", [("AAPL", 1.0)]),
        _make_run("r2", "2023-01-10", [("AAPL", 1.0)]),
    ]
    rows = []
    for d, px in [("2023-01-03", 100.0), ("2023-01-04", 200.0),   # +1 day jumps to 200
                  ("2023-01-10", 220.0), ("2023-01-11", 220.0)]:
        rows.append({"ticker": "AAPL", "date": pd.Timestamp(d), "adjusted_close": px})
    result = run_backtest(runs, pd.DataFrame(rows), tx_cost_bps=0)
    p = result["periods"][0]
    # entry = 2023-01-04 (200), exit = 2023-01-11 (220) → +10%, NOT (220/100-1)=120%
    assert p["entry_date"] == "2023-01-04" and p["exit_date"] == "2023-01-11"
    np.testing.assert_allclose(p["portfolio_return"], 0.10, rtol=1e-4)


def test_delisted_name_exits_at_last_price_not_dropped():
    # AAPL halts after 2023-01-05 (no price at the exit window). It must exit at
    # its last real price (its realized move counts), NOT vanish and boost nothing.
    runs = [
        _make_run("r1", "2023-01-03", [("AAPL", 1.0)]),
        _make_run("r2", "2023-01-31", [("AAPL", 1.0)]),
    ]
    rows = []
    for d, px in [("2023-01-03", 100.0), ("2023-01-04", 100.0), ("2023-01-05", 80.0)]:
        rows.append({"ticker": "AAPL", "date": pd.Timestamp(d), "adjusted_close": px})
    # exit window has no AAPL price after 01-05
    rows.append({"ticker": "SPY", "date": pd.Timestamp("2023-02-01"), "adjusted_close": 400.0})
    result = run_backtest(runs, pd.DataFrame(rows), tx_cost_bps=0)
    p = result["periods"][0]
    # entry 01-04 (100) → last real 01-05 (80) = -20%, captured (not silently 0)
    np.testing.assert_allclose(p["portfolio_return"], -0.20, rtol=1e-4)


def test_distribution_stats_present_and_shaped():
    runs = [_make_run(f"r{i}", d, [("AAPL", 1.0)])
            for i, d in enumerate(["2023-01-03", "2023-02-01", "2023-03-01", "2023-04-03"])]
    dates = ["2023-01-03", "2023-02-01", "2023-03-01", "2023-04-03"]
    prices = _make_prices(["AAPL"], dates, {"AAPL": [100.0, 120.0, 90.0, 130.0]})  # volatile
    dist = run_backtest(runs, prices, tx_cost_bps=0)["summary"]["return_distribution"]
    for k in ("mean", "median", "p05", "p95", "min", "max", "pct_positive", "skew", "excess_kurtosis"):
        assert k in dist
    assert dist["min"] <= dist["median"] <= dist["max"]
