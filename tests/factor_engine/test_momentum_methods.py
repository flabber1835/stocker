"""Tests for the momentum-method variants: raw, risk_adjusted, residual,
residual_riskadj (services/pipeline/app/factors.compute_momentum)."""
import numpy as np
import pandas as pd
import pytest

from app.factors import compute_momentum, cross_section_percentile as cross_section_pct


def _series_from_returns(start: float, daily: list[float]) -> list[float]:
    px = [start]
    for r in daily:
        px.append(px[-1] * (1 + r))
    return px


def _pivot_from_returns(returns_by_ticker: dict[str, list[float]]) -> pd.DataFrame:
    """Build a date×ticker price pivot from per-ticker daily return lists (all equal length)."""
    n = len(next(iter(returns_by_ticker.values())))
    dates = pd.date_range("2020-01-01", periods=n + 1, freq="B")
    data = {t: _series_from_returns(100.0, r) for t, r in returns_by_ticker.items()}
    return pd.DataFrame(data, index=dates)


def test_raw_is_unchanged_default():
    """Default method='raw' equals the plain 12-1 price ratio."""
    rng = np.random.default_rng(0)
    rets = {t: list(rng.normal(0.0005, 0.012, 300)) for t in ("A", "B", "C")}
    pivot = _pivot_from_returns(rets)
    raw = compute_momentum(pivot, method="raw")
    # price_short/price_long - 1 over the 12-1 window
    expected = pivot.iloc[-22] / pivot.iloc[-253] - 1.0
    pd.testing.assert_series_equal(raw.sort_index(), expected.sort_index(), check_names=False)


def test_risk_adjusted_penalizes_high_vol_same_return():
    """Two names with the SAME 12-1 return but different vol: risk_adjusted ranks
    the calmer one higher; raw ranks them equal."""
    # CALM: steady small ups (tiny vol). WILD: same ~net drift but big swings.
    calm = [0.0045, 0.0035] * 130   # mean ~0.004, small but nonzero vol
    wild = [0.04, -0.032] * 130      # mean ~0.004, far higher vol
    pivot = _pivot_from_returns({"CALM": calm, "WILD": wild})
    raw = compute_momentum(pivot, method="raw")
    radj = compute_momentum(pivot, method="risk_adjusted")
    # Raw returns are similar in sign/magnitude; risk-adjust must rank CALM above WILD.
    assert radj["CALM"] > radj["WILD"]
    # And the risk-adjusted gap should exceed the raw gap (vol penalty bites WILD).
    assert (radj["CALM"] - radj["WILD"]) > (raw["CALM"] - raw["WILD"])


def test_residual_strips_common_market_move():
    """Two names = market + idiosyncratic. Residual momentum reflects the
    idiosyncratic part, not the shared market component."""
    rng = np.random.default_rng(3)
    mkt = rng.normal(0.0006, 0.01, 260)
    # WINNER has positive idiosyncratic drift; LOSER negative; both share the market.
    winner = list(mkt + 0.0015)
    loser = list(mkt - 0.0015)
    flat = list(mkt)  # pure market, ~zero idiosyncratic
    pivot = _pivot_from_returns({"WINNER": winner, "LOSER": loser, "FLAT": flat})
    resid = compute_momentum(pivot, method="residual")
    assert resid["WINNER"] > resid["FLAT"] > resid["LOSER"]


def test_methods_return_series_over_all_tickers():
    rng = np.random.default_rng(7)
    rets = {t: list(rng.normal(0.0004, 0.013, 300)) for t in ("A", "B", "C", "D")}
    pivot = _pivot_from_returns(rets)
    for m in ("raw", "risk_adjusted", "residual", "residual_riskadj"):
        s = compute_momentum(pivot, method=m)
        assert set(s.index) == {"A", "B", "C", "D"}
        assert not np.isinf(s.to_numpy()).any()


def test_insufficient_history_falls_back_gracefully():
    """Too few rows → empty (same as raw), regardless of method."""
    rng = np.random.default_rng(1)
    rets = {t: list(rng.normal(0, 0.01, 200)) for t in ("A", "B")}
    pivot = _pivot_from_returns(rets)
    assert compute_momentum(pivot, method="residual_riskadj").empty


def test_blend_windows_rank_average_of_horizons():
    """blend_long_windows blends 12-1 and 6-1: result is a rank in [0,1] over all
    tickers, finite, and reacts to a name that's strong in the recent 6-1 window."""
    rng = np.random.default_rng(9)
    # 320 returns so both 252 and 126 horizons have history.
    base = {t: list(rng.normal(0.0003, 0.012, 320)) for t in ("A", "B", "C", "D")}
    # RECENT: weak early, strong in the most recent 6 months (ex last month) → 6-1 lifts it.
    recent = [(-0.001) ] * 200 + [0.004] * 120
    base["RECENT"] = recent
    pivot = _pivot_from_returns(base)
    blended = compute_momentum(pivot, method="raw", blend_long_windows=[252, 126])
    assert set(blended.index) == {"A", "B", "C", "D", "RECENT"}
    assert not np.isinf(blended.to_numpy()).any()
    assert blended.min() >= 0.0 and blended.max() <= 1.0  # rank-averaged → [0,1]
    # The recent-strength name should out-rank on the blend vs the pure 12-1 horizon.
    single_12_1 = cross_section_pct(compute_momentum(pivot, method="raw", long_window=252))
    assert blended["RECENT"] >= single_12_1["RECENT"] - 1e-9


def test_blend_single_window_equals_single_horizon():
    """A one-element (or None) blend behaves exactly as single-horizon."""
    rng = np.random.default_rng(2)
    rets = {t: list(rng.normal(0.0004, 0.013, 300)) for t in ("A", "B", "C")}
    pivot = _pivot_from_returns(rets)
    single = compute_momentum(pivot, method="raw")
    one = compute_momentum(pivot, method="raw", blend_long_windows=[252])
    none = compute_momentum(pivot, method="raw", blend_long_windows=None)
    pd.testing.assert_series_equal(single.sort_index(), one.sort_index(), check_names=False)
    pd.testing.assert_series_equal(single.sort_index(), none.sort_index(), check_names=False)


def test_residual_riskadj_combines_both_effects():
    """residual_riskadj = residual / formation vol — finite, all tickers, and
    differs from plain residual when vols differ."""
    rng = np.random.default_rng(5)
    mkt = rng.normal(0.0005, 0.01, 260)
    a = list(mkt + rng.normal(0.001, 0.005, 260))   # higher idio vol
    b = list(mkt + rng.normal(0.001, 0.02, 260))    # much higher idio vol
    pivot = _pivot_from_returns({"A": a, "B": b})
    resid = compute_momentum(pivot, method="residual")
    rr = compute_momentum(pivot, method="residual_riskadj")
    assert set(rr.index) == {"A", "B"}
    assert not np.isinf(rr.to_numpy()).any()
    # The risk-adjusted ordering can differ from raw residual; at minimum the
    # transform is not the identity (vols differ between A and B).
    assert not np.allclose(resid.to_numpy(), rr.to_numpy())
