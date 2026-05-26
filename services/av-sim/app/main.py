"""
Alpha Vantage REST API simulator for test harness use.

Answers all GET /query?function=X requests that av-ingestor and llm-vetter make
against https://www.alphavantage.co/query, plus admin endpoints for scenario
loading and as-of-date control.

All state is in-memory: no database is needed.  The simulator is deterministic —
the same load-scenario call always produces identical data for identical inputs.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from .data_gen import (
    BENCHMARK_TICKERS,
    SECTORS,
    generate_earnings_calendar,
    generate_fundamentals,
    generate_news,
    generate_prices,
    generate_universe_tickers,
    trading_days,
)

log = logging.getLogger("av-sim")

app = FastAPI(title="Alpha Vantage Simulator", version="1.0.0")

# ---------------------------------------------------------------------------
# Module-level mutable state
# All mutation happens inside admin endpoints, so no lock is needed for the
# single-threaded test harness usage pattern this service targets.
# ---------------------------------------------------------------------------

# as_of_date controls which price rows are visible.
_as_of_date: str | None = None

# Loaded scenario metadata
_scenario_name: str | None = None
_scenario_regimes: list[dict[str, str]] = []

# prices[ticker][date_str] = {open, high, low, close, adjusted_close, volume}
_prices: dict[str, dict[str, dict[str, Any]]] = {}

# fundamentals[ticker] = AV OVERVIEW JSON dict (keys match AV field names)
_fundamentals: dict[str, dict[str, Any]] = {}

# universe tickers (excludes benchmarks) for LISTING_STATUS
_universe: list[dict[str, Any]] = []

# name lookup used by earnings calendar  { ticker: name }
_names: dict[str, str] = {}

# pre-generated earnings calendar rows (all quarters, all tickers)
_earnings_rows: list[dict[str, str]] = []

# scenario seed stored so we can regenerate earnings deterministically
_scenario_seed: int = 42


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _effective_as_of() -> str:
    """Return the current as_of_date, defaulting to today if none is set."""
    return _as_of_date or date.today().isoformat()


def _current_regime() -> str:
    """Return the active regime name for _effective_as_of()."""
    if not _scenario_regimes:
        return "bull_calm"
    aod = _effective_as_of()
    active = _scenario_regimes[0]["type"]
    for entry in sorted(_scenario_regimes, key=lambda r: r["start_date"]):
        if entry["start_date"] <= aod:
            active = entry["type"]
        else:
            break
    return active


def _prices_up_to(ticker: str, as_of: str) -> dict[str, dict[str, Any]]:
    """Return only the price rows for ticker where date_str <= as_of."""
    all_rows = _prices.get(ticker, {})
    return {d: v for d, v in all_rows.items() if d <= as_of}


def _compact_dates(ticker: str, as_of: str) -> list[str]:
    """Return the last 100 trading-day date strings up to as_of for ticker."""
    visible = sorted(_prices_up_to(ticker, as_of).keys())
    return visible[-100:]


def _full_dates(ticker: str, as_of: str) -> list[str]:
    """Return all trading-day date strings up to as_of for ticker."""
    return sorted(_prices_up_to(ticker, as_of).keys())


# ---------------------------------------------------------------------------
# AV query endpoint
# ---------------------------------------------------------------------------

@app.get("/query")
async def av_query(
    function: str = Query(..., description="AV function name"),
    symbol: str | None = Query(None),
    outputsize: str | None = Query(None),
    tickers: str | None = Query(None),
    time_from: str | None = Query(None),
    sort: str | None = Query(None),
    limit: str | None = Query(None),
    horizon: str | None = Query(None),
    apikey: str | None = Query(None),
) -> Any:
    """
    Central dispatch for all Alpha Vantage query functions.

    Supported functions:
      LISTING_STATUS            → CSV text
      TIME_SERIES_DAILY_ADJUSTED → JSON
      OVERVIEW                  → JSON
      NEWS_SENTIMENT            → JSON
      EARNINGS_CALENDAR         → CSV text
    """
    fn = function.upper().strip()

    if fn == "LISTING_STATUS":
        return _handle_listing_status()

    if fn == "TIME_SERIES_DAILY_ADJUSTED":
        return _handle_time_series(symbol, outputsize)

    if fn == "OVERVIEW":
        return _handle_overview(symbol)

    if fn == "NEWS_SENTIMENT":
        return _handle_news_sentiment(tickers, limit)

    if fn == "EARNINGS_CALENDAR":
        return _handle_earnings_calendar(horizon)

    raise HTTPException(status_code=400, detail=f"Unknown AV function: {function!r}")


# ---------------------------------------------------------------------------
# LISTING_STATUS
# ---------------------------------------------------------------------------

def _handle_listing_status() -> PlainTextResponse:
    """
    Return CSV of all universe tickers.

    The av-ingestor filter logic requires:
      - assetType = "Stock"
      - status = "active"
      - exchange in {NYSE, NASDAQ, NYSE MKT, NYSE ARCA, NYSE American, BATS, OTC}
      - ticker matches ^[A-Z]{1,5}([.\\-][A-Z0-9]{1,4})?$
      - name does not match _NON_INVESTABLE_NAME_RE (no "Fund", "ETF", "Preferred", etc.)

    Benchmarks (SPY/QQQ/IWM/SOXX) are deliberately excluded so the ingestor
    filter keeps them out of the equity universe (they are treated as ETFs).

    If no scenario has been loaded we return a minimal built-in set so health
    checks and startup probes still pass.
    """
    rows = _universe if _universe else _default_listing_rows()

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["symbol", "name", "exchange", "assetType", "ipoDate", "delistingDate", "status"],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "symbol": row["ticker"],
            "name": row["name"],
            "exchange": row["exchange"],
            "assetType": "Stock",
            "ipoDate": "2000-01-01",
            "delistingDate": "",
            "status": "active",
        })

    return PlainTextResponse(content=output.getvalue(), media_type="text/csv")


def _default_listing_rows() -> list[dict[str, Any]]:
    """
    Minimal built-in universe (110 tickers) returned before any scenario is loaded.

    Tickers are simple 4-letter codes that pass av-ingestor's filter rules.
    """
    import hashlib as _hl

    base_tickers = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "JNJ",
        "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK", "SCHW", "USB", "PNC",
        "UNH", "CVS", "HUM", "CI", "MCK", "ABC", "CAH", "DGX", "LH", "TMO",
        "XOM", "CVX", "COP", "EOG", "SLB", "HAL", "MRO", "DVN", "FANG", "PSX",
        "PG", "KO", "PEP", "COST", "WMT", "TGT", "HD", "LOW", "MCD", "SBUX",
        "ORCL", "IBM", "CSCO", "INTC", "AMD", "QCOM", "TXN", "AMAT", "LRCX", "KLAC",
        "LMT", "RTX", "NOC", "GD", "BA", "CAT", "DE", "EMR", "GE", "HON",
        "AMT", "PLD", "CCI", "EQIX", "PSA", "EXR", "DLR", "VTR", "WELL", "ARE",
        "NEE", "DUK", "SO", "AEP", "EXC", "SRE", "PEG", "EIX", "FE", "PPL",
        "NEM", "FCX", "AA", "X", "NUE", "STLD", "RS", "ATI", "CMC", "CENX",
        "ABBV", "LLY", "MRK", "PFE", "BMY", "AMGN", "GILD", "REGN", "VRTX", "BIIB",
    ]

    exchanges = ["NYSE", "NASDAQ"]
    rows = []
    for i, sym in enumerate(base_tickers[:110]):
        seed = int(_hl.sha256(sym.encode()).hexdigest()[:4], 16)
        sector = SECTORS[seed % len(SECTORS)]
        rows.append({
            "ticker": sym,
            "name": f"{sym.capitalize()} Corp",
            "exchange": exchanges[i % 2],
            "sector": sector,
        })
    return rows


# ---------------------------------------------------------------------------
# TIME_SERIES_DAILY_ADJUSTED
# ---------------------------------------------------------------------------

def _handle_time_series(symbol: str | None, outputsize: str | None) -> JSONResponse:
    if not symbol:
        return JSONResponse({"Error Message": "Missing symbol parameter"}, status_code=400)

    ticker = symbol.upper().strip()
    as_of = _effective_as_of()

    if ticker not in _prices:
        # Unknown ticker — return empty series (av-ingestor raises AVError, which is correct)
        return JSONResponse({
            "Meta Data": {"1. Information": "Daily Adjusted Time Series", "2. Symbol": ticker},
            "Time Series (Daily)": {},
        })

    is_compact = (outputsize or "full").lower() == "compact"
    date_keys = _compact_dates(ticker, as_of) if is_compact else _full_dates(ticker, as_of)

    series: dict[str, dict[str, str]] = {}
    ticker_day_prices = _prices[ticker]
    for d_str in date_keys:
        p = ticker_day_prices[d_str]
        series[d_str] = {
            "1. open":             f"{p['open']:.4f}",
            "2. high":             f"{p['high']:.4f}",
            "3. low":              f"{p['low']:.4f}",
            "4. close":            f"{p['close']:.4f}",
            "5. adjusted close":   f"{p['adjusted_close']:.4f}",
            "6. volume":           str(p["volume"]),
            "7. dividend amount":  "0.0",
            "8. split coefficient": "1.0",
        }

    return JSONResponse({
        "Meta Data": {
            "1. Information": "Daily Time Series with Splits and Dividend Events",
            "2. Symbol": ticker,
            "3. Last Refreshed": as_of,
            "4. Output Size": "Compact" if is_compact else "Full size",
            "5. Time Zone": "US/Eastern",
        },
        "Time Series (Daily)": series,
    })


# ---------------------------------------------------------------------------
# OVERVIEW
# ---------------------------------------------------------------------------

def _handle_overview(symbol: str | None) -> JSONResponse:
    if not symbol:
        return JSONResponse({"Error Message": "Missing symbol parameter"}, status_code=400)

    ticker = symbol.upper().strip()

    if ticker in _fundamentals:
        return JSONResponse(_fundamentals[ticker])

    # Unknown ticker — return empty dict (av-ingestor returns None, which is fine)
    return JSONResponse({})


# ---------------------------------------------------------------------------
# NEWS_SENTIMENT
# ---------------------------------------------------------------------------

def _handle_news_sentiment(tickers_param: str | None, limit_param: str | None) -> JSONResponse:
    """
    Generate news articles for the requested ticker(s).

    The llm-vetter calls this one ticker at a time:
        ?function=NEWS_SENTIMENT&tickers=AAPL&time_from=...&sort=LATEST&limit=50
    """
    if not tickers_param:
        return JSONResponse({"feed": []})

    # AV accepts comma-separated tickers, but the vetter sends one at a time.
    requested = [t.strip().upper() for t in tickers_param.split(",") if t.strip()]

    try:
        limit = int(limit_param) if limit_param else 50
    except ValueError:
        limit = 50

    as_of = _effective_as_of()
    regime = _current_regime()

    feed: list[dict[str, Any]] = []
    for ticker in requested:
        articles = generate_news(
            ticker=ticker,
            as_of_date=as_of,
            current_regime=regime,
            limit=limit,
            max_articles=3,
        )
        feed.extend(articles)

    return JSONResponse({"feed": feed})


# ---------------------------------------------------------------------------
# EARNINGS_CALENDAR
# ---------------------------------------------------------------------------

def _handle_earnings_calendar(horizon: str | None) -> PlainTextResponse:
    """
    Return CSV of upcoming earnings dates for all universe tickers.

    The llm-vetter calls this without a symbol parameter (fetches all at once).
    av-ingestor does NOT call this endpoint.
    """
    as_of = _effective_as_of()
    as_of_date = date.fromisoformat(as_of)

    # Determine the cutoff window matching the requested horizon.
    if horizon == "12month":
        cutoff = as_of_date + timedelta(days=365)
    else:
        # Default "3month" (~91 days)
        cutoff = as_of_date + timedelta(days=91)

    # Filter pre-generated rows to those within the window.
    rows_to_emit: list[dict[str, str]] = []
    for row in _earnings_rows:
        try:
            rdate = date.fromisoformat(row["reportDate"])
        except ValueError:
            continue
        if as_of_date <= rdate <= cutoff:
            rows_to_emit.append(row)

    output = io.StringIO()
    fieldnames = ["symbol", "name", "reportDate", "fiscalDateEnding", "estimate", "currency"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows_to_emit:
        writer.writerow(row)

    return PlainTextResponse(content=output.getvalue(), media_type="text/csv")


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

class ResetResponse(BaseModel):
    status: str


class ScenarioRegime(BaseModel):
    start_date: str
    type: str


class LoadScenarioRequest(BaseModel):
    name: str
    seed: int = 42
    universe_size: int = 150
    start_date: str
    end_date: str
    regimes: list[ScenarioRegime]


class LoadScenarioResponse(BaseModel):
    status: str
    tickers: int
    price_rows: int


class SetAsOfDateRequest(BaseModel):
    as_of_date: str


class SetAsOfDateResponse(BaseModel):
    as_of_date: str


class StateResponse(BaseModel):
    as_of_date: str | None
    scenario_name: str | None
    ticker_count: int
    price_rows: int
    current_regime: str
    universe_size: int
    benchmark_count: int


@app.post("/admin/reset", response_model=ResetResponse)
async def admin_reset() -> ResetResponse:
    """Clear all scenario data and reset as_of_date."""
    global _as_of_date, _scenario_name, _scenario_regimes
    global _prices, _fundamentals, _universe, _names, _earnings_rows, _scenario_seed

    _as_of_date = None
    _scenario_name = None
    _scenario_regimes = []
    _prices = {}
    _fundamentals = {}
    _universe = []
    _names = {}
    _earnings_rows = []
    _scenario_seed = 42

    log.info("State reset")
    return ResetResponse(status="reset")


@app.post("/admin/load-scenario", response_model=LoadScenarioResponse)
async def admin_load_scenario(req: LoadScenarioRequest) -> LoadScenarioResponse:
    """
    Generate all price + fundamental data for a scenario and store in memory.

    Steps:
      1. Generate universe tickers (4-letter symbols).
      2. Combine with 4 benchmark ETFs (SPY, QQQ, IWM, SOXX).
      3. Generate prices for ALL tickers via GBM with the given regimes.
      4. Generate fundamentals for universe tickers (benchmarks get a stub).
      5. Pre-generate the full earnings calendar for universe tickers.
    """
    global _as_of_date, _scenario_name, _scenario_regimes
    global _prices, _fundamentals, _universe, _names, _earnings_rows, _scenario_seed

    regimes = [{"start_date": r.start_date, "type": r.type} for r in req.regimes]
    if not regimes:
        raise HTTPException(status_code=422, detail="At least one regime is required")

    # 1. Generate universe tickers
    universe_rows = generate_universe_tickers(req.universe_size, req.seed)
    universe_tickers = [r["ticker"] for r in universe_rows]

    # 2. All tickers (universe + benchmarks)
    all_tickers = universe_tickers + BENCHMARK_TICKERS

    # Build sector map for fundamentals generation
    sector_map: dict[str, str] = {r["ticker"]: r["sector"] for r in universe_rows}

    # 3. Generate prices for all tickers
    log.info(
        "Generating prices for %d tickers [%s → %s] ...",
        len(all_tickers), req.start_date, req.end_date,
    )
    price_data = generate_prices(
        tickers=all_tickers,
        start_date=req.start_date,
        end_date=req.end_date,
        regimes=regimes,
        seed=req.seed,
    )

    # 4. Generate fundamentals for universe tickers.
    #    Benchmarks don't need real fundamentals (av-ingestor won't call OVERVIEW on them).
    fund_data = generate_fundamentals(
        tickers=universe_tickers,
        seed=req.seed,
        sector_map=sector_map,
    )
    # Add minimal benchmark fundamentals so the endpoint doesn't return empty dicts.
    for bm in BENCHMARK_TICKERS:
        fund_data[bm] = {
            "Symbol": bm,
            "PERatio": "22.0",
            "PriceToBookRatio": "4.0",
            "ReturnOnEquityTTM": "0.15",
            "DebtToEquityRatio": "0.50",
            "QuarterlyRevenueGrowthYOY": "0.05",
            "QuarterlyEarningsGrowthYOY": "0.08",
            "MarketCapitalization": "500000000000",
            "Sector": "Financials",
        }

    # 5. Earnings calendar
    names = {r["ticker"]: r["name"] for r in universe_rows}
    earnings = generate_earnings_calendar(
        tickers=universe_tickers,
        names=names,
        seed=req.seed,
    )

    # Count total price rows across all tickers
    total_price_rows = sum(len(v) for v in price_data.values())

    # Commit to module state
    _scenario_name = req.name
    _scenario_regimes = regimes
    _scenario_seed = req.seed
    _prices = price_data
    _fundamentals = fund_data
    _universe = universe_rows
    _names = names
    _earnings_rows = earnings

    # Set as_of_date to start_date by default (test harness advances it via set-as-of-date)
    _as_of_date = req.start_date

    log.info(
        "Scenario %r loaded: %d universe tickers, %d total tickers, %d price rows",
        req.name, len(universe_tickers), len(all_tickers), total_price_rows,
    )
    return LoadScenarioResponse(
        status="loaded",
        tickers=len(all_tickers),
        price_rows=total_price_rows,
    )


@app.post("/admin/set-as-of-date", response_model=SetAsOfDateResponse)
async def admin_set_as_of_date(req: SetAsOfDateRequest) -> SetAsOfDateResponse:
    """Advance the as_of_date cutoff. Only price rows on or before this date are returned."""
    global _as_of_date

    # Validate format
    try:
        date.fromisoformat(req.as_of_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}") from exc

    _as_of_date = req.as_of_date
    log.info("as_of_date set to %s", _as_of_date)
    return SetAsOfDateResponse(as_of_date=_as_of_date)


@app.get("/admin/state", response_model=StateResponse)
async def admin_state() -> StateResponse:
    """Return current simulator state summary."""
    total_price_rows = sum(len(v) for v in _prices.values())
    return StateResponse(
        as_of_date=_as_of_date,
        scenario_name=_scenario_name,
        ticker_count=len(_prices),
        price_rows=total_price_rows,
        current_regime=_current_regime(),
        universe_size=len(_universe),
        benchmark_count=len(BENCHMARK_TICKERS),
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "av-sim"}
