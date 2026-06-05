"""Tests for industry (sector) neutralization of factors.

Covers the pure helper `neutralized_percentile` and its wiring through
`compute_all_factors` — including the asymmetry rule (value/quality neutralize,
momentum/low_vol/liquidity never do) and the universe-wide fallbacks that keep
coverage from shrinking.
"""
import numpy as np
import pandas as pd
import pytest

from app.factors import (
    neutralized_percentile,
    cross_section_percentile,
    compute_all_factors,
)
from stock_strategy_shared.schemas.strategy import FactorEngineConfig


# ── neutralized_percentile ────────────────────────────────────────────────────

class TestNeutralizedPercentile:
    def test_none_sector_map_is_universe_wide(self):
        """sector_map=None must be byte-identical to cross_section_percentile."""
        s = pd.Series({"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0})
        got = neutralized_percentile(s, None)
        exp = cross_section_percentile(s)
        pd.testing.assert_series_equal(got, exp)

    def test_within_sector_ranking_fixes_structural_bias(self):
        """The 'banks flood the top' case: a sector with structurally high raw
        values should NOT sweep the top once neutralized — the best name in each
        sector lands at the top of its own group."""
        # Banks all higher than all tech on the raw scale.
        s = pd.Series({
            "BANK1": 10.0, "BANK2": 11.0, "BANK3": 12.0,
            "TECH1": 1.0,  "TECH2": 2.0,  "TECH3": 3.0,
        })
        sectors = {
            "BANK1": "Financials", "BANK2": "Financials", "BANK3": "Financials",
            "TECH1": "Tech", "TECH2": "Tech", "TECH3": "Tech",
        }
        out = neutralized_percentile(s, sectors, min_group_size=3)

        # Universe-wide, every bank would outrank every tech. Neutralized, the
        # best tech ties the best bank at the top of the [0,1] scale.
        assert out["TECH3"] == pytest.approx(1.0)
        assert out["BANK3"] == pytest.approx(1.0)
        assert out["TECH1"] == pytest.approx(out["BANK1"])  # both bottom-of-sector
        # Within-sector ordering preserved.
        assert out["BANK3"] > out["BANK2"] > out["BANK1"]
        assert out["TECH3"] > out["TECH2"] > out["TECH1"]

    def test_null_sector_falls_back_to_universe(self):
        s = pd.Series({"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "E": 5.0, "F": 6.0})
        # A..E are one big sector; F has no sector → universe-wide fallback.
        sectors = {t: "Big" for t in ["A", "B", "C", "D", "E"]}  # F absent → None
        out = neutralized_percentile(s, sectors, min_group_size=5)
        # F ranked against the FULL universe (6 names, highest) → 1.0
        assert out["F"] == pytest.approx(1.0)
        # A..E ranked within their 5-name sector.
        assert out["E"] == pytest.approx(1.0)
        assert out["A"] == pytest.approx(0.2)

    def test_small_sector_falls_back_to_universe(self):
        """A sector with fewer than min_group_size valid members is not
        neutralized; those tickers rank universe-wide instead."""
        s = pd.Series({"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "E": 5.0, "F": 6.0})
        sectors = {
            "A": "Big", "B": "Big", "C": "Big", "D": "Big",   # 4 members
            "E": "Tiny", "F": "Tiny",                          # 2 members < 3
        }
        out = neutralized_percentile(s, sectors, min_group_size=3)
        # Big (4 members) neutralized: D top of its group.
        assert out["D"] == pytest.approx(1.0)
        # Tiny (2 < 3) falls back to universe-wide: E and F are the 5th/6th
        # largest of all six → 5/6 and 1.0.
        glob = cross_section_percentile(s)
        assert out["E"] == pytest.approx(glob["E"])
        assert out["F"] == pytest.approx(glob["F"])

    def test_all_sectors_too_small_equals_universe_wide(self):
        """If no sector reaches min_group_size, the result is exactly the
        universe-wide ranking."""
        s = pd.Series({"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0})
        sectors = {"A": "X", "B": "X", "C": "Y", "D": "Y"}  # 2 each
        out = neutralized_percentile(s, sectors, min_group_size=5)
        pd.testing.assert_series_equal(out, cross_section_percentile(s))

    def test_nan_values_stay_nan_and_dont_count_toward_group_size(self):
        s = pd.Series({"A": 1.0, "B": 2.0, "C": np.nan, "D": 4.0})
        sectors = {t: "Big" for t in ["A", "B", "C", "D"]}
        # Only 3 non-NaN values; with min_group_size=4 the sector is too thin.
        out = neutralized_percentile(s, sectors, min_group_size=4)
        assert np.isnan(out["C"])
        # 3 valid < 4 → fallback to universe-wide (which also leaves C NaN).
        glob = cross_section_percentile(s)
        assert out["A"] == pytest.approx(glob["A"])

    def test_output_in_unit_interval(self):
        rng = np.random.default_rng(7)
        idx = [f"T{i}" for i in range(60)]
        s = pd.Series(rng.normal(size=60), index=idx)
        sectors = {t: f"S{i % 4}" for i, t in enumerate(idx)}  # 15 per sector
        out = neutralized_percentile(s, sectors, min_group_size=10)
        valid = out.dropna()
        assert ((valid > 0) & (valid <= 1.0)).all()

    def test_deterministic(self):
        s = pd.Series({"A": 3.0, "B": 1.0, "C": 2.0, "D": 5.0, "E": 4.0, "F": 6.0})
        sectors = {t: "Big" for t in s.index}
        a = neutralized_percentile(s, sectors, min_group_size=3)
        b = neutralized_percentile(s, sectors, min_group_size=3)
        pd.testing.assert_series_equal(a, b)


# ── compute_all_factors wiring & asymmetry ────────────────────────────────────

def _pivot(tickers, n=300, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {t: rng.uniform(50, 300) * np.cumprod(1 + rng.normal(0.0003, 0.015, n)) for t in tickers},
        index=dates,
    )


def _prices_long(tickers, n=300, seed=0):
    pivot = _pivot(tickers, n, seed)
    rows = []
    for t in tickers:
        for d, p in pivot[t].items():
            rows.append({"ticker": t, "date": d.date(), "close": p,
                         "adjusted_close": p, "volume": int(1e6)})
    return pd.DataFrame(rows)


def _fund(tickers, seed=1):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "ticker": tickers,
        "pe_ratio": rng.uniform(8, 45, len(tickers)),
        "pb_ratio": rng.uniform(1, 9, len(tickers)),
        "roe": rng.uniform(0.05, 0.4, len(tickers)),
        "debt_to_equity": rng.uniform(0.1, 2.5, len(tickers)),
        "revenue_growth": rng.uniform(-0.05, 0.3, len(tickers)),
        "eps_growth": rng.uniform(-0.1, 0.4, len(tickers)),
    })


class TestComputeAllFactorsNeutralization:
    def setup_method(self):
        self.tickers = [f"T{i:02d}" for i in range(12)]
        # Two sectors of 6 names each.
        self.sector_map = {t: ("Financials" if i < 6 else "Tech")
                           for i, t in enumerate(self.tickers)}
        self.prices = _prices_long(self.tickers)
        self.fund = _fund(self.tickers)

    def _run(self, neutral, sector_map=None):
        cfg = FactorEngineConfig(industry_neutral_factors=neutral, min_sector_group_size=6)
        return compute_all_factors(
            self.prices.copy(), self.fund.copy(), cfg=cfg,
            sector_map=sector_map if sector_map is not None else self.sector_map,
        ).set_index("ticker")

    def test_momentum_unchanged_when_value_quality_neutralized(self):
        """Asymmetry rule: neutralizing value/quality must leave momentum,
        low_volatility, and liquidity byte-identical (they are never neutralized)."""
        base = self._run([])
        neut = self._run(["value", "quality"])
        for col in ["momentum", "low_volatility", "liquidity"]:
            pd.testing.assert_series_equal(base[col], neut[col], check_names=False)

    def test_value_changes_when_neutralized(self):
        base = self._run([])
        neut = self._run(["value"])
        # Within-sector percentile differs numerically from universe-wide.
        assert not np.allclose(base["value"].values, neut["value"].values)
        # quality untouched because only 'value' was neutralized.
        pd.testing.assert_series_equal(base["quality"], neut["quality"], check_names=False)

    def test_quality_changes_when_neutralized(self):
        base = self._run([])
        neut = self._run(["quality"])
        assert not np.allclose(base["quality"].values, neut["quality"].values)
        pd.testing.assert_series_equal(base["value"], neut["value"], check_names=False)

    def test_none_sector_map_falls_back_to_universe(self):
        """Neutral factors requested but no sector_map → universe-wide (identical
        to neutral=[]). Must not raise."""
        base = self._run([])
        none_map = self._run(["value", "quality"], sector_map={})  # empty → all fallback
        # Empty sector map: every ticker falls back, so value/quality match base.
        pd.testing.assert_series_equal(base["value"], none_map["value"], check_names=False)
        pd.testing.assert_series_equal(base["quality"], none_map["quality"], check_names=False)

    def test_neutralized_factor_still_in_unit_interval(self):
        neut = self._run(["value", "quality"])
        for col in ["value", "quality"]:
            v = neut[col].dropna()
            assert ((v > 0) & (v <= 1.0)).all()

    def test_single_rank_shape_preserved(self):
        """The output still has exactly one row per ticker and the six factor
        columns — neutralization does not fragment the ranking."""
        neut = self._run(["value", "quality"])
        assert len(neut) == len(self.tickers)
        for col in ["momentum", "quality", "value", "growth", "low_volatility", "liquidity"]:
            assert col in neut.columns
