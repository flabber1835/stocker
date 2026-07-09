"""
Core vetting logic for the LLM vetter.

Structured as three composable pieces so main.py can drive the loop and
log an execution_step after every individual ticker decision:

  1. fetch_ticker_data()   — pre-fetch AV news + earnings + optional Tavily
                             for all candidates concurrently (fast, one round-trip)
  2. vet_single_ticker()   — one gateway call focused on a single ticker
  3. (loop + trace in main.py)

Per-ticker prompts are more focused than a single batch prompt: the model
only sees one company at a time, so it cannot satisfice by skimming. Each
call produces ~60-80 output tokens, so total generation time on CPU is
~30 tickers × 80 tokens / 3 tok/s ≈ 13 minutes — acceptable for a
human-supervised workflow.
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import date
from typing import Literal

import httpx

from app.tools import fetch_av_news, fetch_av_earnings_calendar, fetch_tavily_news, search_web

# Timeout for gateway HTTP calls — must exceed OLLAMA_TIMEOUT_SECS in llm-gateway
_GATEWAY_TIMEOUT = float(os.getenv("GATEWAY_TIMEOUT_SECS", "700"))

# Gateway chat endpoint helper
async def _gateway_chat(gateway_url: str, payload: dict) -> dict:
    """POST to /v1/chat and return the parsed JSON response dict."""
    async with httpx.AsyncClient(timeout=_GATEWAY_TIMEOUT) as client:
        r = await client.post(f"{gateway_url}/v1/chat", json=payload)
        if not r.is_success:
            # Include the response body so the actual provider error is visible in logs.
            try:
                detail = r.json().get("detail", r.text[:300])
            except Exception:
                detail = r.text[:300]
            raise httpx.HTTPStatusError(
                f"Gateway {r.status_code}: {detail}",
                request=r.request,
                response=r,
            )
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
            "enum": [
                "earnings",     # guidance cut, miss risk, estimate revision
                "regulatory",   # SEC action, FDA, agency enforcement, trading halt
                "management",   # exec departure, insider selling, board change
                "legal",        # litigation, class action, DOJ/FTC investigation
                "competitive",  # major customer loss, market share loss, contract cancellation
                "operational",  # product recall, supply chain failure, facility issue
                "sector",       # sector-wide event not captured by above types
                "drawdown",     # severe recent price decline (falling knife) — bad entry timing
                "none",         # no material risk identified
            ],
        },
        "positive_catalyst":    {"type": "boolean"},
        "positive_reason":      {"type": "string"},
    },
    "required": [
        "exclude", "reason", "confidence", "risk_type",
        "positive_catalyst", "positive_reason",
    ],
}

_STRICTNESS_EXCLUDE_CLAUSE = {
    "strict": """\
EXCLUDE the stock (exclude=true) when there is clear evidence of a material concern that
is SPECIFIC to this company, occurred within the risk assessment window, and is NOT already
reflected in the factor scores. Err on the side of caution — the quant model will find
replacements. Reasons to exclude include:
- Upcoming earnings with ANY deteriorating analyst signals within the past 14 days
  (guidance cuts, estimate revisions, negative pre-announcements)
- Any significant new regulatory attention, legal action, or enforcement activity
- Key executive departure or insider selling pattern (reported within the assessment window)
- Multiple analyst consensus downgrades within the past 14 days
- Pending M&A where the stock is the TARGET (binary event risk — deal break or arb collapse)
- Significant new competitive setback: major customer loss, contract cancellation,
  market share data showing accelerating erosion

Do NOT exclude for long-term secular headwinds, known valuation-visible distress, or any
concern that predates the assessment window and is therefore already priced in.""",

    "moderate": """\
EXCLUDE the stock (exclude=true) only when there is CLEAR and SPECIFIC evidence of:
- Upcoming earnings with deteriorating analyst expectations, revenue warnings, or
  guidance cuts within the assessment window
- Significant NEGATIVE news that is NEW and UNPRICED:
    regulatory/legal: enforcement action, fraud allegation, SEC/FTC/DOJ investigation
    operational:      product recall, facility shutdown, supply chain failure
    competitive:      major customer loss, large contract cancellation, accelerating share loss
    management:       key executive departure (CEO/CFO), significant insider selling
- Pending binary legal or regulatory decision with material downside
- Multiple analyst consensus downgrades within the past 7 days
- Pending acquisition where the stock is the TARGET and the deal has not yet closed
  (binary event risk: deal break, arb spread collapse, regulatory block)

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
    news_lookback_days: int = 7,
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
            news_lookback_days=news_lookback_days,
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

DATA WINDOWS: The pre-fetched news below covers the past {news_lookback_days} days.
For events between day {news_lookback_days} and {risk_horizon_days} — such as an earnings
date, a regulatory filing, or a major customer announcement — use the web_search tool.
Do not speculate about events in that gap; if you cannot find them via search, treat it
as silence (neutral).

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

RISK TYPE — choose the most specific type that fits the identified risk:
  earnings     → guidance cut, estimate revision, miss risk, pre-announcement
  regulatory   → SEC/FDA/FTC/agency enforcement, trading halt, regulatory shutdown
  management   → CEO/CFO departure, insider selling, board change
  legal        → litigation, class action, DOJ investigation, legal judgment
  competitive  → major customer loss, contract cancellation, accelerating market share loss
  operational  → product recall, supply chain failure, facility shutdown, safety issue
  sector       → sector-wide event not captured by the above (last resort)
  drawdown     → severe recent price decline (a "falling knife") — bad moment to
                 enter even absent a specific news event; use when the recent
                 drawdown shown above is the primary reason to avoid the entry
  none         → no material risk identified (use when not excluding)

If not excluding: set risk_type="none" and briefly explain why the stock is safe to hold.

POSITIVE CATALYST — for display and audit purposes only; does NOT affect the stock's score
or portfolio weight. The deterministic ranker owns the final score.

  Two fields that must be consistent:
  positive_catalyst=true  → positive_reason must cite the specific source
  positive_catalyst=false → positive_reason MUST be "" (empty string)
                            No partial credit. No "mild tailwinds." Silence is neutral.

  Set positive_catalyst=true ONLY for:
  - Upcoming earnings with explicit upward estimate revisions or beat expectation
  - Analyst upgrade or price target increase published within the past 14 days (cited)
  - Specific contract win, regulatory approval, or major partnership (cited, recent)
  - Significant insider buying from a named SEC filing (cited)

OUTPUT LENGTH: Keep `reason` and `positive_reason` to 100 words or fewer each.
Be direct — one or two sentences stating the specific finding is ideal.
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
    news_lookback_days: int = 7,
    rank: int | None = None,
    total_candidates: int | None = None,
    composite_score: float | None = None,
    factor_scores: dict | None = None,
    sector: str | None = None,
    regime: str | None = None,
    in_portfolio: bool = False,
    related_tickers: list[str] | None = None,
    company_name: str | None = None,
    drawdown_21d: float | None = None,
) -> str:
    ticker_display = f"{ticker} — {company_name}" if company_name else ticker
    lines = [
        f"Today: {today}",
        f"Ticker: {ticker_display}",
    ]
    if related_tickers:
        lines.append(
            f"Share class siblings: {', '.join(related_tickers)} — "
            f"news and risk events for these tickers apply to {ticker} equally. "
            f"News from sibling tickers has been merged into the feed below."
        )
    lines += [
        f"Portfolio model: enter at rank ≤ {entry_rank} (×{confirmation_days} days), "
        f"exit at rank > {exit_rank} (×{confirmation_days} days). "
        f"Risk horizon: {risk_horizon_days} days.",
        "",
    ]

    # Quantitative standing section — always shown (portfolio status is always meaningful)
    lines.append("QUANTITATIVE STANDING (why the model selected this stock):")
    if rank is not None:
        # Show universe rank and vetter-batch size separately.
        # "Rank: 2 of 50" was ambiguous — LLMs read it as "position 2 in a 50-stock
        # portfolio" and concluded the stock was already held. Universe rank and the
        # number of candidates being vetted today are independent quantities.
        lines.append(f"  Universe rank: #{rank} (out of all ranked stocks in the investable universe)")
        if total_candidates:
            lines.append(f"  Vetter batch: {total_candidates} top-ranked candidates reviewed today")
    if composite_score is not None:
        lines.append(f"  Composite score: {composite_score:.4f}")
    if factor_scores:
        fs_str = ", ".join(f"{k}={v:+.2f}" for k, v in sorted(factor_scores.items()) if v is not None)
        lines.append(f"  Factor z-scores: {fs_str}")
    if regime:
        lines.append(f"  Active regime: {regime}  ← USE THIS REGIME. Do not substitute a different one.")
    if sector:
        lines.append(f"  Sector: {sector}")
    if drawdown_21d is not None:
        # Recent peak-to-now drawdown (21 trading days, NO skip window) — the
        # momentum z-score above skips the most recent month and can look strong
        # even after a fresh crash. This is the "falling knife" check.
        if drawdown_21d <= -0.20:
            dd_note = "  ← STEEP recent drop. Is this a one-off dislocation already priced in, or an ongoing, news-driven decline? A falling knife is a bad entry."
        elif drawdown_21d <= -0.10:
            dd_note = "  ← notable recent pullback — check whether it is news-driven."
        else:
            dd_note = ""
        lines.append(f"  Recent drawdown (21d, vs recent peak): {drawdown_21d:+.1%}{dd_note}")
    lines.append(
        f"  Portfolio status: {'ALREADY HELD — assess continuation risk' if in_portfolio else 'CANDIDATE FOR ENTRY — assess entry risk'}"
    )
    lines.append("")

    if earnings_date:
        lines.append(f"UPCOMING EARNINGS DATE: {earnings_date}")

    all_articles = news + tavily_articles
    if all_articles:
        lines.append(f"RECENT NEWS (past {news_lookback_days} days — use web_search for older events within the risk window):")
        for a in all_articles:
            sentiment = f" [{a['sentiment']}]" if "sentiment" in a else ""
            lines.append(f"  - {a['title']}{sentiment}")
            if a.get("summary"):
                lines.append(f"    {a['summary'][:250]}")
    else:
        lines.append(f"RECENT NEWS (past {news_lookback_days} days): none retrieved — use web_search to check for events within the risk window")

    return "\n".join(lines)


async def fetch_ticker_data(
    tickers: list[str],
    av_api_key: str,
    tavily_api_key: str,
    *,
    related_tickers_map: dict[str, list[str]] | None = None,
    company_name_map: dict[str, str] | None = None,
    news_lookback_days: int = 7,
    max_articles_per_ticker: int = 4,
    earnings_horizon_days: int = 90,
    max_search_results: int = 5,
) -> tuple[dict[str, list[dict]], dict[str, str | None], dict[str, list[dict]], dict]:
    """
    Pre-fetch all external data for the candidate list concurrently.

    related_tickers_map maps each canonical ticker to its share-class siblings
    (e.g. {"GOOG": ["GOOGL"]}). When provided, sibling news is fetched and
    merged into the canonical ticker's feed so the LLM sees the full picture.

    Returns (av_news, earnings_calendar, tavily_results, data_source_counts).
    """
    # Expand fetch list to include sibling tickers so their news is retrieved.
    sibling_set: set[str] = set()
    if related_tickers_map:
        for siblings in related_tickers_map.values():
            sibling_set.update(siblings)
    all_fetch_tickers = tickers + [s for s in sibling_set if s not in tickers]

    av_news_raw, earnings_calendar = await asyncio.gather(
        fetch_av_news(all_fetch_tickers, av_api_key, lookback_days=news_lookback_days,
                      max_articles_per_ticker=max_articles_per_ticker),
        fetch_av_earnings_calendar(tickers, av_api_key, earnings_horizon_days=earnings_horizon_days),
    )

    # Merge sibling news back into the canonical ticker's feed (dedup by title).
    if related_tickers_map:
        for canonical, siblings in related_tickers_map.items():
            merged = list(av_news_raw.get(canonical, []))
            seen_titles = {a.get("title", "") for a in merged}
            for sib in siblings:
                for article in av_news_raw.get(sib, []):
                    title = article.get("title", "")
                    if title not in seen_titles:
                        merged.append(article)
                        seen_titles.add(title)
            if merged:
                av_news_raw[canonical] = merged

    # Only expose canonical tickers in the returned av_news dict.
    av_news: dict[str, list[dict]] = {t: av_news_raw.get(t, []) for t in tickers}

    tavily_results: dict[str, list[dict]] = {}
    if tavily_api_key:
        # Fetch Tavily for canonical tickers and siblings so recent events
        # (earnings surprises, SEC actions, analyst downgrades) are captured
        # regardless of which share class the news is filed under.
        log.info("Fetching Tavily for %d tickers (%d siblings)", len(tickers), len(sibling_set))
        fetched = await asyncio.gather(
            *[fetch_tavily_news(
                t, tavily_api_key,
                max_results=max_search_results,
                company_name=(company_name_map or {}).get(t),
              )
              for t in all_fetch_tickers]
        )
        all_tavily: dict[str, list[dict]] = dict(zip(all_fetch_tickers, fetched))

        # Merge sibling Tavily results into canonical ticker (dedup by title).
        if related_tickers_map:
            for canonical, siblings in related_tickers_map.items():
                merged_tv = list(all_tavily.get(canonical, []))
                seen_tv = {a.get("title", "") for a in merged_tv}
                for sib in siblings:
                    for article in all_tavily.get(sib, []):
                        title = article.get("title", "")
                        if title not in seen_tv:
                            merged_tv.append(article)
                            seen_tv.add(title)
                if merged_tv:
                    all_tavily[canonical] = merged_tv

        tavily_results = {t: all_tavily.get(t, []) for t in tickers}

    data_sources = {
        "av_news_tickers":           sum(1 for t in tickers if av_news.get(t)),
        "earnings_calendar_tickers": sum(1 for t in tickers if earnings_calendar.get(t)),
        "tavily_tickers":            sum(1 for t in tickers if tavily_results.get(t)),
        "sibling_tickers_fetched":   len(sibling_set),
    }
    log.info(
        "Data fetch complete: AV news=%d, earnings=%d, Tavily=%d, siblings=%d",
        data_sources["av_news_tickers"],
        data_sources["earnings_calendar_tickers"],
        data_sources["tavily_tickers"],
        data_sources["sibling_tickers_fetched"],
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

    # A drawdown exclusion is price-based, not news-based, so it is legitimately
    # data-light — exempt it from the "no supporting data" suspicion checks.
    is_drawdown = risk_type == "drawdown"

    # Exclude with no data and high/medium confidence is suspicious
    if exclude and not has_data and confidence in ("high", "medium") and not is_drawdown:
        flags.append(f"EXCLUDE with {confidence} confidence but no news/earnings/search data provided")

    # Exclude with no supporting data at any confidence is suspicious
    if exclude and not has_data and not is_drawdown:
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
    if len(raw) > 2500:
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
        current_year = int(today[:4])
        # Allow prior year (recent history), current year, and up to 2 years
        # forward (analyst targets, guidance). Flag only implausibly distant years.
        allowed_years = {str(y) for y in range(current_year - 1, current_year + 3)}
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


def _parse_llm_response(
    raw: str,
    ticker: str,
    news: list[dict],
    earnings_date: str | None,
    tavily_articles: list[dict],
    today: str,
    agent_searches: list[dict],
    latency_ms: int,
    user_message: str,
    system_prompt: str,
    vetter_config: dict,
    news_titles: list[str] | None = None,
    regime: str | None = None,
) -> dict:
    """Parse the raw LLM response string into a structured vetter result dict.

    Handles JSON extraction from code fences and bare prose. On parse failure it
    returns exclude=FALSE (KEEP), NOT a forced exclude: a transient LLM/parse glitch
    must not force-sell a name, and the deterministic falling-knife backstop still
    runs afterward on the kept result, so a genuine crash is still caught. (The
    exclusion authority is the deterministic veto, not a parse error.)
    """
    if news_titles is None:
        news_titles = []

    # Extract JSON from whatever format the model chose:
    #   Case 1: leading code fence  ```json {...} ```
    #   Case 2: JSON embedded in prose  "Here is my assessment:\n```json\n{...}\n```"
    #   Case 3: bare prose with a JSON object somewhere  "Analysis...\n{...}"
    clean = raw
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean.strip()).strip()
    elif "```json" in clean:
        m = re.search(r"```json\s*(.*?)\s*```", clean, re.DOTALL)
        if m:
            clean = m.group(1).strip()
    else:
        brace = clean.find("{")
        if brace > 0:
            clean = clean[brace:]

    try:
        # raw_decode stops after the first complete JSON value, ignoring any
        # trailing content (closing fences, commentary) the model appends.
        parsed, _ = json.JSONDecoder().raw_decode(clean)
    except json.JSONDecodeError as exc:
        log.error("Invalid JSON for ticker %s: %s | raw: %s", ticker, exc, clean[:300])
        return {
            "ticker":      ticker,
            "exclude":     False,
            "reason":      f"LLM response could not be parsed — defaulting to KEEP (informational only). Raw: {raw[:100]}",
            "confidence":  "low",
            "risk_type":   "none",
            "positive_catalyst":   False,
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
            "vetter_config":  vetter_config,
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

    # A drawdown exclusion is price-based and legitimately has no news/search
    # data — do not auto-reverse it for lacking supporting articles.
    if (
        parsed.get("exclude", False)
        and not has_any_supporting_data
        and parsed.get("confidence", "low") in ("high", "medium")
        and parsed.get("risk_type") != "drawdown"
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

    return {
        "ticker":      ticker,
        "exclude":     bool(parsed.get("exclude", False)),
        "reason":      parsed.get("reason", ""),
        "confidence":  parsed.get("confidence", "low"),
        "risk_type":   parsed.get("risk_type", "none"),
        "positive_catalyst":   bool(parsed.get("positive_catalyst", False)),
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
        "vetter_config":  vetter_config,
        "hallucination_flags": hallucination_flags,
    }


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
    news_lookback_days: int = 7,
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
    related_tickers: list[str] | None = None,
    company_name: str | None = None,
    drawdown_21d: float | None = None,
) -> dict:
    """
    Ask the LLM to make a single exclude/keep decision for one ticker.

    When tavily_api_key is provided the model runs as an agent: it can call
    web_search up to max_searches_per_ticker times before giving its final decision.
    Without a Tavily key it falls back to a single structured call.

    related_tickers: sibling share-class tickers for the same company (e.g. ["GOOGL"]
    for GOOG). Their news has already been merged into the `news` / `tavily_articles`
    feeds by fetch_ticker_data; this param just tells the LLM about the siblings.

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
        "related_tickers": related_tickers or [],
        "drawdown_21d": drawdown_21d,
    }
    system_prompt = _build_system_prompt(
        entry_rank=entry_rank,
        exit_rank=exit_rank,
        confirmation_days=confirmation_days,
        risk_horizon_days=risk_horizon_days,
        news_lookback_days=news_lookback_days,
        strictness=strictness,
        system_prompt_override=system_prompt_override,
    )
    user_message = _format_ticker_message(
        ticker, news, earnings_date, tavily_articles, today,
        entry_rank=entry_rank,
        exit_rank=exit_rank,
        confirmation_days=confirmation_days,
        risk_horizon_days=risk_horizon_days,
        news_lookback_days=news_lookback_days,
        rank=rank,
        total_candidates=total_candidates,
        composite_score=composite_score,
        factor_scores=factor_scores,
        sector=sector,
        regime=regime,
        in_portfolio=in_portfolio,
        related_tickers=related_tickers,
        company_name=company_name,
        drawdown_21d=drawdown_21d,
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
                "max_tokens": 2048,
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
            "max_tokens": 2048,
            "response_schema": PER_TICKER_SCHEMA,
        }
        final_resp_data = await _gateway_chat(gateway_url, final_payload)

    else:
        # ── Single-call fallback (no Tavily configured) ───────────────────────
        final_payload = {
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
            "temperature": 0.1,
            "max_tokens": 2048,
            "response_schema": PER_TICKER_SCHEMA,
        }
        final_resp_data = await _gateway_chat(gateway_url, final_payload)

    latency_ms = round((time.monotonic() - t0) * 1000)
    raw = (final_resp_data.get("content") or "").strip()

    _parse_kwargs = dict(
        ticker=ticker,
        news=news,
        earnings_date=earnings_date,
        tavily_articles=tavily_articles,
        today=today,
        agent_searches=agent_searches,
        latency_ms=latency_ms,
        user_message=user_message,
        system_prompt=system_prompt,
        vetter_config=vetter_config,
        news_titles=news_titles,
        regime=regime,
    )
    result = _parse_llm_response(raw=raw, **_parse_kwargs)

    # Retry once with doubled max_tokens on parse failure.
    # A truncated response means the model ran out of budget mid-JSON; giving
    # it more room usually produces a complete, parseable response on the retry.
    # On second failure fall through to the fixed exclude=False fallback result.
    if result.get("parse_error"):
        log.warning("[llm-vetter] %s: parse error on first attempt — retrying with doubled max_tokens", ticker)
        retry_payload = {**final_payload, "max_tokens": final_payload.get("max_tokens", 2048) * 2}
        try:
            retry_resp = await _gateway_chat(gateway_url, retry_payload)
            retry_raw = (retry_resp.get("content") or "").strip()
            retry_result = _parse_llm_response(raw=retry_raw, **_parse_kwargs)
            if not retry_result.get("parse_error"):
                log.info("[llm-vetter] %s: parse retry succeeded", ticker)
                return retry_result
            log.error("[llm-vetter] %s: parse retry also failed — defaulting to exclude=False", ticker)
        except Exception as exc:
            log.error("[llm-vetter] %s: parse retry failed with exception: %s", ticker, exc)

    return result
