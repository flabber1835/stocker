"""A sweep leg must surface its per-session equity curve, not just a summary.

Until now `run_config_both_windows` discarded the SimResult and kept only
`.summary`, so a sweep persisted four numbers per window and the SHAPE of a run was
unrecoverable the moment it finished. The dashboard's live_stats is transient — it
is overwritten each poll and gone at completion.

The cost was concrete: an owner watched several candidates track SPY and then
collapse in the final month of period A, and there was no way to confirm or dismiss
it afterwards. A wind tunnel that decides what goes live should not return an exit
code and throw away the execution.

These tests cover the sweep-side contract (the curve comes back, correctly split by
phase, and never leaks into the JSONB stored on bt_sweep_results). The DB write
itself lives in main.py and is exercised against a real bt-postgres.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.sweep import SweepWindows, run_config_both_windows
from stock_strategy_shared.schemas.strategy import StrategyConfig

_REGIMES = {
    "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
    "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
    "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
    "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
}
_W = {"momentum": 0.9, "quality": 0.025, "value": 0.025, "growth": 0.025,
      "low_volatility": 0.025}


def _base_config() -> dict:
    return StrategyConfig(**{
        "strategy_id": "sweep_equity_test",
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
    }).model_dump(mode="json")


@pytest.fixture(scope="module")
def frames():
    days = pd.bdate_range("2024-01-02", periods=420)
    spec = {"AAA": 0.0004, "BBB": 0.0008, "CCC": 0.0012, "DDD": 0.0002,
            "EEE": 0.0010, "SPY": 0.0005}
    rows = []
    for t, drift in spec.items():
        px = 100.0
        for i, d in enumerate(days):
            px *= 1.0 + drift + 0.002 * np.sin(i / 7.0 + sum(map(ord, t)) % 10)
            rows.append({"ticker": t, "date": d, "open": px * 0.999, "close": px,
                         "adjusted_close": px, "volume": 1_000_000.0})
    prices = pd.DataFrame(rows)
    fnd = pd.DataFrame([
        {"ticker": t, "as_of_date": days[0], "pe_ratio": 15.0, "pb_ratio": 2.0,
         "roe": 0.15, "debt_to_equity": 0.5, "revenue_growth": 0.05,
         "eps_growth": 0.05} for t in spec if t != "SPY"])
    return prices, fnd, days


@pytest.fixture(scope="module")
def result(frames):
    prices, fnd, days = frames
    windows = SweepWindows(
        tune_start=days[-120].date(), tune_end=days[-60].date(),
        validate_start=days[-60].date(), validate_end=days[-1].date())
    return run_config_both_windows(
        prices, fnd, {}, _base_config(), {}, windows,
        sim_kwargs=dict(tx_cost_bps=0, fill_timing="close", rebalance_every=5))


def test_the_curve_comes_back_for_both_phases(result):
    assert result.get("error_message") is None, result.get("error_message")
    eq = result["equity_by_phase"]
    assert set(eq) == {"tune", "validate"}
    assert eq["tune"] and eq["validate"], "a phase returned an empty curve"


def test_the_fills_come_back_for_both_phases(result):
    tr = result["trades_by_phase"]
    assert set(tr) == {"tune", "validate"}
    assert tr["tune"], "no fills recorded for the tune window"


def test_fills_carry_the_reason(result):
    """`reason` is why this is worth storing: it names the MECHANISM that produced
    the fill (orphan exit, trailing stop, delist sweep, drift trim). Without it a
    wave of delist exits at delist_recovery_pct is indistinguishable from an
    ordinary drawdown in the equity curve."""
    t = result["trades_by_phase"]["tune"][0]
    assert {"date", "ticker", "action", "qty", "price", "tx_cost", "reason"} <= set(t)
    assert any(x.get("reason") for x in result["trades_by_phase"]["tune"])


def test_positions_come_back_for_both_phases(result):
    """What the book HELD, not only what it traded — the only way to see breadth
    and deployment over time. The 35-names-drifting-to-26 defect was invisible in
    both the summary and the trade log, and obvious here."""
    pos = result["positions_by_phase"]
    assert set(pos) == {"tune", "validate"}
    assert pos["tune"], "no positions recorded for the tune window"
    p = pos["tune"][0]
    assert {"date", "ticker", "qty", "weight", "market_value"} <= set(p)


def test_the_forest_map_rides_in_the_summary(result):
    """It reaches the evaluator through the existing `result` plumbing — no new
    packet section, no extra query. Small by construction: chapters and
    aggregates, never rows."""
    for key in ("in_sample", "out_sample"):
        fm = (result[key] or {}).get("forest_map")
        assert fm and "error" not in fm, fm
        assert fm["deployment"]["configured_cap"] == 3
        assert fm["n_chapters"] > 0


def test_rows_carry_what_the_diagnosis_needs(result):
    """book vs SPY on a date is the whole question — 'did we fall while the market
    held up, and when'."""
    row = result["equity_by_phase"]["tune"][0]
    assert {"date", "portfolio_value", "spy_value", "drawdown"} <= set(row)
    assert isinstance(row["portfolio_value"], (int, float))


def test_the_phases_cover_their_own_windows(result, frames):
    _p, _f, days = frames
    tune = [r["date"] for r in result["equity_by_phase"]["tune"]]
    val = [r["date"] for r in result["equity_by_phase"]["validate"]]
    assert max(tune) <= days[-60].date(), "tune curve ran past its window"
    assert min(val) >= days[-60].date(), "validate curve started before its window"
    assert tune == sorted(tune) and val == sorted(val)


def test_the_curve_is_not_stored_in_the_summary_jsonb(result):
    """It is popped by the caller before persistence. Serialising thousands of
    rows into bt_sweep_results' JSONB would make them unqueryable by date, which
    is the only way anyone wants to read them."""
    for key in ("in_sample", "out_sample"):
        for leaked in ("equity_by_phase", "trades_by_phase",
                       "positions_by_phase", "equity", "trades", "positions"):
            assert leaked not in (result[key] or {})


def test_an_errored_config_returns_no_curve():
    """A config that cannot be built must produce an error row, not a half-written
    curve that would look like a real (very short) run."""
    bad = run_config_both_windows(
        pd.DataFrame(), pd.DataFrame(), {}, _base_config(),
        {"portfolio_builder.max_positions": -1},
        SweepWindows(date(2024, 1, 2), date(2024, 3, 1),
                     date(2024, 3, 1), date(2024, 5, 1)),
        sim_kwargs=dict(tx_cost_bps=0, fill_timing="close", rebalance_every=5))
    assert bad.get("error_message")
    assert not bad.get("equity_by_phase")
    assert not bad.get("trades_by_phase")
    assert not bad.get("positions_by_phase")


def test_the_ranked_universe_comes_back(result):
    """The one thing a run's own trace cannot reconstruct.

    `target` holds only the survivors, so a name absent from it is
    indistinguishable from a name that was never ranked — which makes
    growth-capture, oracle recall and paired regret impossible after the fact.
    This is the record of what the model SAW.
    """
    rk = result["rankings_by_phase"]
    assert set(rk) == {"tune", "validate"}
    assert rk["tune"], "no ranked universe recorded for the tune window"
    r = rk["tune"][0]
    assert {"date", "ticker", "rank", "composite_score", "selected"} <= set(r)


def test_rankings_include_names_that_were_NOT_selected(result):
    """A rank dump of only the book would answer nothing — the passed-over names
    are the entire point."""
    rows = result["rankings_by_phase"]["tune"]
    assert any(not r["selected"] for r in rows), "only selected names recorded"
    assert any(r["selected"] for r in rows)


def test_the_row_cap_is_reported(result):
    """Without it, 'absent from the table' is ambiguous between 'ranked and
    passed over' and 'beyond the cap' — and every recall number computed off the
    table would be quietly wrong."""
    for key in ("in_sample", "out_sample"):
        assert (result[key] or {}).get("ranking_rank_cap")


def test_rankings_are_not_stored_in_the_summary_jsonb(result):
    """Same reason as the other row streams: thousands of rows in JSONB are
    unqueryable by date, which is the only way anyone wants to read them."""
    for key in ("in_sample", "out_sample"):
        for leaked in ("rankings_by_phase", "rankings"):
            assert leaked not in (result[key] or {})
