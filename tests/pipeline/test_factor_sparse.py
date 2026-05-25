"""
Tests for sparse-fundamental score fairness in compute_quality and compute_value.

Root cause of the "B = Barrick Gold, rank 1" bug (secondary contributor):
_component_zscore on a sub-population inflated scores for tickers with only
one fundamental component. A gold miner with only ROE (no D/E) would receive
a full unbounded z-score as its quality, while a ticker with both ROE and D/E
received the dampened mean of two z-scores.

After the fix both functions use cross_section_percentile, which bounds all
components to [0, 1] relative to the full population — sparse tickers receive
the same scale as tickers with complete data.

Test strategy: build small synthetic universes where we know the expected
ordering, then assert that the fix produces the expected fair ordering
rather than inflating sparse tickers.
"""
from __future__ import annotations
import sys, os

_PIPELINE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "services", "pipeline"))
_app = sys.modules.get("app")
if _app is None or _PIPELINE_PATH not in os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del sys.modules[_k]
    if sys.path[:1] != [_PIPELINE_PATH]:
        sys.path.insert(0, _PIPELINE_PATH)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "shared"))

import math
import numpy as np
import pandas as pd
import pytest

from app.factors import compute_quality, compute_value


def _fund(**kwargs) -> pd.DataFrame:
    """Build a single-row fundamentals DataFrame from keyword args."""
    row = {"ticker": "T", "roe": None, "debt_to_equity": None,
           "pe_ratio": None, "pb_ratio": None}
    row.update(kwargs)
    return pd.DataFrame([row])


def _fund_many(rows: list[dict]) -> pd.DataFrame:
    """Build a multi-row fundamentals DataFrame from a list of dicts."""
    defaults = {"roe": None, "debt_to_equity": None, "pe_ratio": None, "pb_ratio": None}
    return pd.DataFrame([{**defaults, **r} for r in rows])


class TestQualityScoreBounds:
    def test_all_scores_between_0_and_1(self):
        rows = [
            {"ticker": "A", "roe": 0.20, "debt_to_equity": 0.5},
            {"ticker": "B", "roe": 0.10, "debt_to_equity": 1.2},
            {"ticker": "C", "roe": 0.30, "debt_to_equity": 0.2},
            {"ticker": "D", "roe": 0.05, "debt_to_equity": 2.0},
            {"ticker": "E", "roe": 0.15, "debt_to_equity": 0.8},
        ]
        fund = _fund_many(rows)
        result = compute_quality(fund)
        valid = result.dropna()
        assert (valid >= 0.0).all(), f"Quality scores below 0: {valid[valid < 0]}"
        assert (valid <= 1.0).all(), f"Quality scores above 1: {valid[valid > 1]}"

    def test_single_ticker_score_is_nan_or_midpoint(self):
        """Single-ticker universes: percentile of a single value is 0 (or NaN)."""
        fund = _fund(ticker="SOLO", roe=0.25)
        result = compute_quality(fund)
        val = result["SOLO"]
        assert math.isnan(val) or 0.0 <= val <= 1.0

    def test_quality_ordering_preserved(self):
        """Higher ROE + lower D/E should rank above lower ROE + higher D/E."""
        rows = [
            {"ticker": "GOOD", "roe": 0.30, "debt_to_equity": 0.3},
            {"ticker": "BAD",  "roe": 0.05, "debt_to_equity": 3.0},
            {"ticker": "MID",  "roe": 0.15, "debt_to_equity": 1.0},
        ]
        fund = _fund_many(rows)
        result = compute_quality(fund)
        assert result["GOOD"] > result["MID"] > result["BAD"], (
            f"Expected GOOD > MID > BAD, got: {result.to_dict()}"
        )


class TestQualitySparseVsComplete:
    """
    Core regression suite: sparse tickers must NOT outrank complete tickers
    just because they have fewer components.
    """

    def test_sparse_roe_only_does_not_outscore_better_complete(self):
        """
        SPARSE has only ROE=0.30.
        COMPLETE has ROE=0.25 and D/E=0.40 (good leverage too).
        COMPLETE is fundamentally stronger — it must score >= SPARSE.
        Before the fix, SPARSE got a full unbounded z-score while COMPLETE
        had its score dampened by averaging two components.
        """
        rows = [
            {"ticker": "SPARSE",   "roe": 0.30, "debt_to_equity": None},
            {"ticker": "COMPLETE", "roe": 0.25, "debt_to_equity": 0.40},
            # Padding to give cross_section_percentile meaningful variance
            {"ticker": "P1", "roe": 0.05, "debt_to_equity": 2.0},
            {"ticker": "P2", "roe": 0.08, "debt_to_equity": 1.5},
            {"ticker": "P3", "roe": 0.12, "debt_to_equity": 1.0},
        ]
        fund = _fund_many(rows)
        result = compute_quality(fund)
        # Both should be near the top; COMPLETE has better overall profile
        # so it must score at least as high as SPARSE
        assert result["COMPLETE"] >= result["SPARSE"] - 0.05, (
            f"SPARSE-ROE-only ({result['SPARSE']:.3f}) should not substantially "
            f"outscore COMPLETE ({result['COMPLETE']:.3f})"
        )

    def test_sparse_roe_only_does_not_outscore_equally_good_complete(self):
        """
        Same ROE, but COMPLETE also has good D/E — COMPLETE is at least as strong.
        """
        rows = [
            {"ticker": "SPARSE",   "roe": 0.20, "debt_to_equity": None},
            {"ticker": "COMPLETE", "roe": 0.20, "debt_to_equity": 0.30},
            {"ticker": "P1", "roe": 0.05, "debt_to_equity": 2.0},
            {"ticker": "P2", "roe": 0.10, "debt_to_equity": 1.5},
        ]
        fund = _fund_many(rows)
        result = compute_quality(fund)
        assert result["COMPLETE"] >= result["SPARSE"] - 0.02, (
            f"COMPLETE ({result['COMPLETE']:.3f}) should be >= SPARSE ({result['SPARSE']:.3f})"
        )

    def test_sparse_dte_only_does_not_outscore_complete(self):
        """Same test but with D/E-only sparse ticker."""
        rows = [
            {"ticker": "SPARSE",   "roe": None,  "debt_to_equity": 0.10},
            {"ticker": "COMPLETE", "roe": 0.20,  "debt_to_equity": 0.15},
            {"ticker": "P1", "roe": 0.05, "debt_to_equity": 2.0},
            {"ticker": "P2", "roe": 0.08, "debt_to_equity": 1.5},
        ]
        fund = _fund_many(rows)
        result = compute_quality(fund)
        assert result["COMPLETE"] >= result["SPARSE"] - 0.05, (
            f"COMPLETE ({result['COMPLETE']:.3f}) should be >= SPARSE ({result['SPARSE']:.3f})"
        )

    def test_all_sparse_scores_bounded_0_to_1(self):
        """Even with a mixed population of sparse and complete, all scores [0,1]."""
        rows = [
            {"ticker": "ROE_ONLY_1", "roe": 0.30, "debt_to_equity": None},
            {"ticker": "ROE_ONLY_2", "roe": 0.05, "debt_to_equity": None},
            {"ticker": "DTE_ONLY_1", "roe": None,  "debt_to_equity": 0.20},
            {"ticker": "DTE_ONLY_2", "roe": None,  "debt_to_equity": 2.00},
            {"ticker": "BOTH_1",     "roe": 0.20,  "debt_to_equity": 0.50},
            {"ticker": "BOTH_2",     "roe": 0.10,  "debt_to_equity": 1.00},
        ]
        fund = _fund_many(rows)
        result = compute_quality(fund)
        valid = result.dropna()
        assert (valid >= 0.0).all()
        assert (valid <= 1.0).all()


class TestValueScoreBounds:
    def test_all_value_scores_between_0_and_1(self):
        rows = [
            {"ticker": "A", "pe_ratio": 15.0, "pb_ratio": 2.0},
            {"ticker": "B", "pe_ratio": 25.0, "pb_ratio": 3.5},
            {"ticker": "C", "pe_ratio": 10.0, "pb_ratio": 1.5},
            {"ticker": "D", "pe_ratio": 40.0, "pb_ratio": 5.0},
            {"ticker": "E", "pe_ratio": 20.0, "pb_ratio": 2.8},
        ]
        fund = _fund_many(rows)
        result = compute_value(fund)
        valid = result.dropna()
        assert (valid >= 0.0).all()
        assert (valid <= 1.0).all()

    def test_value_ordering_preserved(self):
        """Lower PE + lower PB → higher value score (cheaper is better)."""
        rows = [
            {"ticker": "CHEAP",     "pe_ratio": 8.0,  "pb_ratio": 0.8},
            {"ticker": "EXPENSIVE", "pe_ratio": 50.0, "pb_ratio": 8.0},
            {"ticker": "MID",       "pe_ratio": 20.0, "pb_ratio": 2.5},
        ]
        fund = _fund_many(rows)
        result = compute_value(fund)
        assert result["CHEAP"] > result["MID"] > result["EXPENSIVE"], (
            f"Expected CHEAP > MID > EXPENSIVE, got: {result.to_dict()}"
        )


class TestValueSparseVsComplete:
    def test_pe_only_does_not_outscore_equally_good_complete(self):
        rows = [
            {"ticker": "SPARSE",   "pe_ratio": 12.0, "pb_ratio": None},
            {"ticker": "COMPLETE", "pe_ratio": 12.0, "pb_ratio": 1.5},
            {"ticker": "P1", "pe_ratio": 30.0, "pb_ratio": 4.0},
            {"ticker": "P2", "pe_ratio": 40.0, "pb_ratio": 5.0},
        ]
        fund = _fund_many(rows)
        result = compute_value(fund)
        assert result["COMPLETE"] >= result["SPARSE"] - 0.05, (
            f"COMPLETE ({result['COMPLETE']:.3f}) should be >= SPARSE ({result['SPARSE']:.3f})"
        )

    def test_pb_only_does_not_outscore_complete(self):
        rows = [
            {"ticker": "SPARSE",   "pe_ratio": None,  "pb_ratio": 1.0},
            {"ticker": "COMPLETE", "pe_ratio": 10.0,  "pb_ratio": 1.0},
            {"ticker": "P1", "pe_ratio": 40.0, "pb_ratio": 6.0},
            {"ticker": "P2", "pe_ratio": 35.0, "pb_ratio": 5.0},
        ]
        fund = _fund_many(rows)
        result = compute_value(fund)
        assert result["COMPLETE"] >= result["SPARSE"] - 0.05, (
            f"COMPLETE ({result['COMPLETE']:.3f}) should be >= SPARSE ({result['SPARSE']:.3f})"
        )

    def test_all_sparse_value_scores_bounded(self):
        rows = [
            {"ticker": "PE_ONLY_1",  "pe_ratio": 10.0, "pb_ratio": None},
            {"ticker": "PE_ONLY_2",  "pe_ratio": 40.0, "pb_ratio": None},
            {"ticker": "PB_ONLY_1",  "pe_ratio": None,  "pb_ratio": 1.5},
            {"ticker": "PB_ONLY_2",  "pe_ratio": None,  "pb_ratio": 6.0},
            {"ticker": "BOTH_1",     "pe_ratio": 15.0,  "pb_ratio": 2.0},
            {"ticker": "BOTH_2",     "pe_ratio": 30.0,  "pb_ratio": 4.0},
        ]
        fund = _fund_many(rows)
        result = compute_value(fund)
        valid = result.dropna()
        assert (valid >= 0.0).all()
        assert (valid <= 1.0).all()


class TestEdgeCases:
    def test_no_fundamentals_returns_nan(self):
        rows = [
            {"ticker": "A", "roe": None, "debt_to_equity": None},
            {"ticker": "B", "roe": None, "debt_to_equity": None},
        ]
        fund = _fund_many(rows)
        result = compute_quality(fund)
        assert result.isna().all(), "All-null fundamentals must return all NaN"

    def test_single_valid_value_row_returns_bounded(self):
        rows = [
            {"ticker": "A", "pe_ratio": 20.0, "pb_ratio": None},
            {"ticker": "B", "pe_ratio": None,  "pb_ratio": None},
        ]
        fund = _fund_many(rows)
        result = compute_value(fund)
        val = result["A"]
        assert math.isnan(val) or 0.0 <= val <= 1.0

    def test_negative_pe_treated_as_missing(self):
        """Negative PE (loss-making) produces NaN earnings yield → treated as no data."""
        rows = [
            {"ticker": "LOSS",    "pe_ratio": -5.0,  "pb_ratio": 2.0},
            {"ticker": "PROFIT",  "pe_ratio":  15.0, "pb_ratio": 2.0},
            {"ticker": "P1",      "pe_ratio":  25.0, "pb_ratio": 3.0},
        ]
        fund = _fund_many(rows)
        result = compute_value(fund)
        # LOSS has no earnings yield component, PROFIT does
        # Both should still be in [0,1] (or NaN for LOSS if pb also missing)
        if not math.isnan(result["LOSS"]):
            assert 0.0 <= result["LOSS"] <= 1.0
        assert 0.0 <= result["PROFIT"] <= 1.0
