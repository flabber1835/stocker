"""
Tests for LLM vetter parse failure and retry behavior.

Parse failures default to exclude=False (KEEP) because the vetter is informational
only — a failed parse is silent noise, not a risk signal. The retry gives the LLM
a second chance with doubled max_tokens before falling back to the safe KEEP default.
"""
from __future__ import annotations
import os as _os, sys as _sys

_VETTER_PATH = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "services", "llm-vetter"))
_app = _sys.modules.get("app")
if _app is None or _VETTER_PATH not in _os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(_sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del _sys.modules[_k]
    if _sys.path[:1] != [_VETTER_PATH]:
        _sys.path.insert(0, _VETTER_PATH)

import json
import pytest
import unittest.mock as mock

from app.vetter import _parse_llm_response, _format_ticker_message, vet_single_ticker


def _make_parse_result(raw: str, ticker: str = "AAPL", news: list | None = None) -> dict:
    return _parse_llm_response(
        raw=raw,
        ticker=ticker,
        news=news or [],
        earnings_date=None,
        tavily_articles=[],
        today="2026-05-25",
        agent_searches=[],
        latency_ms=100,
        user_message="test prompt",
        system_prompt="test system",
        vetter_config={},
    )


class TestParseFailureDefaultsToKeep:
    """Parse failures must default to exclude=False — silence is not a risk signal."""

    def test_invalid_json_sets_exclude_false(self):
        result = _make_parse_result("NOT JSON AT ALL", ticker="GOLD")
        assert result["exclude"] is False, "parse failure must default to KEEP, not exclude"

    def test_invalid_json_sets_parse_error_true(self):
        result = _make_parse_result("{ broken json", ticker="GOLD")
        assert result["parse_error"] is True

    def test_invalid_json_confidence_is_low(self):
        result = _make_parse_result("{ broken json", ticker="GOLD")
        assert result["confidence"] == "low"

    def test_empty_response_keep(self):
        result = _make_parse_result("", ticker="TSLA")
        assert result["exclude"] is False
        assert result["parse_error"] is True

    def test_whitespace_only_keep(self):
        result = _make_parse_result("   \n\n\t  ", ticker="TSLA")
        assert result["exclude"] is False
        assert result["parse_error"] is True

    def test_markdown_fence_without_json_keep(self):
        result = _make_parse_result("```json\n```", ticker="TSLA")
        assert result["exclude"] is False
        assert result["parse_error"] is True

    def test_invalid_json_reason_mentions_keep_or_defaulting(self):
        result = _make_parse_result("completely garbled response $$%%", ticker="GOLD")
        reason_lower = result["reason"].lower()
        assert "keep" in reason_lower or "default" in reason_lower, (
            f"reason should mention KEEP or defaulting, got: {result['reason']!r}"
        )

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


class TestParseRetry:
    """vet_single_ticker retries with doubled max_tokens on parse failure."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        """First response is garbage; retry returns valid JSON → use retry result."""
        valid_json = json.dumps({
            "exclude": False, "reason": "No risk found.", "confidence": "low",
            "risk_type": "none", "positive_catalyst": False, "positive_reason": "",
        })
        import app.vetter as _vmod
        original = _vmod._gateway_chat
        call_count = [0]

        async def _fake(url, payload):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"content": "NOT JSON"}
            return {"content": valid_json}

        vet_single_ticker.__globals__["_gateway_chat"] = _fake
        try:
            result = await vet_single_ticker(
                ticker="AAPL", news=[], earnings_date=None, tavily_articles=[],
                gateway_url="http://fake", today="2026-05-25", tavily_api_key="",
            )
        finally:
            vet_single_ticker.__globals__["_gateway_chat"] = original

        assert call_count[0] == 2, f"expected 2 calls (initial + retry), got {call_count[0]}"
        assert result.get("parse_error") is not True
        assert result["exclude"] is False

    @pytest.mark.asyncio
    async def test_retry_doubles_max_tokens(self):
        """The retry payload must use double the original max_tokens."""
        valid_json = json.dumps({
            "exclude": False, "reason": "ok", "confidence": "low",
            "risk_type": "none", "positive_catalyst": False, "positive_reason": "",
        })
        original = vet_single_ticker.__globals__["_gateway_chat"]
        captured = []

        async def _fake(url, payload):
            captured.append(dict(payload))
            if len(captured) == 1:
                return {"content": "NOT JSON"}
            return {"content": valid_json}

        vet_single_ticker.__globals__["_gateway_chat"] = _fake
        try:
            await vet_single_ticker(
                ticker="MSFT", news=[], earnings_date=None, tavily_articles=[],
                gateway_url="http://fake", today="2026-05-25", tavily_api_key="",
            )
        finally:
            vet_single_ticker.__globals__["_gateway_chat"] = original

        assert len(captured) == 2
        first_tokens = captured[0]["max_tokens"]
        retry_tokens = captured[1]["max_tokens"]
        assert retry_tokens == first_tokens * 2, (
            f"retry max_tokens ({retry_tokens}) should be 2× initial ({first_tokens})"
        )

    @pytest.mark.asyncio
    async def test_double_parse_failure_returns_keep(self):
        """Both attempts fail to parse → final result is exclude=False (safe KEEP default)."""
        original = vet_single_ticker.__globals__["_gateway_chat"]

        async def _fake(url, payload):
            return {"content": "TOTALLY BROKEN $$%%"}

        vet_single_ticker.__globals__["_gateway_chat"] = _fake
        try:
            result = await vet_single_ticker(
                ticker="TSLA", news=[], earnings_date=None, tavily_articles=[],
                gateway_url="http://fake", today="2026-05-25", tavily_api_key="",
            )
        finally:
            vet_single_ticker.__globals__["_gateway_chat"] = original

        assert result["exclude"] is False, "double parse failure must default to KEEP"
        assert result["parse_error"] is True

    @pytest.mark.asyncio
    async def test_retry_exception_falls_back_to_keep(self):
        """If the retry gateway call raises, original parse_error result (exclude=False) is returned."""
        original = vet_single_ticker.__globals__["_gateway_chat"]
        call_count = [0]

        async def _fake(url, payload):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"content": "NOT JSON"}
            raise RuntimeError("gateway timeout on retry")

        vet_single_ticker.__globals__["_gateway_chat"] = _fake
        try:
            result = await vet_single_ticker(
                ticker="NVDA", news=[], earnings_date=None, tavily_articles=[],
                gateway_url="http://fake", today="2026-05-25", tavily_api_key="",
            )
        finally:
            vet_single_ticker.__globals__["_gateway_chat"] = original

        assert result["exclude"] is False
        assert result["parse_error"] is True


class TestCompanyNameInjection:
    """Company name must appear in the prompt and anchor Tavily queries."""

    def test_company_name_in_ticker_line(self):
        msg = _format_ticker_message(
            ticker="B",
            news=[], earnings_date=None, tavily_articles=[],
            today="2026-05-25",
            company_name="Barrick Gold Corporation",
        )
        assert "Barrick Gold Corporation" in msg, (
            f"company name should appear in the prompt, got:\n{msg[:300]}"
        )
        assert "Ticker: B" in msg

    def test_no_company_name_unchanged(self):
        msg = _format_ticker_message(
            ticker="AAPL",
            news=[], earnings_date=None, tavily_articles=[],
            today="2026-05-25",
        )
        assert "Ticker: AAPL" in msg
        assert "—" not in msg.split("\n")[1], "no dash separator when company_name is None"

    def test_company_name_format_includes_separator(self):
        msg = _format_ticker_message(
            ticker="GOOG",
            news=[], earnings_date=None, tavily_articles=[],
            today="2026-05-25",
            company_name="Alphabet Inc",
        )
        assert "GOOG — Alphabet Inc" in msg


class TestTavilyQueryWithCompanyName:
    """Tavily query must include quoted company name to prevent ticker noise."""

    @pytest.mark.asyncio
    async def test_tavily_query_uses_company_name(self):
        from app.tools import fetch_tavily_news

        captured_queries = []

        async def _fake_post(url, **kwargs):
            captured_queries.append(kwargs["json"]["query"])
            r = mock.MagicMock()
            r.raise_for_status = mock.MagicMock()
            r.json.return_value = {"results": []}
            return r

        with mock.patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = mock.AsyncMock(side_effect=_fake_post)
            await fetch_tavily_news(
                "B", "fake-key",
                company_name="Barrick Gold Corporation",
            )

        assert len(captured_queries) == 1
        q = captured_queries[0]
        assert '"Barrick Gold Corporation"' in q, (
            f"query should anchor on quoted company name, got: {q!r}"
        )
        assert "(B)" in q

    @pytest.mark.asyncio
    async def test_tavily_query_ticker_only_when_no_name(self):
        from app.tools import fetch_tavily_news

        captured_queries = []

        async def _fake_post(url, **kwargs):
            captured_queries.append(kwargs["json"]["query"])
            r = mock.MagicMock()
            r.raise_for_status = mock.MagicMock()
            r.json.return_value = {"results": []}
            return r

        with mock.patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = mock.AsyncMock(side_effect=_fake_post)
            await fetch_tavily_news("AAPL", "fake-key")

        assert len(captured_queries) == 1
        q = captured_queries[0]
        assert q == "AAPL stock news risks outlook"
