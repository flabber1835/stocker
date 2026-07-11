"""bt-engine simulator: determinism, the gold-standard truncation no-look-ahead
test, falling-knife veto at selection, fill-timing semantics, tx costs, delist
handling. All synthetic data — no DB, no network."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.sim import SimParams, run_simulation
from stock_strategy_shared.schemas.strategy import StrategyConfig

_REGIMES = {
    "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
    "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
    "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
    "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
}
_W = {"momentum": 0.9, "quality": 0.025, "value": 0.025, "growth": 0.025, "low_volatility": 0.025}


def _cfg(**pb_over) -> StrategyConfig:
    pb = {
        "method": "greedy_score_per_port_vol", "max_positions": 3,
        "max_position_weight": 0.6, "max_sector_weight": 1.0, "weighting": "equal_weight",
        "candidate_count": 10, "covariance_window_days": 40,
        "min_covariance_observations": 20, "covariance_shrinkage": 0.2,
        "cluster_correlation_threshold": 0.99, "max_cluster_weight": 1.0,
        "max_tickers_per_cluster": None,
    }
    pb.update(pb_over)
    return StrategyConfig(**{
        "strategy_id": "bt_sim_test",
        "min_non_null_factors": 1,
        "universe": {"source": "av_listing", "min_price": 1.0, "min_avg_dollar_volume_20d": 0.0},
        "regime_detection": {"slow_sma": 20, "vol_window": 5, "vol_threshold": 0.8,
                             "confirmation_days": 1, "regimes": _REGIMES},
        "factor_weights": {"bull_calm": _W, "bull_stress": _W,
                           "bear_stress": _W, "bear_calm": _W},
        "regime_weighting_enabled": False,
        "static_factor_weights": _W,
        "portfolio_builder": pb,
        "vetter": {"candidate_count": 10},
    })


def _make_data(n_days=520, crash_ticker=None, delist_ticker=None, delist_at=None):
    """Deterministic geometric walks, distinct drifts. Returns (prices, fundamentals)."""
    days = pd.bdate_range("2024-01-02", periods=n_days)
    spec = {"AAA": 0.0004, "BBB": 0.0008, "CCC": 0.0012, "DDD": 0.0002,
            "EEE": 0.0010, "FFF": 0.0006, "SPY": 0.0005}
    rows = []
    for t, drift in spec.items():
        px = 100.0
        for i, d in enumerate(days):
            # NOT hash(): string hashing is PYTHONHASHSEED-randomized per process,
            # which made this "deterministic" dataset differ run-to-run (flaky).
            wiggle = 0.002 * np.sin(i / 7.0 + sum(map(ord, t)) % 10)
            px = px * (1.0 + drift + wiggle)
            if crash_ticker == t and i >= n_days - 15:
                px *= 0.96                                     # ~45% crash over 15d
            if delist_ticker == t and delist_at is not None and i >= delist_at:
                continue                                       # no more prints
            rows.append({"ticker": t, "date": d, "open": px * 0.999, "close": px,
                         "adjusted_close": px, "volume": 1_000_000.0})
    prices = pd.DataFrame(rows)
    fundamentals = pd.DataFrame([
        {"ticker": t, "as_of_date": days[0], "pe_ratio": 15.0, "pb_ratio": 2.0,
         "roe": 0.15, "debt_to_equity": 0.5, "revenue_growth": 0.05, "eps_growth": 0.05}
        for t in spec if t != "SPY"])
    return prices, fundamentals, days


def _params(days, span=60, **over):
    start = days[-span].date()
    end = days[-1].date()
    base = dict(start=start, end=end, tx_cost_bps=0, fill_timing="close",
                rebalance_every=5)
    base.update(over)
    return SimParams(**base)


def test_determinism_identical_equity():
    prices, fnd, days = _make_data()
    cfg = _cfg()
    r1 = run_simulation(prices.copy(), fnd.copy(), {}, cfg, _params(days))
    r2 = run_simulation(prices.copy(), fnd.copy(), {}, cfg, _params(days))
    assert r1.equity == r2.equity
    assert r1.trades == r2.trades
    assert r1.summary == r2.summary


def test_truncation_no_look_ahead():
    """Gold standard: sim ending at K on FULL data == sim on data TRUNCATED at K.
    Any read of post-K data would make them diverge."""
    prices, fnd, days = _make_data()
    cfg = _cfg()
    k_idx = len(days) - 20
    k = days[k_idx].date()
    p = _params(days, span=60)
    p_k = SimParams(start=p.start, end=k, tx_cost_bps=0, fill_timing="close",
                    rebalance_every=5)
    full = run_simulation(prices.copy(), fnd.copy(), {}, cfg, p_k)
    truncated = run_simulation(prices[prices["date"] <= days[k_idx]].copy(),
                               fnd.copy(), {}, cfg, p_k)
    assert full.equity == truncated.equity
    assert full.trades == truncated.trades


def test_falling_knife_never_buys_crashed_name():
    prices, fnd, days = _make_data(crash_ticker="EEE")
    cfg = _cfg()
    # window covers the crash; EEE has the strongest drift so absent the veto it
    # would rank top — the veto must keep it out during/after the crash window.
    res = run_simulation(prices, fnd, {}, cfg,
                         _params(days, span=12, rebalance_every=2))
    bought = {t["ticker"] for t in res.trades if t["action"] in ("entry", "buy_add")}
    assert "EEE" not in bought


def test_fill_timing_close_vs_next_open_prices():
    prices, fnd, days = _make_data()
    cfg = _cfg()
    res_close = run_simulation(prices.copy(), fnd.copy(), {}, cfg,
                               _params(days, fill_timing="close"))
    res_open = run_simulation(prices.copy(), fnd.copy(), {}, cfg,
                              _params(days, fill_timing="next_open"))
    assert res_close.trades and res_open.trades
    first_close = res_close.trades[0]
    first_open = next(t for t in res_open.trades if t["ticker"] == first_close["ticker"])
    # close fills on the decision day; next_open fills on the NEXT trading day
    assert first_open["date"] > first_close["date"]
    assert first_open["price"] != first_close["price"]


def test_tx_costs_reduce_final_equity():
    prices, fnd, days = _make_data()
    cfg = _cfg()
    free = run_simulation(prices.copy(), fnd.copy(), {}, cfg,
                          _params(days, tx_cost_bps=0))
    costly = run_simulation(prices.copy(), fnd.copy(), {}, cfg,
                            _params(days, tx_cost_bps=100))
    assert costly.equity[-1]["portfolio_value"] < free.equity[-1]["portfolio_value"]
    assert costly.summary["tx_cost_bps"] == 100
    assert all(t["tx_cost"] > 0 for t in costly.trades if t["qty"] >= 1)


def test_accounting_day_one_conserves_capital():
    """Buying at close with zero costs must conserve value: cash + positions ≈
    starting capital on the first day (only share-flooring residue)."""
    prices, fnd, days = _make_data()
    cfg = _cfg()
    res = run_simulation(prices, fnd, {}, cfg, _params(days))
    day0 = res.equity[0]["portfolio_value"]
    assert day0 == pytest.approx(100_000.0, rel=0.01)


def test_delisted_holding_force_exits():
    prices, fnd, days = _make_data(delist_ticker="CCC", delist_at=495)  # 520-day set
    cfg = _cfg()
    res = run_simulation(prices, fnd, {}, cfg,
                         _params(days, span=55, rebalance_every=3))
    held_last = {p["ticker"] for p in res.positions if p["date"] == res.positions[-1]["date"]}
    assert "CCC" not in held_last
    # equity stays finite/positive throughout
    assert all(np.isfinite(r["portfolio_value"]) and r["portfolio_value"] > 0
               for r in res.equity)


def test_summary_shape():
    prices, fnd, days = _make_data()
    res = run_simulation(prices, fnd, {}, _cfg(), _params(days))
    for k in ("total_return", "annualized_return", "sharpe_ratio", "max_drawdown",
              "benchmark_total_return", "alpha", "avg_turnover", "win_rate",
              "n_rebalances", "n_trades"):
        assert k in res.summary, k
    assert res.summary["n_rebalances"] > 0 and res.summary["n_trades"] > 0
