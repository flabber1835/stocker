import os
from contextlib import asynccontextmanager
from datetime import date

import httpx
from fastapi import BackgroundTasks, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .alpha_vantage import AVClient
from .universe import download_iwv_holdings, get_benchmark_tickers, save_universe_snapshot

DATABASE_URL = os.environ["DATABASE_URL"]
AV_API_KEY = os.getenv("AV_API_KEY", "demo")
AV_RATE_LIMIT_RPM = int(os.getenv("AV_RATE_LIMIT_RPM", "75"))
MOCK_DATA = os.getenv("MOCK_DATA", "false").lower() == "true"

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="av-ingestor", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "av-ingestor"}


@app.post("/jobs/fetch-universe")
async def fetch_universe(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_fetch_universe)
    return {"status": "started", "job": "fetch-universe"}


@app.post("/jobs/fetch-data")
async def fetch_data(background_tasks: BackgroundTasks):
    """Fetch prices and fundamentals in a single pass — one loop, two AV calls per ticker."""
    tickers = await _get_universe_tickers()
    background_tasks.add_task(_run_fetch_data, tickers)
    return {"status": "started", "job": "fetch-data", "ticker_count": len(tickers)}


@app.post("/jobs/fetch-prices")
async def fetch_prices(background_tasks: BackgroundTasks):
    """Fetch prices only. Use fetch-data for a full refresh."""
    tickers = await _get_universe_tickers()
    background_tasks.add_task(_run_fetch_prices, tickers)
    return {"status": "started", "job": "fetch-prices", "ticker_count": len(tickers)}


@app.post("/jobs/fetch-fundamentals")
async def fetch_fundamentals(background_tasks: BackgroundTasks):
    """Fetch fundamentals only. Use fetch-data for a full refresh."""
    tickers = await _get_universe_tickers()
    background_tasks.add_task(_run_fetch_fundamentals, tickers)
    return {"status": "started", "job": "fetch-fundamentals"}


@app.get("/status")
async def status():
    async with SessionLocal() as session:
        universe_count = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM universe_tickers ut
                    JOIN universe_snapshots us ON ut.snapshot_id = us.id
                    WHERE us.id = (SELECT MAX(id) FROM universe_snapshots WHERE id IS NOT NULL)
                    """
                )
            )
        ).scalar() or 0

        price_rows = (
            await session.execute(text("SELECT COUNT(*) FROM daily_prices"))
        ).scalar() or 0

        fundamental_rows = (
            await session.execute(text("SELECT COUNT(*) FROM fundamentals"))
        ).scalar() or 0

    return {
        "universe_tickers": universe_count,
        "price_rows": price_rows,
        "fundamental_rows": fundamental_rows,
    }


async def _get_universe_tickers() -> list[str]:
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT DISTINCT ut.ticker
                FROM universe_tickers ut
                JOIN universe_snapshots us ON ut.snapshot_id = us.id
                WHERE us.id = (SELECT MAX(id) FROM universe_snapshots)
                """
            )
        )
        return [row[0] for row in result.fetchall()]


async def _run_fetch_universe():
    print("[fetch-universe] starting")
    async with httpx.AsyncClient() as http:
        tickers = await download_iwv_holdings(http)
        benchmarks = await get_benchmark_tickers(http)

    all_tickers = tickers + benchmarks
    print(f"[fetch-universe] downloaded {len(tickers)} universe tickers + {len(benchmarks)} benchmarks")

    async with SessionLocal() as session:
        async with session.begin():
            snapshot_id = await save_universe_snapshot(session, "IWV", all_tickers)

    print(f"[fetch-universe] saved snapshot_id={snapshot_id} with {len(all_tickers)} tickers")


async def _run_fetch_data(tickers: list[str]):
    """Single-pass fetch: prices + fundamentals interleaved, one AVClient, one rate-limit budget."""
    extra = [t for t in ("SPY", "QQQ") if t not in tickers]
    all_tickers = tickers + extra
    today = date.today()
    print(f"[fetch-data] starting for {len(all_tickers)} tickers (prices + fundamentals in one pass)")

    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(all_tickers):
            label = f"({i+1}/{len(all_tickers)})"

            # ── prices ────────────────────────────────────────────────────────
            try:
                rows = await client.get_daily_prices(ticker)
                if rows:
                    async with SessionLocal() as session:
                        async with session.begin():
                            await session.execute(
                                text(
                                    """
                                    INSERT INTO daily_prices
                                        (ticker, date, open, high, low, close, adjusted_close, volume)
                                    VALUES
                                        (:ticker, :date, :open, :high, :low, :close, :adjusted_close, :volume)
                                    ON CONFLICT (ticker, date) DO NOTHING
                                    """
                                ),
                                [
                                    {
                                        "ticker": ticker,
                                        "date": date.fromisoformat(r["date"]),
                                        "open": r["open"],
                                        "high": r["high"],
                                        "low": r["low"],
                                        "close": r["close"],
                                        "adjusted_close": r["adjusted_close"],
                                        "volume": r["volume"],
                                    }
                                    for r in rows
                                ],
                            )
                    print(f"[fetch-data] {ticker} prices: {len(rows)} rows {label}")
                else:
                    print(f"[fetch-data] {ticker} prices: no data {label}")
            except Exception as e:
                print(f"[fetch-data] {ticker} prices: error - {e}")

            # ── fundamentals ──────────────────────────────────────────────────
            try:
                overview = await client.get_overview(ticker)
                if overview:
                    async with SessionLocal() as session:
                        async with session.begin():
                            await session.execute(
                                text(
                                    """
                                    INSERT INTO fundamentals
                                        (ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity,
                                         revenue_growth, eps_growth, market_cap, avg_volume)
                                    VALUES
                                        (:ticker, :as_of_date, :pe_ratio, :pb_ratio, :roe, :debt_to_equity,
                                         :revenue_growth, :eps_growth, :market_cap, :avg_volume)
                                    ON CONFLICT (ticker, as_of_date) DO UPDATE SET
                                        pe_ratio       = EXCLUDED.pe_ratio,
                                        pb_ratio       = EXCLUDED.pb_ratio,
                                        roe            = EXCLUDED.roe,
                                        debt_to_equity = EXCLUDED.debt_to_equity,
                                        revenue_growth = EXCLUDED.revenue_growth,
                                        eps_growth     = EXCLUDED.eps_growth,
                                        market_cap     = EXCLUDED.market_cap,
                                        avg_volume     = EXCLUDED.avg_volume,
                                        fetched_at     = NOW()
                                    """
                                ),
                                {"ticker": ticker, "as_of_date": today, **overview},
                            )
                    print(f"[fetch-data] {ticker} fundamentals: upserted {label}")
                else:
                    print(f"[fetch-data] {ticker} fundamentals: no data {label}")
            except Exception as e:
                print(f"[fetch-data] {ticker} fundamentals: error - {e}")

    finally:
        await client.close()

    print("[fetch-data] done")


async def _run_fetch_prices(tickers: list[str]):
    extra = [t for t in ("SPY", "QQQ") if t not in tickers]
    all_tickers = tickers + extra
    print(f"[fetch-prices] starting for {len(all_tickers)} tickers")

    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(all_tickers):
            try:
                rows = await client.get_daily_prices(ticker)
                if not rows:
                    print(f"[fetch-prices] {ticker}: no data returned")
                    continue
                async with SessionLocal() as session:
                    async with session.begin():
                        await session.execute(
                            text(
                                """
                                INSERT INTO daily_prices
                                    (ticker, date, open, high, low, close, adjusted_close, volume)
                                VALUES
                                    (:ticker, :date, :open, :high, :low, :close, :adjusted_close, :volume)
                                ON CONFLICT (ticker, date) DO NOTHING
                                """
                            ),
                            [
                                {
                                    "ticker": ticker,
                                    "date": date.fromisoformat(r["date"]),
                                    "open": r["open"],
                                    "high": r["high"],
                                    "low": r["low"],
                                    "close": r["close"],
                                    "adjusted_close": r["adjusted_close"],
                                    "volume": r["volume"],
                                }
                                for r in rows
                            ],
                        )
                print(f"[fetch-prices] {ticker}: upserted {len(rows)} rows ({i+1}/{len(all_tickers)})")
            except Exception as e:
                print(f"[fetch-prices] {ticker}: error - {e}")
    finally:
        await client.close()

    print("[fetch-prices] done")


async def _run_fetch_fundamentals(tickers: list[str]):
    print(f"[fetch-fundamentals] starting for {len(tickers)} tickers")
    today = date.today()

    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(tickers):
            try:
                overview = await client.get_overview(ticker)
                if not overview:
                    print(f"[fetch-fundamentals] {ticker}: no data returned")
                    continue
                async with SessionLocal() as session:
                    async with session.begin():
                        await session.execute(
                            text(
                                """
                                INSERT INTO fundamentals
                                    (ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity,
                                     revenue_growth, eps_growth, market_cap, avg_volume)
                                VALUES
                                    (:ticker, :as_of_date, :pe_ratio, :pb_ratio, :roe, :debt_to_equity,
                                     :revenue_growth, :eps_growth, :market_cap, :avg_volume)
                                ON CONFLICT (ticker, as_of_date) DO UPDATE SET
                                    pe_ratio       = EXCLUDED.pe_ratio,
                                    pb_ratio       = EXCLUDED.pb_ratio,
                                    roe            = EXCLUDED.roe,
                                    debt_to_equity = EXCLUDED.debt_to_equity,
                                    revenue_growth = EXCLUDED.revenue_growth,
                                    eps_growth     = EXCLUDED.eps_growth,
                                    market_cap     = EXCLUDED.market_cap,
                                    avg_volume     = EXCLUDED.avg_volume,
                                    fetched_at     = NOW()
                                """
                            ),
                            {"ticker": ticker, "as_of_date": today, **overview},
                        )
                print(f"[fetch-fundamentals] {ticker}: upserted ({i+1}/{len(tickers)})")
            except Exception as e:
                print(f"[fetch-fundamentals] {ticker}: error - {e}")
    finally:
        await client.close()

    print("[fetch-fundamentals] done")
