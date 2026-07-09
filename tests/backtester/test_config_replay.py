"""G1 config-replay unit tests — pure, no DB. Verify the composer re-ranks +
re-selects under a candidate config using the vendored chain math, with no
look-ahead, and produces portfolio_runs run_backtest can score."""
import pandas as pd
import pytest

from app.config_replay import (
    factor_df_from_rows,
    confirmed_regime_for_date,
    build_target_for_date,
    replay_history,
)
from app.simulate import run_backtest
from stock_strategy_shared.schemas.strategy import StrategyConfig

_REGIMES = {
    "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
    "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
    "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
    "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
}


# momentum-dominant weights (rows only carry momentum; the rest renormalize out).
_W = {"momentum": 0.9, "quality": 0.025, "value": 0.025, "growth": 0.025, "low_volatility": 0.025}


def _cfg(**pb_over) -> StrategyConfig:
    pb = {
        "method": "greedy_score_per_port_vol", "max_positions": 3,
        "max_position_weight": 0.6, "max_sector_weight": 1.0, "weighting": "equal_weight",
        "candidate_count": 10, "covariance_window_days": 30,
        "min_covariance_observations": 20, "covariance_shrinkage": 0.2,
        "cluster_correlation_threshold": 0.99, "max_cluster_weight": 1.0,
        "max_tickers_per_cluster": None,
    }
    pb.update(pb_over)
    return StrategyConfig(**{
        "strategy_id": "cfgreplay_test",
        "min_non_null_factors": 1,
        "universe": {"source": "av_listing", "min_price": 1.0, "min_avg_dollar_volume_20d": 0.0},
        "regime_detection": {"slow_sma": 20, "vol_window": 5, "vol_threshold": 0.5,
                             "confirmation_days": 1, "regimes": _REGIMES},
        "factor_weights": {
            "bull_calm": _W, "bull_stress": _W, "bear_stress": _W, "bear_calm": _W,
        },
        "regime_weighting_enabled": False,
        "static_factor_weights": _W,
        "portfolio_builder": pb,
        "vetter": {"candidate_count": 10},
    })


def _prices(tickers, dates, base=100.0, step=1.0):
    """Deterministic rising series per ticker (distinct slopes so covariance is
    well-defined and tickers are rankable)."""
    rows = []
    for i, t in enumerate(tickers):
        px = base + i * 5
        for d in dates:
            px += step + i * 0.1
            rows.append({"ticker": t, "date": d, "adjusted_close": px,
                         "close": px, "volume": 1_000_000})
    return pd.DataFrame(rows)


def test_factor_df_from_rows_prefers_jsonb_then_columns():
    rows = [
        {"ticker": "AAA", "scores": {"momentum": 0.9, "quality": 0.1}},
        {"ticker": "BBB", "scores": None, "momentum": 0.4, "quality": None},
    ]
    df = factor_df_from_rows(rows).set_index("ticker")
    assert df.loc["AAA", "momentum"] == pytest.approx(0.9)
    assert df.loc["BBB", "momentum"] == pytest.approx(0.4)
    assert pd.isna(df.loc["BBB", "quality"])          # null column → NaN (renormalized out)


def test_confirmed_regime_falls_back_on_short_history():
    cfg = _cfg()
    spy = pd.DataFrame({"date": pd.to_datetime(["2026-01-02", "2026-01-03"]),
                        "adjusted_close": [400.0, 401.0]})   # < slow_sma rows
    raw, confirmed = confirmed_regime_for_date(spy, cfg, [], None)
    assert raw in _REGIMES and confirmed in _REGIMES        # no crash, valid regime


def test_build_target_respects_max_positions_and_do_not_buy():
    cfg = _cfg(max_positions=2, do_not_buy=["CCC"])
    dates = pd.bdate_range("2026-01-02", periods=25)
    tickers = ["AAA", "BBB", "CCC", "DDD", "SPY"]
    prices = _prices(tickers, dates)
    # momentum: CCC highest (would be picked but for do_not_buy), then DDD, BBB, AAA
    rows = [
        {"ticker": "AAA", "scores": {"momentum": 0.1}},
        {"ticker": "BBB", "scores": {"momentum": 0.5}},
        {"ticker": "CCC", "scores": {"momentum": 0.9}},
        {"ticker": "DDD", "scores": {"momentum": 0.7}},
    ]
    fdf = factor_df_from_rows(rows)
    holdings = build_target_for_date(fdf, prices, cfg, "bull_calm", sector_map={})
    picked = {h["ticker"] for h in holdings}
    assert "CCC" not in picked                              # do_not_buy honored
    assert len(holdings) <= 2                               # max_positions cap
    assert sum(h["weight"] for h in holdings) == pytest.approx(1.0, abs=1e-6)


def test_cash_reserve_delevers_below_full_investment():
    cfg = _cfg(cash_reserve=0.1)
    dates = pd.bdate_range("2026-01-02", periods=25)
    prices = _prices(["AAA", "BBB", "DDD", "SPY"], dates)
    rows = [{"ticker": t, "scores": {"momentum": v}}
            for t, v in [("AAA", 0.3), ("BBB", 0.6), ("DDD", 0.9)]]
    holdings = build_target_for_date(factor_df_from_rows(rows), prices, cfg, "bull_calm", {})
    assert sum(h["weight"] for h in holdings) == pytest.approx(0.9, abs=1e-6)


def test_replay_history_end_to_end_feeds_backtest():
    cfg = _cfg()
    dates = pd.bdate_range("2026-01-02", periods=40)
    tickers = ["AAA", "BBB", "DDD", "EEE", "SPY"]
    prices = _prices(tickers, dates)
    # Two rebalance dates late enough that each has a full covariance window behind it.
    d1, d2 = str(dates[25].date()), str(dates[30].date())
    fr = {
        d1: [{"ticker": t, "scores": {"momentum": v}}
             for t, v in [("AAA", 0.2), ("BBB", 0.5), ("DDD", 0.9), ("EEE", 0.7)]],
        d2: [{"ticker": t, "scores": {"momentum": v}}
             for t, v in [("AAA", 0.9), ("BBB", 0.6), ("DDD", 0.3), ("EEE", 0.4)]],
    }
    runs, caveats = replay_history(fr, prices, cfg, sector_map={})
    assert len(runs) == 2
    assert runs[0]["portfolio_date"] == d1 and runs[0]["holdings"]
    assert any("vetter" in c for c in caveats)              # documented boundary surfaced
    # The synthetic book must be scoreable by the de-biased simulator.
    result = run_backtest(runs, prices, tx_cost_bps=0)
    assert result["summary"]                                # non-empty summary
    assert result["periods"]


def test_replay_skips_dates_with_no_feasible_portfolio():
    cfg = _cfg()
    dates = pd.bdate_range("2026-01-02", periods=40)
    prices = _prices(["AAA", "SPY"], dates)                 # only 1 non-SPY name
    fr = {str(dates[30].date()): [{"ticker": "AAA", "scores": {"momentum": 0.9}}]}
    runs, _ = replay_history(fr, prices, cfg, sector_map={})
    assert runs == []                                       # < 2 selectable → skipped, no crash
