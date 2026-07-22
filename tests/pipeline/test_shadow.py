"""Shadow champion/challenger (closed-loop item 4): pure challenger-target
construction reusing the shared canonical select, and the inert-by-default
guard (no CHALLENGER_CONFIG_PATH → the hook is a no-op, no DB touched)."""
import asyncio
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.shadow import build_challenger_target
from stock_strategy_shared.schemas.strategy import StrategyConfig

_REGIMES = {
    "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
    "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
    "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
    "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
}
_W = {"momentum": 0.9, "quality": 0.025, "value": 0.025, "growth": 0.025,
      "low_volatility": 0.025}


def _cfg(**pb_overrides):
    pb = {
        "method": "greedy_score_per_port_vol", "max_positions": 3,
        "max_position_weight": 0.6, "max_sector_weight": 1.0,
        "weighting": "equal_weight", "candidate_count": 10,
        "covariance_window_days": 60, "min_covariance_observations": 20,
        "covariance_shrinkage": 0.2, "cluster_correlation_threshold": 0.99,
        "max_cluster_weight": 1.0, "max_tickers_per_cluster": None,
    }
    pb.update(pb_overrides)
    return StrategyConfig(**{
        "strategy_id": "challenger_test",
        "min_non_null_factors": 1,
        "universe": {"source": "av_listing", "min_price": 1.0,
                     "min_avg_dollar_volume_20d": 0.0},
        "regime_detection": {"slow_sma": 20, "vol_window": 5, "vol_threshold": 0.8,
                             "confirmation_days": 1, "regimes": _REGIMES},
        "factor_weights": {r: _W for r in _REGIMES},
        "regime_weighting_enabled": False,
        "static_factor_weights": _W,
        "portfolio_builder": pb,
        "vetter": {"candidate_count": 10},
    })


def _ranked(tickers):
    return pd.DataFrame({
        "ticker": tickers,
        "rank": range(1, len(tickers) + 1),
        "composite_score": np.linspace(1.0, 0.1, len(tickers)),
    })


def _prices(tickers, days=80, seed=7):
    rng = np.random.default_rng(seed)
    d0 = date(2026, 4, 1)
    rows = []
    for k, t in enumerate(tickers):
        px = 50.0 + 10 * k
        for i in range(days):
            px *= 1.0 + rng.normal(0.0004, 0.01)
            rows.append({"ticker": t, "date": d0 + timedelta(days=i),
                         "adjusted_close": px})
    return pd.DataFrame(rows)


TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]


def test_builds_target_within_caps():
    target, err = build_challenger_target(
        _ranked(TICKERS), _prices(TICKERS), {}, _cfg())
    assert err is None and target
    assert len(target) <= 3
    assert all(w <= 0.6 + 1e-9 for w in target.values())
    assert sum(target.values()) <= 1.0 + 1e-9
    assert set(target) <= set(TICKERS)


def test_do_not_buy_respected():
    cfg = _cfg(do_not_buy=["AAA"])
    target, err = build_challenger_target(
        _ranked(TICKERS), _prices(TICKERS), {}, cfg)
    assert err is None and "AAA" not in target


def test_insufficient_prices_fails_with_reason_not_crash():
    thin = _prices(TICKERS).groupby("ticker").head(3)   # 3 days < min_observations
    target, err = build_challenger_target(_ranked(TICKERS), thin, {}, _cfg())
    assert target == {} and err is not None


def test_deterministic():
    a, _ = build_challenger_target(_ranked(TICKERS), _prices(TICKERS), {}, _cfg())
    b, _ = build_challenger_target(_ranked(TICKERS), _prices(TICKERS), {}, _cfg())
    assert a == b


def test_shadow_hook_inert_without_config_path(monkeypatch):
    from app import main
    g = main._run_shadow_build.__globals__
    monkeypatch.setitem(g, "CHALLENGER_CONFIG_PATH", "")
    # engine untouched: poison it so any DB access would blow up the test
    monkeypatch.setitem(g, "engine", None)
    asyncio.run(main._run_shadow_build())        # must return silently
    # lineage param (audit-3 fix #3) accepted and equally inert without config
    asyncio.run(main._run_shadow_build("11111111-1111-1111-1111-111111111111"))
