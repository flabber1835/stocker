"""
Data-fetching tools for the LLM vetter.

Primary source: Alpha Vantage NEWS_SENTIMENT and EARNINGS_CALENDAR.
Optional secondary source: Tavily web search (set TAVILY_API_KEY to enable).

All functions are async and return plain dicts/lists ready to embed in a prompt.
They never raise — on API failure they return an empty result so the LLM still
gets to make a best-effort decision based on whatever data is available.
"""

import asyncio
import csv
import io
import logging
import os
from datetime import date, timedelta

import httpx

log = logging.getLogger("llm-vetter.tools")

AV_BASE = os.getenv("AV_BASE_URL", "https://www.alphavantage.co/query")
TAVILY_BASE = os.getenv("TAVILY_BASE_URL", "https://api.tavily.com/search")

_FINANCIAL_DOMAINS = [
    "reuters.com", "bloomberg.com", "ft.com",
    "wsj.com", "cnbc.com", "marketwatch.com",
    "seekingalpha.com", "barrons.com", "sec.gov",
    "finance.yahoo.com", "thestreet.com",
    "fda.gov", "ftc.gov",
]


async def fetch_av_news(
    tickers: list[str],
    api_key: str,
    *,
    lookback_days: int = 7,
    max_articles_per_ticker: int = 4,
    max_results_per_ticker: int = 50,
    concurrency: int = 5,
    min_request_interval: float = 0.25,
) -> dict[str, list[dict]]:
    """
    Fetch recent news sentiment from Alpha Vantage — one request per ticker.

    Individual calls give all results focused on one ticker, so relevance scores
    are higher and per-ticker coverage is much better than batching multiple
    tickers together (where 50 results are split across 10 tickers).

    Rate limiting: requests are serialized through a start_lock so they begin no
    faster than 1/min_request_interval per second (default 4 RPS), well within
    AV's stated 5 RPS burst limit. concurrency caps in-flight requests.
    50 tickers at 0.25s spacing completes in ~15 seconds, well within 75 RPM quota.
    """
    if not api_key or api_key == "demo":
        return {}

    since = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%dT0000")
    result: dict[str, list[dict]] = {t: [] for t in tickers}
    sem = asyncio.Semaphore(concurrency)
    start_lock = asyncio.Lock()
    last_sent_at: list[float] = [0.0]

    async def _fetch_one(client: httpx.AsyncClient, ticker: str) -> None:
        async with sem:
            # Enforce minimum inter-request interval to avoid AV burst detection.
            async with start_lock:
                now = asyncio.get_event_loop().time()
                wait = min_request_interval - (now - last_sent_at[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                last_sent_at[0] = asyncio.get_event_loop().time()

            try:
                resp = await client.get(AV_BASE, params={
                    "function": "NEWS_SENTIMENT",
                    "tickers": ticker,
                    "time_from": since,
                    "sort": "LATEST",
                    "limit": str(max_results_per_ticker),
                    "apikey": api_key,
                })
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                log.warning("AV news fetch failed for %s: %s", ticker, exc)
                return

            if "Note" in data or "Information" in data or "Error Message" in data:
                error_key = next(k for k in ("Note", "Information", "Error Message") if k in data)
                log.warning("AV news API error for %s (%s): %s", ticker, error_key, data[error_key])
                return

            feed = data.get("feed", [])
            filtered = 0
            for article in feed:
                title = article.get("title", "")
                summary = article.get("summary", "")
                published = article.get("time_published", "")[:8]

                for ts in article.get("ticker_sentiment", []):
                    if ts.get("ticker", "") != ticker:
                        continue
                    relevance = float(ts.get("relevance_score", 0))
                    if relevance < 0.1:
                        filtered += 1
                        continue
                    if len(result[ticker]) < max_articles_per_ticker:
                        result[ticker].append({
                            "title": title,
                            "summary": summary[:300],
                            "sentiment": ts.get("ticker_sentiment_label", "Neutral"),
                            "sentiment_score": round(float(ts.get("ticker_sentiment_score", 0)), 3),
                            "relevance_score": round(relevance, 3),
                            "published": published,
                        })

            log.info(
                "AV news: %s → %d articles kept, %d filtered (relevance<0.1), %d in feed",
                ticker, len(result[ticker]), filtered, len(feed),
            )

    async with httpx.AsyncClient(timeout=30) as client:
        await asyncio.gather(*[_fetch_one(client, t) for t in tickers])

    tickers_with_news = sum(1 for t in tickers if result[t])
    log.info("AV news complete: %d/%d tickers got articles", tickers_with_news, len(tickers))
    return result


async def fetch_av_earnings_calendar(
    tickers: list[str],
    api_key: str,
    *,
    earnings_horizon_days: int = 90,
) -> dict[str, str | None]:
    """
    Fetch upcoming earnings dates from Alpha Vantage EARNINGS_CALENDAR (CSV endpoint).
    Returns {ticker: "YYYY-MM-DD"} for tickers with earnings within earnings_horizon_days.
    """
    if not api_key or api_key == "demo":
        return {t: None for t in tickers}

    ticker_set = set(tickers)
    result: dict[str, str | None] = {t: None for t in tickers}
    cutoff = date.today() + timedelta(days=earnings_horizon_days)

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            # AV supports "3month" (~91d) or "12month". Use 12month when the
            # configured horizon exceeds 91 days so all relevant dates are fetched;
            # the local cutoff filter below then trims to the exact horizon.
            av_horizon = "12month" if earnings_horizon_days > 91 else "3month"
            resp = await client.get(AV_BASE, params={
                "function": "EARNINGS_CALENDAR",
                "horizon": av_horizon,
                "apikey": api_key,
            })
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                symbol = row.get("symbol", "")
                report_date_str = row.get("reportDate", "")
                if symbol not in ticker_set or not report_date_str:
                    continue
                try:
                    report_date = date.fromisoformat(report_date_str)
                    if date.today() <= report_date <= cutoff:
                        result[symbol] = report_date_str
                except ValueError:
                    pass
        except Exception as exc:
            log.warning("AV earnings calendar fetch failed: %s", exc)

    return result


async def search_web(
    query: str,
    api_key: str,
    *,
    max_results: int = 5,
) -> list[dict]:
    """
    Generic web search via Tavily for an arbitrary query string.
    Used by the agentic vetter loop when the LLM calls the web_search tool.
    """
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                TAVILY_BASE,
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": max_results,
                    "include_domains": _FINANCIAL_DOMAINS,
                },
                timeout=45,
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "title":   r.get("title", ""),
                    "content": r.get("content", r.get("snippet", ""))[:1500],
                    "url":     r.get("url", ""),
                }
                for r in data.get("results", [])
            ]
    except Exception as exc:
        log.warning("Tavily search failed for query '%s': %s", query, exc)
        return []


async def fetch_tavily_news(
    ticker: str,
    api_key: str,
    *,
    max_results: int = 5,
) -> list[dict]:
    """
    Search Tavily for recent news about a ticker. Used for tickers where AV
    returned little or no news. Returns [] if TAVILY_API_KEY is not set.
    """
    if not api_key:
        return []

    query = f"{ticker} stock news risks outlook"
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                TAVILY_BASE,
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": max_results,
                    "include_domains": _FINANCIAL_DOMAINS,
                },
                timeout=45,
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"title": r.get("title", ""), "summary": r.get("content", "")[:1000]}
                for r in data.get("results", [])
            ]
    except Exception as exc:
        log.warning("Tavily search failed for %s: %s", ticker, exc)
        return []
