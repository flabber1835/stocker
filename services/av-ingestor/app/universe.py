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

# Warrants (-W, -WS), units (-U), rights (-R), and their no-dash equivalents.
# 5-char tickers ending in W/U where first 4 chars are a base ticker (e.g. BTMDW, BTMDU).
_WARRANT_RE = re.compile(
    r"-W[S]?$"        # dash-warrant: APGB-W, APGB-WS
    r"|-U$"           # dash-unit:    APGB-U
    r"|-R$"           # dash-right:   AVK-R
    r"|[A-Z]{4,}W$"   # no-dash warrant: BTMDW (4+W), ADALW (5+W)
    r"|[A-Z]{4,}U$"   # no-dash unit:    BTMDU (4+U), ADALU (5+U)
    r"|[A-Z]{4,}WS$"  # no-dash warrant with WS suffix: FTWWS
)

# Futures and options-like ticker patterns: tickers containing embedded digits
# (e.g. CL2025Z, ES2506M) that slip through AV LISTING_STATUS as assetType=Stock.
_DERIVATIVE_TICKER_RE = re.compile(
    r"FUT$"                             # explicit futures suffix
    r"|^[A-Z]{1,4}[0-9]{1,2}[A-Z]?[0-9]?$"  # embedded-digit futures/options ticker
)

# Name keywords that identify non-investable securities regardless of ticker format.
# Catches rights (SPAC rights ending in R), when-issued spinoff shares (ending in V),
# warrants with non-standard ticker suffixes, ETF providers, leveraged/inverse products,
# and fund wrappers that AV sometimes classifies as assetType=Stock.
_NON_INVESTABLE_NAME_RE = re.compile(
    r"\bright[s]?\b"          # SPAC rights: "Right", "Rights"
    r"|\bwhen.?issued\b"      # spinoff when-issued shares
    r"|\bwt\.?\b"             # warrant abbreviation: "Wt", "Wt."
    r"|\bwarrant[s]?\b"       # full word: "Warrant", "Warrants"
    r"|\bcontingent.value\b"  # contingent value rights (CVRs)
    r"|\bsubscription.right"  # subscription rights
    # ETF providers — these products sometimes appear as assetType=Stock in AV data
    r"|ProShares"
    r"|iShares"
    r"|\bSPDR\b"
    r"|Invesco"
    r"|Direxion"
    r"|VanEck"
    r"|WisdomTree"
    r"|First Trust"
    # Generic non-investable keywords
    r"|\bETF\b"
    r"|\bFund\b"
    r"|\bLeveraged\b"
    r"|\bInverse\b"
    r"|\bFuture[s]?\b"
    , re.I
)

_AV_LISTING_URL = "https://www.alphavantage.co/query?function=LISTING_STATUS&apikey={api_key}"

# Exchanges considered part of the broad US equity universe.
_US_EXCHANGES = {"NYSE", "NASDAQ", "NYSE MKT", "NYSE ARCA", "NYSE American", "BATS", "OTC"}


async def download_av_listing(session: httpx.AsyncClient, api_key: str) -> tuple[list[dict], dict]:
    """Fetch all active US equities from Alpha Vantage LISTING_STATUS.

    This is the canonical universe source. Returns (rows, stats) where stats contains
    counts for each filter stage so callers can log what was dropped and why.
    """
    url = _AV_LISTING_URL.format(api_key=api_key)
    response = await session.get(url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()

    df = pd.read_csv(io.StringIO(response.text), dtype=str)
    df.columns = [c.strip() for c in df.columns]

    rows = []
    raw_rows = []       # every row AV returned, as-is
    filtered_rows = []  # rows dropped, with reason attached
    for _, row in df.iterrows():
        av_row = {k: str(v).strip() for k, v in row.items()}
        raw_rows.append(av_row)
        ticker = av_row.get("symbol", "")
        if not _TICKER_RE.match(ticker):
            filtered_rows.append({**av_row, "_filter_reason": "ticker_format"})
            continue
        if _WARRANT_RE.search(ticker):
            filtered_rows.append({**av_row, "_filter_reason": "warrant_or_unit"})
            continue
        if _DERIVATIVE_TICKER_RE.search(ticker):
            filtered_rows.append({**av_row, "_filter_reason": "derivative_ticker"})
            continue
        name = av_row.get("name", "")
        if _NON_INVESTABLE_NAME_RE.search(name):
            filtered_rows.append({**av_row, "_filter_reason": "non_investable_name"})
            continue
        if av_row.get("status", "").lower() != "active":
            filtered_rows.append({**av_row, "_filter_reason": "inactive"})
            continue
        if av_row.get("assetType", "") not in ("Stock",):
            filtered_rows.append({**av_row, "_filter_reason": "non_stock"})
            continue
        if av_row.get("exchange", "") not in _US_EXCHANGES:
            filtered_rows.append({**av_row, "_filter_reason": "wrong_exchange"})
            continue
        rows.append(
            {
                "ticker": ticker,
                "name": av_row.get("name") or None,
                "weight_pct": None,
                "sector": None,
                "asset_class": "Equity",
            }
        )

    if len(rows) < 100:
        raise ValueError(
            f"AV LISTING_STATUS returned only {len(rows)} active US stocks — expected 3000+."
        )

    stats = {
        "total_rows": len(raw_rows),
        "accepted": len(rows),
        "filtered": len(filtered_rows),
        "raw_listing": raw_rows,
        "filtered_rows": filtered_rows,
        "accepted_tickers": [r["ticker"] for r in rows],
    }
    return rows, stats


async def download_av_universe(session: httpx.AsyncClient, av_api_key: str = "") -> tuple[list[dict], dict]:
    """Build the equity universe from Alpha Vantage LISTING_STATUS.

    Returns (tickers, stats) where stats contains filter-stage counts.
    """
    if os.getenv("MOCK_DATA", "false").lower() == "true":
        tickers = _mock_universe()
        stats = {"total_rows": len(tickers), "accepted": len(tickers), "filtered_warrant_unit": 0}
        return tickers, stats

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


async def get_benchmark_tickers() -> list[dict]:
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
