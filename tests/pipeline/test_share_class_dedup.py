"""
Tests for share-class deduplication in the pipeline ranker.

Regression: GOOG and GOOGL (or BRK.A and BRK.B, CMCSA/CMCSK, etc.) were both
appearing in rankings because their company names from Alpha Vantage differ by
share-class suffix ("Alphabet Inc." vs "Alphabet Inc Class A").

Fix: _normalize_company_name() strips share-class and legal-entity suffixes
before using the name as a dedup group key.
"""
import os
import sys

import pandas as pd
import pytest

# ── path bootstrap ────────────────────────────────────────────────────────────

_PIPELINE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "pipeline")
)
_SHARED_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared")
)
for _k in list(sys.modules.keys()):
    if _k == "app" or _k.startswith("app."):
        del sys.modules[_k]
if _PIPELINE_PATH not in sys.path:
    sys.path.insert(0, _PIPELINE_PATH)
if _SHARED_PATH not in sys.path:
    sys.path.insert(1, _SHARED_PATH)

from app.main import _normalize_company_name


# ── _normalize_company_name unit tests ───────────────────────────────────────

class TestNormalizeCompanyName:
    def test_identical_names_same_result(self):
        assert _normalize_company_name("Alphabet Inc.") == _normalize_company_name("Alphabet Inc.")

    def test_class_a_stripped(self):
        """GOOGL: 'Alphabet Inc Class A' → same as 'Alphabet Inc.'"""
        assert (
            _normalize_company_name("Alphabet Inc Class A")
            == _normalize_company_name("Alphabet Inc.")
        )

    def test_class_c_stripped(self):
        """GOOG: 'Alphabet Inc Class C' → same as 'Alphabet Inc.'"""
        assert (
            _normalize_company_name("Alphabet Inc Class C")
            == _normalize_company_name("Alphabet Inc.")
        )

    def test_series_a_stripped(self):
        assert (
            _normalize_company_name("Berkshire Hathaway Series A")
            == _normalize_company_name("Berkshire Hathaway")
        )

    def test_brk_a_brk_b_same_group(self):
        """BRK.A / BRK.B: 'Berkshire Hathaway Inc. Class A' vs 'Class B'."""
        a = _normalize_company_name("Berkshire Hathaway Inc Class A")
        b = _normalize_company_name("Berkshire Hathaway Inc Class B")
        assert a == b, f"'{a}' != '{b}'"

    def test_legal_suffix_stripped(self):
        assert _normalize_company_name("Apple Inc.") == _normalize_company_name("Apple")

    def test_corp_stripped(self):
        assert _normalize_company_name("Comcast Corp.") == _normalize_company_name("Comcast Corp")

    def test_ltd_stripped(self):
        assert _normalize_company_name("Shell Ltd") == _normalize_company_name("Shell")

    def test_lowercase(self):
        """Normalised result is always lowercase."""
        result = _normalize_company_name("ALPHABET INC CLASS A")
        assert result == result.lower()

    def test_different_companies_differ(self):
        """Google and Microsoft should NOT normalise to the same key."""
        assert _normalize_company_name("Alphabet Inc.") != _normalize_company_name("Microsoft Corp.")

    def test_empty_string_stays_empty(self):
        assert _normalize_company_name("") == ""

    def test_whitespace_stripped(self):
        assert _normalize_company_name("  Apple Inc.  ") == _normalize_company_name("Apple Inc.")

    def test_class_with_number_stripped(self):
        """Some companies have 'Class A1' or similar."""
        assert (
            _normalize_company_name("SomeCompany Inc Class A1")
            == _normalize_company_name("SomeCompany Inc")
        )


# ── Dedup behaviour with a fake ranked DataFrame ─────────────────────────────

def _make_ranked_df(rows):
    """Helper: create a minimal ranked DataFrame from (ticker, rank, name) tuples."""
    data = [{"ticker": t, "rank": r, "composite_score": 1.0 / r} for t, r, _ in rows]
    df = pd.DataFrame(data)
    name_map = {t: n for t, _, n in rows if n}
    return df, name_map


def _apply_dedup(df: pd.DataFrame, name_map: dict) -> pd.DataFrame:
    """Apply the same dedup logic used in pipeline main._rank_universe."""
    df = df.sort_values("rank").reset_index(drop=True)
    df["_group_key"] = df["ticker"].map(
        lambda t: _normalize_company_name(name_map[t]) if name_map.get(t) else f"__solo_{t}"
    )
    dup_mask = df["_group_key"].duplicated(keep="first")
    df = df[~dup_mask].drop(columns=["_group_key"]).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    return df


class TestDedupLogic:
    def test_goog_googl_deduped_same_name(self):
        """Both tickers with identical name → lower-ranked dropped."""
        rows = [
            ("GOOGL", 3, "Alphabet Inc."),
            ("GOOG",  5, "Alphabet Inc."),
            ("AAPL",  7, "Apple Inc."),
        ]
        df, nm = _make_ranked_df(rows)
        result = _apply_dedup(df, nm)
        tickers = result["ticker"].tolist()
        assert "GOOGL" in tickers, "Better-ranked share class should be kept"
        assert "GOOG" not in tickers, "Lower-ranked share class should be removed"
        assert "AAPL" in tickers

    def test_goog_googl_deduped_different_name_suffix(self):
        """GOOG/GOOGL where names differ by 'Class A' suffix — must still dedup."""
        rows = [
            ("GOOGL", 3, "Alphabet Inc Class A"),  # AV sometimes returns this
            ("GOOG",  5, "Alphabet Inc."),
            ("AAPL",  7, "Apple Inc."),
        ]
        df, nm = _make_ranked_df(rows)
        result = _apply_dedup(df, nm)
        tickers = result["ticker"].tolist()
        assert "GOOGL" in tickers
        assert "GOOG" not in tickers

    def test_brk_a_brk_b_deduped(self):
        """BRK.A/BRK.B with Class A/B suffixes → only better rank survives."""
        rows = [
            ("BRK.A", 2, "Berkshire Hathaway Inc Class A"),
            ("BRK.B", 4, "Berkshire Hathaway Inc Class B"),
            ("MSFT",  6, "Microsoft Corp."),
        ]
        df, nm = _make_ranked_df(rows)
        result = _apply_dedup(df, nm)
        tickers = result["ticker"].tolist()
        assert "BRK.A" in tickers
        assert "BRK.B" not in tickers
        assert "MSFT" in tickers

    def test_no_name_tickers_not_merged(self):
        """Two tickers without names should NOT dedup with each other."""
        rows = [
            ("ABC", 1, None),
            ("XYZ", 2, None),
        ]
        df, nm = _make_ranked_df(rows)
        result = _apply_dedup(df, nm)
        assert len(result) == 2, "Tickers with no name should not be merged"

    def test_no_dedup_unrelated_companies(self):
        """Unrelated companies with different names are both kept."""
        rows = [
            ("AAPL", 1, "Apple Inc."),
            ("MSFT", 2, "Microsoft Corp."),
            ("AMZN", 3, "Amazon.com Inc."),
        ]
        df, nm = _make_ranked_df(rows)
        result = _apply_dedup(df, nm)
        assert len(result) == 3

    def test_dedup_preserves_best_rank(self):
        """When three share classes exist, the one with the best rank is kept."""
        rows = [
            ("META.C", 10, "Meta Platforms Inc Class C"),
            ("META.A",  4, "Meta Platforms Inc Class A"),
            ("META.B",  7, "Meta Platforms Inc Class B"),
            ("AAPL",   15, "Apple Inc."),
        ]
        df, nm = _make_ranked_df(rows)
        result = _apply_dedup(df, nm)
        tickers = result["ticker"].tolist()
        assert "META.A" in tickers, "Best-ranked share class should survive"
        assert "META.B" not in tickers
        assert "META.C" not in tickers
        assert "AAPL" in tickers

    def test_ranks_reassigned_sequentially_after_dedup(self):
        """After dedup, ranks should be 1, 2, 3, … with no gaps."""
        rows = [
            ("GOOGL", 1, "Alphabet Inc Class A"),
            ("GOOG",  2, "Alphabet Inc."),
            ("AAPL",  3, "Apple Inc."),
            ("MSFT",  4, "Microsoft Corp."),
        ]
        df, nm = _make_ranked_df(rows)
        result = _apply_dedup(df, nm)
        assert result["rank"].tolist() == list(range(1, len(result) + 1))
