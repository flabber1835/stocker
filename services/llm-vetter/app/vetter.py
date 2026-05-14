"""
Core vetting logic for the LLM vetter.

Structured as three composable pieces so main.py can drive the loop and
log an execution_step after every individual ticker decision:

  1. fetch_ticker_data()   — pre-fetch AV news + earnings + optional Tavily
                             for all candidates concurrently (fast, one round-trip)
  2. vet_single_ticker()   — one Ollama call focused on a single ticker
  3. (loop + trace in main.py)

Per-ticker prompts are more focused than a single batch prompt: the model
only sees one company at a time, so it cannot satisfice by skimming. Each
call produces ~60-80 output tokens, so total generation time on CPU is
~30 tickers × 80 tokens / 3 tok/s ≈ 13 minutes — acceptable for a
human-supervised workflow.
"""

import json
import logging
import time
from datetime import date

from ollama import AsyncClient

from app.tools import fetch_av_news, fetch_av_earnings_calendar, fetch_tavily_news
import asyncio

log = logging.getLogger("llm-vetter.vetter")

# Structured-output schema for a single-ticker decision
PER_TICKER_SCHEMA = {
    "type": "object",
    "properties": {
        "exclude":    {"type": "boolean"},
        "reason":     {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "risk_type":  {
            "type": "string",
            "enum": ["earnings", "regulatory", "management", "legal", "sector", "none"],
        },
    },
    "required": ["exclude", "reason", "confidence", "risk_type"],
}

SYSTEM_PROMPT = """\
You are a financial risk analyst. Decide whether to EXCLUDE a single stock from a
30-day equity portfolio holding.

You will be given recent news (with sentiment labels) and an upcoming earnings date
if one falls within the next 45 days.

EXCLUDE the stock (exclude=true) only when there is CLEAR and SPECIFIC evidence of:
- Upcoming earnings with deteriorating analyst expectations, revenue warnings, or
  guidance cuts likely within the 30-day window
- Significant negative news: regulatory action, fraud allegation, product recall,
  key executive departure, major customer loss
- Pending binary legal or regulatory decision with material downside
- Multiple analyst consensus downgrades within the past 7 days

Do NOT exclude based on:
- General macro or market uncertainty (applies to all stocks equally)
- Minor price weakness with no specific catalyst
- Long-term concerns that do not affect the next 30 days
- Absence of news — silence is neutral, not negative

Set confidence:
  "high"   — clear, imminent, specific risk
  "medium" — material concern but uncertain timing or magnitude
  "low"    — weak signal, worth noting but not strongly actionable

If not excluding, set risk_type to "none" and explain briefly why the stock is
safe to hold for 30 days given the available information.
"""


def _format_ticker_message(
    ticker: str,
    news: list[dict],
    earnings_date: str | None,
    tavily_articles: list[dict],
    today: str,
) -> str:
    lines = [
        f"Today: {today}",
        f"Ticker: {ticker}",
        f"Holding period: 30 days",
        "",
    ]

    if earnings_date:
        lines.append(f"UPCOMING EARNINGS DATE: {earnings_date}")

    all_articles = news + tavily_articles
    if all_articles:
        lines.append("RECENT NEWS:")
        for a in all_articles:
            sentiment = f" [{a['sentiment']}]" if "sentiment" in a else ""
            lines.append(f"  - {a['title']}{sentiment}")
            if a.get("summary"):
                lines.append(f"    {a['summary'][:250]}")
    else:
        lines.append("RECENT NEWS: none retrieved")

    return "\n".join(lines)


async def fetch_ticker_data(
    tickers: list[str],
    av_api_key: str,
    tavily_api_key: str,
) -> tuple[dict[str, list[dict]], dict[str, str | None], dict[str, list[dict]], dict]:
    """
    Pre-fetch all external data for the candidate list concurrently.

    Returns (av_news, earnings_calendar, tavily_results, data_source_counts).
    """
    av_news, earnings_calendar = await asyncio.gather(
        fetch_av_news(tickers, av_api_key),
        fetch_av_earnings_calendar(tickers, av_api_key),
    )

    tavily_results: dict[str, list[dict]] = {}
    if tavily_api_key:
        tickers_without_news = [t for t in tickers if not av_news.get(t)]
        if tickers_without_news:
            log.info("Fetching Tavily for %d tickers with no AV news", len(tickers_without_news))
            fetched = await asyncio.gather(
                *[fetch_tavily_news(t, tavily_api_key) for t in tickers_without_news]
            )
            tavily_results = dict(zip(tickers_without_news, fetched))

    data_sources = {
        "av_news_tickers":          sum(1 for t in tickers if av_news.get(t)),
        "earnings_calendar_tickers": sum(1 for t in tickers if earnings_calendar.get(t)),
        "tavily_tickers":           sum(1 for t in tickers if tavily_results.get(t)),
    }
    log.info(
        "Data fetch complete: AV news=%d, earnings=%d, Tavily=%d",
        data_sources["av_news_tickers"],
        data_sources["earnings_calendar_tickers"],
        data_sources["tavily_tickers"],
    )
    return av_news, earnings_calendar, tavily_results, data_sources


def _detect_hallucination_flags(
    ticker: str,
    parsed: dict,
    news: list[dict],
    earnings_date: str | None,
    raw: str,
) -> list[str]:
    """
    Heuristic checks for suspicious LLM output.
    These are signals for human review, not hard rejections.
    """
    flags = []
    exclude = parsed.get("exclude", False)
    confidence = parsed.get("confidence", "low")
    reason = parsed.get("reason", "")
    risk_type = parsed.get("risk_type", "none")

    # Exclude with no data and high/medium confidence is suspicious
    if exclude and not news and not earnings_date and confidence in ("high", "medium"):
        flags.append(f"EXCLUDE with {confidence} confidence but no news/earnings data provided")

    # Exclude with no supporting data at any confidence is suspicious
    if exclude and not news and not earnings_date:
        flags.append("EXCLUDE with no supporting data (no news, no earnings date)")

    # Exclude with risk_type=none is contradictory
    if exclude and risk_type == "none":
        flags.append("EXCLUDE decision but risk_type='none' — contradictory")

    # Keep with high confidence and a non-none risk_type is contradictory
    if not exclude and confidence == "high" and risk_type != "none":
        flags.append(f"KEEP with high confidence but risk_type='{risk_type}' — contradictory")

    # Very short reason suggests the model didn't reason properly
    if len(reason) < 25:
        flags.append(f"Reason suspiciously short ({len(reason)} chars): '{reason}'")

    # Reason doesn't mention the ticker (model may have confused tickers).
    # Only meaningful when data was provided — generic "no news" reasons are expected otherwise.
    has_data = bool(news) or earnings_date is not None
    if has_data and ticker.upper() not in reason.upper() and len(reason) > 50:
        flags.append(f"Reason does not mention ticker '{ticker}' — possible ticker confusion")

    # Raw JSON unexpectedly long (model leaked extra content outside schema)
    if len(raw) > 800:
        flags.append(f"Raw response unusually long ({len(raw)} chars) — possible schema bleed")

    return flags


async def vet_single_ticker(
    ticker: str,
    news: list[dict],
    earnings_date: str | None,
    tavily_articles: list[dict],
    client: AsyncClient,
    model: str,
    today: str,
) -> dict:
    """
    Ask the LLM to make a single exclude/keep decision for one ticker.

    Returns a dict with the decision plus full execution trace fields:
    prompt, raw_response, latency_ms, news_titles, hallucination_flags.
    """
    user_message = _format_ticker_message(ticker, news, earnings_date, tavily_articles, today)
    news_titles = [a.get("title", "") for a in (news + tavily_articles)]

    t0 = time.monotonic()
    response = await client.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        format=PER_TICKER_SCHEMA,
        options={"temperature": 0.1, "num_predict": 256},
    )
    latency_ms = round((time.monotonic() - t0) * 1000)

    raw = response.message.content
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Invalid JSON for ticker %s: %s | raw: %s", ticker, exc, raw[:300])
        return {
            "ticker":      ticker,
            "exclude":     False,
            "reason":      f"LLM response could not be parsed — defaulting to keep. Raw: {raw[:100]}",
            "confidence":  "low",
            "risk_type":   "none",
            "had_av_news":    bool(news),
            "had_earnings":   earnings_date is not None,
            "had_tavily":     bool(tavily_articles),
            "parse_error":    True,
            "latency_ms":     latency_ms,
            "prompt":         user_message,
            "system_prompt":  SYSTEM_PROMPT,
            "raw_response":   raw,
            "news_titles":    news_titles,
            "earnings_date":  earnings_date,
            "hallucination_flags": [f"JSON parse error: {exc}"],
        }

    hallucination_flags = _detect_hallucination_flags(ticker, parsed, news, earnings_date, raw)
    if hallucination_flags:
        for flag in hallucination_flags:
            log.warning("[llm-vetter] %s hallucination flag: %s", ticker, flag)

    return {
        "ticker":      ticker,
        "exclude":     bool(parsed.get("exclude", False)),
        "reason":      parsed.get("reason", ""),
        "confidence":  parsed.get("confidence", "low"),
        "risk_type":   parsed.get("risk_type", "none"),
        "had_av_news":    bool(news),
        "had_earnings":   earnings_date is not None,
        "had_tavily":     bool(tavily_articles),
        "latency_ms":     latency_ms,
        "prompt":         user_message,
        "system_prompt":  SYSTEM_PROMPT,
        "raw_response":   raw,
        "news_titles":    news_titles,
        "earnings_date":  earnings_date,
        "hallucination_flags": hallucination_flags,
    }
