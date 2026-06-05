"""Tests for the gross-profitability quality factor (Novy-Marx).

compute_quality(use_gross_profitability=True) swaps the profitability leg from
ROE to gross_profit/total_assets, keeping inverse-leverage as the safety leg,
and falls back to ROE whenever the gross-profit inputs are missing.
"""
import numpy as np
import pandas as pd
import pytest

from app.factors import compute_quality, compute_all_factors
from stock_strategy_shared.schemas.strategy import FactorEngineConfig


def _fund(rows: dict) -> pd.DataFrame:
    """rows: {ticker: {col: val}} → fundamentals DataFrame with a ticker column."""
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "ticker"
    return df.reset_index()


class TestComputeQualityGrossProfitability:
    def test_flag_off_is_legacy_roe_behaviour(self):
        """Default (flag off) must equal the historical ROE/leverage composite —
        even when gross_profit/total_assets columns are present."""
        fund = _fund({
            "A": {"roe": 0.30, "debt_to_equity": 0.5, "gross_profit": 1e9, "total_assets": 1e11},
            "B": {"roe": 0.10, "debt_to_equity": 1.5, "gross_profit": 9e9, "total_assets": 1e10},
            "C": {"roe": 0.20, "debt_to_equity": 1.0, "gross_profit": 5e9, "total_assets": 5e10},
        })
        without_cols = _fund({
            "A": {"roe": 0.30, "debt_to_equity": 0.5},
            "B": {"roe": 0.10, "debt_to_equity": 1.5},
            "C": {"roe": 0.20, "debt_to_equity": 1.0},
        })
        q_with = compute_quality(fund, use_gross_profitability=False)
        q_without = compute_quality(without_cols, use_gross_profitability=False)
        pd.testing.assert_series_equal(q_with, q_without)

    def test_flag_on_uses_gross_profits_to_assets(self):
        """With the flag on, quality ranking follows gross_profit/total_assets,
        not ROE. Construct a case where the two disagree."""
        # B has the WORST ROE but by far the best gross-profits-to-assets (0.9).
        # Leverage held equal so the profitability leg drives the ordering.
        fund = _fund({
            "A": {"roe": 0.40, "debt_to_equity": 1.0, "gross_profit": 1e9,  "total_assets": 1e11},  # GP/A=0.01
            "B": {"roe": 0.05, "debt_to_equity": 1.0, "gross_profit": 9e9,  "total_assets": 1e10},  # GP/A=0.90
            "C": {"roe": 0.20, "debt_to_equity": 1.0, "gross_profit": 5e9,  "total_assets": 5e10},  # GP/A=0.10
        })
        q_roe = compute_quality(fund, use_gross_profitability=False)
        q_gp = compute_quality(fund, use_gross_profitability=True)

        # ROE ranks A > C > B; gross-profitability ranks B > C > A.
        assert q_roe["A"] > q_roe["B"]
        assert q_gp["B"] > q_gp["A"]
        assert q_gp["B"] > q_gp["C"] > q_gp["A"]

    def test_flag_on_missing_columns_falls_back_to_roe(self):
        """Flag on but no gross_profit/total_assets columns → identical to ROE."""
        fund = _fund({
            "A": {"roe": 0.30, "debt_to_equity": 0.5},
            "B": {"roe": 0.10, "debt_to_equity": 1.5},
            "C": {"roe": 0.20, "debt_to_equity": 1.0},
        })
        q_on = compute_quality(fund, use_gross_profitability=True)
        q_off = compute_quality(fund, use_gross_profitability=False)
        pd.testing.assert_series_equal(q_on, q_off)

    def test_flag_on_all_nan_gross_profit_falls_back_to_roe(self):
        """Columns present but entirely NaN (pre-backfill) → fall back to ROE."""
        fund = _fund({
            "A": {"roe": 0.30, "debt_to_equity": 0.5, "gross_profit": np.nan, "total_assets": np.nan},
            "B": {"roe": 0.10, "debt_to_equity": 1.5, "gross_profit": np.nan, "total_assets": np.nan},
            "C": {"roe": 0.20, "debt_to_equity": 1.0, "gross_profit": np.nan, "total_assets": np.nan},
        })
        q_on = compute_quality(fund, use_gross_profitability=True)
        fund_roe = fund.drop(columns=["gross_profit", "total_assets"])
        q_off = compute_quality(fund_roe, use_gross_profitability=False)
        pd.testing.assert_series_equal(q_on, q_off)

    def test_nonpositive_total_assets_is_treated_as_missing(self):
        """total_assets <= 0 is corrupt → that ticker's gross-profitability is
        NaN; with another valid name present the factor still computes."""
        fund = _fund({
            "A": {"roe": 0.30, "debt_to_equity": 1.0, "gross_profit": 5e9, "total_assets": 0.0},
            "B": {"roe": 0.10, "debt_to_equity": 1.0, "gross_profit": 5e9, "total_assets": 5e10},
            "C": {"roe": 0.20, "debt_to_equity": 1.0, "gross_profit": 5e9, "total_assets": 1e11},
        })
        q = compute_quality(fund, use_gross_profitability=True)
        # A's profitability leg is NaN (0 assets), but it still has the leverage
        # leg via neutral-fill, so quality is not NaN.
        assert not np.isnan(q["A"])
        # B (GP/A=0.10) ranks above C (GP/A=0.05) on profitability.
        assert q["B"] > q["C"]

    def test_partial_gross_profit_data_does_not_fall_back(self):
        """If SOME tickers have valid gross-profitability, use it (don't fall
        back to ROE just because others are missing)."""
        fund = _fund({
            "A": {"roe": 0.40, "debt_to_equity": 1.0, "gross_profit": 1e9, "total_assets": 1e11},  # GP/A=0.01
            "B": {"roe": 0.05, "debt_to_equity": 1.0, "gross_profit": 9e9, "total_assets": 1e10},  # GP/A=0.90
            "C": {"roe": 0.20, "debt_to_equity": 1.0, "gross_profit": np.nan, "total_assets": np.nan},
        })
        q_gp = compute_quality(fund, use_gross_profitability=True)
        # B's huge gross-profitability must beat A despite A's higher ROE → proves
        # we used GP, not the ROE fallback.
        assert q_gp["B"] > q_gp["A"]

    def test_safety_leg_still_present(self):
        """Inverse-leverage still contributes: with equal profitability, the
        lower-leverage name ranks higher."""
        fund = _fund({
            "A": {"roe": 0.20, "debt_to_equity": 0.2, "gross_profit": 5e9, "total_assets": 5e10},
            "B": {"roe": 0.20, "debt_to_equity": 3.0, "gross_profit": 5e9, "total_assets": 5e10},
        })
        q = compute_quality(fund, use_gross_profitability=True)
        assert q["A"] > q["B"]  # same GP/A, A less levered → safer → higher quality


class TestComputeAllFactorsGrossProfitability:
    def test_config_flag_threads_through(self):
        tickers = [f"T{i:02d}" for i in range(8)]
        rng = np.random.default_rng(3)
        dates = pd.date_range("2020-01-01", periods=300, freq="B")
        rows = []
        for t in tickers:
            prices = rng.uniform(50, 300) * np.cumprod(1 + rng.normal(0.0003, 0.015, 300))
            for d, p in zip(dates, prices):
                rows.append({"ticker": t, "date": d.date(), "close": p,
                             "adjusted_close": p, "volume": int(1e6)})
        prices_long = pd.DataFrame(rows)
        fund = pd.DataFrame({
            "ticker": tickers,
            "pe_ratio": rng.uniform(8, 45, 8), "pb_ratio": rng.uniform(1, 9, 8),
            "roe": rng.uniform(0.05, 0.4, 8), "debt_to_equity": rng.uniform(0.1, 2.5, 8),
            "revenue_growth": rng.uniform(-0.05, 0.3, 8), "eps_growth": rng.uniform(-0.1, 0.4, 8),
            "gross_profit": rng.uniform(1e8, 9e10, 8), "total_assets": rng.uniform(5e9, 5e11, 8),
        })
        off = compute_all_factors(
            prices_long.copy(), fund.copy(),
            cfg=FactorEngineConfig(quality_use_gross_profitability=False),
        ).set_index("ticker")
        on = compute_all_factors(
            prices_long.copy(), fund.copy(),
            cfg=FactorEngineConfig(quality_use_gross_profitability=True),
        ).set_index("ticker")
        # Quality differs; the non-fundamental factors are untouched.
        assert not np.allclose(off["quality"].values, on["quality"].values)
        pd.testing.assert_series_equal(off["momentum"], on["momentum"], check_names=False)
        pd.testing.assert_series_equal(off["value"], on["value"], check_names=False)
