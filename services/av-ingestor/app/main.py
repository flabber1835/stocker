import json
import os
import re
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .alpha_vantage import AVClient
from .universe import download_iwv_holdings, get_benchmark_tickers, save_universe_snapshot

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")

AV_API_KEY = os.getenv("AV_API_KEY", "demo")
if AV_API_KEY in ("", "demo"):
    print("[av-ingestor] WARNING: AV_API_KEY is 'demo' — using Alpha Vantage demo key, data will be very limited")
AV_RATE_LIMIT_RPM = int(os.getenv("AV_RATE_LIMIT_RPM", "75"))
MOCK_DATA = os.getenv("MOCK_DATA", "false").lower() == "true"
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

CHECKPOINT_EVERY = 100

_TICKER_RE = re.compile(r'^[A-Z0-9.\-]{1,10}$')

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

BENCHMARK_TICKERS = ("SPY", "QQQ", "IWM", "SOXX")


def _coverage(ok: int, total: int) -> Optional[float]:
    return ok / total if total else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ingest_runs SET status='failed', completed_at=NOW(), "
                "error_message='Service restarted while run was active' "
                "WHERE status='running'"
            )
        )
    yield
    await engine.dispose()


app = FastAPI(title="av-ingestor", lifespan=lifespan)


# ── Run lifecycle helpers ────────────────────────────────

async def _start_run(run_id: str, job_type: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO ingest_runs (run_id, job_type, status, started_at) "
                "VALUES (:run_id, :job_type, 'running', :now)"
            ),
            {"run_id": run_id, "job_type": job_type, "now": datetime.now(timezone.utc)},
        )


async def _finish_run(
    run_id: str,
    status: str,
    *,
    ticker_count: Optional[int] = None,
    price_rows: Optional[int] = None,
    fund_rows: Optional[int] = None,
    error_count: int = 0,
    error_message: Optional[str] = None,
    price_coverage_pct: Optional[float] = None,
    fundamental_coverage_pct: Optional[float] = None,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ingest_runs SET status=:status, completed_at=:now, "
                "ticker_count=:tc, price_rows=:pr, fund_rows=:fr, "
                "error_count=:ec, error_message=:err, "
                "price_coverage_pct=:pcp, fundamental_coverage_pct=:fcp "
                "WHERE run_id=:rid"
            ),
            {
                "status": status, "now": datetime.now(timezone.utc),
                "tc": ticker_count, "pr": price_rows, "fr": fund_rows,
                "ec": error_count, "err": error_message,
                "pcp": round(price_coverage_pct, 4) if price_coverage_pct is not None else None,
                "fcp": round(fundamental_coverage_pct, 4) if fundamental_coverage_pct is not None else None,
                "rid": run_id,
            },
        )


# ── Trace file helpers ───────────────────────────

async def _write_trace_file(
    run_id: str,
    job_type: str,
    status: str,
    started_at: datetime,
    **progress,
) -> None:
    if not ARTIFACTS_PATH:
        return
    try:
        traces_dir = os.path.join(ARTIFACTS_PATH, "traces")
        os.makedirs(traces_dir, exist_ok=True)
        fname = f"{started_at.strftime('%Y-%m-%d')}_{job_type.replace('-', '_')}_{run_id[:8]}.json"
        payload = {
            "run_id": run_id,
            "job_type": job_type,
            "status": status,
            "started_at": started_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **progress,
        }
        path = os.path.join(traces_dir, fname)
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"[{job_type}] trace → {path} (status={status})")
    except Exception as exc:
        print(f"[{job_type}] WARNING: failed to write trace file: {exc}")
        traceback.print_exc()


async def _checkpoint(run_id: str, job_type: str, started_at: datetime, **progress) -> None:
    await _write_trace_file(run_id, job_type, "running", started_at, **progress)


# ── Endpoints ──────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "av-ingestor"}


async def _assert_no_running_job() -> None:
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT run_id FROM ingest_runs WHERE status='running' LIMIT 1")
        )
        if row.fetchone() is not None:
            raise HTTPException(
                status_code=409,
                detail="Another ingest job is already running. Wait for it to complete.",
            )


@app.post("/jobs/fetch-universe")
async def fetch_universe(background_tasks: BackgroundTasks):
    await _assert_no_running_job()
    run_id = str(uuid.uuid4())
    background_tasks.add_task(_run_fetch_universe, run_id)
    return {"status": "started", "job": "fetch-universe", "run_id": run_id}


@app.post("/jobs/fetch-data")
async def fetch_data(background_tasks: BackgroundTasks):
    await _assert_no_running_job()
    tickers, snapshot_id = await _get_universe_tickers()
    run_id = str(uuid.uuid4())
    background_tasks.add_task(_run_fetch_data, run_id, tickers)
    return {"status": "started", "job": "fetch-data", "run_id": run_id, "ticker_count": len(tickers), "snapshot_id": snapshot_id}


@app.post("/jobs/fetch-prices")
async def fetch_prices(background_tasks: BackgroundTasks):
    await _assert_no_running_job()
    tickers, snapshot_id = await _get_universe_tickers()
    run_id = str(uuid.uuid4())
    background_tasks.add_task(_run_fetch_prices, run_id, tickers)
    return {"status": "started", "job": "fetch-prices", "run_id": run_id, "ticker_count": len(tickers), "snapshot_id": snapshot_id}


@app.post("/jobs/fetch-fundamentals")
async def fetch_fundamentals(background_tasks: BackgroundTasks):
    await _assert_no_running_job()
    tickers, snapshot_id = await _get_universe_tickers()
    run_id = str(uuid.uuid4())
    background_tasks.add_task(_run_fetch_fundamentals, run_id, tickers)
    return {"status": "started", "job": "fetch-fundamentals", "run_id": run_id, "snapshot_id": snapshot_id}


@app.get("/runs/latest")
async def get_latest_run():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, job_type, status, ticker_count, price_rows, fund_rows, "
                "       error_count, error_message, started_at, completed_at "
                "FROM ingest_runs ORDER BY started_at DESC LIMIT 1"
            )
        )
        result = row.mappings().first()
    if result is None:
        raise HTTPException(status_code=404, detail="No ingest runs yet")
    return {
        "run_id": str(result["run_id"]),
        "job_type": result["job_type"],
        "status": result["status"],
        "started_at": result["started_at"].isoformat() if result["started_at"] else None,
        "completed_at": result["completed_at"].isoformat() if result["completed_at"] else None,
    }


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, job_type, status, ticker_count, price_rows, fund_rows, "
                "       error_count, error_message, price_coverage_pct, fundamental_coverage_pct, "
                "       started_at, completed_at "
                "FROM ingest_runs WHERE run_id = :rid"
            ),
            {"rid": run_id},
        )
        result = row.mappings().first()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {
        "run_id": str(result["run_id"]),
        "job_type": result["job_type"],
        "status": result["status"],
        "ticker_count": result["ticker_count"],
        "price_rows": result["price_rows"],
        "fund_rows": result["fund_rows"],
        "error_count": result["error_count"],
        "error_message": result["error_message"],
        "price_coverage_pct": float(result["price_coverage_pct"]) if result["price_coverage_pct"] is not None else None,
        "fundamental_coverage_pct": float(result["fundamental_coverage_pct"]) if result["fundamental_coverage_pct"] is not None else None,
        "started_at": result["started_at"].isoformat() if result["started_at"] else None,
        "completed_at": result["completed_at"].isoformat() if result["completed_at"] else None,
    }


@app.get("/status")
async def status():
    async with SessionLocal() as session:
        universe_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM universe_tickers ut "
                    "JOIN universe_snapshots us ON ut.snapshot_id = us.id "
                    "WHERE us.id = (SELECT MAX(id) FROM universe_snapshots WHERE id IS NOT NULL)"
                )
            )
        ).scalar() or 0
        price_rows = (await session.execute(text("SELECT COUNT(*) FROM daily_prices"))).scalar() or 0
        fundamental_rows = (await session.execute(text("SELECT COUNT(*) FROM fundamentals"))).scalar() or 0

    return {"universe_tickers": universe_count, "price_rows": price_rows, "fundamental_rows": fundamental_rows}


# ── Helpers ──────────────────────────────────

async def _get_universe_tickers() -> tuple[list[str], int | None]:
    """Return (tickers, snapshot_id) pinned to the latest snapshot at call time.

    Uses a single atomic subquery so a concurrent snapshot insert cannot cause
    the snapshot_id and ticker list to diverge (TOCTOU fix).
    """
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT DISTINCT ut.ticker, ut.snapshot_id "
                "FROM universe_tickers ut "
                "WHERE ut.snapshot_id = (SELECT MAX(id) FROM universe_snapshots)"
            )
        )
        rows = result.fetchall()
        if not rows:
            return [], None
        snapshot_id = rows[0][1]
        return [row[0] for row in rows], snapshot_id


# ── Job implementations ────────────────────────────

async def _run_fetch_universe(run_id: str) -> None:
    started_at = datetime.now(timezone.utc)
    await _start_run(run_id, "fetch-universe")
    await _checkpoint(run_id, "fetch-universe", started_at, step="download")
    print("[fetch-universe] starting")
    try:
        async with httpx.AsyncClient() as http:
            tickers = await download_iwv_holdings(http)
            benchmarks = await get_benchmark_tickers(http)
        all_tickers = tickers + benchmarks
        print(f"[fetch-universe] downloaded {len(tickers)} universe + {len(benchmarks)} benchmarks")
        await _checkpoint(run_id, "fetch-universe", started_at,
                          step="save", ticker_count=len(all_tickers))

        async with SessionLocal() as session:
            async with session.begin():
                snapshot_id = await save_universe_snapshot(session, "IWV", all_tickers)
        print(f"[fetch-universe] saved snapshot_id={snapshot_id} with {len(all_tickers)} tickers")
        await _finish_run(run_id, "success", ticker_count=len(all_tickers))
        await _write_trace_file(run_id, "fetch-universe", "success", started_at,
                                ticker_count=len(all_tickers), snapshot_id=snapshot_id)
    except Exception as exc:
        traceback.print_exc()
        err = str(exc)[:1000]
        print(f"[fetch-universe] FAILED: {exc}")
        await _finish_run(run_id, "failed", error_message=err)
        await _write_trace_file(run_id, "fetch-universe", "failed", started_at, error_message=err)
        raise


async def _run_fetch_data(run_id: str, tickers: list[str]) -> None:
    started_at = datetime.now(timezone.utc)
    await _start_run(run_id, "fetch-data")
    benchmark_set = set(BENCHMARK_TICKERS)
    extra_benchmarks = [t for t in BENCHMARK_TICKERS if t not in set(tickers)]
    price_tickers = tickers + extra_benchmarks
    fundamental_tickers = [t for t in tickers if t not in benchmark_set]
    fundamental_set = set(fundamental_tickers)
    today = date.today()
    print(f"[fetch-data] starting: {len(price_tickers)} price tickers, "
          f"{len(fundamental_tickers)} fundamental tickers")
    await _checkpoint(run_id, "fetch-data", started_at,
                      tickers_done=0, total_tickers=len(price_tickers),
                      price_rows=0, fund_rows=0, error_count=0)

    price_ok = price_rows_written = fund_ok = err_count = 0
    # avg_dollar_volume_20d computed from the last 20 price rows for each ticker,
    # since AV OVERVIEW does not reliably provide this field.
    _ticker_avg_dv: dict[str, float] = {}
    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(price_tickers):
            if not _TICKER_RE.match(ticker):
                print(f"[fetch-data] skipping invalid ticker: {ticker!r}")
                continue
            label = f"({i+1}/{len(price_tickers)})"
            try:
                rows = await client.get_daily_prices(ticker)
                if rows:
                    async with SessionLocal() as session:
                        async with session.begin():
                            await session.execute(
                                text(
                                    "INSERT INTO daily_prices "
                                    "    (ticker, date, open, high, low, close, adjusted_close, volume) "
                                    "VALUES "
                                    "    (:ticker, :date, :open, :high, :low, :close, :adjusted_close, :volume) "
                                    "ON CONFLICT (ticker, date) DO UPDATE SET "
                                    "    open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, "
                                    "    close=EXCLUDED.close, adjusted_close=EXCLUDED.adjusted_close, "
                                    "    volume=EXCLUDED.volume, fetched_at=NOW()"
                                ),
                                [{"ticker": ticker, "date": date.fromisoformat(r["date"]),
                                  "open": r["open"], "high": r["high"], "low": r["low"],
                                  "close": r["close"], "adjusted_close": r["adjusted_close"],
                                  "volume": r["volume"]} for r in rows],
                            )
                    price_rows_written += len(rows)
                    price_ok += 1
                    last_20 = sorted(rows, key=lambda r: r["date"])[-20:]
                    dv_vals = [(r["close"] or 0) * (r["volume"] or 0) for r in last_20]
                    if dv_vals:
                        _ticker_avg_dv[ticker] = sum(dv_vals) / len(dv_vals)
                    print(f"[fetch-data] {ticker} prices: {len(rows)} rows {label}")
                else:
                    print(f"[fetch-data] {ticker} prices: no data {label}")
            except Exception as e:
                err_count += 1
                print(f"[fetch-data] {ticker} prices: error - {e}")

            if ticker in fundamental_set:
                try:
                    overview = await client.get_overview(ticker)
                    if overview:
                        overview["avg_volume"] = _ticker_avg_dv.get(ticker)
                        async with SessionLocal() as session:
                            async with session.begin():
                                await session.execute(
                                    text(
                                        "INSERT INTO fundamentals "
                                        "    (ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity, "
                                        "     revenue_growth, eps_growth, market_cap, avg_volume) "
                                        "VALUES "
                                        "    (:ticker, :as_of_date, :pe_ratio, :pb_ratio, :roe, :debt_to_equity, "
                                        "     :revenue_growth, :eps_growth, :market_cap, :avg_volume) "
                                        "ON CONFLICT (ticker, as_of_date) DO UPDATE SET "
                                        "    pe_ratio=EXCLUDED.pe_ratio, pb_ratio=EXCLUDED.pb_ratio, "
                                        "    roe=EXCLUDED.roe, debt_to_equity=EXCLUDED.debt_to_equity, "
                                        "    revenue_growth=EXCLUDED.revenue_growth, eps_growth=EXCLUDED.eps_growth, "
                                        "    market_cap=EXCLUDED.market_cap, avg_volume=EXCLUDED.avg_volume, "
                                        "    fetched_at=NOW()"
                                    ),
                                    {"ticker": ticker, "as_of_date": today, **overview},
                                )
                        fund_ok += 1
                        print(f"[fetch-data] {ticker} fundamentals: upserted {label}")
                    else:
                        print(f"[fetch-data] {ticker} fundamentals: no data {label}")
                except Exception as e:
                    err_count += 1
                    print(f"[fetch-data] {ticker} fundamentals: error - {e}")

            if (i + 1) % CHECKPOINT_EVERY == 0:
                await _checkpoint(run_id, "fetch-data", started_at,
                                  tickers_done=i + 1, total_tickers=len(price_tickers),
                                  price_rows=price_rows_written, fund_rows=fund_ok,
                                  error_count=err_count)
        status = "partial_success" if err_count > 0 else "success"
        pcp = _coverage(price_ok, len(price_tickers))
        fcp = _coverage(fund_ok, len(fundamental_tickers))
        await _finish_run(run_id, status,
                          ticker_count=len(price_tickers), price_rows=price_rows_written,
                          fund_rows=fund_ok, error_count=err_count,
                          price_coverage_pct=pcp, fundamental_coverage_pct=fcp)
        await _write_trace_file(run_id, "fetch-data", status, started_at,
                                tickers_done=len(price_tickers), total_tickers=len(price_tickers),
                                price_rows=price_rows_written, fund_rows=fund_ok,
                                error_count=err_count)
        print("[fetch-data] done")
    except Exception as exc:
        traceback.print_exc()
        err = str(exc)[:1000]
        print(f"[fetch-data] FATAL: {exc}")
        await _finish_run(run_id, "failed", error_message=err)
        await _write_trace_file(run_id, "fetch-data", "failed", started_at, error_message=err)
        raise
    finally:
        await client.close()


async def _run_fetch_prices(run_id: str, tickers: list[str]) -> None:
    started_at = datetime.now(timezone.utc)
    await _start_run(run_id, "fetch-prices")
    extra = [t for t in BENCHMARK_TICKERS if t not in set(tickers)]
    all_tickers = tickers + extra
    print(f"[fetch-prices] starting for {len(all_tickers)} tickers")
    await _checkpoint(run_id, "fetch-prices", started_at,
                      tickers_done=0, total_tickers=len(all_tickers),
                      price_rows=0, error_count=0)

    rows_written = err_count = tickers_ok = 0
    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(all_tickers):
            if not _TICKER_RE.match(ticker):
                print(f"[fetch-prices] skipping invalid ticker: {ticker!r}")
                continue
            try:
                rows = await client.get_daily_prices(ticker)
                if not rows:
                    print(f"[fetch-prices] {ticker}: no data returned")
                else:
                    async with SessionLocal() as session:
                        async with session.begin():
                            await session.execute(
                                text(
                                    "INSERT INTO daily_prices "
                                    "    (ticker, date, open, high, low, close, adjusted_close, volume) "
                                    "VALUES "
                                    "    (:ticker, :date, :open, :high, :low, :close, :adjusted_close, :volume) "
                                    "ON CONFLICT (ticker, date) DO UPDATE SET "
                                    "    open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, "
                                    "    close=EXCLUDED.close, adjusted_close=EXCLUDED.adjusted_close, "
                                    "    volume=EXCLUDED.volume, fetched_at=NOW()"
                                ),
                                [{"ticker": ticker, "date": date.fromisoformat(r["date"]),
                                  "open": r["open"], "high": r["high"], "low": r["low"],
                                  "close": r["close"], "adjusted_close": r["adjusted_close"],
                                  "volume": r["volume"]} for r in rows],
                            )
                    rows_written += len(rows)
                    tickers_ok += 1
                    print(f"[fetch-prices] {ticker}: upserted {len(rows)} rows ({i+1}/{len(all_tickers)})")
            except Exception as e:
                err_count += 1
                print(f"[fetch-prices] {ticker}: error - {e}")
            if (i + 1) % CHECKPOINT_EVERY == 0:
                await _checkpoint(run_id, "fetch-prices", started_at,
                                  tickers_done=i + 1, total_tickers=len(all_tickers),
                                  price_rows=rows_written, error_count=err_count)
        status = "partial_success" if err_count > 0 else "success"
        pcp = _coverage(tickers_ok, len(all_tickers))
        await _finish_run(run_id, status,
                          ticker_count=len(all_tickers), price_rows=rows_written, error_count=err_count,
                          price_coverage_pct=pcp)
        await _write_trace_file(run_id, "fetch-prices", status, started_at,
                                tickers_done=len(all_tickers), total_tickers=len(all_tickers),
                                price_rows=rows_written, error_count=err_count,
                                price_coverage_pct=pcp)
        print("[fetch-prices] done")
    except Exception as exc:
        traceback.print_exc()
        err = str(exc)[:1000]
        print(f"[fetch-prices] FATAL: {exc}")
        await _finish_run(run_id, "failed", error_message=err)
        await _write_trace_file(run_id, "fetch-prices", "failed", started_at, error_message=err)
        raise
    finally:
        await client.close()


async def _run_fetch_fundamentals(run_id: str, tickers: list[str]) -> None:
    started_at = datetime.now(timezone.utc)
    await _start_run(run_id, "fetch-fundamentals")
    investable = [t for t in tickers if t not in set(BENCHMARK_TICKERS)]
    print(f"[fetch-fundamentals] starting for {len(investable)} investable tickers")
    today = date.today()
    await _checkpoint(run_id, "fetch-fundamentals", started_at,
                      tickers_done=0, total_tickers=len(investable),
                      fund_rows=0, error_count=0)

    fund_ok = err_count = 0
    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(investable):
            if not _TICKER_RE.match(ticker):
                print(f"[fetch-fundamentals] skipping invalid ticker: {ticker!r}")
                continue
            try:
                overview = await client.get_overview(ticker)
                if not overview:
                    print(f"[fetch-fundamentals] {ticker}: no data returned")
                else:
                    # Compute avg_dollar_volume_20d from existing price data
                    async with engine.connect() as conn:
                        dv_row = await conn.execute(
                            text(
                                "SELECT AVG(close * volume) FROM ("
                                "  SELECT close, volume FROM daily_prices "
                                "  WHERE ticker = :ticker ORDER BY date DESC LIMIT 20"
                                ") t"
                            ),
                            {"ticker": ticker},
                        )
                        dv_val = dv_row.scalar()
                    overview["avg_volume"] = float(dv_val) if dv_val is not None else None

                    async with SessionLocal() as session:
                        async with session.begin():
                            await session.execute(
                                text(
                                    "INSERT INTO fundamentals "
                                    "    (ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity, "
                                    "     revenue_growth, eps_growth, market_cap, avg_volume) "
                                    "VALUES "
                                    "    (:ticker, :as_of_date, :pe_ratio, :pb_ratio, :roe, :debt_to_equity, "
                                    "     :revenue_growth, :eps_growth, :market_cap, :avg_volume) "
                                    "ON CONFLICT (ticker, as_of_date) DO UPDATE SET "
                                    "    pe_ratio=EXCLUDED.pe_ratio, pb_ratio=EXCLUDED.pb_ratio, "
                                    "    roe=EXCLUDED.roe, debt_to_equity=EXCLUDED.debt_to_equity, "
                                    "    revenue_growth=EXCLUDED.revenue_growth, eps_growth=EXCLUDED.eps_growth, "
                                    "    market_cap=EXCLUDED.market_cap, avg_volume=EXCLUDED.avg_volume, "
                                    "    fetched_at=NOW()"
                                ),
                                {"ticker": ticker, "as_of_date": today, **overview},
                            )
                    fund_ok += 1
                    print(f"[fetch-fundamentals] {ticker}: upserted ({i+1}/{len(investable)})")
            except Exception as e:
                err_count += 1
                print(f"[fetch-fundamentals] {ticker}: error - {e}")
            if (i + 1) % CHECKPOINT_EVERY == 0:
                await _checkpoint(run_id, "fetch-fundamentals", started_at,
                                  tickers_done=i + 1, total_tickers=len(investable),
                                  fund_rows=fund_ok, error_count=err_count)
        status = "partial_success" if err_count > 0 else "success"
        fcp = _coverage(fund_ok, len(investable))
        await _finish_run(run_id, status,
                          ticker_count=len(investable), fund_rows=fund_ok, error_count=err_count,
                          fundamental_coverage_pct=fcp)
        await _write_trace_file(run_id, "fetch-fundamentals", status, started_at,
                                tickers_done=len(investable), total_tickers=len(investable),
                                fund_rows=fund_ok, error_count=err_count)
        print("[fetch-fundamentals] done")
    except Exception as exc:
        traceback.print_exc()
        err = str(exc)[:1000]
        print(f"[fetch-fundamentals] FATAL: {exc}")
        await _finish_run(run_id, "failed", error_message=err)
        await _write_trace_file(run_id, "fetch-fundamentals", "failed", started_at, error_message=err)
        raise
    finally:
        await client.close()
