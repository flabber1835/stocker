"""
Tests for the LLM vetter integration points in portfolio-builder:
  - _apply_conviction_boost: pure function for score boosting
  - vetter exclusion application logic (mirrors _do_build)

These tests use no DB or network; they exercise the deterministic math directly.
"""
import pytest
from app.main import _apply_conviction_boost

BOOST_MAP = {"high": 0.25, "medium": 0.12, "low": 0.05, "none": 0.0}
MAX_BOOST = 0.30


# ── _apply_conviction_boost ───────────────────────────────────────────────────


class TestApplyConvictionBoost:

    def test_high_conviction_applies_correct_boost(self):
        result = _apply_conviction_boost(1.0, "high", BOOST_MAP, MAX_BOOST)
        assert abs(result - 1.25) < 1e-9

    def test_medium_conviction_applies_correct_boost(self):
        result = _apply_conviction_boost(2.0, "medium", BOOST_MAP, MAX_BOOST)
        assert abs(result - (2.0 + 2.0 * 0.12)) < 1e-9

    def test_low_conviction_applies_correct_boost(self):
        result = _apply_conviction_boost(1.0, "low", BOOST_MAP, MAX_BOOST)
        assert abs(result - 1.05) < 1e-9

    def test_none_conviction_no_change(self):
        result = _apply_conviction_boost(1.0, "none", BOOST_MAP, MAX_BOOST)
        assert result == 1.0

    def test_unknown_conviction_no_change(self):
        result = _apply_conviction_boost(1.0, "ultra_high", BOOST_MAP, MAX_BOOST)
        assert result == 1.0

    def test_negative_score_lifted_not_penalised(self):
        # abs(-0.5) * 0.25 = 0.125, so result = -0.5 + 0.125 = -0.375
        result = _apply_conviction_boost(-0.5, "high", BOOST_MAP, MAX_BOOST)
        assert abs(result - (-0.5 + 0.5 * 0.25)) < 1e-9
        assert result > -0.5   # lifted toward zero, not pushed further negative

    def test_boost_capped_at_max_boost(self):
        # boost_map["high"]=0.50 > max_boost=0.30 → capped to 0.30
        result = _apply_conviction_boost(1.0, "high", {"high": 0.50}, 0.30)
        assert abs(result - 1.30) < 1e-9

    def test_zero_score_stays_zero(self):
        # abs(0) * boost = 0, no change
        result = _apply_conviction_boost(0.0, "high", BOOST_MAP, MAX_BOOST)
        assert result == 0.0

    def test_boost_is_additive_not_multiplicative(self):
        # If multiplicative: 1.0 * (1 + 0.25) = 1.25 (same for positive scores)
        # Difference shows on negative: additive = -0.5 + 0.125 = -0.375
        #                               multiplicative = -0.5 * 1.25 = -0.625 (worse)
        result = _apply_conviction_boost(-1.0, "high", BOOST_MAP, MAX_BOOST)
        assert result > -1.0  # additive: score improved
        assert abs(result - (-1.0 + 1.0 * 0.25)) < 1e-9

    def test_large_positive_score_boosted_proportionally(self):
        result = _apply_conviction_boost(10.0, "high", BOOST_MAP, MAX_BOOST)
        assert abs(result - (10.0 + 10.0 * 0.25)) < 1e-9


# ── Vetter exclusion application logic ───────────────────────────────────────
#
# Mirrors the filter logic in _do_build (step 2b).  Tested as a standalone
# simulation so no DB mock is needed.


def _apply_exclusions(
    candidate_tickers: list,
    scores_map: dict,
    rank_map: dict,
    excluded_set: set,
) -> tuple[list, dict, dict]:
    """Mirror of the exclusion filtering block in _do_build."""
    remaining = [t for t in candidate_tickers if t not in excluded_set]
    new_scores = {t: v for t, v in scores_map.items() if t not in excluded_set}
    new_ranks  = {t: v for t, v in rank_map.items()   if t not in excluded_set}
    return remaining, new_scores, new_ranks


class TestVetterExclusionApplication:

    def test_excluded_ticker_removed_from_all_structures(self):
        tickers = ["AAPL", "MSFT", "GOOG"]
        scores  = {"AAPL": 1.0, "MSFT": 0.8, "GOOG": 0.6}
        ranks   = {"AAPL": 1,   "MSFT": 2,   "GOOG": 3}

        remaining, new_scores, new_ranks = _apply_exclusions(tickers, scores, ranks, {"MSFT"})

        assert "MSFT" not in remaining
        assert "MSFT" not in new_scores
        assert "MSFT" not in new_ranks
        assert len(remaining) == 2

    def test_no_exclusions_leaves_everything_unchanged(self):
        tickers = ["AAPL", "MSFT"]
        scores  = {"AAPL": 1.0, "MSFT": 0.8}
        ranks   = {"AAPL": 1,   "MSFT": 2}

        remaining, new_scores, new_ranks = _apply_exclusions(tickers, scores, ranks, set())

        assert remaining == tickers
        assert new_scores == scores
        assert new_ranks  == ranks

    def test_all_tickers_excluded_produces_empty_result(self):
        tickers = ["AAPL", "MSFT"]
        scores  = {"AAPL": 1.0, "MSFT": 0.8}
        ranks   = {"AAPL": 1,   "MSFT": 2}

        remaining, new_scores, new_ranks = _apply_exclusions(
            tickers, scores, ranks, {"AAPL", "MSFT"}
        )

        assert remaining  == []
        assert new_scores == {}
        assert new_ranks  == {}

    def test_exclusion_not_in_candidates_is_harmless(self):
        """Excluding a ticker that isn't in the candidate list must not raise."""
        tickers = ["AAPL"]
        scores  = {"AAPL": 1.0}
        ranks   = {"AAPL": 1}

        remaining, new_scores, new_ranks = _apply_exclusions(
            tickers, scores, ranks, {"NONEXISTENT", "ALSO_MISSING"}
        )

        assert remaining  == ["AAPL"]
        assert new_scores == {"AAPL": 1.0}

    def test_rank_order_preserved_after_exclusion(self):
        """Candidates must remain in their original rank order after exclusion."""
        tickers = ["AAPL", "MSFT", "GOOG", "AMZN"]
        scores  = {t: float(i) for i, t in enumerate(tickers, 1)}
        ranks   = {t: i for i, t in enumerate(tickers, 1)}

        remaining, _, _ = _apply_exclusions(tickers, scores, ranks, {"MSFT"})

        assert remaining == ["AAPL", "GOOG", "AMZN"]

    def test_multiple_exclusions_all_removed(self):
        tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "TSLA"]
        scores  = {t: 1.0 for t in tickers}
        ranks   = {t: i for i, t in enumerate(tickers, 1)}

        remaining, new_scores, _ = _apply_exclusions(
            tickers, scores, ranks, {"MSFT", "AMZN"}
        )

        assert set(remaining)      == {"AAPL", "GOOG", "TSLA"}
        assert set(new_scores.keys()) == {"AAPL", "GOOG", "TSLA"}


# ── End-to-end boost + exclusion scenario ────────────────────────────────────

class TestBoostAndExclusionCombined:
    """
    Simulate the full vetter integration path:
      1. Remove excluded tickers
      2. Apply conviction boosts to remaining
    """

    def test_excluded_ticker_not_boosted(self):
        tickers = ["AAPL", "MSFT"]
        scores  = {"AAPL": 1.0, "MSFT": 1.0}
        ranks   = {"AAPL": 1,   "MSFT": 2}
        conviction_map = {"AAPL": "high", "MSFT": "high"}

        # MSFT is excluded by vetter
        remaining, scores, _ = _apply_exclusions(tickers, scores, ranks, {"MSFT"})

        # Apply boosts to remaining only
        for ticker, conviction in conviction_map.items():
            if ticker in scores:
                scores[ticker] = _apply_conviction_boost(
                    scores[ticker], conviction, BOOST_MAP, MAX_BOOST
                )

        assert "MSFT" not in scores
        assert abs(scores["AAPL"] - 1.25) < 1e-9  # AAPL boosted

    def test_boost_applied_only_to_candidates_with_positive_catalyst(self):
        tickers = ["AAPL", "MSFT", "GOOG"]
        scores  = {"AAPL": 1.0, "MSFT": 1.0, "GOOG": 1.0}

        # Only AAPL has a positive catalyst
        conviction_map = {"AAPL": "high"}

        for ticker, conviction in conviction_map.items():
            if ticker in scores:
                scores[ticker] = _apply_conviction_boost(
                    scores[ticker], conviction, BOOST_MAP, MAX_BOOST
                )

        assert abs(scores["AAPL"] - 1.25) < 1e-9
        assert scores["MSFT"] == 1.0
        assert scores["GOOG"] == 1.0
