"""Unit tests for the speculative-style factors (small_cap, volume_surge, near_high,
high_volatility) added for the speculative_growth strategy.

These are optional factors (default weight 0) so they never affect the core model;
these tests pin their raw-signal semantics + the compute_all_factors wiring.
"""
import os

import numpy as np
import pandas as pd
import yaml

from app.factors import (compute_small_cap, compute_volume_surge, compute_near_high,
                         compute_all_factors)
from app.rank import rank_universe
from stock_strategy_shared.schemas.strategy import StrategyConfig

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _load(fname):
    return StrategyConfig(**yaml.safe_load(open(os.path.join(_ROOT, "strategies", fname))))


def _aslike_and_boring():
    """Two ranked rows: a pre-profit 'ASTS-like' story stock (null quality/value/growth,
    strong price/volume signals) and a boring quality/value name."""
    return pd.DataFrame([
        {"ticker": "ASTSLIKE", "momentum": 0.95, "low_volatility": 0.05, "high_volatility": 0.95,
         "near_high": 0.95, "volume_surge": 0.90, "liquidity": 0.60, "small_cap": 0.90,
         "quality": np.nan, "value": np.nan, "growth": np.nan, "issuance": np.nan},
        {"ticker": "BORING", "momentum": 0.30, "low_volatility": 0.90, "high_volatility": 0.10,
         "near_high": 0.30, "volume_surge": 0.40, "liquidity": 0.60, "small_cap": 0.20,
         "quality": 0.90, "value": 0.90, "growth": 0.50, "issuance": 0.50},
    ])


# ── compute_small_cap (raw = -market_cap → smaller ranks higher) ───────────────

def test_small_cap_prefers_smaller_market_cap():
    f = pd.DataFrame({"ticker": ["BIG", "SMALL", "MID"],
                      "market_cap": [1e12, 1e9, 1e10]})
    s = compute_small_cap(f)
    # raw = -market_cap, so SMALL (smallest cap) has the largest raw value
    assert s["SMALL"] > s["MID"] > s["BIG"]


def test_small_cap_nan_on_missing_or_nonpositive():
    f = pd.DataFrame({"ticker": ["A", "B"], "market_cap": [0.0, 5e9]})
    s = compute_small_cap(f)
    assert np.isnan(s["A"]) and not np.isnan(s["B"])


def test_small_cap_empty_when_column_absent():
    f = pd.DataFrame({"ticker": ["A"], "roe": [0.1]})
    assert compute_small_cap(f).empty


# ── compute_volume_surge (recent vs baseline volume) ───────────────────────────

def _vol_rows(ticker, vols, start="2025-01-01"):
    dates = pd.date_range(start, periods=len(vols))
    return pd.DataFrame({"ticker": ticker, "date": dates,
                         "close": 10.0, "volume": vols})


def test_volume_surge_detects_recent_spike():
    # 60 flat days then a 5-day spike → surge ratio > 1
    vols = [1_000_000] * 60 + [5_000_000] * 5
    s = compute_volume_surge(_vol_rows("SURGE", vols), short_window=5, long_window=60)
    assert s["SURGE"] > 1.5


def test_volume_surge_flat_is_about_one():
    s = compute_volume_surge(_vol_rows("FLAT", [1_000_000] * 70), short_window=5, long_window=60)
    assert abs(s["FLAT"] - 1.0) < 0.05


def test_volume_surge_nan_with_insufficient_history():
    s = compute_volume_surge(_vol_rows("SHORT", [1_000_000] * 30), short_window=5, long_window=60)
    assert np.isnan(s["SHORT"])


# ── compute_near_high (close / trailing high) ──────────────────────────────────

def test_near_high_at_high_is_one():
    idx = pd.date_range("2025-01-01", periods=10)
    # ATH rises to and ends at the max; BELOW peaked then fell to half
    px = pd.DataFrame({
        "ATH":   np.linspace(10, 20, 10),          # ends at its own high
        "BELOW": [10, 12, 20, 18, 16, 14, 12, 11, 10, 10],  # ends well below its 20 high
    }, index=idx)
    s = compute_near_high(px, window=252)
    assert abs(s["ATH"] - 1.0) < 1e-9
    assert s["BELOW"] < 0.6        # 10 / 20


# ── compute_all_factors wiring (new columns + high_vol = 1 - low_vol) ──────────

def _make_panel(n_days=140, tickers=("AAA", "BBB", "CCC")):
    rng = np.random.default_rng(0)
    dates = pd.date_range("2025-01-01", periods=n_days)
    rows = []
    for i, t in enumerate(tickers):
        px = 100.0 * (1 + pd.Series(rng.normal(0.0005, 0.01 * (i + 1), n_days))).cumprod()
        for d, p in zip(dates, px):
            rows.append({"ticker": t, "date": d, "adjusted_close": round(p, 4),
                         "close": round(p, 4), "volume": 1_000_000 + i * 100_000})
    prices = pd.DataFrame(rows)
    funds = pd.DataFrame({"ticker": list(tickers),
                          "market_cap": [1e12, 1e10, 1e9],
                          "roe": [0.1, 0.2, 0.05], "pe_ratio": [15, 30, 50],
                          "pb_ratio": [2, 5, 8], "revenue_growth": [0.1, 0.5, 0.9],
                          "eps_growth": [0.1, 0.3, 0.2]})
    return prices, funds


def test_compute_all_factors_emits_speculative_columns():
    prices, funds = _make_panel()
    out = compute_all_factors(prices, funds).set_index("ticker")
    for col in ("small_cap", "volume_surge", "near_high", "high_volatility"):
        assert col in out.columns, f"missing {col}"
    # high_volatility is the inverse percentile of low_volatility
    for t in out.index:
        assert abs(out.loc[t, "high_volatility"] - (1.0 - out.loc[t, "low_volatility"])) < 1e-9
    # smaller market cap (CCC=1e9) should out-rank larger (AAA=1e12) on small_cap
    assert out.loc["CCC", "small_cap"] > out.loc["AAA", "small_cap"]


# ── behavioral contrast: spec config surfaces what core screens out ────────────

def test_speculative_config_ranks_preprofit_story_stock_high():
    spec = _load("speculative_growth_v1.yaml")
    out = rank_universe(_aslike_and_boring(), "bull_calm", spec)
    ranked = list(out["ticker"])
    assert "ASTSLIKE" in ranked, "pre-profit story stock must be RANKED (not dropped) under spec"
    assert ranked[0] == "ASTSLIKE", "spec weights momentum/high-vol/breakout — story stock should top it"


def test_core_config_drops_preprofit_story_stock():
    core = _load("quality_core_v1.yaml")
    out = rank_universe(_aslike_and_boring(), "bull_calm", core)
    ranked = list(out["ticker"])
    # core requires quality/value/growth — the ASTS-like row has them null → dropped
    assert "ASTSLIKE" not in ranked
    assert "BORING" in ranked
