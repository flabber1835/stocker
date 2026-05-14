"""
Data-fetching tools for the LLM vetter.

Primary source: Alpha Vantage NEWS_SENTIMENT and EARNINGS_CALENDAR.
Optional secondary source: Tavily web search (set TAVILY_API_KEY to enable).

All functions are async and return plain dicts/lists ready to embed in a prompt.
They never raise — on API failure they return an empty result so the LLM still
gets to make a best-effort decision based on whatever data is available.
"""

import csv
import io
import logging
from datetime import date, timedelta

import httpx

log = logging.getLogger("llm-vetter.tools")

AV_BASE = "https://www.alphavantage.co/query"
TAVILY_BASE = "https://api.tavily.com/search"


async def fetch_av_news(
    tickers: list[str],
    api_key: str,
    *,
    lookback_days: int = 7,
    max_articles_per_ticker: int = 4,
) -> dict[str, list[dict]]:
    """
    Fetch recent news sentiment from Alpha Vantage for up to 50 tickers at once.
    Returns {ticker: [{"title":..., "summary":..., "sentiment":..., "published":...}]}.
    """
    if not api_key or api_key == "demo":
        return {}

    since = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%dT0000")
    # AV accepts comma-separated tickers; cap at 50 to stay within API limits
    batches = [tickers[i:i + 50] for i in range(0, len(tickers), 50)]
    result: dict[str, list[dict]] = {t: [] for t in tickers}

    async with httpx.AsyncClient(timeout=30) as client:
        for batch in batches:
            try:
                resp = await client.get(AV_BASE, params={
                    "function": "NEWS_SENTIMENT",
                    "tickers": ",".join(batch),
                    "time_from": since,
                    "sort": "RELEVANCE",
                    "limit": "200",
                    "apikey": api_key,
                })
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                log.warning("AV news fetch failed: %s", exc)
                continue

            # Detect API-level errors/notices returned as JSON (not HTTP errors)
            if "Note" in data or "Information" in data or "Error Message" in data:
                msg = data.get("Note") or data.get("Information") or data.get("Error Message")
                log.warning("AV news API message (no feed returned): %s", msg)
                continue

            feed = data.get("feed", [])
            log.info("AV news: batch of %d tickers → %d articles returned", len(batch), len(feed))

            filtered_by_relevance = 0
            for article in feed:
                title = article.get("title", "")
                summary = article.get("summary", "")
                published = article.get("time_published", "")[:8]  # YYYYMMDD

                for ts in article.get("ticker_sentiment", []):
                    ticker = ts.get("ticker", "")
                    if ticker not in result:
                        continue
                    sentiment_score = float(ts.get("ticker_sentiment_score", 0))
                    sentiment_label = ts.get("ticker_sentiment_label", "Neutral")
                    relevance = float(ts.get("relevance_score", 0))

                    if relevance < 0.1:
                        filtered_by_relevance += 1
                        continue

                    if len(result[ticker]) < max_articles_per_ticker:
                        result[ticker].append({
                            "title": title,
                            "summary": summary[:300],
                            "sentiment": sentiment_label,
                            "sentiment_score": round(sentiment_score, 3),
                            "relevance_score": round(relevance, 3),
                            "published": published,
                        })

            tickers_with_news = sum(1 for t in batch if result.get(t))
            log.info(
                "AV news: %d/%d tickers got articles (filtered %d by relevance<0.1)",
                tickers_with_news, len(batch), filtered_by_relevance,
            )

    return result


async def fetch_av_earnings_calendar(
    tickers: list[str],
    api_key: str,
) -> dict[str, str | None]:
    """
    Fetch upcoming earnings dates from Alpha Vantage EARNINGS_CALENDAR (CSV endpoint).
    Returns {ticker: "YYYY-MM-DD"} for tickers with earnings in the next 45 days, else None.
    """
    if not api_key or api_key == "demo":
        return {t: None for t in tickers}

    ticker_set = set(tickers)
    result: dict[str, str | None] = {t: None for t in tickers}
    cutoff = date.today() + timedelta(days=45)

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(AV_BASE, params={
                "function": "EARNINGS_CALENDAR",
                "horizon": "3month",
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


async def fetch_tavily_news(
    ticker: str,
    api_key: str,
    *,
    max_results: int = 3,
) -> list[dict]:
    """
    Search Tavily for recent news about a ticker. Used for tickers where AV
    returned little or no news. Returns [] if TAVILY_API_KEY is not set.
    """
    if not api_key:
        return []

    query = f"{ticker} stock news risks outlook"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                TAVILY_BASE,
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_domains": [
                        "reuters.com", "bloomberg.com", "ft.com",
                        "wsj.com", "cnbc.com", "marketwatch.com",
                        "seekingalpha.com", "barrons.com",
                    ],
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"title": r.get("title", ""), "summary": r.get("content", "")[:300]}
                for r in data.get("results", [])
            ]
    except Exception as exc:
        log.warning("Tavily search failed for %s: %s", ticker, exc)
        return []
