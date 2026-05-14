"""
Core vetting logic: pre-fetches news + earnings data for each candidate ticker,
then asks the LLM to identify 30-day holding risks.

Design choices:
- Data is pre-fetched and formatted before the LLM call. This avoids tool-calling
  latency (30+ round trips) and keeps the LLM focused on reasoning, not retrieval.
- A single structured-output call handles all candidates at once. qwen2.5:14b
  handles 100-ticker contexts reliably within its window.
- Tavily is used as a fallback for tickers that AV returned no news on.
- Temperature is set very low (0.1) for consistent, reproducible JSON output.
"""

import asyncio
import logging
from datetime import date

from ollama import AsyncClient

from app.tools import fetch_av_news, fetch_av_earnings_calendar, fetch_tavily_news

log = logging.getLogger("llm-vetter.vetter")

# JSON schema for Ollama structured output — qwen2.5 respects this reliably
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "exclusions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker":     {"type": "string"},
                    "reason":     {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "risk_type":  {"type": "string"},
                },
                "required": ["ticker", "reason", "confidence", "risk_type"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["exclusions", "summary"],
}

SYSTEM_PROMPT = """\
You are a financial risk analyst reviewing stocks for a 30-day equity portfolio holding.

Your task: identify stocks in the provided list that carry specific, identifiable risks
that make a 30-day holding inadvisable RIGHT NOW. You are given recent news and upcoming
earnings dates for each stock.

Reasons to flag a stock for EXCLUSION:
- Upcoming earnings within 30 days with clear signs of expected disappointment
  (analyst estimate cuts, revenue warnings, margin pressure commentary)
- Significant negative news: regulatory action, fraud allegations, product recall,
  key executive departure, major customer loss
- Pending legal or regulatory decisions with binary outcomes
- Recent analyst consensus downgrades (multiple downgrades in past week)

Do NOT flag based on:
- General market uncertainty or macro concerns that apply to all stocks
- Minor price weakness without a specific catalyst
- Long-term structural concerns that don't affect the next 30 days
- Absence of news (silence is neutral, not negative)

Be conservative: only flag stocks with CLEAR and SPECIFIC evidence. The portfolio
algorithm has already filtered for quality; your job is to catch near-term event risk
that a quantitative model cannot see.

Respond with a JSON object matching the schema. Set confidence to:
- "high":   clear evidence of imminent specific risk
- "medium": material concern but uncertain timing or magnitude
- "low":    weak signal worth noting but not strongly actionable
"""


def _format_candidate_block(
    ticker: str,
    news: list[dict],
    earnings_date: str | None,
    tavily_articles: list[dict],
) -> str:
    lines = [f"### {ticker}"]

    if earnings_date:
        lines.append(f"UPCOMING EARNINGS: {earnings_date}")

    all_articles = news + tavily_articles
    if all_articles:
        lines.append("RECENT NEWS:")
        for a in all_articles:
            sentiment = f" [{a['sentiment']}]" if "sentiment" in a else ""
            lines.append(f"  - {a['title']}{sentiment}")
            if a.get("summary"):
                lines.append(f"    {a['summary'][:200]}")
    else:
        lines.append("RECENT NEWS: none retrieved")

    return "\n".join(lines)


async def vet_candidates(
    candidates: list[dict],  # [{"ticker": str, "rank": int, "composite_score": float}]
    *,
    ollama_host: str,
    model: str,
    av_api_key: str,
    tavily_api_key: str,
) -> dict:
    """
    Vet a list of ranked candidates for 30-day holding risks.

    Returns:
        {
          "exclusions": [{"ticker", "reason", "confidence", "risk_type"}, ...],
          "summary": str,
          "data_sources": {"av_news": int, "earnings_calendar": int, "tavily": int},
        }
    """
    tickers = [c["ticker"] for c in candidates]
    today = date.today().isoformat()

    log.info("Fetching data for %d candidates (date=%s)", len(tickers), today)

    # Fetch AV news and earnings calendar concurrently
    av_news, earnings_calendar = await asyncio.gather(
        fetch_av_news(tickers, av_api_key),
        fetch_av_earnings_calendar(tickers, av_api_key),
    )

    # Use Tavily for tickers that AV returned no news on (if key is configured)
    tavily_results: dict[str, list[dict]] = {}
    if tavily_api_key:
        tickers_without_news = [t for t in tickers if not av_news.get(t)]
        if tickers_without_news:
            log.info("Fetching Tavily news for %d tickers with no AV data", len(tickers_without_news))
            tavily_tasks = [
                fetch_tavily_news(t, tavily_api_key)
                for t in tickers_without_news
            ]
            tavily_fetched = await asyncio.gather(*tavily_tasks)
            tavily_results = dict(zip(tickers_without_news, tavily_fetched))

    av_news_count = sum(1 for t in tickers if av_news.get(t))
    earnings_count = sum(1 for t in tickers if earnings_calendar.get(t))
    tavily_count = sum(1 for t in tickers if tavily_results.get(t))

    log.info(
        "Data summary: AV news=%d tickers, earnings=%d tickers, Tavily=%d tickers",
        av_news_count, earnings_count, tavily_count,
    )

    # Build the per-ticker data blocks
    candidate_blocks = []
    for c in candidates:
        ticker = c["ticker"]
        block = _format_candidate_block(
            ticker,
            news=av_news.get(ticker, []),
            earnings_date=earnings_calendar.get(ticker),
            tavily_articles=tavily_results.get(ticker, []),
        )
        candidate_blocks.append(block)

    user_message = (
        f"Today's date: {today}\n"
        f"Portfolio holding period: 30 days\n"
        f"Candidates to review ({len(tickers)} total):\n\n"
        + "\n\n".join(candidate_blocks)
    )

    log.info("Calling Ollama model=%s with %d candidates", model, len(tickers))

    client = AsyncClient(host=ollama_host)
    response = await client.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        format=RESPONSE_SCHEMA,
        options={"temperature": 0.1, "num_predict": 2048},
    )

    raw = response.message.content
    import json
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Failed to parse LLM response as JSON: %s\nRaw: %s", exc, raw[:500])
        raise RuntimeError(f"LLM returned invalid JSON: {exc}") from exc

    exclusions = parsed.get("exclusions", [])
    summary = parsed.get("summary", f"Reviewed {len(tickers)} candidates.")

    # Validate tickers — only keep tickers that were actually in the candidate list
    ticker_set = set(tickers)
    valid_exclusions = [e for e in exclusions if e.get("ticker") in ticker_set]
    if len(valid_exclusions) < len(exclusions):
        hallucinated = len(exclusions) - len(valid_exclusions)
        log.warning("LLM hallucinated %d tickers not in candidate list — dropped", hallucinated)

    log.info(
        "Vetting complete: %d/%d flagged for exclusion",
        len(valid_exclusions), len(tickers),
    )

    return {
        "exclusions": valid_exclusions,
        "summary": summary,
        "data_sources": {
            "av_news_tickers": av_news_count,
            "earnings_calendar_tickers": earnings_count,
            "tavily_tickers": tavily_count,
        },
    }
