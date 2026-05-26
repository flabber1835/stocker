"""
Tavily search API simulator.

Simulates POST /search (https://api.tavily.com/search) so the llm-vetter can
call Tavily without real API keys during testing.

Results are deterministic: the ticker is extracted from the query and a
sha256 hash byte drives article count and sentiment mix.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="tavily-sim")


# ── article templates ─────────────────────────────────────────────────────────

_POSITIVE_TEMPLATES = [
    {
        "title_tpl": "{ticker} beats earnings expectations with strong revenue growth",
        "content_tpl": (
            "{ticker} Inc reported quarterly earnings that exceeded analyst consensus estimates. "
            "Revenue grew 12% year-over-year driven by strong demand across all business segments. "
            "Management raised full-year guidance citing robust order backlog and improving margins."
        ),
        "url_tpl": "https://reuters.com/technology/{ticker_lower}-earnings-beat",
        "score": 0.88,
    },
    {
        "title_tpl": "Analysts upgrade {ticker} on improving fundamentals",
        "content_tpl": (
            "Multiple Wall Street analysts upgraded {ticker} this week, citing improving "
            "balance sheet metrics and accelerating free cash flow generation. "
            "The consensus price target was raised by an average of 8%."
        ),
        "url_tpl": "https://bloomberg.com/news/{ticker_lower}-analyst-upgrade",
        "score": 0.82,
    },
    {
        "title_tpl": "{ticker} secures major contract win expanding market share",
        "content_tpl": (
            "{ticker} announced a significant multi-year contract with a Fortune 500 customer. "
            "The deal is expected to contribute $200M in incremental annual revenue and "
            "reinforces the company's competitive position in its core market."
        ),
        "url_tpl": "https://marketwatch.com/story/{ticker_lower}-contract-win",
        "score": 0.79,
    },
]

_NEGATIVE_TEMPLATES = [
    {
        "title_tpl": "{ticker} faces headwinds as sector demand softens",
        "content_tpl": (
            "{ticker} acknowledged slower order growth in its latest investor update. "
            "Management noted macroeconomic uncertainty is causing customers to delay "
            "capital expenditure decisions, pressuring near-term revenue visibility."
        ),
        "url_tpl": "https://wsj.com/articles/{ticker_lower}-demand-softening",
        "score": 0.74,
    },
    {
        "title_tpl": "Rising input costs weigh on {ticker} margins",
        "content_tpl": (
            "{ticker} warned that elevated raw material and logistics costs could compress "
            "gross margins by 50-100 basis points in the coming quarter. "
            "Analysts revised estimates modestly lower following the pre-announcement."
        ),
        "url_tpl": "https://cnbc.com/2024/01/{ticker_lower}-margin-pressure",
        "score": 0.71,
    },
]

_NEUTRAL_TEMPLATES = [
    {
        "title_tpl": "{ticker} presents at industry conference",
        "content_tpl": (
            "{ticker} management presented at the annual investment conference, reiterating "
            "full-year guidance and highlighting the company's long-term strategic priorities. "
            "No material new information was disclosed."
        ),
        "url_tpl": "https://seekingalpha.com/article/{ticker_lower}-conference",
        "score": 0.65,
    },
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _extract_ticker(query: str) -> str:
    """Return the first all-caps word of 1-5 chars in the query, else 'UNKN'."""
    m = re.search(r"\b([A-Z]{1,5})\b", query)
    return m.group(1) if m else "UNKN"


def _render(template: dict, ticker: str) -> dict:
    lower = ticker.lower()
    return {
        "title":   template["title_tpl"].format(ticker=ticker, ticker_lower=lower),
        "content": template["content_tpl"].format(ticker=ticker, ticker_lower=lower),
        "url":     template["url_tpl"].format(ticker=ticker, ticker_lower=lower),
        "score":   template["score"],
    }


def _build_results(ticker: str, max_results: int) -> list[dict]:
    """
    Deterministically pick 0-2 results based on sha256(ticker).

    Byte 0 drives result count; byte 1 drives article mix.
    """
    digest = hashlib.sha256(ticker.encode()).digest()
    count_seed = digest[0]
    mix_seed = digest[1]

    # 0 results for roughly 15% of tickers (count_seed < 38)
    # 1 result  for roughly 35% (38 <= count_seed < 128)
    # 2 results for roughly 50% (count_seed >= 128)
    if count_seed < 38:
        n = 0
    elif count_seed < 128:
        n = 1
    else:
        n = 2

    n = min(n, max_results)

    if n == 0:
        return []

    articles: list[dict] = []

    # First article: positive if mix_seed is even, negative if odd
    if mix_seed % 2 == 0:
        articles.append(_render(_POSITIVE_TEMPLATES[mix_seed % len(_POSITIVE_TEMPLATES)], ticker))
    else:
        articles.append(_render(_NEGATIVE_TEMPLATES[mix_seed % len(_NEGATIVE_TEMPLATES)], ticker))

    if n >= 2:
        # Second article: neutral, or opposite sentiment to first
        idx = (mix_seed // 2) % len(_NEUTRAL_TEMPLATES)
        articles.append(_render(_NEUTRAL_TEMPLATES[idx], ticker))

    return articles[:max_results]


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "tavily-sim"}


@app.post("/search")
async def search(request: Request):
    """
    Simulate POST /search (Tavily search API).

    Extracts the ticker from the query, returns 0-2 deterministic articles
    based on the ticker hash, capped at max_results.
    """
    try:
        body: dict = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})

    query: str = body.get("query", "")
    max_results: int = int(body.get("max_results", 5))

    ticker = _extract_ticker(query)
    results = _build_results(ticker, max_results)

    return {"results": results}
