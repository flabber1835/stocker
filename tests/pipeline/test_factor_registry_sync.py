"""P3: the FACTOR_REGISTRY, what compute_all_factors actually produces, and the
persisted legacy columns must stay in lockstep. A registry-only factor (declared but
never assigned in compute_all_factors) would silently persist as an all-NaN column;
this fails CI instead.
"""
import os
import sys

import numpy as np
import pandas as pd

from app.factors import compute_all_factors
from stock_strategy_shared.factor_registry import FACTOR_NAMES
from stock_strategy_shared.schemas.strategy import FactorEngineConfig

# The persisted per-factor columns (migration 0030).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "db", "migrations", "versions"))
import importlib
_m0030 = importlib.import_module("0030_factor_scores_jsonb")
_LEGACY = _m0030._LEGACY_FACTOR_COLUMNS


def test_registry_matches_persisted_columns():
    assert set(FACTOR_NAMES) == set(_LEGACY), (
        "FACTOR_REGISTRY drifted from the persisted factor_scores columns "
        f"(0030 _LEGACY_FACTOR_COLUMNS): {set(FACTOR_NAMES) ^ set(_LEGACY)}"
    )


def _synth_prices(tickers, days):
    rows = []
    base = pd.Timestamp("2026-01-02")
    for ti, tk in enumerate(tickers):
        for d in range(days):
            px = 100.0 + ti * 5 + d * 0.3 + (d % 5)   # deterministic, trending
            rows.append({"ticker": tk, "date": base + pd.Timedelta(days=d),
                         "adjusted_close": px, "close": px, "volume": 1_000_000 + d * 10})
    return pd.DataFrame(rows)


def _synth_fundamentals(tickers):
    return pd.DataFrame([{
        "ticker": tk, "pe_ratio": 15.0 + i, "pb_ratio": 2.0 + i * 0.1, "roe": 0.15,
        "debt_to_equity": 0.5, "revenue_growth": 0.1, "eps_growth": 0.12,
        "gross_profit": 1e9, "total_assets": 5e9, "shares_outstanding": 1e8,
        "shares_outstanding_prior": 1.01e8, "market_cap": 1e10 + i * 1e9,
    } for i, tk in enumerate(tickers)])


def test_compute_all_factors_produces_every_registry_factor():
    tickers = [f"T{i}" for i in range(8)]
    cfg = FactorEngineConfig()   # real windows (momentum_long >= 126); columns must exist
    prices = _synth_prices(tickers, days=300)
    funds = _synth_fundamentals(tickers)
    out = compute_all_factors(prices, funds, cfg=cfg)
    missing = set(FACTOR_NAMES) - set(out.columns)
    assert not missing, (
        f"compute_all_factors did not produce these registry factors (would persist "
        f"as silent all-NaN columns): {missing}"
    )
