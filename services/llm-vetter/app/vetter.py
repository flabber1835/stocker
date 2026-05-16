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

from app.tools import fetch_av_news, fetch_av_earnings_calendar, fetch_tavily_news, search_web
import asyncio

log = logging.getLogger("llm-vetter.vetter")

MAX_TOOL_CALLS = 3  # max web searches the agent may make per ticker

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for recent news, analyst reports, earnings guidance, "
                "SEC filings, or regulatory news about a specific stock. "
                "Use targeted queries such as 'MRNA Moderna earnings guidance 2026' "
                "or 'CENX Century Aluminum SEC filing regulatory 2026'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Specific search query for the stock",
                    }
                },
                "required": ["query"],
            },
        },
    }
]

# Structured-output schema for a single-ticker decision
PER_TICKER_SCHEMA = {
    "type": "object",
    "properties": {
        "exclude":              {"type": "boolean"},
        "reason":               {"type": "string"},
        "confidence":           {"type": "string", "enum": ["high", "medium", "low"]},
        "risk_type":            {
            "type": "string",
            "enum": ["earnings", "regulatory", "management", "legal", "sector", "none"],
        },
        "positive_catalyst":    {"type": "boolean"},
        "positive_conviction":  {"type": "string", "enum": ["high", "medium", "low", "none"]},
        "positive_reason":      {"type": "string"},
    },
    "required": [
        "exclude", "reason", "confidence", "risk_type",
        "positive_catalyst", "positive_conviction", "positive_reason",
    ],
}

SYSTEM_PROMPT = """\
You are a financial risk analyst reviewing stocks selected by a quantitative equity
strategy. Each stock was chosen because it scored highly on quality, value, momentum,
growth, or low-volatility factors — or some combination. Your job is to decide
whether to EXCLUDE a single stock from a 30-day equity portfolio holding.

IMPORTANT CONTEXT: The quantitative model selects stocks for investment thesis reasons.
A deep-value stock may intentionally be distressed. A momentum stock may already be
priced for growth. Before excluding, consider whether the risk you found is ALREADY
REFLECTED in why the model selected this stock, or whether it is a NEW, UNPRICED risk.


You have a web_search tool. Use it proactively — run 1-2 targeted searches per
ticker to check for risks even when no news is pre-loaded. Good queries:
  "TICKER company name earnings guidance Q2 2026"
  "TICKER company name analyst downgrade SEC filing 2026"
  "TICKER company name recall lawsuit regulatory news"

EXCLUDE the stock (exclude=true) only when there is CLEAR and SPECIFIC evidence of:
- Upcoming earnings with deteriorating analyst expectations, revenue warnings, or
  guidance cuts likely within the 30-day window
- Significant NEGATIVE news that is NEW and UNPRICED: regulatory action, fraud allegation,
  product recall, key executive departure, major customer loss
- Pending binary legal or regulatory decision with material downside
- Multiple analyst consensus downgrades within the past 7 days
- Pending acquisition or merger where the stock is the TARGET and the deal has not
  yet closed — binary event risk (deal break, arb spread collapse, regulatory block)

Do NOT exclude based on:
- General macro or market uncertainty (applies to all stocks equally)
- Minor price weakness with no specific catalyst
- Long-term concerns that do not affect the next 30 days
- Absence of news after searching — silence is neutral, not negative
- Known challenges that are already reflected in the stock's valuation (high EY, low PB)

Set confidence:
  "high"   — clear, imminent, specific risk that is NEW and UNPRICED
  "medium" — material concern but uncertain timing or magnitude
  "low"    — weak signal, worth noting but not strongly actionable

If not excluding, set risk_type to "none" and explain briefly why the stock is
safe to hold for 30 days given available information.

POSITIVE CATALYST ASSESSMENT:
In the same pass, assess whether there is a POSITIVE catalyst likely to drive
outperformance in the next 30 days. Set positive_catalyst=true only when there
is CLEAR and SPECIFIC evidence of:
- Upcoming earnings where analyst consensus expects a strong beat, or recent
  upward estimate revisions explicitly cited
- Analyst upgrades or price target increases published within the past 14 days
- Positive product launch, major contract win, regulatory approval, or
  partnership announcement that is recent and specific
- Significant insider buying signal from a filing you can cite

The same evidence rules apply to positive_conviction as to confidence:
  "high"   — specific, verifiable, recent positive catalyst with a cited source
  "medium" — material positive signal but uncertain timing or magnitude
  "low"    — mild tailwind worth noting, weakly supported
  "none"   — no clear positive catalyst found (most common — default to this)

If no positive catalyst exists, set positive_catalyst=false,
positive_conviction="none", positive_reason="" (empty string).
Do NOT invent positive reasons. Silence is neutral, not positive.
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
        # Fetch Tavily for all tickers unconditionally so recent events (earnings
        # surprises, SEC actions, analyst downgrades from the past week) are always
        # captured regardless of AV news coverage.
        log.info("Fetching Tavily for all %d tickers", len(tickers))
        fetched = await asyncio.gather(
            *[fetch_tavily_news(t, tavily_api_key) for t in tickers]
        )
        tavily_results = dict(zip(tickers, fetched))

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
    today: str | None = None,
    tavily_articles: list[dict] | None = None,
    agent_searches: list[dict] | None = None,
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

    # Keep with high/medium confidence and a non-none risk_type is contradictory
    if not exclude and confidence in ("high", "medium") and risk_type != "none":
        flags.append(f"KEEP with {confidence} confidence but risk_type='{risk_type}' — contradictory")

    # Very short reason suggests the model didn't reason properly
    if len(reason) < 25:
        flags.append(f"Reason suspiciously short ({len(reason)} chars): '{reason}'")

    # Reason doesn't mention the ticker (model may have confused tickers).
    # Only meaningful when data was provided — generic "no news" reasons are expected otherwise.
    has_data = bool(news) or earnings_date is not None or bool(tavily_articles) or bool(agent_searches)
    if has_data and ticker.upper() not in reason.upper() and len(reason) > 50:
        flags.append(f"Reason does not mention ticker '{ticker}' — possible ticker confusion")

    # Raw JSON unexpectedly long (model leaked extra content outside schema)
    if len(raw) > 800:
        flags.append(f"Raw response unusually long ({len(raw)} chars) — possible schema bleed")

    # Contradiction: reason says "no concerns" / "no risk" but exclude=True
    no_concern_phrases = ("no concerns", "no significant", "no material", "no risk", "safe to hold", "no issues")
    if exclude and any(p in reason.lower() for p in no_concern_phrases):
        flags.append("Reason language suggests no concern but exclude=True — contradiction")

    # Contradiction: exclude=True and positive_catalyst=True simultaneously
    positive_catalyst = parsed.get("positive_catalyst", False)
    if exclude and positive_catalyst:
        flags.append("exclude=True and positive_catalyst=True simultaneously — contradictory")

    # Future date hallucination: earnings_date provided but reason references a different date
    if earnings_date and today:
        # Check if reason mentions a year that doesn't match today's year (crude check)
        import re as _re
        years_in_reason = set(_re.findall(r"\b20\d\d\b", reason))
        current_year = today[:4]
        next_year = str(int(current_year) + 1)
        bad_years = years_in_reason - {current_year, next_year}
        if bad_years:
            flags.append(f"Reason references unexpected year(s) {bad_years} — possible date hallucination")

    return flags


async def vet_single_ticker(
    ticker: str,
    news: list[dict],
    earnings_date: str | None,
    tavily_articles: list[dict],
    client: AsyncClient,
    model: str,
    today: str,
    tavily_api_key: str = "",
) -> dict:
    """
    Ask the LLM to make a single exclude/keep decision for one ticker.

    When tavily_api_key is provided the model runs as an agent: it can call
    web_search up to MAX_TOOL_CALLS times before giving its final decision.
    Without a Tavily key it falls back to a single structured call.

    Returns a dict with the decision plus full execution trace fields.
    """
    user_message = _format_ticker_message(ticker, news, earnings_date, tavily_articles, today)
    news_titles = [a.get("title", "") for a in (news + tavily_articles)]
    agent_searches: list[dict] = []

    t0 = time.monotonic()

    if tavily_api_key:
        # ── Agentic loop ─────────────────────────────────────────────────────
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ]

        tool_calls_made = False

        for _ in range(MAX_TOOL_CALLS):
            resp = await client.chat(
                model=model,
                messages=messages,
                tools=AGENT_TOOLS,
                options={"temperature": 0.1},
            )

            if not resp.message.tool_calls:
                # Model is ready to decide — preserve its reasoning in context
                messages.append({"role": "assistant", "content": resp.message.content or ""})
                break

            tool_calls_made = True

            # Serialize the assistant message with tool_calls as a plain dict
            asst_msg: dict = {
                "role": "assistant",
                "content": resp.message.content or "",
                "tool_calls": [
                    {
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments if isinstance(tc.function.arguments, dict) else {},
                        }
                    }
                    for tc in resp.message.tool_calls
                ],
            }
            messages.append(asst_msg)

            for tc in resp.message.tool_calls:
                fn_name = tc.function.name
                args = tc.function.arguments if isinstance(tc.function.arguments, dict) else {}
                query = args.get("query", "")

                log.info("[agent] %s → %s(%r)", ticker, fn_name, query)

                if fn_name == "web_search" and query:
                    results = await search_web(query, tavily_api_key)
                    agent_searches.append({"query": query, "result_count": len(results)})
                    if results:
                        result_text = "\n\n".join(
                            f"**{r['title']}**\n{r['content']}"
                            for r in results
                        )
                        news_titles += [r["title"] for r in results]
                    else:
                        result_text = "No results found."
                else:
                    result_text = f"Unknown tool: {fn_name}"
                    agent_searches.append({"query": query, "result_count": 0, "error": "unknown tool"})

                messages.append({"role": "tool", "content": result_text})

        # Final structured decision — enforce schema, remind model if it searched
        final_prompt = (
            "Based on your research, provide your final KEEP or EXCLUDE decision."
            if tool_calls_made else
            "Provide your KEEP or EXCLUDE decision."
        )
        messages.append({"role": "user", "content": final_prompt})
        response = await client.chat(
            model=model,
            messages=messages,
            format=PER_TICKER_SCHEMA,
            options={"temperature": 0.1, "num_predict": 256},
        )

    else:
        # ── Single-call fallback (no Tavily configured) ───────────────────────
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
    raw = (response.message.content or "").strip()

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
            "positive_catalyst":   False,
            "positive_conviction": "none",
            "positive_reason":     "",
            "had_av_news":    bool(news),
            "had_earnings":   earnings_date is not None,
            "had_tavily":     bool(tavily_articles),
            "parse_error":    True,
            "agent_searches": agent_searches,
            "latency_ms":     latency_ms,
            "prompt":         user_message,
            "system_prompt":  SYSTEM_PROMPT,
            "raw_response":   raw,
            "news_titles":    news_titles,
            "earnings_date":  earnings_date,
            "hallucination_flags": [f"JSON parse error: {exc}"],
        }

    hallucination_flags = _detect_hallucination_flags(
        ticker, parsed, news, earnings_date, raw, today=today,
        tavily_articles=tavily_articles, agent_searches=agent_searches,
    )
    if hallucination_flags:
        for flag in hallucination_flags:
            log.warning("[llm-vetter] %s hallucination flag: %s", ticker, flag)

    # Hard override: reverse exclusions that have no data support at high/medium confidence.
    # Checks all sources: AV news, Tavily pre-fetch, agent web searches, earnings calendar.
    all_sources = news + tavily_articles
    agent_found_data = any(s.get("result_count", 0) > 0 for s in agent_searches)
    has_any_supporting_data = bool(all_sources) or earnings_date is not None or agent_found_data

    if (
        parsed.get("exclude", False)
        and not has_any_supporting_data
        and parsed.get("confidence", "low") in ("high", "medium")
    ):
        original_confidence = parsed["confidence"]
        log.warning(
            "[llm-vetter] %s: AUTO-OVERRIDE — exclude=True with %s confidence but no data found; reversing to KEEP",
            ticker, original_confidence,
        )
        parsed["exclude"] = False
        parsed["confidence"] = "low"
        parsed["reason"] = (
            f"[AUTO-OVERRIDE: exclusion reversed — no news, no earnings, no search results found. "
            f"Original model decision was exclude=True with {original_confidence} confidence.] "
            + parsed.get("reason", "")
        )
        hallucination_flags.append(
            f"AUTO-OVERRIDDEN: exclude=True ({original_confidence} confidence) with no supporting data → forced to KEEP"
        )

    # Positive conviction override: downgrade high/medium positive conviction with no data
    if (
        parsed.get("positive_catalyst", False)
        and not has_any_supporting_data
        and parsed.get("positive_conviction", "none") in ("high", "medium")
    ):
        log.warning(
            "[llm-vetter] %s: downgrading positive_conviction from %s → low (no supporting data)",
            ticker, parsed["positive_conviction"],
        )
        parsed["positive_conviction"] = "low"
        hallucination_flags.append(
            f"positive_conviction downgraded to 'low' — no supporting data found"
        )


    return {
        "ticker":      ticker,
        "exclude":     bool(parsed.get("exclude", False)),
        "reason":      parsed.get("reason", ""),
        "confidence":  parsed.get("confidence", "low"),
        "risk_type":   parsed.get("risk_type", "none"),
        "positive_catalyst":   bool(parsed.get("positive_catalyst", False)),
        "positive_conviction": parsed.get("positive_conviction", "none"),
        "positive_reason":     parsed.get("positive_reason", ""),
        "had_av_news":    bool(news),
        "had_earnings":   earnings_date is not None,
        "had_tavily":     bool(tavily_articles),
        "agent_searches": agent_searches,
        "latency_ms":     latency_ms,
        "prompt":         user_message,
        "system_prompt":  SYSTEM_PROMPT,
        "raw_response":   raw,
        "news_titles":    news_titles,
        "earnings_date":  earnings_date,
        "hallucination_flags": hallucination_flags,
    }
