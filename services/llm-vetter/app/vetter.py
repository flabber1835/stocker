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
import re
import time
from datetime import date
from typing import Literal

import httpx

from app.tools import fetch_av_news, fetch_av_earnings_calendar, fetch_tavily_news, search_web
import asyncio

# Gateway chat endpoint helper
async def _gateway_chat(gateway_url: str, payload: dict) -> dict:
    """POST to /v1/chat and return the parsed JSON response dict."""
    async with httpx.AsyncClient(timeout=700.0) as client:
        r = await client.post(f"{gateway_url}/v1/chat", json=payload)
        r.raise_for_status()
        return r.json()

log = logging.getLogger("llm-vetter.vetter")

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

_STRICTNESS_EXCLUDE_CLAUSE = {
    "strict": """\
EXCLUDE the stock (exclude=true) when there is evidence of material concern, even if
the timing or magnitude is uncertain. Err on the side of caution — the model can always
find replacements. Reasons to exclude include:
- Any significant negative news or regulatory attention, even if the outcome is unclear
- Upcoming earnings with ANY deteriorating analyst signals (not just imminent guidance cuts)
- Multiple analyst downgrades within the past 14 days
- Material legal or regulatory proceedings with uncertain outcome
- Management changes or insider selling patterns
- Pending M&A where the stock is the TARGET (binary event risk)""",

    "moderate": """\
EXCLUDE the stock (exclude=true) only when there is CLEAR and SPECIFIC evidence of:
- Upcoming earnings with deteriorating analyst expectations, revenue warnings, or
  guidance cuts within the assessment window
- Significant NEGATIVE news that is NEW and UNPRICED: regulatory action, fraud allegation,
  product recall, key executive departure, major customer loss
- Pending binary legal or regulatory decision with material downside
- Multiple analyst consensus downgrades within the past 7 days
- Pending acquisition or merger where the stock is the TARGET and the deal has not
  yet closed — binary event risk (deal break, arb spread collapse, regulatory block)

Do NOT exclude based on:
- General macro or market uncertainty (applies to all stocks equally)
- Minor price weakness with no specific catalyst
- Long-term concerns that do not affect the holding period
- Absence of news after searching — silence is neutral, not negative
- Known challenges that are already reflected in the stock's valuation (high EY, low PB)""",

    "permissive": """\
EXCLUDE the stock (exclude=true) ONLY when there is an IMMINENT, HIGH-CONVICTION,
BINARY event that materially threatens the investment within the exact holding period:
- Earnings already expected to massively miss consensus with explicit analyst warnings
- Active regulatory shutdown, trading halt, or SEC fraud enforcement action
- Announced deal break in a pending acquisition (stock is target)

Do NOT exclude for:
- Uncertain or speculative risks
- Downgrades without accompanying price target cuts below current price
- Long-term fundamental concerns
- Any macro risk
- Any risk already visible in the valuation metrics (the model selected this for a reason)
- Absence of news — silence is strongly neutral in permissive mode""",
}


def _build_system_prompt(
    entry_rank: int = 25,
    exit_rank: int = 40,
    confirmation_days: int = 3,
    risk_horizon_days: int = 90,
    strictness: str = "moderate",
    system_prompt_override: str | None = None,
) -> str:
    exclude_clause = _STRICTNESS_EXCLUDE_CLAUSE.get(strictness, _STRICTNESS_EXCLUDE_CLAUSE["moderate"])
    if system_prompt_override is not None:
        return system_prompt_override.format(
            entry_rank=entry_rank,
            exit_rank=exit_rank,
            confirmation_days=confirmation_days,
            risk_horizon_days=risk_horizon_days,
            exclude_clause=exclude_clause,
        )
    return f"""\
You are a financial risk analyst embedded in a quantitative equity strategy. Your sole
job is to review one stock at a time and decide whether to EXCLUDE it from the portfolio,
and whether a POSITIVE CATALYST exists that the quant model may have missed.

You are a last-mile filter — not a stock picker. The quant model has already done the
heavy lifting. You are looking for specific, recent, unpriced negative events.

PORTFOLIO MODEL: Buffer-zone strategy — variable holding periods, typically weeks to
several months. No fixed sell date.
  Entry: rank ≤ {entry_rank} for {confirmation_days} consecutive daily ranking runs
  Hold:  rank stays ≤ {exit_rank}  (buffer — prevents whipsawing)
  Exit:  rank > {exit_rank} for {confirmation_days} consecutive runs

  CANDIDATE FOR ENTRY → apply entry standard (normal scrutiny)
  ALREADY HELD → apply exit standard (prefer continuation; only exclude for a genuinely
                 new, unpriced risk that materially changes the investment thesis)

RISK ASSESSMENT WINDOW: {risk_horizon_days} days. Events beyond this window are background
noise unless they represent structural changes (fraud, going-concern, business model collapse).

QUANTITATIVE CONTEXT: Rank, factor z-scores, sector, and active regime are in the user message.

  Rank calibration — harder bar for exclusion as rank decreases:
    Rank 1–10  → top quant conviction; require clear, specific, verified evidence to exclude
    Rank 11–30 → normal bar
    Rank 31–50 → lower quant conviction; give more weight to credible concerns

  Factor z-scores explain WHY the model selected the stock (scores clipped at ±2.5):
    quality=+2.1   → strong profitability and balance sheet
    momentum=+1.8  → strong recent price trend vs universe
    value=+2.0     → cheap relative to peers (may look "distressed" — that is intentional)
    growth=+1.5    → accelerating revenues or earnings
    low_volatility=+1.8 → low realized return volatility

    ⚠ A stock with value=+2.3 and quality=-0.5 was selected BECAUSE it is cheap and
      somewhat distressed. Excluding it for "weak margins" defeats the value thesis.
      Only exclude if the distress is NEW and WORSENING beyond what the valuation reflects.

  Regime: the active regime determines which factors are weighted most heavily.
    bull_calm   → momentum-heavy weights
    bull_stress → quality and low-volatility weighted more
    bear_stress → maximum defensive posture; quality and low-vol dominate
    bear_calm   → value works; orderly declining market

THE CORE PRINCIPLE: Only exclude for risks that are ALL THREE of:
  1. SPECIFIC  — names this company, not just the sector or market
  2. RECENT    — happened within the past {risk_horizon_days} days
  3. UNPRICED  — not already reflected in the factor scores or valuation

General macro uncertainty, long-term secular headwinds, and known challenges visible in
the valuation are NOT reasons to exclude. Silence is neutral, not negative.

WEB SEARCH: Use 1–2 targeted searches per ticker before deciding.
  Good queries: "TICKER earnings guidance Q2 2026" / "TICKER SEC filing regulatory 2026"
  Never repeat a query already issued for this ticker.

STRICT RULE: Do not assert any specific fact (earnings date, analyst name, price target,
guidance figure) unless it appears verbatim in the provided news or a search result you
received. If you cannot verify it, do not state it.

{exclude_clause}

CONFIDENCE:
  "high"   → clear, imminent, specific, verified risk (you can cite the source)
  "medium" → credible concern but uncertain timing or magnitude
  "low"    → weak signal; not actionable alone

If not excluding: set risk_type="none" and briefly explain why the stock is safe to hold.

POSITIVE CATALYST — LOCKED UNIT (all three must be consistent):
  positive_catalyst=true  → conviction must be "high"/"medium"/"low" based on evidence
                            reason must cite the specific source
  positive_catalyst=false → conviction MUST be "none", reason MUST be "" (empty string)
                            No partial credit. No "mild tailwinds." Silence is neutral.

  Set positive_catalyst=true ONLY for:
  - Upcoming earnings with explicit upward estimate revisions or beat expectation
  - Analyst upgrade or price target increase published within the past 14 days (cited)
  - Specific contract win, regulatory approval, or major partnership (cited, recent)
  - Significant insider buying from a named SEC filing (cited)
"""


def _format_ticker_message(
    ticker: str,
    news: list[dict],
    earnings_date: str | None,
    tavily_articles: list[dict],
    today: str,
    entry_rank: int = 25,
    exit_rank: int = 40,
    confirmation_days: int = 3,
    risk_horizon_days: int = 90,
    rank: int | None = None,
    total_candidates: int | None = None,
    composite_score: float | None = None,
    factor_scores: dict | None = None,
    sector: str | None = None,
    regime: str | None = None,
    in_portfolio: bool = False,
) -> str:
    lines = [
        f"Today: {today}",
        f"Ticker: {ticker}",
        f"Portfolio model: enter at rank ≤ {entry_rank} (×{confirmation_days} days), "
        f"exit at rank > {exit_rank} (×{confirmation_days} days). "
        f"Risk horizon: {risk_horizon_days} days.",
        "",
    ]

    # Quantitative standing section — always shown (portfolio status is always meaningful)
    lines.append("QUANTITATIVE STANDING (why the model selected this stock):")
    if rank is not None:
        # Avoid misleading "top 100%" for the lowest-ranked candidate
        pct = f" (top {round(rank / total_candidates * 100):.0f}%)" if total_candidates and rank < total_candidates else ""
        lines.append(f"  Rank: {rank}{f' of {total_candidates}' if total_candidates else ''}{pct}")
    if composite_score is not None:
        lines.append(f"  Composite score: {composite_score:.4f}")
    if factor_scores:
        fs_str = ", ".join(f"{k}={v:+.2f}" for k, v in sorted(factor_scores.items()) if v is not None)
        lines.append(f"  Factor z-scores: {fs_str}")
    if regime:
        lines.append(f"  Active regime: {regime}  ← USE THIS REGIME. Do not substitute a different one.")
    if sector:
        lines.append(f"  Sector: {sector}")
    lines.append(
        f"  Portfolio status: {'ALREADY HELD — assess continuation risk' if in_portfolio else 'CANDIDATE FOR ENTRY — assess entry risk'}"
    )
    lines.append("")

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
    *,
    news_lookback_days: int = 7,
    max_articles_per_ticker: int = 4,
    earnings_horizon_days: int = 90,
    max_search_results: int = 5,
) -> tuple[dict[str, list[dict]], dict[str, str | None], dict[str, list[dict]], dict]:
    """
    Pre-fetch all external data for the candidate list concurrently.

    Returns (av_news, earnings_calendar, tavily_results, data_source_counts).
    """
    av_news, earnings_calendar = await asyncio.gather(
        fetch_av_news(tickers, av_api_key, lookback_days=news_lookback_days, max_articles_per_ticker=max_articles_per_ticker),
        fetch_av_earnings_calendar(tickers, av_api_key, earnings_horizon_days=earnings_horizon_days),
    )

    tavily_results: dict[str, list[dict]] = {}
    if tavily_api_key:
        # Fetch Tavily for all tickers unconditionally so recent events (earnings
        # surprises, SEC actions, analyst downgrades from the past week) are always
        # captured regardless of AV news coverage.
        log.info("Fetching Tavily for all %d tickers", len(tickers))
        fetched = await asyncio.gather(
            *[fetch_tavily_news(t, tavily_api_key, max_results=max_search_results) for t in tickers]
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
    regime: str | None = None,
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
    has_data = bool(news or earnings_date or tavily_articles or agent_searches)

    # Exclude with no data and high/medium confidence is suspicious
    if exclude and not has_data and confidence in ("high", "medium"):
        flags.append(f"EXCLUDE with {confidence} confidence but no news/earnings/search data provided")

    # Exclude with no supporting data at any confidence is suspicious
    if exclude and not has_data:
        flags.append("EXCLUDE with no supporting data (no news, no earnings date, no search results)")

    # Exclude with risk_type=none is contradictory
    if exclude and risk_type == "none":
        flags.append("EXCLUDE decision but risk_type='none' — contradictory")

    # Keep with high/medium confidence and a non-none risk_type is contradictory
    if not exclude and confidence in ("high", "medium") and risk_type != "none":
        flags.append(f"KEEP with {confidence} confidence but risk_type='{risk_type}' — contradictory")

    # Very short reason suggests the model didn't reason properly
    if len(reason) < 25:
        flags.append(f"Reason suspiciously short ({len(reason)} chars): '{reason}'")

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

    # Future date hallucination: reason or positive_reason references an unexpected year
    if today:
        current_year = today[:4]
        next_year = str(int(current_year) + 1)
        allowed_years = {current_year, next_year}
        years_in_reason = set(re.findall(r"\b20\d\d\b", reason))
        bad_years = years_in_reason - allowed_years
        if bad_years:
            flags.append(f"Reason references unexpected year(s) {bad_years} — possible date hallucination")
        positive_reason = parsed.get("positive_reason", "")
        years_in_positive_reason = set(re.findall(r"\b20\d\d\b", positive_reason))
        bad_positive_years = years_in_positive_reason - allowed_years
        if bad_positive_years:
            flags.append(f"positive_reason references unexpected year(s) {bad_positive_years} — possible date hallucination")

    # Contradiction: positive_catalyst=True but positive_reason is empty/very short
    positive_reason_text = parsed.get("positive_reason", "")
    if parsed.get("positive_catalyst", False) and len(positive_reason_text.strip()) < 15:
        flags.append(f"positive_catalyst=True but positive_reason is empty/too short ({len(positive_reason_text)} chars)")

    # Contradiction: positive_catalyst=False but conviction is not 'none'
    positive_conviction = parsed.get("positive_conviction", "none")
    if not parsed.get("positive_catalyst", False) and positive_conviction not in ("none", ""):
        flags.append(f"positive_catalyst=False but positive_conviction='{positive_conviction}' — contradictory")

    # Regime hallucination: reason cites a regime name that doesn't match the input regime
    all_regimes = {"bull_calm", "bull_stress", "bear_calm", "bear_stress"}
    if regime and regime in all_regimes:
        wrong_regimes = all_regimes - {regime}
        reason_lower = reason.lower()
        cited_wrong = [r for r in wrong_regimes if r in reason_lower]
        if cited_wrong:
            flags.append(
                f"Reason references regime(s) {cited_wrong} but active regime is '{regime}' — regime hallucination"
            )

    return flags


async def vet_single_ticker(
    ticker: str,
    news: list[dict],
    earnings_date: str | None,
    tavily_articles: list[dict],
    gateway_url: str,
    today: str,
    tavily_api_key: str = "",
    entry_rank: int = 25,
    exit_rank: int = 40,
    confirmation_days: int = 3,
    risk_horizon_days: int = 90,
    max_searches_per_ticker: int = 3,
    strictness: Literal["strict", "moderate", "permissive"] = "moderate",
    max_search_results: int = 5,
    system_prompt_override: str | None = None,
    rank: int | None = None,
    total_candidates: int | None = None,
    composite_score: float | None = None,
    factor_scores: dict | None = None,
    sector: str | None = None,
    regime: str | None = None,
    in_portfolio: bool = False,
) -> dict:
    """
    Ask the LLM to make a single exclude/keep decision for one ticker.

    When tavily_api_key is provided the model runs as an agent: it can call
    web_search up to max_searches_per_ticker times before giving its final decision.
    Without a Tavily key it falls back to a single structured call.

    Returns a dict with the decision plus full execution trace fields.
    """
    vetter_config = {
        "entry_rank": entry_rank,
        "exit_rank": exit_rank,
        "confirmation_days": confirmation_days,
        "risk_horizon_days": risk_horizon_days,
        "strictness": strictness,
        "max_searches_per_ticker": max_searches_per_ticker,
        "rank": rank,
        "composite_score": composite_score,
        "sector": sector,
        "regime": regime,
        "in_portfolio": in_portfolio,
    }
    system_prompt = _build_system_prompt(
        entry_rank=entry_rank,
        exit_rank=exit_rank,
        confirmation_days=confirmation_days,
        risk_horizon_days=risk_horizon_days,
        strictness=strictness,
        system_prompt_override=system_prompt_override,
    )
    user_message = _format_ticker_message(
        ticker, news, earnings_date, tavily_articles, today,
        entry_rank=entry_rank,
        exit_rank=exit_rank,
        confirmation_days=confirmation_days,
        risk_horizon_days=risk_horizon_days,
        rank=rank,
        total_candidates=total_candidates,
        composite_score=composite_score,
        factor_scores=factor_scores,
        sector=sector,
        regime=regime,
        in_portfolio=in_portfolio,
    )
    # Use a set to deduplicate titles; list preserves insertion order via dict.fromkeys.
    _seen_titles: set[str] = set()
    news_titles: list[str] = []
    for a in (news + tavily_articles):
        t = a.get("title", "")
        if t and t not in _seen_titles:
            _seen_titles.add(t)
            news_titles.append(t)
    agent_searches: list[dict] = []

    t0 = time.monotonic()

    # Build the web_search ToolDef for the gateway (unified format)
    web_search_tool = {
        "name": AGENT_TOOLS[0]["function"]["name"],
        "description": AGENT_TOOLS[0]["function"]["description"],
        "parameters": AGENT_TOOLS[0]["function"]["parameters"],
    }

    if tavily_api_key:
        # ── Agentic loop ─────────────────────────────────────────────────────
        # Messages use unified gateway format (no system role — system is top-level)
        messages: list[dict] = [
            {"role": "user", "content": user_message},
        ]

        tool_calls_made = False
        loop_ended_on_tool_call = False

        for _ in range(max_searches_per_ticker):
            payload = {
                "system": system_prompt,
                "messages": messages,
                "tools": [web_search_tool],
                "temperature": 0.1,
                "max_tokens": 512,
            }
            resp_data = await _gateway_chat(gateway_url, payload)

            resp_tool_calls = resp_data.get("tool_calls", [])

            if not resp_tool_calls:
                # Model is ready to decide — preserve its reasoning in context
                messages.append({"role": "assistant", "content": resp_data.get("content", "")})
                break

            tool_calls_made = True

            # Append assistant message with tool_calls in unified format
            asst_msg: dict = {
                "role": "assistant",
                "content": resp_data.get("content", ""),
                "tool_calls": resp_tool_calls,  # [{id, name, arguments}]
            }
            messages.append(asst_msg)

            for tc in resp_tool_calls:
                fn_name = tc["name"]
                args = tc.get("arguments", {}) if isinstance(tc.get("arguments"), dict) else {}
                query = args.get("query", "")
                tc_id = tc.get("id", "call_0")

                log.info("[agent] %s → %s(%r)", ticker, fn_name, query)

                if fn_name == "web_search" and query:
                    results = await search_web(query, tavily_api_key, max_results=max_search_results)
                    # Filter to articles not already seen from pre-fetch or prior searches.
                    new_results = [r for r in results if r["title"] not in _seen_titles]
                    agent_searches.append({"query": query, "result_count": len(new_results)})
                    if new_results:
                        result_text = "\n\n".join(
                            f"**{r['title']}**\n{r['content']}"
                            for r in new_results
                        )
                        for r in new_results:
                            _seen_titles.add(r["title"])
                            news_titles.append(r["title"])
                    else:
                        result_text = "No new results found (all results already seen)."
                else:
                    result_text = f"Unknown tool: {fn_name}"
                    agent_searches.append({"query": query, "result_count": 0, "error": "unknown tool"})

                # Tool result in unified format
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": fn_name,
                    "content": result_text,
                })
        else:
            # Loop exhausted MAX_TOOL_CALLS and the last response was still requesting
            # tool calls (never produced a text response). Those unfetched tool calls
            # are dropped. Append a note so the final prompt has a clean message to
            # respond to rather than a dangling tool-call assistant message.
            loop_ended_on_tool_call = True
            messages.append({
                "role": "user",
                "content": "Search limit reached. Synthesize your decision from the information gathered so far.",
            })

        # Final structured decision — enforce schema.
        # When loop_ended_on_tool_call=True the previous message is already a user
        # message ("Search limit reached..."), so do NOT append another user message
        # to avoid back-to-back user messages which some backends reject.
        if not loop_ended_on_tool_call:
            final_prompt = (
                "Based on your research, provide your final KEEP or EXCLUDE decision."
                if tool_calls_made else
                "Provide your KEEP or EXCLUDE decision."
            )
            messages.append({"role": "user", "content": final_prompt})

        final_payload = {
            "system": system_prompt,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 256,
            "response_schema": PER_TICKER_SCHEMA,
        }
        final_resp_data = await _gateway_chat(gateway_url, final_payload)

    else:
        # ── Single-call fallback (no Tavily configured) ───────────────────────
        final_payload = {
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
            "temperature": 0.1,
            "max_tokens": 256,
            "response_schema": PER_TICKER_SCHEMA,
        }
        final_resp_data = await _gateway_chat(gateway_url, final_payload)

    latency_ms = round((time.monotonic() - t0) * 1000)
    raw = (final_resp_data.get("content") or "").strip()

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
            "system_prompt":  system_prompt,
            "raw_response":   raw,
            "news_titles":    news_titles,
            "earnings_date":  earnings_date,
            "vetter_config": vetter_config,
            "hallucination_flags": [f"JSON parse error: {exc}"],
        }

    hallucination_flags = _detect_hallucination_flags(
        ticker, parsed, news, earnings_date, raw, today=today,
        tavily_articles=tavily_articles, agent_searches=agent_searches,
        regime=regime,
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

    # Positive conviction override: clear catalyst entirely when no supporting data.
    # Leaving positive_catalyst=True with conviction="low" and empty reason is
    # internally contradictory (the LOCKED UNIT rule) and still triggers a small
    # score boost in portfolio-builder with zero evidentiary basis.
    if (
        parsed.get("positive_catalyst", False)
        and not has_any_supporting_data
        and parsed.get("positive_conviction", "none") in ("high", "medium")
    ):
        log.warning(
            "[llm-vetter] %s: clearing positive catalyst — %s conviction with no supporting data",
            ticker, parsed["positive_conviction"],
        )
        parsed["positive_catalyst"] = False
        parsed["positive_conviction"] = "none"
        parsed["positive_reason"] = ""
        hallucination_flags.append(
            "positive_catalyst cleared (was high/medium conviction with no supporting data)"
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
        "system_prompt":  system_prompt,
        "raw_response":   raw,
        "news_titles":    news_titles,
        "earnings_date":  earnings_date,
        "vetter_config": vetter_config,
        "hallucination_flags": hallucination_flags,
    }
