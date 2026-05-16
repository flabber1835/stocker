import io
import logging
import os
import re
from datetime import date

import httpx
import pandas as pd

log = logging.getLogger("av-ingestor.universe")

MOCK_TICKERS = [
    ("AAPL", "Apple Inc", "Information Technology"),
    ("MSFT", "Microsoft Corp", "Information Technology"),
    ("GOOGL", "Alphabet Inc", "Communication Services"),
    ("AMZN", "Amazon.com Inc", "Consumer Discretionary"),
    ("NVDA", "NVIDIA Corp", "Information Technology"),
    ("META", "Meta Platforms Inc", "Communication Services"),
    ("TSLA", "Tesla Inc", "Consumer Discretionary"),
    ("JPM", "JPMorgan Chase & Co", "Financials"),
    ("JNJ", "Johnson & Johnson", "Health Care"),
    ("V", "Visa Inc", "Financials"),
    ("UNH", "UnitedHealth Group Inc", "Health Care"),
    ("XOM", "Exxon Mobil Corp", "Energy"),
    ("PG", "Procter & Gamble Co", "Consumer Staples"),
    ("HD", "Home Depot Inc", "Consumer Discretionary"),
    ("MA", "Mastercard Inc", "Financials"),
    ("BAC", "Bank of America Corp", "Financials"),
    ("ABBV", "AbbVie Inc", "Health Care"),
    ("AVGO", "Broadcom Inc", "Information Technology"),
    ("MRK", "Merck & Co Inc", "Health Care"),
    ("PEP", "PepsiCo Inc", "Consumer Staples"),
    ("KO", "Coca-Cola Co", "Consumer Staples"),
    ("LLY", "Eli Lilly and Co", "Health Care"),
    ("COST", "Costco Wholesale Corp", "Consumer Staples"),
    ("WMT", "Walmart Inc", "Consumer Staples"),
    ("CVX", "Chevron Corp", "Energy"),
    ("TMO", "Thermo Fisher Scientific Inc", "Health Care"),
    ("MCD", "McDonald's Corp", "Consumer Discretionary"),
    ("ABT", "Abbott Laboratories", "Health Care"),
    ("ACN", "Accenture PLC", "Information Technology"),
    ("DHR", "Danaher Corp", "Health Care"),
]

_TICKER_RE = re.compile(r"^[A-Z]{1,5}([.\-][A-Z0-9]{1,4})?$")

_AV_LISTING_URL = "https://www.alphavantage.co/query?function=LISTING_STATUS&apikey={api_key}"

# Exchanges considered part of the broad US equity universe.
_US_EXCHANGES = {"NYSE", "NASDAQ", "NYSE MKT", "NYSE ARCA", "NYSE American", "BATS", "OTC"}


async def download_av_listing(session: httpx.AsyncClient, api_key: str) -> list[dict]:
    """Fetch all active US equities from Alpha Vantage LISTING_STATUS.

    This is the canonical universe source. Returns dicts with weight_pct=None and sector=None.
    """
    url = _AV_LISTING_URL.format(api_key=api_key)
    response = await session.get(url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()

    df = pd.read_csv(io.StringIO(response.text), dtype=str)
    df.columns = [c.strip() for c in df.columns]

    rows = []
    for _, row in df.iterrows():
        ticker = str(row.get("symbol", "")).strip()
        if not _TICKER_RE.match(ticker):
            continue
        if str(row.get("status", "")).strip().lower() != "active":
            continue
        if str(row.get("assetType", "")).strip() not in ("Stock",):
            continue
        exchange = str(row.get("exchange", "")).strip()
        if exchange not in _US_EXCHANGES:
            continue
        rows.append(
            {
                "ticker": ticker,
                "name": str(row.get("name", "")).strip() or None,
                "weight_pct": None,
                "sector": None,
                "asset_class": "Equity",
            }
        )

    if len(rows) < 100:
        raise ValueError(
            f"AV LISTING_STATUS returned only {len(rows)} active US stocks — expected 3000+."
        )

    return rows


async def download_av_universe(session: httpx.AsyncClient, av_api_key: str = "") -> list[dict]:
    """Build the equity universe from Alpha Vantage LISTING_STATUS."""
    if os.getenv("MOCK_DATA", "false").lower() == "true":
        return _mock_universe()

    if not av_api_key or av_api_key == "demo":
        raise RuntimeError(
            "AV_API_KEY is required for universe construction "
            "(set AV_API_KEY env var or use MOCK_DATA=true)"
        )

    return await download_av_listing(session, av_api_key)


def _mock_universe() -> list[dict]:
    total = len(MOCK_TICKERS)
    return [
        {
            "ticker": ticker,
            "name": name,
            "weight_pct": round(100.0 / total, 6),
            "sector": sector,
            "asset_class": "Equity",
        }
        for ticker, name, sector in MOCK_TICKERS
    ]


async def get_benchmark_tickers(session: httpx.AsyncClient) -> list[dict]:
    return [
        {"ticker": "SPY",  "name": "SPDR S&P 500 ETF",             "weight_pct": None, "sector": None, "asset_class": "ETF"},
        {"ticker": "QQQ",  "name": "Invesco QQQ Trust",             "weight_pct": None, "sector": None, "asset_class": "ETF"},
        {"ticker": "IWM",  "name": "iShares Russell 2000 ETF",      "weight_pct": None, "sector": None, "asset_class": "ETF"},
        {"ticker": "SOXX", "name": "iShares Semiconductor ETF",     "weight_pct": None, "sector": None, "asset_class": "ETF"},
    ]


_NON_EQUITY_CLASSES = {"cash", "cash and/or derivatives", "money market", "fixed income", "futures"}


def _is_investable_equity(t: dict) -> bool:
    ac = (t.get("asset_class") or "").lower().strip()
    if not ac:
        return True
    return ac not in _NON_EQUITY_CLASSES


async def save_universe_snapshot(conn, etf_ticker: str, tickers: list[dict]) -> int:
    from sqlalchemy import text

    today = date.today()
    investable = [t for t in tickers if _is_investable_equity(t)]
    dropped = len(tickers) - len(investable)
    if dropped:
        print(f"[universe] filtered {dropped} non-equity positions (cash/derivatives) from snapshot")

    result = await conn.execute(
        text(
            "INSERT INTO universe_snapshots (etf_ticker, snapshot_date, ticker_count) "
            "VALUES (:etf_ticker, :snapshot_date, :ticker_count) "
            "RETURNING id"
        ),
        {"etf_ticker": etf_ticker, "snapshot_date": today, "ticker_count": len(investable)},
    )
    snapshot_id = result.scalar_one()

    if investable:
        await conn.execute(
            text(
                "INSERT INTO universe_tickers (snapshot_id, ticker, name, weight_pct, sector, asset_class) "
                "VALUES (:snapshot_id, :ticker, :name, :weight_pct, :sector, :asset_class)"
            ),
            [
                {
                    "snapshot_id": snapshot_id,
                    "ticker": t["ticker"],
                    "name": t.get("name"),
                    "weight_pct": t.get("weight_pct"),
                    "sector": t.get("sector"),
                    "asset_class": t.get("asset_class"),
                }
                for t in investable
            ],
        )

    return snapshot_id
