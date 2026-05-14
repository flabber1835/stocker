"""
Tests for the llm-vetter vetting loop and per-ticker crash isolation.

The per-ticker crash isolation logic lives in main._do_vet (the for-loop
around vet_single_ticker).  We extract and test that pattern directly so
the test does not need a live DB, Ollama, or FastAPI server.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch


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
    Minimal reproduction of the crash-isolation loop from main._do_vet.
    The real loop catches exceptions per ticker and continues; this mirrors
    that behaviour so we can unit-test isolation without a live service.
    """
    ticker_results: list[dict] = []
    for ticker in candidates:
        try:
            result = await vet_single_ticker_fn(ticker)
        except Exception as exc:
            result = _make_crash_result(ticker, exc)
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
