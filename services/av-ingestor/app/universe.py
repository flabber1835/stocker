import io
import os
import re
from datetime import date

import httpx
import pandas as pd

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

IWV_CSV_URL = (
    "https://www.ishares.com/us/products/239714/IWV/1467271812596.ajax"
    "?fileType=csv&fileName=IWV_holdings&dataType=fund"
)

_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


async def download_iwv_holdings(session: httpx.AsyncClient) -> list[dict]:
    if os.getenv("MOCK_DATA", "false").lower() == "true":
        return _mock_universe()

    response = await session.get(IWV_CSV_URL, follow_redirects=True, timeout=30.0)
    response.raise_for_status()

    # iShares CSVs have a variable number of metadata rows before the actual header.
    # Scan to find the first row that contains a recognisable column name.
    lines = response.text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if any(kw in line for kw in ("Ticker", "TICKER", "Symbol")):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Could not locate header row in IWV holdings CSV")

    # on_bad_lines='skip' drops footer/disclaimer rows that have fewer columns than the header
    df = pd.read_csv(
        io.StringIO(response.text),
        skiprows=header_idx,
        header=0,
        dtype=str,
        on_bad_lines="skip",
    )
    df.columns = [c.strip() for c in df.columns]

    ticker_col = _find_column(df, ["Ticker", "TICKER", "Symbol"])
    name_col = _find_column(df, ["Name", "NAME", "Security"])
    weight_col = _find_column(df, ["Weight (%)", "Weight(%)", "WEIGHT (%)", "Weight"])
    sector_col = _find_column(df, ["Sector", "SECTOR"])
    asset_class_col = _find_column(df, ["Asset Class", "ASSET CLASS", "AssetClass"])

    rows = []
    for _, row in df.iterrows():
        ticker = str(row.get(ticker_col, "")).strip()
        if not _TICKER_RE.match(ticker):
            continue
        rows.append(
            {
                "ticker": ticker,
                "name": str(row.get(name_col, "")).strip() if name_col else None,
                "weight_pct": _parse_float(row.get(weight_col)) if weight_col else None,
                "sector": str(row.get(sector_col, "")).strip() if sector_col else None,
                "asset_class": str(row.get(asset_class_col, "")).strip() if asset_class_col else None,
            }
        )

    return rows


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    for col in df.columns:
        for c in candidates:
            if c.lower() in col.lower():
                return col
    return None


def _parse_float(val) -> float | None:
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


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
        {"ticker": "SPY", "name": "SPDR S&P 500 ETF", "weight_pct": None, "sector": None, "asset_class": "ETF"},
        {"ticker": "QQQ", "name": "Invesco QQQ Trust", "weight_pct": None, "sector": None, "asset_class": "ETF"},
    ]


async def save_universe_snapshot(conn, etf_ticker: str, tickers: list[dict]) -> int:
    from sqlalchemy import text

    today = date.today()
    result = await conn.execute(
        text(
            """
            INSERT INTO universe_snapshots (etf_ticker, snapshot_date, ticker_count)
            VALUES (:etf_ticker, :snapshot_date, :ticker_count)
            RETURNING id
            """
        ),
        {"etf_ticker": etf_ticker, "snapshot_date": today, "ticker_count": len(tickers)},
    )
    snapshot_id = result.scalar_one()

    if tickers:
        await conn.execute(
            text(
                """
                INSERT INTO universe_tickers (snapshot_id, ticker, name, weight_pct, sector, asset_class)
                VALUES (:snapshot_id, :ticker, :name, :weight_pct, :sector, :asset_class)
                """
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
                for t in tickers
            ],
        )

    return snapshot_id
