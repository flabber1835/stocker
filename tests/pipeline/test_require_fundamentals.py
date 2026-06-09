"""Tests for the require_fundamentals universe filter.

ETFs / closed-end funds (SOXX, SNXX, QQQ, IWM, …) file no fundamentals, so they
were leaking to the TOP of the speculative ranking — its required_factors are
price/volume-only ([momentum, liquidity]), which a fundamentals-less ETF satisfies.
`require_fundamentals: true` drops them from the rankable universe BEFORE factor
computation; the core strategy leaves it False (it drops them implicitly via
required_factors=quality, which is null for a fund).
"""
import os

import numpy as np
import pandas as pd
import yaml

from app.factors import drop_fundamentalless, compute_all_factors
from stock_strategy_shared.schemas.strategy import StrategyConfig, UniverseConfig

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _load(fname):
    return StrategyConfig(**yaml.safe_load(open(os.path.join(_ROOT, "strategies", fname))))


def _prices(tickers, days=300):
    rows = []
    base = pd.Timestamp("2025-01-01")
    for t in tickers:
        for i in range(days):
            rows.append({"ticker": t, "date": base + pd.Timedelta(days=i),
                         "adjusted_close": 10.0 + i * 0.05, "close": 10.0 + i * 0.05,
                         "volume": 5_000_000})
    return pd.DataFrame(rows)


# ── drop_fundamentalless (pure helper) ────────────────────────────────────────

def test_drop_fundamentalless_removes_etfs_when_required():
    prices = _prices(["AAPL", "SOXX", "MSFT", "SNXX"], days=5)
    out, dropped = drop_fundamentalless(prices, {"AAPL", "MSFT"}, require_fundamentals=True)
    assert dropped == 2
    assert set(out["ticker"].unique()) == {"AAPL", "MSFT"}


def test_drop_fundamentalless_noop_when_flag_false():
    prices = _prices(["AAPL", "SOXX"], days=5)
    out, dropped = drop_fundamentalless(prices, {"AAPL"}, require_fundamentals=False)
    assert dropped == 0
    assert set(out["ticker"].unique()) == {"AAPL", "SOXX"}


def test_drop_fundamentalless_noop_when_nothing_to_drop():
    prices = _prices(["AAPL", "MSFT"], days=5)
    out, dropped = drop_fundamentalless(prices, {"AAPL", "MSFT"}, require_fundamentals=True)
    assert dropped == 0
    assert set(out["ticker"].unique()) == {"AAPL", "MSFT"}


def test_drop_fundamentalless_empty_prices():
    out, dropped = drop_fundamentalless(pd.DataFrame(columns=["ticker"]), set(), True)
    assert dropped == 0
    assert out.empty


# ── config wiring ─────────────────────────────────────────────────────────────

def test_core_does_not_require_fundamentals():
    assert _load("quality_core_v1.yaml").universe.require_fundamentals is False


def test_speculative_requires_fundamentals():
    assert _load("speculative_growth_v1.yaml").universe.require_fundamentals is True


def test_universe_config_default_is_false():
    assert UniverseConfig().require_fundamentals is False


# ── behavioral: an ETF can no longer reach factor_scores ──────────────────────

def test_etf_absent_from_factors_after_filter():
    # An ETF with strong price/volume signals but no fundamentals row.
    prices = _prices(["AAPL", "MSFT", "NVDA", "SOXX"], days=300)
    fundamentals = pd.DataFrame([
        {"ticker": t, "pe_ratio": 20.0, "pb_ratio": 3.0, "roe": 0.2, "debt_to_equity": 0.5,
         "revenue_growth": 0.1, "eps_growth": 0.1, "gross_profit": 1e9, "total_assets": 5e9,
         "shares_outstanding": 1e9, "shares_outstanding_prior": 1e9, "market_cap": 2e10}
        for t in ["AAPL", "MSFT", "NVDA"]  # SOXX deliberately absent
    ])
    fund_tickers = set(fundamentals["ticker"])

    filtered, dropped = drop_fundamentalless(prices, fund_tickers, require_fundamentals=True)
    assert dropped == 1

    factors = compute_all_factors(prices_long=filtered, fundamentals=fundamentals,
                                  cfg=_load("speculative_growth_v1.yaml").factor_engine)
    assert "SOXX" not in set(factors["ticker"])
    assert {"AAPL", "MSFT", "NVDA"} <= set(factors["ticker"])
