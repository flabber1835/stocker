"""The portfolio high-water mark must survive a trailing stop.

The defect: `for t, peak in plan.stopped.items()` rebound the module-level `peak`
— the portfolio high-water mark — to a stopped TICKER's price. The next
`peak = max(peak, equity)` then compared a share price against a portfolio value,
so the watermark collapsed to the current equity and every later drawdown was
measured from a fresh baseline. A run reported -2.2% max drawdown while its worst
SINGLE DAY was -5.2%.

Nothing else broke, which is what made it survive: `peak` feeds only the
`drawdown` field, so returns, CAGR and Sharpe were all correct and the numbers
looked plausible together. Only the arithmetic relationship below is violated.

That relationship is the test, and it holds for ANY equity path:

    max_drawdown <= worst single-day return

because after a day that falls x%, drawdown from the peak is at least x% (the
peak is at least the prior day's equity). It needs no fixture tuning, no
knowledge of the strategy, and it is exactly what the shadowing broke.
"""
from __future__ import annotations

import pytest


def _max_drawdown(values: list[float]) -> float:
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return worst


def _worst_day(values: list[float]) -> float:
    return min((b / a - 1.0 for a, b in zip(values, values[1:])), default=0.0)


class TestTheInvariant:
    @pytest.mark.parametrize("path", [
        [100.0, 110.0, 104.0, 120.0, 113.0, 130.0],          # rising, small dips
        [100.0, 95.0, 90.0, 85.0, 80.0],                     # monotone fall
        [100.0, 150.0, 75.0, 160.0],                         # one violent day
        [100.0] * 10,                                        # flat
        [100.0, 101.0, 100.5, 102.0, 101.0, 103.0],          # grind up
    ])
    def test_max_drawdown_is_never_shallower_than_the_worst_day(self, path):
        assert _max_drawdown(path) <= _worst_day(path) + 1e-12

    def test_a_reset_watermark_violates_it(self):
        """The shadowing, in miniature.

        The clobber happened BEFORE `peak = max(peak, equity)` on the very session
        a stop fired — which is typically a falling one. So that day's drawdown
        was recorded as 0 no matter how far equity fell, and the invariant breaks:
        the reported maximum ends up SHALLOWER than a single day's decline.

        Resetting on a quiet day merely under-reports; resetting on the worst day
        is what produces an impossible number, so that is the case pinned here.
        """
        path = [100.0, 130.0, 123.0, 116.0, 110.0]
        worst_i = min(range(1, len(path)), key=lambda i: path[i] / path[i - 1])
        honest = _max_drawdown(path)

        peak, worst = path[0], 0.0
        for i, v in enumerate(path):
            if i == worst_i:
                peak = v            # a ticker price landing in the portfolio peak
            peak = max(peak, v)
            worst = min(worst, v / peak - 1.0)

        assert honest < worst, "the reset must under-report, or this proves nothing"
        assert worst > _worst_day(path) + 1e-12, (
            "and it under-reports past the invariant — reporting a maximum "
            "drawdown shallower than one day's fall, which is impossible")


class TestTheSimulatorHonoursIt:
    """Against the real sim, with the trailing stop ON — the configuration that
    triggered the bug. A stop must fire for this to be meaningful, so that is
    asserted rather than assumed."""

    def test_sim_equity_satisfies_the_invariant_with_stops_firing(self):
        import numpy as np
        import pandas as pd

        from app.sim import SimParams, run_simulation
        from stock_strategy_shared.schemas.strategy import StrategyConfig

        regimes = {
            "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
            "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
            "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
            "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
        }
        w = {"momentum": 1.0, "quality": 0.0, "value": 0.0, "growth": 0.0,
             "low_volatility": 0.0, "liquidity": 0.0}
        cfg = StrategyConfig(**{
            "strategy_id": "dd_watermark_test",
            "min_non_null_factors": 1, "required_factors": [],
            "universe": {"source": "av_listing", "min_price": 1.0,
                         "min_avg_dollar_volume_20d": 0.0},
            "regime_detection": {"slow_sma": 20, "vol_window": 5,
                                 "vol_threshold": 0.8, "confirmation_days": 1,
                                 "regimes": regimes},
            "factor_weights": {r: w for r in regimes},
            "regime_weighting_enabled": False, "static_factor_weights": w,
            "portfolio_builder": {
                "method": "greedy_score_per_port_vol", "max_positions": 4,
                "max_position_weight": 0.5, "max_sector_weight": 1.0,
                "weighting": "equal_weight", "candidate_count": 12,
                "covariance_window_days": 40, "min_covariance_observations": 20,
                "covariance_shrinkage": 0.2, "cluster_correlation_threshold": 0.99,
                "max_cluster_weight": 1.0, "max_tickers_per_cluster": None,
                "cash_reserve": 0.0, "vol_target_enabled": False,
            },
            "vetter": {"candidate_count": 12},
            # ON, and wide enough that only a real collapse trips it.
            "trailing_stop": {"enabled": True, "stop_pct": 0.20,
                              "arm_after_sessions": 2, "max_stops_per_run": 5},
        })

        # run_simulation needs FACTOR_LOOKBACK_DAYS (420 CALENDAR days) of price
        # history BEFORE `start`, so the sim window is the tail of a longer frame.
        # The book rallies through the warm-up, then the non-SPY names collapse
        # inside the window — which is what puts a stopped ticker's price into the
        # loop variable that used to shadow `peak`.
        days = pd.bdate_range("2023-01-02", periods=520)
        crash_from = 400
        rows = []
        for k, t in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "SPY"]):
            px = 100.0
            for i, d in enumerate(days):
                if i < crash_from:
                    drift = 0.004
                else:
                    drift = -0.012 if t != "SPY" else 0.0002
                px *= 1.0 + drift + 0.001 * np.sin(i / 6.0 + k)
                rows.append({"ticker": t, "date": d, "open": px * 0.999,
                             "close": px, "adjusted_close": px,
                             "volume": 1_000_000.0})
        prices = pd.DataFrame(rows)
        fnd = pd.DataFrame([
            {"ticker": t, "as_of_date": days[0], "pe_ratio": 15.0, "pb_ratio": 2.0,
             "roe": 0.15, "debt_to_equity": 0.5, "revenue_growth": 0.05,
             "eps_growth": 0.05}
            for t in ("AAA", "BBB", "CCC", "DDD", "EEE")])

        res = run_simulation(
            prices, fnd, {}, cfg,
            SimParams(start=days[crash_from - 20].date(), end=days[-1].date(),
                      tx_cost_bps=0, fill_timing="close",
                      rebalance_every=5))

        assert res.summary.get("n_stop_exits", 0) > 0, (
            "no stop fired — this fixture cannot exercise the shadowing bug")

        vals = [r["portfolio_value"] for r in res.equity]
        assert len(vals) > 2
        assert res.summary["max_drawdown"] <= _worst_day(vals) + 1e-6, (
            f"max_drawdown {res.summary['max_drawdown']} is shallower than the "
            f"worst single day {_worst_day(vals):.4f} — the portfolio high-water "
            f"mark was reset (a stopped ticker's price shadowing `peak`)")
        assert res.summary["max_drawdown"] == pytest.approx(_max_drawdown(vals),
                                                            abs=1e-4)
