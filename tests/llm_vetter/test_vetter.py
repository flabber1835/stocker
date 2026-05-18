"""
Tests for the llm-vetter vetting loop and per-ticker crash isolation.

The per-ticker crash isolation logic lives in main._do_vet (the for-loop
around vet_single_ticker).  We extract and test that pattern directly so
the test does not need a live DB, Ollama, or FastAPI server.
"""
import os as _os, sys as _sys

# Ensure llm-vetter's 'app' package is on sys.path regardless of which other
# service's test files ran first and cached a different 'app' module.
_VETTER_PATH = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "services", "llm-vetter"))
_app = _sys.modules.get("app")
if _app is None or _VETTER_PATH not in _os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(_sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del _sys.modules[_k]
    if _VETTER_PATH not in _sys.path:
        _sys.path.insert(0, _VETTER_PATH)

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from app.main import _vet_with_crash_isolation


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ok_result(ticker: str) -> dict:
    """Return a minimal successful vet result for a ticker."""
    return {
        "ticker": ticker,
        "exclude": False,
        "reason": f"{ticker} looks fine for the next 30 days",
        "confidence": "low",
        "risk_type": "none",
        "had_av_news": False,
        "had_earnings": False,
        "had_tavily": False,
        "parse_error": False,
        "crashed": False,
        "latency_ms": 100,
        "prompt": "",
        "system_prompt": "",
        "raw_response": "{}",
        "news_titles": [],
        "earnings_date": None,
        "hallucination_flags": [],
    }


def _make_crash_result(ticker: str, exc: Exception) -> dict:
    """Reproduce the crash-handling dict that main._do_vet builds on exception."""
    return {
        "ticker": ticker,
        "exclude": False,
        "reason": f"Ticker vetting crashed: {exc}",
        "confidence": "low",
        "risk_type": "none",
        "had_av_news": False,
        "had_earnings": False,
        "had_tavily": False,
        "parse_error": False,
        "crashed": True,
        "crash_traceback": "",
        "latency_ms": 0,
        "prompt": "",
        "system_prompt": "",
        "raw_response": "",
        "news_titles": [],
        "earnings_date": None,
        "hallucination_flags": [],
    }


async def _run_vetting_loop(candidates: list[str], vet_single_ticker_fn) -> list[dict]:
    """
    Thin wrapper around the real crash-isolation helper from app.main.
    Calls _vet_with_crash_isolation for each ticker so tests exercise the
    production isolation logic directly.
    """
    ticker_results: list[dict] = []
    for ticker in candidates:
        result = await _vet_with_crash_isolation(ticker, vet_single_ticker_fn)
        ticker_results.append(result)
    return ticker_results


# ── Per-ticker crash isolation ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crash_on_third_ticker_does_not_stop_loop():
    """
    When vet_single_ticker raises on the 3rd call, the loop must continue
    processing the remaining tickers.
    """
    tickers = ["AAPL", "MSFT", "NVDA", "GOOG", "AMZN"]
    call_count = 0

    async def mock_vet(ticker: str) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise RuntimeError("Ollama timed out for NVDA")
        return _make_ok_result(ticker)

    results = await _run_vetting_loop(tickers, mock_vet)

    # All 5 tickers must have a result — the crash must not abort the loop
    assert len(results) == 5


@pytest.mark.asyncio
async def test_crash_on_third_ticker_marks_crashed_true():
    """The crashed ticker's result dict must have crashed=True."""
    tickers = ["AAPL", "MSFT", "NVDA", "GOOG", "AMZN"]
    call_count = 0

    async def mock_vet(ticker: str) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise ValueError("unexpected model output")
        return _make_ok_result(ticker)

    results = await _run_vetting_loop(tickers, mock_vet)

    crashed = [r for r in results if r.get("crashed")]
    assert len(crashed) == 1
    assert crashed[0]["ticker"] == "NVDA"
    assert crashed[0]["crashed"] is True


@pytest.mark.asyncio
async def test_non_crashed_tickers_have_crashed_false():
    """All tickers except the crashing one should have crashed=False."""
    tickers = ["AAPL", "MSFT", "NVDA", "GOOG", "AMZN"]
    call_count = 0

    async def mock_vet(ticker: str) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise RuntimeError("crash on third")
        return _make_ok_result(ticker)

    results = await _run_vetting_loop(tickers, mock_vet)

    ok_results = [r for r in results if not r.get("crashed")]
    assert len(ok_results) == 4
    ok_tickers = {r["ticker"] for r in ok_results}
    assert ok_tickers == {"AAPL", "MSFT", "GOOG", "AMZN"}


@pytest.mark.asyncio
async def test_crash_result_defaults_to_keep():
    """
    A crashed ticker must default to exclude=False (do not silently exclude
    a stock just because the vetter crashed on it).
    """
    tickers = ["AAPL", "CRASH_ME"]
    call_count = 0

    async def mock_vet(ticker: str) -> dict:
        nonlocal call_count
        call_count += 1
        if ticker == "CRASH_ME":
            raise RuntimeError("network error")
        return _make_ok_result(ticker)

    results = await _run_vetting_loop(tickers, mock_vet)

    crash_result = next(r for r in results if r["ticker"] == "CRASH_ME")
    assert crash_result["exclude"] is False


@pytest.mark.asyncio
async def test_multiple_crashes_still_produces_all_results():
    """Even if every other ticker crashes, we still get a result for each one."""
    tickers = [f"T{i}" for i in range(6)]
    call_count = 0

    async def mock_vet(ticker: str) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count % 2 == 0:
            raise Exception(f"crash on {ticker}")
        return _make_ok_result(ticker)

    results = await _run_vetting_loop(tickers, mock_vet)

    assert len(results) == 6
    crashed = [r for r in results if r.get("crashed")]
    ok = [r for r in results if not r.get("crashed")]
    assert len(crashed) == 3
    assert len(ok) == 3


# ── _detect_hallucination_flags ───────────────────────────────────────────────

from app.vetter import _detect_hallucination_flags


def _parsed(exclude=False, confidence="low", risk_type="none", reason="No significant risk identified for this ticker.", positive_catalyst=False):
    return {
        "exclude": exclude,
        "confidence": confidence,
        "risk_type": risk_type,
        "reason": reason,
        "positive_catalyst": positive_catalyst,
    }


def test_no_flags_for_clean_keep():
    flags = _detect_hallucination_flags("AAPL", _parsed(), news=[], earnings_date=None, raw="{}")
    assert flags == []


def test_exclude_high_confidence_no_data_flagged():
    flags = _detect_hallucination_flags(
        "XYZ", _parsed(exclude=True, confidence="high", risk_type="earnings",
                       reason="XYZ missed Q1 earnings badly and guidance was cut."),
        news=[], earnings_date=None, raw="{}"
    )
    assert any("high confidence" in f for f in flags)


def test_exclude_no_data_always_flagged():
    flags = _detect_hallucination_flags(
        "XYZ", _parsed(exclude=True, confidence="low", risk_type="governance",
                       reason="XYZ had governance concerns worth noting."),
        news=[], earnings_date=None, raw="{}"
    )
    assert any("no supporting data" in f.lower() for f in flags)


def test_exclude_with_news_not_flagged_for_no_data():
    news = [{"title": "XYZ Misses Q1 Revenue Estimates by 15%", "summary": "...", "sentiment": "Bearish"}]
    flags = _detect_hallucination_flags(
        "XYZ", _parsed(exclude=True, confidence="high", risk_type="earnings",
                       reason="XYZ missed Q1 earnings badly."),
        news=news, earnings_date=None, raw="{}"
    )
    no_data_flags = [f for f in flags if "no supporting data" in f.lower() or "no news/earnings" in f.lower()]
    assert no_data_flags == []


def test_contradictory_exclude_true_positive_catalyst_flagged():
    flags = _detect_hallucination_flags(
        "AAPL", _parsed(exclude=True, confidence="medium", risk_type="macro",
                        reason="AAPL faces macro headwinds.", positive_catalyst=True),
        news=[], earnings_date=None, raw="{}"
    )
    assert any("positive_catalyst" in f for f in flags)


def test_exclude_risk_type_none_flagged():
    flags = _detect_hallucination_flags(
        "XYZ", _parsed(exclude=True, confidence="low", risk_type="none",
                       reason="XYZ has some concerns."),
        news=[], earnings_date=None, raw="{}"
    )
    assert any("risk_type='none'" in f for f in flags)


def test_short_reason_flagged():
    flags = _detect_hallucination_flags(
        "XYZ", _parsed(reason="Bad."),
        news=[], earnings_date=None, raw="{}"
    )
    assert any("short" in f.lower() for f in flags)


def test_date_hallucination_in_reason_flagged():
    """Year clearly in the past should be flagged as date hallucination."""
    parsed = _parsed(reason="XYZ reported strong earnings in Q3 2019 results.")
    flags = _detect_hallucination_flags("XYZ", parsed, news=[], earnings_date=None, raw="{}", today="2026-05-17")
    assert any("unexpected year" in f.lower() for f in flags)


def test_date_hallucination_current_year_not_flagged():
    """Current year and next year in reason are fine."""
    parsed = _parsed(reason="XYZ expected to report Q2 2026 earnings in August 2027.")
    flags = _detect_hallucination_flags("XYZ", parsed, news=[], earnings_date=None, raw="{}", today="2026-05-17")
    date_flags = [f for f in flags if "unexpected year" in f.lower()]
    assert date_flags == []


def test_date_hallucination_in_positive_reason_flagged():
    """Old year in positive_reason should also be flagged."""
    parsed = {
        **_parsed(positive_catalyst=True),
        "positive_conviction": "high",
        "positive_reason": "XYZ signed a landmark AI partnership in January 2020.",
    }
    flags = _detect_hallucination_flags("XYZ", parsed, news=[], earnings_date=None, raw="{}", today="2026-05-17")
    positive_date_flags = [f for f in flags if "positive_reason" in f and "unexpected year" in f]
    assert positive_date_flags, f"Expected positive_reason date flag, got: {flags}"


def test_positive_catalyst_true_empty_reason_flagged():
    """positive_catalyst=True with no positive_reason text should be flagged."""
    parsed = {
        **_parsed(positive_catalyst=True),
        "positive_conviction": "high",
        "positive_reason": "",
    }
    flags = _detect_hallucination_flags("XYZ", parsed, news=[], earnings_date=None, raw="{}")
    assert any("positive_reason" in f and "empty" in f.lower() for f in flags)


def test_positive_catalyst_false_with_conviction_flagged():
    """positive_catalyst=False with a non-'none' conviction is contradictory."""
    parsed = {
        **_parsed(positive_catalyst=False),
        "positive_conviction": "medium",
        "positive_reason": "",
    }
    flags = _detect_hallucination_flags("XYZ", parsed, news=[], earnings_date=None, raw="{}")
    assert any("positive_catalyst=False" in f and "positive_conviction" in f for f in flags)


def test_positive_catalyst_false_none_conviction_not_flagged():
    """positive_catalyst=False with conviction='none' is normal — no flag."""
    parsed = {
        **_parsed(positive_catalyst=False),
        "positive_conviction": "none",
        "positive_reason": "",
    }
    flags = _detect_hallucination_flags("XYZ", parsed, news=[], earnings_date=None, raw="{}")
    assert not any("positive_conviction" in f for f in flags)


# ── _build_summary ────────────────────────────────────────────────────────────

from app.main import _build_summary


def _r(
    ticker,
    *,
    exclude=False,
    crashed=False,
    confidence="low",
    positive_catalyst=False,
    positive_conviction="none",
    had_av_news=False,
    had_earnings=False,
    had_tavily=False,
    latency_ms=100,
    hallucination_flags=None,
):
    return {
        "ticker": ticker,
        "exclude": exclude,
        "crashed": crashed,
        "confidence": confidence,
        "positive_catalyst": positive_catalyst,
        "positive_conviction": positive_conviction,
        "had_av_news": had_av_news,
        "had_earnings": had_earnings,
        "had_tavily": had_tavily,
        "latency_ms": latency_ms,
        "hallucination_flags": hallucination_flags or [],
    }


class TestBuildSummary:
    def test_empty_results(self):
        s = _build_summary([], 10)
        assert s["total_candidates"] == 10
        assert s["completed"] == 0
        assert s["remaining"] == 10
        assert s["excluded"] == 0
        assert s["kept"] == 0
        assert s["crashed"] == 0
        assert s["avg_latency_ms"] is None

    def test_counts_excluded_kept_remaining(self):
        results = [_r("AAPL"), _r("MSFT", exclude=True), _r("GOOG")]
        s = _build_summary(results, 5)
        assert s["excluded"] == 1
        assert s["kept"] == 2
        assert s["completed"] == 3
        assert s["remaining"] == 2

    def test_crashed_not_counted_as_kept_or_excluded(self):
        results = [_r("AAPL"), _r("CRASH", crashed=True)]
        s = _build_summary(results, 2)
        assert s["crashed"] == 1
        assert s["kept"] == 1
        assert s["excluded"] == 0

    def test_confidence_distribution(self):
        results = [
            _r("A", confidence="high"),
            _r("B", confidence="medium"),
            _r("C", confidence="low"),
            _r("D", confidence="low"),
        ]
        s = _build_summary(results, 4)
        assert s["confidence_dist"] == {"high": 1, "medium": 1, "low": 2}

    def test_positive_catalysts_and_conviction_dist(self):
        results = [
            _r("AAPL", positive_catalyst=True, positive_conviction="high"),
            _r("MSFT", positive_catalyst=True, positive_conviction="low"),
            _r("GOOG"),
        ]
        s = _build_summary(results, 3)
        assert s["positive_catalysts"] == 2
        assert set(s["positive_catalyst_tickers"]) == {"AAPL", "MSFT"}
        assert s["positive_conviction_dist"]["high"] == 1
        assert s["positive_conviction_dist"]["low"] == 1
        assert s["positive_conviction_dist"]["medium"] == 0

    def test_no_data_tickers(self):
        results = [
            _r("AAPL", had_av_news=True),
            _r("EMPTY"),  # all had_* False
        ]
        s = _build_summary(results, 2)
        assert "EMPTY" in s["tickers_no_data"]
        assert "AAPL" not in s["tickers_no_data"]

    def test_avg_and_total_latency(self):
        results = [_r("AAPL", latency_ms=100), _r("MSFT", latency_ms=300)]
        s = _build_summary(results, 2)
        assert s["avg_latency_ms"] == 200
        assert s["total_latency_ms"] == 400

    def test_hallucination_flag_count(self):
        results = [
            _r("AAPL", hallucination_flags=["flag1", "flag2"]),
            _r("MSFT", hallucination_flags=["flag3"]),
        ]
        s = _build_summary(results, 2)
        assert s["hallucination_flags"] == 3

    def test_all_excluded(self):
        results = [_r("A", exclude=True), _r("B", exclude=True)]
        s = _build_summary(results, 2)
        assert s["excluded"] == 2
        assert s["kept"] == 0
        assert s["remaining"] == 0

    def test_parse_errors_counted(self):
        results = [_r("A"), {"ticker": "B", "exclude": False, "crashed": False,
                              "confidence": "low", "positive_catalyst": False,
                              "positive_conviction": "none", "had_av_news": False,
                              "had_earnings": False, "had_tavily": False,
                              "latency_ms": 50, "hallucination_flags": [],
                              "parse_error": True}]
        s = _build_summary(results, 2)
        assert s["parse_errors"] == 1


def test_no_flag_for_valid_exclude_with_earnings():
    flags = _detect_hallucination_flags(
        "XYZ", _parsed(exclude=True, confidence="high", risk_type="earnings",
                       reason="XYZ is expected to miss Q2 earnings significantly."),
        news=[], earnings_date="2026-06-01", raw="{}"
    )
    no_data_flags = [f for f in flags if "no supporting data" in f.lower() or "no news/earnings" in f.lower()]
    assert no_data_flags == []


def test_regime_hallucination_flagged():
    """Reason mentions bear_stress when active regime is bull_calm."""
    parsed = _parsed(reason="Given the bear_stress regime, this stock fits defensive posture.")
    flags = _detect_hallucination_flags("XYZ", parsed, news=[], earnings_date=None, raw="{}", regime="bull_calm")
    assert any("regime hallucination" in f for f in flags)


def test_regime_correct_not_flagged():
    """Reason correctly mentions bull_calm — no flag."""
    parsed = _parsed(reason="In bull_calm the momentum factor is weighted heavily.")
    flags = _detect_hallucination_flags("XYZ", parsed, news=[], earnings_date=None, raw="{}", regime="bull_calm")
    assert not any("regime hallucination" in f for f in flags)


def test_regime_none_no_flag():
    """When regime is not passed (None), skip the check entirely."""
    parsed = _parsed(reason="Given the bear_stress regime, some concern exists.")
    flags = _detect_hallucination_flags("XYZ", parsed, news=[], earnings_date=None, raw="{}", regime=None)
    assert not any("regime hallucination" in f for f in flags)
