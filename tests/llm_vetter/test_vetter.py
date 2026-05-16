"""
Tests for the llm-vetter vetting loop and per-ticker crash isolation.

The per-ticker crash isolation logic lives in main._do_vet (the for-loop
around vet_single_ticker).  We extract and test that pattern directly so
the test does not need a live DB, Ollama, or FastAPI server.
"""
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


def test_no_flag_for_valid_exclude_with_earnings():
    flags = _detect_hallucination_flags(
        "XYZ", _parsed(exclude=True, confidence="high", risk_type="earnings",
                       reason="XYZ is expected to miss Q2 earnings significantly."),
        news=[], earnings_date="2026-06-01", raw="{}"
    )
    no_data_flags = [f for f in flags if "no supporting data" in f.lower() or "no news/earnings" in f.lower()]
    assert no_data_flags == []
