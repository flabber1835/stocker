"""
Tests for the LLM vetter integration points in portfolio-builder:
  - vetter exclusion application logic (mirrors _do_build)

These tests use no DB or network; they exercise the deterministic logic directly.
"""
import pytest


# ── Vetter exclusion application logic ───────────────────────────────────────
#
# Mirrors the exclusion-filter primitive in _do_build. Note: as of the
# cluster-on-full-universe ordering change this filter is applied to the
# SELECTABLE pool at selection (step 5), AFTER covariance + clustering — the
# excluded names are retained through the cluster build so they can bridge
# single-linkage clusters. The primitive (remove names from a list + maps) is
# unchanged; only WHERE it runs moved. Tested standalone so no DB mock is needed.


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
