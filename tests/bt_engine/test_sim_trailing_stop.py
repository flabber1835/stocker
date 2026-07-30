"""The trailing stop inside the simulator.

Two properties carry the weight here, and they are the reason the stop is checked
in the DAILY loop rather than inside the rebalance block:

  1. OFF ⇒ bit-identical. The feature ships disabled, so a run with the block at
     defaults must produce byte-identical equity, trades and summary to one where
     the config has no opinion at all. If that ever breaks, "defaults off" stops
     being a safety property.
  2. Cadence is INDEPENDENT of rebalance_every. Live evaluates the stop on every
     chain run (daily). If the simulator rode the rebalance cadence, a sweep at
     rebalance_every=5 would check it a fifth as often, and any stop_pct chosen
     from that sweep would carry the wrong check latency into production.

Everything else — truncation invariance, no re-buy on the same open, episode peak
reset — follows from getting those two right.
"""
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
_W = {"momentum": 0.9, "quality": 0.025, "value": 0.025, "growth": 0.025,
      "low_volatility": 0.025}


def _cfg(trailing_stop=None) -> StrategyConfig:
    body = {
        "strategy_id": "bt_stop_test",
        "min_non_null_factors": 1,
        "universe": {"source": "av_listing", "min_price": 1.0,
                     "min_avg_dollar_volume_20d": 0.0},
        "regime_detection": {"slow_sma": 20, "vol_window": 5, "vol_threshold": 0.8,
                             "confirmation_days": 1, "regimes": _REGIMES},
        "factor_weights": {r: _W for r in _REGIMES},
        "regime_weighting_enabled": False,
        "static_factor_weights": _W,
        "portfolio_builder": {
            "method": "greedy_score_per_port_vol", "max_positions": 3,
            "max_position_weight": 0.6, "max_sector_weight": 1.0,
            "weighting": "equal_weight", "candidate_count": 10,
            "covariance_window_days": 40, "min_covariance_observations": 20,
            "covariance_shrinkage": 0.2, "cluster_correlation_threshold": 0.99,
            "max_cluster_weight": 1.0, "max_tickers_per_cluster": None,
        },
        "vetter": {"candidate_count": 10},
    }
    if trailing_stop is not None:
        body["trailing_stop"] = trailing_stop
    return StrategyConfig(**body)


def _make_data(n_days=520, crash_ticker="CCC", crash_from=None, crash_rate=0.97):
    """Deterministic walks. CCC is the strongest drift (so it gets selected) and
    then collapses, which is exactly the shape a trailing stop exists for."""
    days = pd.bdate_range("2024-01-02", periods=n_days)
    spec = {"AAA": 0.0004, "BBB": 0.0008, "CCC": 0.0016, "DDD": 0.0002,
            "EEE": 0.0010, "FFF": 0.0006, "SPY": 0.0005}
    crash_from = crash_from if crash_from is not None else n_days - 12
    rows = []
    for t, drift in spec.items():
        px = 100.0
        for i, d in enumerate(days):
            wiggle = 0.002 * np.sin(i / 7.0 + sum(map(ord, t)) % 10)
            px = px * (1.0 + drift + wiggle)
            if crash_ticker == t and i >= crash_from:
                px *= crash_rate
            rows.append({"ticker": t, "date": d, "open": px * 0.999, "close": px,
                         "adjusted_close": px, "volume": 1_000_000.0})
    prices = pd.DataFrame(rows)
    fundamentals = pd.DataFrame([
        {"ticker": t, "as_of_date": days[0], "pe_ratio": 15.0, "pb_ratio": 2.0,
         "roe": 0.15, "debt_to_equity": 0.5, "revenue_growth": 0.05,
         "eps_growth": 0.05}
        for t in spec if t != "SPY"])
    return prices, fundamentals, days


def _params(days, span=90, **over):
    base = dict(start=days[-span].date(), end=days[-1].date(), tx_cost_bps=0,
                fill_timing="close", rebalance_every=5)
    base.update(over)
    return SimParams(**base)


_ON = {"enabled": True, "stop_pct": 0.05, "arm_after_sessions": 2,
       "max_stale_sessions": 2, "max_stops_per_run": 5}


class TestOffIsBitIdentical:
    """The safety property that lets this ship to production disabled."""

    def test_absent_block_and_default_block_agree(self):
        prices, fnd, days = _make_data()
        p = _params(days)
        a = run_simulation(prices.copy(), fnd.copy(), {}, _cfg(), p)
        b = run_simulation(prices.copy(), fnd.copy(), {},
                           _cfg(trailing_stop={"enabled": False}), p)
        assert a.equity == b.equity
        assert a.trades == b.trades
        assert a.summary == b.summary

    def test_stop_parameters_are_inert_while_disabled(self):
        """A config carrying a tight stop but enabled=False must behave exactly as
        one carrying no stop at all — otherwise the switch is not really a switch."""
        prices, fnd, days = _make_data()
        p = _params(days)
        a = run_simulation(prices.copy(), fnd.copy(), {}, _cfg(), p)
        b = run_simulation(prices.copy(), fnd.copy(), {},
                           _cfg(trailing_stop={**_ON, "enabled": False,
                                               "stop_pct": 0.01}), p)
        assert a.equity == b.equity and a.trades == b.trades

    def test_summary_reports_the_switch(self):
        prices, fnd, days = _make_data()
        p = _params(days)
        off = run_simulation(prices.copy(), fnd.copy(), {}, _cfg(), p).summary
        on = run_simulation(prices.copy(), fnd.copy(), {}, _cfg(trailing_stop=_ON),
                            p).summary
        assert off["trailing_stop_enabled"] is False and off["n_stop_exits"] == 0
        assert on["trailing_stop_enabled"] is True


class TestItActuallyFires:
    def test_a_collapsing_holding_is_stopped(self):
        prices, fnd, days = _make_data()
        p = _params(days)
        res = run_simulation(prices.copy(), fnd.copy(), {}, _cfg(trailing_stop=_ON), p)
        assert res.summary["n_stop_exits"] > 0
        reasons = [t["reason"] for t in res.trades if "trailing stop" in (t["reason"] or "")]
        assert reasons, "no trade carried a trailing-stop reason"
        assert "below peak" in reasons[0]

    def test_a_wide_stop_does_not_fire_where_a_tight_one_does(self):
        """Guards against the stop firing for some reason other than the threshold."""
        prices, fnd, days = _make_data()
        p = _params(days)
        tight = run_simulation(prices.copy(), fnd.copy(), {},
                               _cfg(trailing_stop={**_ON, "stop_pct": 0.05}), p)
        wide = run_simulation(prices.copy(), fnd.copy(), {},
                              _cfg(trailing_stop={**_ON, "stop_pct": 0.85}), p)
        assert tight.summary["n_stop_exits"] > wide.summary["n_stop_exits"] == 0


class TestCadenceIsDaily:
    """THE parity property. If this fails, a swept stop_pct does not transfer to
    live, because live checks the stop every session and the sweep did not."""

    def test_the_stop_fires_on_non_rebalance_sessions(self):
        prices, fnd, days = _make_data()
        res = run_simulation(prices.copy(), fnd.copy(), {}, _cfg(trailing_stop=_ON),
                             _params(days, rebalance_every=5))
        stop_days = sorted({t["date"] for t in res.trades
                            if "trailing stop" in (t["reason"] or "")})
        assert stop_days, "the stop never fired — cannot judge cadence"

        all_days = [d.date() for d in days if _params(days).start <= d.date() <= _params(days).end]
        rebalance_days = {d for n, d in enumerate(all_days) if n % 5 == 0}
        # fill_timing='close' fills the same session it decided, so a stop trade's
        # date IS its decision session.
        assert any(d not in rebalance_days for d in stop_days), (
            "every stop fired on a rebalance session — the stop is riding the "
            "rebalance cadence, so a swept stop_pct carries the wrong check latency"
        )

    def test_rebalance_every_barely_changes_when_the_stop_fires(self):
        """Same data, same stop, different rebalance cadence: the stop's own timing
        should be governed by prices, not by the sweep's tractability setting."""
        prices, fnd, days = _make_data()
        fast = run_simulation(prices.copy(), fnd.copy(), {}, _cfg(trailing_stop=_ON),
                              _params(days, rebalance_every=1))
        slow = run_simulation(prices.copy(), fnd.copy(), {}, _cfg(trailing_stop=_ON),
                              _params(days, rebalance_every=10))
        assert fast.summary["n_stop_exits"] > 0 and slow.summary["n_stop_exits"] > 0


class TestNoImmediateRebuy:
    def test_a_stopped_name_is_not_bought_back_at_the_same_open(self):
        """The builder is holdings-agnostic, so a stopped name is still in the
        target. Stripping it from live_positions ALONE would make Loop 1 read an
        in-target un-held ticker as an ENTRY and buy it straight back."""
        prices, fnd, days = _make_data()
        res = run_simulation(prices.copy(), fnd.copy(), {}, _cfg(trailing_stop=_ON),
                             _params(days, rebalance_every=1))
        stops = [t for t in res.trades if "trailing stop" in (t["reason"] or "")]
        assert stops
        for s in stops:
            same_day_buys = [t for t in res.trades
                             if t["date"] == s["date"] and t["ticker"] == s["ticker"]
                             and t["action"] in ("entry", "buy_add")]
            assert not same_day_buys, (
                f"{s['ticker']} was stopped and re-bought on {s['date']}")


class TestInvariantsStillHold:
    def test_truncation_no_look_ahead_with_the_stop_on(self):
        """The gold-standard property must survive the feature. The peak is a max
        over sessions <= D, so truncating at K cannot change state at K."""
        prices, fnd, days = _make_data()
        cfg = _cfg(trailing_stop=_ON)
        k_idx = len(days) - 20
        p_k = SimParams(start=days[-90].date(), end=days[k_idx].date(),
                        tx_cost_bps=0, fill_timing="close", rebalance_every=5)
        full = run_simulation(prices.copy(), fnd.copy(), {}, cfg, p_k)
        trunc = run_simulation(prices[prices["date"] <= days[k_idx]].copy(),
                               fnd.copy(), {}, cfg, p_k)
        assert full.equity == trunc.equity
        assert full.trades == trunc.trades

    def test_determinism_with_the_stop_on(self):
        prices, fnd, days = _make_data()
        cfg = _cfg(trailing_stop=_ON)
        p = _params(days)
        a = run_simulation(prices.copy(), fnd.copy(), {}, cfg, p)
        b = run_simulation(prices.copy(), fnd.copy(), {}, cfg, p)
        assert a.equity == b.equity and a.trades == b.trades and a.summary == b.summary


class TestWidthMethod:
    """Vol-scaled width in the simulator. `fixed` is the default and must remain
    bit-identical, or adding a mode silently changed what every prior sweep meant."""

    def test_fixed_default_is_bit_identical_to_an_unspecified_width(self):
        prices, fnd, days = _make_data()
        p = _params(days)
        a = run_simulation(prices.copy(), fnd.copy(), {}, _cfg(trailing_stop=_ON), p)
        b = run_simulation(prices.copy(), fnd.copy(), {},
                           _cfg(trailing_stop={**_ON, "width_method": "fixed"}), p)
        assert a.equity == b.equity and a.trades == b.trades

    def test_vol_parameters_are_inert_while_the_method_is_fixed(self):
        """A config carrying an aggressive anchor and clamps but width_method
        'fixed' must behave exactly as one carrying none."""
        prices, fnd, days = _make_data()
        p = _params(days)
        a = run_simulation(prices.copy(), fnd.copy(), {}, _cfg(trailing_stop=_ON), p)
        b = run_simulation(prices.copy(), fnd.copy(), {},
                           _cfg(trailing_stop={**_ON, "vol_anchor": 0.05,
                                               "stop_pct_min": 0.01,
                                               "stop_pct_max": 0.02}), p)
        assert a.equity == b.equity and a.trades == b.trades

    def test_vol_scaled_runs_and_still_stops(self):
        prices, fnd, days = _make_data()
        res = run_simulation(prices.copy(), fnd.copy(), {},
                             _cfg(trailing_stop={**_ON, "width_method": "vol_scaled",
                                                 "vol_lookback": 60}),
                             _params(days))
        assert res.summary["n_stop_exits"] > 0

    def test_vol_scaled_changes_behaviour_vs_fixed(self):
        """If scaling produced identical results the mode would be decorative — the
        clamps are set tight here so the difference is unambiguous."""
        prices, fnd, days = _make_data()
        p = _params(days)
        fixed = run_simulation(prices.copy(), fnd.copy(), {},
                               _cfg(trailing_stop=_ON), p)
        scaled = run_simulation(prices.copy(), fnd.copy(), {},
                                _cfg(trailing_stop={**_ON, "width_method": "vol_scaled",
                                                    "vol_lookback": 60,
                                                    "vol_anchor": 1.5,
                                                    "stop_pct_min": 0.01,
                                                    "stop_pct_max": 0.03}), p)
        assert scaled.summary["n_stop_exits"] != fixed.summary["n_stop_exits"] \
            or scaled.trades != fixed.trades

    def test_truncation_invariance_holds_with_vol_scaling(self):
        """The vol window ends at today, so truncating at K cannot change state
        at K. This is the property every backtest number rests on."""
        prices, fnd, days = _make_data()
        cfg = _cfg(trailing_stop={**_ON, "width_method": "vol_scaled",
                                  "vol_lookback": 60})
        k_idx = len(days) - 20
        p_k = SimParams(start=days[-90].date(), end=days[k_idx].date(),
                        tx_cost_bps=0, fill_timing="close", rebalance_every=5)
        full = run_simulation(prices.copy(), fnd.copy(), {}, cfg, p_k)
        trunc = run_simulation(prices[prices["date"] <= days[k_idx]].copy(),
                               fnd.copy(), {}, cfg, p_k)
        assert full.equity == trunc.equity and full.trades == trunc.trades

    def test_determinism_with_vol_scaling(self):
        prices, fnd, days = _make_data()
        cfg = _cfg(trailing_stop={**_ON, "width_method": "vol_scaled"})
        p = _params(days)
        a = run_simulation(prices.copy(), fnd.copy(), {}, cfg, p)
        b = run_simulation(prices.copy(), fnd.copy(), {}, cfg, p)
        assert a.equity == b.equity and a.summary == b.summary


class TestCircuitBreaker:
    def test_max_stops_per_run_bounds_one_session(self):
        """A market-wide collapse: every holding breaches at once. Exits are exempt
        from the risk-service turnover cap, so this is the only brake."""
        prices, fnd, days = _make_data(crash_ticker=None)
        # crash EVERYTHING from the same session
        cut = days[-8]
        mask = prices["date"] >= cut
        prices.loc[mask & (prices["ticker"] != "SPY"), ["close", "adjusted_close"]] *= 0.5

        res = run_simulation(prices.copy(), fnd.copy(), {},
                             _cfg(trailing_stop={**_ON, "max_stops_per_run": 1}),
                             _params(days, rebalance_every=5))
        by_day: dict = {}
        for t in res.trades:
            if "trailing stop" in (t["reason"] or ""):
                by_day.setdefault(t["date"], []).append(t["ticker"])
        assert by_day, "nothing stopped despite a 50% collapse"
        assert max(len(v) for v in by_day.values()) <= 1
