"""
Tests for LLM vetter parse failure → exclude=True behavior.

Before the fix, a JSONDecodeError from the LLM returned exclude=False,
silently passing an unvetted stock through as if it were clean.
After the fix, parse failures must exclude the ticker and set parse_error=True
so the operator sees the failure instead of getting a false-safe result.
"""
from __future__ import annotations
import os as _os, sys as _sys

_VETTER_PATH = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "services", "llm-vetter"))
_app = _sys.modules.get("app")
if _app is None or _VETTER_PATH not in _os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(_sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del _sys.modules[_k]
    # Always insert at 0 — another service's path may already be at 0 even if
    # vetter's path is present further down the list.
    if _sys.path[:1] != [_VETTER_PATH]:
        _sys.path.insert(0, _VETTER_PATH)

import json
import unittest.mock as mock

from app.vetter import _parse_llm_response


def _make_parse_result(raw: str, ticker: str = "AAPL") -> dict:
    """Call _parse_llm_response with minimal required args."""
    return _parse_llm_response(
        raw=raw,
        ticker=ticker,
        news=[],
        earnings_date=None,
        tavily_articles=[],
        today="2026-05-25",
        agent_searches=[],
        latency_ms=100,
        user_message="test prompt",
        system_prompt="test system",
        vetter_config={},
    )


class TestParseFailureExcludesStock:
    def test_invalid_json_sets_exclude_true(self):
        result = _make_parse_result("NOT JSON AT ALL", ticker="GOLD")
        assert result["exclude"] is True, "parse failure must exclude the ticker"

    def test_invalid_json_sets_parse_error_true(self):
        result = _make_parse_result("{ broken json", ticker="GOLD")
        assert result["parse_error"] is True

    def test_invalid_json_confidence_is_low(self):
        result = _make_parse_result("{ broken json", ticker="GOLD")
        assert result["confidence"] == "low"

    def test_invalid_json_reason_mentions_excluded(self):
        result = _make_parse_result("completely garbled response $$%%", ticker="GOLD")
        assert "excluded" in result["reason"].lower(), (
            f"reason must say 'excluded', got: {result['reason']!r}"
        )

    def test_invalid_json_reason_mentions_manual_review(self):
        result = _make_parse_result("completely garbled response $$%%", ticker="GOLD")
        assert "manual review" in result["reason"].lower(), (
            f"reason must mention 'manual review', got: {result['reason']!r}"
        )

    def test_empty_response_excluded(self):
        result = _make_parse_result("", ticker="TSLA")
        assert result["exclude"] is True
        assert result["parse_error"] is True

    def test_whitespace_only_excluded(self):
        result = _make_parse_result("   \n\n\t  ", ticker="TSLA")
        assert result["exclude"] is True
        assert result["parse_error"] is True

    def test_markdown_fence_without_json_excluded(self):
        result = _make_parse_result("```json\n```", ticker="TSLA")
        assert result["exclude"] is True
        assert result["parse_error"] is True

    def test_raw_response_preserved_in_result(self):
        raw = "this is the raw garbled text the LLM returned"
        result = _make_parse_result(raw, ticker="AAPL")
        assert result["raw_response"] == raw

    def test_ticker_preserved_in_result(self):
        result = _make_parse_result("bad json", ticker="XYZ")
        assert result["ticker"] == "XYZ"

    def test_hallucination_flags_contain_parse_error(self):
        result = _make_parse_result("NOT JSON", ticker="B")
        flags = result.get("hallucination_flags", [])
        assert any("parse error" in f.lower() or "json" in f.lower() for f in flags), (
            f"hallucination_flags should contain a parse-error entry, got: {flags}"
        )

    def test_valid_json_exclude_false_not_affected(self):
        """Sanity: a valid JSON response with exclude=false is not touched."""
        valid_raw = json.dumps({
            "exclude": False,
            "reason": "No material risk identified.",
            "confidence": "medium",
            "risk_type": "none",
            "positive_catalyst": False,
            "positive_reason": "",
        })
        result = _make_parse_result(valid_raw, ticker="AAPL")
        assert result["exclude"] is False
        assert result.get("parse_error") is not True

    def test_valid_json_exclude_true_not_affected(self):
        """Sanity: a valid JSON with exclude=true is not erroneously reversed."""
        valid_raw = json.dumps({
            "exclude": True,
            "reason": "Earnings miss and guidance cut.",
            "confidence": "high",
            "risk_type": "earnings",
            "positive_catalyst": False,
            "positive_reason": "",
        })
        # Provide news so the no-data auto-override does not fire
        result = _parse_llm_response(
            raw=valid_raw,
            ticker="NFLX",
            news=[{"title": "NFLX guidance cut", "sentiment": "Bearish"}],
            earnings_date=None,
            tavily_articles=[],
            today="2026-05-25",
            agent_searches=[],
            latency_ms=50,
            user_message="test",
            system_prompt="test",
            vetter_config={},
        )
        assert result["exclude"] is True
        assert result.get("parse_error") is not True
