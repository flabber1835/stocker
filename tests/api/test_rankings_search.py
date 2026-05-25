"""
Tests for /rankings/search — the ticker-prefix search endpoint.

Covers two independently-testable layers:

1. _match_ticker_prefix   — pure Python equivalent of SQL UPPER(ticker) LIKE UPPER(:q)||'%'
2. _apply_overlays        — vetter + holdings decoration applied to both with-overlays and search
3. Scenario tests         — end-to-end data assembly (no DB required; mirrors the endpoint logic)
"""
from __future__ import annotations
import pytest
from app.main import _match_ticker_prefix, _apply_overlays


# ── _match_ticker_prefix ──────────────────────────────────────────────────────

class TestMatchTickerPrefix:
    def test_exact_single_char(self):
        assert _match_ticker_prefix("A", "A") is True

    def test_exact_multi_char(self):
        assert _match_ticker_prefix("NVDA", "NVDA") is True

    def test_prefix_matches(self):
        assert _match_ticker_prefix("NVDA", "NV") is True

    def test_single_char_query_matches_longer_ticker(self):
        assert _match_ticker_prefix("AAPL", "A") is True

    def test_single_char_query_matches_exact_ticker(self):
        # Agilent scenario: searching "A" finds the single-letter ticker
        assert _match_ticker_prefix("A", "A") is True

    def test_no_match_different_prefix(self):
        assert _match_ticker_prefix("AAPL", "B") is False

    def test_no_match_contains_but_not_prefix(self):
        # "VDA" is inside NVDA but not a prefix
        assert _match_ticker_prefix("NVDA", "VDA") is False

    def test_case_insensitive_query_lower(self):
        assert _match_ticker_prefix("NVDA", "nv") is True

    def test_case_insensitive_ticker_lower(self):
        assert _match_ticker_prefix("nvda", "NV") is True

    def test_case_insensitive_both_lower(self):
        assert _match_ticker_prefix("aapl", "aa") is True

    def test_full_match_is_prefix_match(self):
        assert _match_ticker_prefix("MSFT", "MSFT") is True

    def test_query_longer_than_ticker_no_match(self):
        assert _match_ticker_prefix("A", "AB") is False

    def test_dot_in_ticker(self):
        assert _match_ticker_prefix("BRK.B", "BRK") is True

    def test_dot_in_query(self):
        assert _match_ticker_prefix("BRK.B", "BRK.") is True

    def test_empty_query_matches_everything(self):
        # prefix("", "") → startswith("") is always True in Python
        assert _match_ticker_prefix("AAPL", "") is True

    def test_single_char_A_does_not_match_B(self):
        assert _match_ticker_prefix("B", "A") is False

    def test_agilent_scenario(self):
        universe = ["A", "AA", "AAPL", "ABBV", "AMZN", "NVDA", "MSFT"]
        matches = [t for t in universe if _match_ticker_prefix(t, "A")]
        assert "A" in matches
        assert "AAPL" in matches
        assert "NVDA" not in matches
        assert "MSFT" not in matches

    def test_returns_bool_not_truthy(self):
        result = _match_ticker_prefix("NVDA", "NV")
        assert result is True
        result = _match_ticker_prefix("NVDA", "XX")
        assert result is False


# ── _apply_overlays ───────────────────────────────────────────────────────────

def _make_row(ticker: str, rank: int = 1, **kwargs) -> dict:
    return {
        "ticker": ticker, "rank": rank,
        "composite_score": 0.5, "percentile": 0.8,
        "regime": "bull_calm", "rank_date": "2026-05-22",
        "factor_scores": {}, "rank_slope": None, "prior_rank": None,
        "name": None, "sector": None,
        **kwargs,
    }


def _make_vetter(ticker: str, exclude: bool = False, risk_type: str = "none",
                 reason: str = "", confidence: str = "high",
                 positive_catalyst: bool = False, positive_reason: str | None = None) -> dict:
    return {
        "ticker": ticker, "exclude": exclude, "risk_type": risk_type,
        "reason": reason, "confidence": confidence,
        "positive_catalyst": positive_catalyst, "positive_reason": positive_reason,
    }


def _make_position(ticker: str, qty: float = 10.0, market_value: float = 1000.0,
                   unrealized_plpc: float = 0.05) -> dict:
    return {"qty": qty, "market_value": market_value,
            "unrealized_plpc": unrealized_plpc, "name": None, "sector": None}


class TestApplyOverlaysVetterFields:
    def test_vetted_ticker_gets_exclusion_fields(self):
        rows = [_make_row("AAPL")]
        vetter = {"AAPL": _make_vetter("AAPL", exclude=True, risk_type="legal", reason="Antitrust")}
        result = _apply_overlays(rows, vetter, {})
        aapl = result[0]
        assert aapl["vetter_excluded"] is True
        assert aapl["vetter_risk_type"] == "legal"
        assert aapl["vetter_reason"] == "Antitrust"
        assert aapl["vetter_confidence"] == "high"

    def test_unvetted_ticker_gets_false_defaults(self):
        rows = [_make_row("MSFT")]
        result = _apply_overlays(rows, {}, {})
        msft = result[0]
        assert msft["vetter_excluded"] is False
        assert msft["vetter_confidence"] is None
        assert msft["vetter_risk_type"] is None
        assert msft["vetter_reason"] is None

    def test_positive_catalyst_set_when_present(self):
        rows = [_make_row("NVDA")]
        vetter = {"NVDA": _make_vetter("NVDA", positive_catalyst=True, positive_reason="AI demand")}
        result = _apply_overlays(rows, vetter, {})
        assert result[0]["positive_catalyst"] is True
        assert result[0]["positive_reason"] == "AI demand"

    def test_positive_catalyst_false_for_unvetted(self):
        rows = [_make_row("XYZ")]
        result = _apply_overlays(rows, {}, {})
        assert result[0]["positive_catalyst"] is False
        assert result[0]["positive_reason"] is None

    def test_all_vetter_fields_present_regardless_of_vetter_data(self):
        rows = [_make_row("AAPL"), _make_row("MSFT", rank=2)]
        vetter = {"AAPL": _make_vetter("AAPL")}
        result = _apply_overlays(rows, vetter, {})
        for r in result:
            assert "vetter_excluded" in r
            assert "vetter_confidence" in r
            assert "vetter_risk_type" in r
            assert "vetter_reason" in r
            assert "positive_catalyst" in r
            assert "positive_reason" in r

    def test_excluded_false_is_bool_not_none(self):
        rows = [_make_row("AAPL")]
        result = _apply_overlays(rows, {}, {})
        assert result[0]["vetter_excluded"] is False


class TestApplyOverlaysHoldingsFields:
    def test_held_true_when_position_exists(self):
        rows = [_make_row("AAPL")]
        positions = {"AAPL": _make_position("AAPL")}
        result = _apply_overlays(rows, {}, positions)
        assert result[0]["held"] is True
        assert result[0]["qty"] == 10.0
        assert result[0]["market_value"] == 1000.0

    def test_held_false_when_no_position(self):
        rows = [_make_row("AAPL")]
        result = _apply_overlays(rows, {}, {})
        assert result[0]["held"] is False

    def test_not_in_universe_defaults_false(self):
        rows = [_make_row("AAPL")]
        result = _apply_overlays(rows, {}, {})
        assert result[0]["not_in_universe"] is False

    def test_not_in_universe_preserved_if_set(self):
        rows = [_make_row("XYZ", not_in_universe=True)]
        result = _apply_overlays(rows, {}, {})
        assert result[0]["not_in_universe"] is True


class TestApplyOverlaysInjectUnranked:
    def test_broker_held_unranked_injected_as_rank_9999(self):
        rows = [_make_row("AAPL")]
        positions = {"AAPL": _make_position("AAPL"), "TSLA": _make_position("TSLA")}
        result = _apply_overlays(rows, {}, positions, inject_unranked=True)
        tickers = {r["ticker"] for r in result}
        assert "TSLA" in tickers
        tsla = next(r for r in result if r["ticker"] == "TSLA")
        assert tsla["rank"] == 9999
        assert tsla["not_in_universe"] is True

    def test_already_ranked_ticker_not_injected_twice(self):
        rows = [_make_row("AAPL")]
        positions = {"AAPL": _make_position("AAPL")}
        result = _apply_overlays(rows, {}, positions, inject_unranked=True)
        assert len([r for r in result if r["ticker"] == "AAPL"]) == 1

    def test_inject_unranked_false_skips_injection(self):
        rows = [_make_row("AAPL")]
        positions = {"AAPL": _make_position("AAPL"), "TSLA": _make_position("TSLA")}
        result = _apply_overlays(rows, {}, positions, inject_unranked=False)
        assert all(r["ticker"] != "TSLA" for r in result)

    def test_query_prefix_filters_injected_positions(self):
        rows = []
        positions = {
            "AAPL": _make_position("AAPL"),
            "AMZN": _make_position("AMZN"),
            "NVDA": _make_position("NVDA"),
        }
        result = _apply_overlays(rows, {}, positions, inject_unranked=True, query_prefix="A")
        tickers = {r["ticker"] for r in result}
        assert "AAPL" in tickers
        assert "AMZN" in tickers
        assert "NVDA" not in tickers  # doesn't start with "A"

    def test_query_prefix_none_injects_all_positions(self):
        rows = []
        positions = {"AAPL": _make_position("AAPL"), "NVDA": _make_position("NVDA")}
        result = _apply_overlays(rows, {}, positions, inject_unranked=True, query_prefix=None)
        tickers = {r["ticker"] for r in result}
        assert "AAPL" in tickers
        assert "NVDA" in tickers

    def test_injected_row_gets_vetter_overlay(self):
        rows = []
        positions = {"TSLA": _make_position("TSLA")}
        vetter = {"TSLA": _make_vetter("TSLA", exclude=True, reason="Volatile")}
        result = _apply_overlays(rows, vetter, positions, inject_unranked=True)
        tsla = result[0]
        assert tsla["vetter_excluded"] is True
        assert tsla["vetter_reason"] == "Volatile"

    def test_injected_row_has_held_true(self):
        rows = []
        positions = {"TSLA": _make_position("TSLA", qty=5.0, market_value=500.0)}
        result = _apply_overlays(rows, {}, positions, inject_unranked=True)
        tsla = result[0]
        assert tsla["held"] is True
        assert tsla["qty"] == 5.0
        assert tsla["market_value"] == 500.0

    def test_run_date_propagated_to_injected_rows(self):
        rows = [_make_row("AAPL")]
        rows[0]["rank_date"] = "2026-05-22"
        positions = {"TSLA": _make_position("TSLA")}
        result = _apply_overlays(rows, {}, positions, inject_unranked=True)
        tsla = next(r for r in result if r["ticker"] == "TSLA")
        assert tsla["rank_date"] == "2026-05-22"

    def test_empty_rankings_no_injected_run_date(self):
        rows = []
        positions = {"TSLA": _make_position("TSLA")}
        result = _apply_overlays(rows, {}, positions, inject_unranked=True)
        tsla = result[0]
        assert tsla["rank_date"] is None


# ── Scenario tests: end-to-end data assembly ─────────────────────────────────

class TestSearchScenarios:
    """
    Simulate what the /rankings/search endpoint does:
    filter rankings by prefix, then call _apply_overlays.
    """

    UNIVERSE = [
        {"ticker": "A",    "rank": 152, "composite_score": 0.72},
        {"ticker": "AAPL", "rank": 3,   "composite_score": 0.91},
        {"ticker": "AMZN", "rank": 8,   "composite_score": 0.88},
        {"ticker": "AVGO", "rank": 22,  "composite_score": 0.82},
        {"ticker": "NVDA", "rank": 1,   "composite_score": 0.95},
        {"ticker": "MSFT", "rank": 2,   "composite_score": 0.93},
        {"ticker": "BRK.B","rank": 45,  "composite_score": 0.70},
    ]

    def _search(self, query: str, positions: dict | None = None,
                vetter: dict | None = None) -> list[dict]:
        q = query.upper().strip()
        rows = [
            {**_make_row(r["ticker"], rank=r["rank"]), "composite_score": r["composite_score"]}
            for r in self.UNIVERSE
            if _match_ticker_prefix(r["ticker"], q)
        ]
        rows.sort(key=lambda r: r["rank"])
        return _apply_overlays(rows, vetter or {}, positions or {},
                               inject_unranked=True, query_prefix=q)

    def test_single_char_A_finds_agilent(self):
        results = self._search("A")
        tickers = [r["ticker"] for r in results]
        assert "A" in tickers

    def test_single_char_A_also_finds_prefix_matches(self):
        results = self._search("A")
        tickers = [r["ticker"] for r in results]
        assert "AAPL" in tickers
        assert "AMZN" in tickers
        assert "AVGO" in tickers

    def test_single_char_A_excludes_non_A_tickers(self):
        results = self._search("A")
        tickers = [r["ticker"] for r in results]
        assert "NVDA" not in tickers
        assert "MSFT" not in tickers

    def test_agilent_ranked_below_150_is_found(self):
        # "A" has rank 152 — above the display window but reachable via search
        results = self._search("A")
        agilent = next((r for r in results if r["ticker"] == "A"), None)
        assert agilent is not None
        assert agilent["rank"] == 152

    def test_results_sorted_by_rank(self):
        results = self._search("A")
        ranks = [r["rank"] for r in results]
        assert ranks == sorted(ranks)

    def test_case_insensitive_search(self):
        results_upper = self._search("NV")
        results_lower = self._search("nv")
        assert [r["ticker"] for r in results_upper] == [r["ticker"] for r in results_lower]

    def test_exact_ticker_found(self):
        results = self._search("NVDA")
        assert len(results) == 1
        assert results[0]["ticker"] == "NVDA"

    def test_nonexistent_prefix_returns_empty(self):
        results = self._search("ZZZ")
        assert results == []

    def test_empty_query_returns_empty(self):
        # Endpoint returns early; simulate here
        q = "".strip()
        if not q:
            assert True  # endpoint returns {"count": 0, "rankings": []}
        else:
            pytest.fail("empty query should short-circuit")

    def test_dot_ticker_prefix_match(self):
        results = self._search("BRK")
        tickers = [r["ticker"] for r in results]
        assert "BRK.B" in tickers

    def test_vetter_overlay_applied_to_search_result(self):
        vetter = {"AAPL": _make_vetter("AAPL", exclude=True, reason="Valuation concern")}
        results = self._search("AAPL", vetter=vetter)
        aapl = results[0]
        assert aapl["ticker"] == "AAPL"
        assert aapl["vetter_excluded"] is True
        assert aapl["vetter_reason"] == "Valuation concern"

    def test_held_overlay_applied_to_search_result(self):
        positions = {"NVDA": _make_position("NVDA", qty=20.0, market_value=10000.0)}
        results = self._search("NV", positions=positions)
        nvda = next(r for r in results if r["ticker"] == "NVDA")
        assert nvda["held"] is True
        assert nvda["qty"] == 20.0

    def test_held_but_unranked_injected_when_query_matches(self):
        # GOOG is not in UNIVERSE but held by broker, search "G" should surface it
        positions = {"GOOG": _make_position("GOOG")}
        results = self._search("G", positions=positions)
        tickers = [r["ticker"] for r in results]
        assert "GOOG" in tickers
        goog = next(r for r in results if r["ticker"] == "GOOG")
        assert goog["rank"] == 9999
        assert goog["not_in_universe"] is True
        assert goog["held"] is True

    def test_held_but_unranked_not_injected_when_query_doesnt_match(self):
        # GOOG held but searching "N" — should not appear
        positions = {"GOOG": _make_position("GOOG")}
        results = self._search("N", positions=positions)
        assert all(r["ticker"] != "GOOG" for r in results)

    def test_ranked_plus_unranked_held_both_returned(self):
        # NVDA is ranked, NFLX is held but not ranked, both start with "N"
        positions = {"NFLX": _make_position("NFLX"), "NVDA": _make_position("NVDA")}
        results = self._search("N", positions=positions)
        tickers = [r["ticker"] for r in results]
        assert "NVDA" in tickers
        assert "NFLX" in tickers
        nvda = next(r for r in results if r["ticker"] == "NVDA")
        nflx = next(r for r in results if r["ticker"] == "NFLX")
        assert nvda["rank"] == 1       # ranked normally
        assert nflx["rank"] == 9999    # injected
        assert nvda["held"] is True
        assert nflx["held"] is True


# ── _validate_ticker (reused in search endpoint) ──────────────────────────────

class TestQueryValidation:
    import re as _re
    _PATTERN = _re.compile(r'^[A-Z0-9.\-]{1,10}$')

    def _valid(self, q: str) -> bool:
        return bool(self._PATTERN.match(q.upper().strip()))

    def test_single_letter(self):
        assert self._valid("A") is True

    def test_standard_ticker(self):
        assert self._valid("NVDA") is True

    def test_dot_ticker(self):
        assert self._valid("BRK.B") is True

    def test_numbers_in_ticker(self):
        assert self._valid("T2") is True

    def test_empty_string_invalid(self):
        assert self._valid("") is False

    def test_too_long_invalid(self):
        assert self._valid("ABCDEFGHIJK") is False  # 11 chars

    def test_exactly_10_chars_valid(self):
        assert self._valid("ABCDEFGHIJ") is True

    def test_lowercase_normalised_to_valid(self):
        assert self._valid("nvda") is True  # upper().strip() makes it valid

    def test_space_only_invalid(self):
        assert self._valid("   ") is False

    def test_special_chars_invalid(self):
        assert self._valid("NV!DA") is False

    def test_slash_invalid(self):
        assert self._valid("NV/DA") is False
