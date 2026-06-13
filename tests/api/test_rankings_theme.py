"""Tests for /rankings/theme — the hardcoded AI-buildout theme filter endpoint.

Two layers (mirrors test_rankings_search.py's approach — no DB required):
1. Overlay assembly  — the endpoint decorates ranked theme rows with vetter/held/
   cluster overlays and, crucially, does NOT inject non-theme broker positions
   (inject_unranked=False).
2. Source/structure  — the endpoint filters on the shared AI_BUILDOUT_UNIVERSE set
   via `ticker = ANY(:theme)` and returns the theme metadata block.
"""
from __future__ import annotations

from pathlib import Path

from app.main import _apply_overlays
from stock_strategy_shared.ai_universe import AI_BUILDOUT_UNIVERSE

API_MAIN = Path(__file__).resolve().parents[2] / "services" / "api" / "app" / "main.py"


# ── Overlay assembly ──────────────────────────────────────────────────────────

def _ranked(ticker, rank):
    return {"ticker": ticker, "rank": rank, "composite_score": 0.5, "percentile": 0.9,
            "regime": "bull_calm", "rank_date": "2026-06-12", "factor_scores": {}}


class TestThemeOverlayAssembly:
    def test_only_theme_rows_no_broker_injection(self):
        """inject_unranked=False: a non-theme broker position must NOT appear, even
        though it is held — the Theme filter scopes the view to the theme set."""
        ranked = [_ranked("NVDA", 1), _ranked("VRT", 12)]
        held = {"AAPL": {"qty": 5, "market_value": 1000.0, "unrealized_plpc": 0.1,
                         "name": "Apple", "sector": "Tech", "market_cap": 3e12}}
        out = _apply_overlays(ranked, {}, held, inject_unranked=False)
        tickers = {r["ticker"] for r in out}
        assert tickers == {"NVDA", "VRT"}
        assert "AAPL" not in tickers

    def test_held_theme_name_keeps_held_overlay(self):
        ranked = [_ranked("NVDA", 1)]
        held = {"NVDA": {"qty": 10, "market_value": 9000.0, "unrealized_plpc": 0.2,
                         "name": "NVIDIA", "sector": "Tech", "market_cap": 3e12}}
        out = _apply_overlays(ranked, {}, held, inject_unranked=False)
        assert out[0]["held"] is True
        assert out[0]["qty"] == 10

    def test_vetter_and_cluster_overlays_applied(self):
        ranked = [_ranked("OKLO", 86)]
        vetter = {"OKLO": {"exclude": True, "confidence": "high", "risk_type": "drawdown",
                           "reason": "falling knife", "positive_catalyst": False,
                           "positive_reason": None, "crashed": True}}
        out = _apply_overlays(ranked, vetter, {}, inject_unranked=False,
                              cluster_by_ticker={"OKLO": "c7"})
        assert out[0]["vetter_excluded"] is True
        assert out[0]["vetter_risk_type"] == "drawdown"
        assert out[0]["cluster_id"] == "c7"

    def test_caller_rows_not_mutated(self):
        ranked = [_ranked("NVDA", 1)]
        _apply_overlays(ranked, {}, {}, inject_unranked=False)
        assert "held" not in ranked[0]      # overlay keys written only on the copy


# ── Source / structure ────────────────────────────────────────────────────────

class TestThemeEndpointStructure:
    def test_endpoint_defined(self):
        src = API_MAIN.read_text()
        assert '@app.get("/rankings/theme")' in src

    def test_uses_hardcoded_universe_and_any_filter(self):
        src = API_MAIN.read_text()
        assert "AI_BUILDOUT_UNIVERSE" in src
        assert "ticker = ANY(:theme)" in src

    def test_does_not_inject_unranked(self):
        # The theme view must not pull in non-theme broker positions.
        src = API_MAIN.read_text()
        assert "inject_unranked=False, cluster_by_ticker=cluster_by_ticker" in src

    def test_returns_theme_metadata(self):
        src = API_MAIN.read_text()
        assert '"id": "ai_buildout"' in src
        assert "universe_size" in src

    def test_universe_is_non_empty(self):
        assert len(AI_BUILDOUT_UNIVERSE) > 0
