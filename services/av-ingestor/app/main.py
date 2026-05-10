import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Optional

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
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

BENCHMARK_TICKERS = ("SPY", "QQQ")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="av-ingestor", lifespan=lifespan)


# ── Trace helpers ──────────────────────────────────────────────

async def _start_run(run_id: str, trace_id: str, job_type: str) -> datetime:
    started_at = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO ingest_runs (run_id, trace_id, job_type, status, started_at) "
                "VALUES (:run_id, :trace_id, :job_type, 'running', :started_at)"
            ),
            {"run_id": run_id, "trace_id": trace_id, "job_type": job_type, "started_at": started_at},
        )
        await conn.execute(
            text(
                "INSERT INTO execution_traces "
                "(trace_id, job_type, status, root_run_id, started_at) "
                "VALUES (:tid, 'ingest_run', 'running', CAST(:rid AS uuid), :now)"
            ),
            {"tid": trace_id, "rid": run_id, "now": started_at},
        )
    return started_at


async def _finish_run(
    run_id: str,
    trace_id: str,
    status: str,
    *,
    ticker_count: Optional[int] = None,
    price_rows: Optional[int] = None,
    fund_rows: Optional[int] = None,
    error_count: int = 0,
    error_message: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ingest_runs SET status=:status, completed_at=:now, "
                "ticker_count=:tc, price_rows=:pr, fund_rows=:fr, "
                "error_count=:ec, error_message=:err WHERE run_id=:rid"
            ),
            {"status": status, "now": now, "tc": ticker_count, "pr": price_rows,
             "fr": fund_rows, "ec": error_count, "err": error_message, "rid": run_id},
        )
        await conn.execute(
            text("UPDATE execution_traces SET status=:status, completed_at=:now WHERE trace_id=:tid"),
            {"status": status, "now": now, "tid": trace_id},
        )


async def _log_step(
    trace_id: str,
    step_name: str,
    status: str,
    *,
    started_at: Optional[datetime] = None,
    input_summary: Optional[dict] = None,
    output_summary: Optional[dict] = None,
    warnings: Optional[list] = None,
    error_message: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO execution_steps "
                "(step_id, trace_id, service, step_name, status, started_at, completed_at, "
                " input_summary, output_summary, warnings, error_message) "
                "VALUES (:sid, :tid, 'av-ingestor', :step, :status, :started, :now, "
                "        CAST(:inp AS jsonb), CAST(:out AS jsonb), CAST(:warn AS jsonb), :err)"
            ),
            {
                "sid": str(uuid.uuid4()), "tid": trace_id, "step": step_name,
                "status": status, "started": started_at or now, "now": now,
                "inp": json.dumps(input_summary) if input_summary else None,
                "out": json.dumps(output_summary) if output_summary else None,
                "warn": json.dumps(warnings) if warnings else None,
                "err": error_message,
            },
        )


async def _write_trace_file(
    trace_id: str,
    run_id: str,
    job_type: str,
    status: str,
    started_at: datetime,
    **extra,
) -> None:
    if not ARTIFACTS_PATH:
        return
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT service, step_name, status, started_at, completed_at, "
                "       input_summary, output_summary, warnings, error_message "
                "FROM execution_steps WHERE trace_id = :tid ORDER BY started_at ASC"
            ),
            {"tid": trace_id},
        )
        steps = [dict(r) for r in rows.mappings()]
    traces_dir = os.path.join(ARTIFACTS_PATH, "traces")
    os.makedirs(traces_dir, exist_ok=True)
    fname = f"{started_at.strftime('%Y-%m-%d')}_{job_type}_{trace_id[:8]}.json"
    payload = {
        "trace_id": trace_id, "run_id": run_id, "job_type": job_type,
        "status": status, "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        **extra, "steps": steps,
    }
    path = os.path.join(traces_dir, fname)
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"[av-ingestor] trace written → {path}")


# ── Endpoints ────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "av-ingestor"}


@app.post("/jobs/fetch-universe")
async def fetch_universe(background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    background_tasks.add_task(_run_fetch_universe, run_id, trace_id)
    return {"status": "started", "job": "fetch-universe", "run_id": run_id, "trace_id": trace_id}


@app.post("/jobs/fetch-data")
async def fetch_data(background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    tickers = await _get_universe_tickers()
    background_tasks.add_task(_run_fetch_data, run_id, trace_id, tickers)
    return {"status": "started", "job": "fetch-data", "run_id": run_id, "trace_id": trace_id, "ticker_count": len(tickers)}


@app.post("/jobs/fetch-prices")
async def fetch_prices(background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    tickers = await _get_universe_tickers()
    background_tasks.add_task(_run_fetch_prices, run_id, trace_id, tickers)
    return {"status": "started", "job": "fetch-prices", "run_id": run_id, "trace_id": trace_id, "ticker_count": len(tickers)}


@app.post("/jobs/fetch-fundamentals")
async def fetch_fundamentals(background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    tickers = await _get_universe_tickers()
    background_tasks.add_task(_run_fetch_fundamentals, run_id, trace_id, tickers)
    return {"status": "started", "job": "fetch-fundamentals", "run_id": run_id, "trace_id": trace_id}


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    from fastapi import HTTPException
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, trace_id, job_type, status, ticker_count, price_rows, fund_rows, "
                "       error_count, error_message, started_at, completed_at "
                "FROM ingest_runs WHERE run_id = :rid"
            ),
            {"rid": run_id},
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {
        "run_id": str(result.run_id),
        "trace_id": str(result.trace_id) if result.trace_id else None,
        "job_type": result.job_type,
        "status": result.status,
        "ticker_count": result.ticker_count,
        "price_rows": result.price_rows,
        "fund_rows": result.fund_rows,
        "error_count": result.error_count,
        "error_message": result.error_message,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
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


# ── Helpers ───────────────────────────────────────────────────

async def _get_universe_tickers() -> list[str]:
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT DISTINCT ut.ticker FROM universe_tickers ut "
                "JOIN universe_snapshots us ON ut.snapshot_id = us.id "
                "WHERE us.id = (SELECT MAX(id) FROM universe_snapshots)"
            )
        )
        return [row[0] for row in result.fetchall()]


# ── Job implementations ────────────────────────────────────────────

async def _run_fetch_universe(run_id: str, trace_id: str) -> None:
    started_at = await _start_run(run_id, trace_id, "fetch-universe")
    print("[fetch-universe] starting")
    try:
        t0 = datetime.now(timezone.utc)
        async with httpx.AsyncClient() as http:
            tickers = await download_iwv_holdings(http)
            benchmarks = await get_benchmark_tickers(http)
        all_tickers = tickers + benchmarks
        print(f"[fetch-universe] downloaded {len(tickers)} universe + {len(benchmarks)} benchmarks")
        await _log_step(
            trace_id, "download_holdings", "success", started_at=t0,
            output_summary={"universe_tickers": len(tickers), "benchmark_tickers": len(benchmarks), "total": len(all_tickers)},
        )

        t0 = datetime.now(timezone.utc)
        async with SessionLocal() as session:
            async with session.begin():
                snapshot_id = await save_universe_snapshot(session, "IWV", all_tickers)
        print(f"[fetch-universe] saved snapshot_id={snapshot_id} with {len(all_tickers)} tickers")
        await _log_step(
            trace_id, "save_snapshot", "success", started_at=t0,
            output_summary={"snapshot_id": snapshot_id, "ticker_count": len(all_tickers)},
        )

        await _finish_run(run_id, trace_id, "success", ticker_count=len(all_tickers))
        await _write_trace_file(trace_id, run_id, "fetch-universe", "success", started_at,
                                ticker_count=len(all_tickers), snapshot_id=snapshot_id)
    except Exception as exc:
        err = str(exc)[:1000]
        print(f"[fetch-universe] FAILED: {exc}")
        await _finish_run(run_id, trace_id, "failed", error_message=err)
        await _write_trace_file(trace_id, run_id, "fetch-universe", "failed", started_at, error=err)
        raise


async def _run_fetch_data(run_id: str, trace_id: str, tickers: list[str]) -> None:
    started_at = await _start_run(run_id, trace_id, "fetch-data")
    benchmark_set = set(BENCHMARK_TICKERS)
    extra_benchmarks = [t for t in BENCHMARK_TICKERS if t not in set(tickers)]
    price_tickers = tickers + extra_benchmarks
    fundamental_tickers = [t for t in tickers if t not in benchmark_set]
    today = date.today()

    print(f"[fetch-data] starting: {len(price_tickers)} price, {len(fundamental_tickers)} fundamentals")
    await _log_step(
        trace_id, "load_tickers", "success",
        output_summary={"universe_count": len(tickers), "price_tickers": len(price_tickers), "fundamental_tickers": len(fundamental_tickers)},
    )

    price_ok = price_no_data = price_err = price_rows_written = 0
    fund_ok = fund_no_data = fund_err = 0
    t_price = datetime.now(timezone.utc)

    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(price_tickers):
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
                    print(f"[fetch-data] {ticker} prices: {len(rows)} rows {label}")
                else:
                    price_no_data += 1
                    print(f"[fetch-data] {ticker} prices: no data {label}")
            except Exception as e:
                price_err += 1
                print(f"[fetch-data] {ticker} prices: error - {e}")

            if ticker not in set(fundamental_tickers):
                continue
            try:
                overview = await client.get_overview(ticker)
                if overview:
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
                    fund_no_data += 1
                    print(f"[fetch-data] {ticker} fundamentals: no data {label}")
            except Exception as e:
                fund_err += 1
                print(f"[fetch-data] {ticker} fundamentals: error - {e}")
    finally:
        await client.close()

    price_warnings = []
    if price_err:
        price_warnings.append(f"{price_err} tickers had price errors")
    if price_no_data:
        price_warnings.append(f"{price_no_data} tickers returned no price data")
    await _log_step(
        trace_id, "fetch_prices", "success", started_at=t_price,
        output_summary={"rows_written": price_rows_written, "ok": price_ok, "no_data": price_no_data, "errors": price_err},
        warnings=price_warnings or None,
    )

    fund_warnings = [f"{fund_err} tickers had fundamentals errors"] if fund_err else None
    await _log_step(
        trace_id, "fetch_fundamentals", "success",
        output_summary={"tickers_ok": fund_ok, "no_data": fund_no_data, "errors": fund_err},
        warnings=fund_warnings,
    )

    total_err = price_err + fund_err
    await _finish_run(run_id, trace_id, "success",
                      ticker_count=len(price_tickers), price_rows=price_rows_written,
                      fund_rows=fund_ok, error_count=total_err)
    await _write_trace_file(trace_id, run_id, "fetch-data", "success", started_at,
                            price_tickers=len(price_tickers), fundamental_tickers=len(fundamental_tickers),
                            price_rows_written=price_rows_written, fund_ok=fund_ok, error_count=total_err)
    print("[fetch-data] done")


async def _run_fetch_prices(run_id: str, trace_id: str, tickers: list[str]) -> None:
    started_at = await _start_run(run_id, trace_id, "fetch-prices")
    extra = [t for t in BENCHMARK_TICKERS if t not in set(tickers)]
    all_tickers = tickers + extra
    print(f"[fetch-prices] starting for {len(all_tickers)} tickers")

    await _log_step(trace_id, "load_tickers", "success",
                    output_summary={"ticker_count": len(all_tickers)})

    ok = no_data = err = rows_written = 0
    t0 = datetime.now(timezone.utc)
    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(all_tickers):
            try:
                rows = await client.get_daily_prices(ticker)
                if not rows:
                    no_data += 1
                    print(f"[fetch-prices] {ticker}: no data returned")
                    continue
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
                ok += 1
                print(f"[fetch-prices] {ticker}: upserted {len(rows)} rows ({i+1}/{len(all_tickers)})")
            except Exception as e:
                err += 1
                print(f"[fetch-prices] {ticker}: error - {e}")
    finally:
        await client.close()

    warnings = []
    if err:
        warnings.append(f"{err} tickers had errors")
    if no_data:
        warnings.append(f"{no_data} tickers returned no data")
    await _log_step(trace_id, "fetch_prices", "success", started_at=t0,
                    output_summary={"rows_written": rows_written, "ok": ok, "no_data": no_data, "errors": err},
                    warnings=warnings or None)

    await _finish_run(run_id, trace_id, "success",
                      ticker_count=len(all_tickers), price_rows=rows_written, error_count=err)
    await _write_trace_file(trace_id, run_id, "fetch-prices", "success", started_at,
                            ticker_count=len(all_tickers), rows_written=rows_written, error_count=err)
    print("[fetch-prices] done")


async def _run_fetch_fundamentals(run_id: str, trace_id: str, tickers: list[str]) -> None:
    started_at = await _start_run(run_id, trace_id, "fetch-fundamentals")
    investable = [t for t in tickers if t not in set(BENCHMARK_TICKERS)]
    print(f"[fetch-fundamentals] starting for {len(investable)} investable tickers")
    today = date.today()

    await _log_step(trace_id, "load_tickers", "success",
                    output_summary={"investable_count": len(investable), "benchmarks_skipped": len(tickers) - len(investable)})

    ok = no_data = err = 0
    t0 = datetime.now(timezone.utc)
    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(investable):
            try:
                overview = await client.get_overview(ticker)
                if not overview:
                    no_data += 1
                    print(f"[fetch-fundamentals] {ticker}: no data returned")
                    continue
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
                ok += 1
                print(f"[fetch-fundamentals] {ticker}: upserted ({i+1}/{len(investable)})")
            except Exception as e:
                err += 1
                print(f"[fetch-fundamentals] {ticker}: error - {e}")
    finally:
        await client.close()

    warnings = [f"{err} tickers had errors"] if err else None
    await _log_step(trace_id, "fetch_fundamentals", "success", started_at=t0,
                    output_summary={"tickers_ok": ok, "no_data": no_data, "errors": err},
                    warnings=warnings)

    await _finish_run(run_id, trace_id, "success",
                      ticker_count=len(investable), fund_rows=ok, error_count=err)
    await _write_trace_file(trace_id, run_id, "fetch-fundamentals", "success", started_at,
                            ticker_count=len(investable), fund_ok=ok, error_count=err)
    print("[fetch-fundamentals] done")
