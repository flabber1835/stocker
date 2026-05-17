import asyncio
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
from .universe import download_av_universe, get_benchmark_tickers, save_universe_snapshot

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

_TICKER_RE = re.compile(r"^[A-Z]{1,5}([.\-][A-Z0-9]{1,4})?$")

# In-memory progress for the currently running fetch-data job.
# Polled by /runs/latest so the dashboard can show real progress.
_fetch_data_progress: dict = {}  # {run_id, tickers_done, total_tickers}

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

BENCHMARK_TICKERS = ("SPY", "QQQ", "IWM", "SOXX")


# ── Pure deterministic helpers (importable for tests) ─────────────────────────

def _should_skip_price(ticker: str, ticker_latest: dict, spy_max) -> bool:
    """Return True if this ticker's price data is already current (matches spy_max)."""
    return bool(spy_max and ticker_latest.get(ticker) == spy_max)


def _should_use_compact(ticker: str, ticker_latest: dict) -> bool:
    """Return True if the ticker already has price history — use compact (100-day) fetch."""
    return ticker_latest.get(ticker) is not None


def _should_skip_fundamentals(ticker: str, fund_latest: dict, today: date, max_age_days: int = 7) -> bool:
    """Return True if fundamentals were fetched within max_age_days (AV OVERVIEW is quarterly data)."""
    last = fund_latest.get(ticker)
    if last is None:
        return False
    return (today - last).days < max_age_days


def _build_benchmarks_first(universe_tickers: list[str]) -> list[str]:
    """Return the ordered ticker list with benchmarks first, then universe (deduped)."""
    universe_set = set(universe_tickers)
    extra_benchmarks = [t for t in BENCHMARK_TICKERS if t not in universe_set]
    return extra_benchmarks + list(universe_tickers)


def _coverage(ok: int, total: int) -> Optional[float]:
    return ok / total if total else None


async def _upsert_prices(session, ticker: str, rows: list[dict]) -> None:
    """Upsert daily price rows for a single ticker."""
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
          "close": r["close"],
          "adjusted_close": r["adjusted_close"] if r.get("adjusted_close") and 0 < r["adjusted_close"] < 1_000_000 else None,
          "volume": r["volume"]} for r in rows],
    )


async def _upsert_fundamentals(session, ticker: str, overview: dict, today: date) -> None:
    """Upsert fundamental data for a single ticker. Pops 'sector' from overview dict."""
    sector = overview.pop("sector", None)
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
    if sector:
        await session.execute(
            text(
                "UPDATE universe_tickers SET sector=:sector "
                "WHERE ticker=:ticker AND sector IS DISTINCT FROM :sector"
            ),
            {"ticker": ticker, "sector": sector},
        )


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

# Serialises concurrent job-start requests so the TOCTOU check-then-insert is atomic.
# Single-process service (Docker), so asyncio.Lock is sufficient.
_job_lock = asyncio.Lock()


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
    async with _job_lock:
        await _assert_no_running_job()
        run_id = str(uuid.uuid4())
        background_tasks.add_task(_run_fetch_universe, run_id)
    return {"status": "started", "job": "fetch-universe", "run_id": run_id}


@app.post("/jobs/fetch-data")
async def fetch_data(background_tasks: BackgroundTasks):
    async with _job_lock:
        await _assert_no_running_job()
        tickers, snapshot_id = await _get_universe_tickers()
        run_id = str(uuid.uuid4())
        background_tasks.add_task(_run_fetch_data, run_id, tickers)
    return {"status": "started", "job": "fetch-data", "run_id": run_id, "ticker_count": len(tickers), "snapshot_id": snapshot_id}


@app.post("/jobs/fetch-prices")
async def fetch_prices(background_tasks: BackgroundTasks):
    async with _job_lock:
        await _assert_no_running_job()
        tickers, snapshot_id = await _get_universe_tickers()
        run_id = str(uuid.uuid4())
        background_tasks.add_task(_run_fetch_prices, run_id, tickers)
    return {"status": "started", "job": "fetch-prices", "run_id": run_id, "ticker_count": len(tickers), "snapshot_id": snapshot_id}


@app.post("/jobs/fetch-fundamentals")
async def fetch_fundamentals(background_tasks: BackgroundTasks):
    async with _job_lock:
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
    run_id = str(result["run_id"])
    resp = {
        "run_id": run_id,
        "job_type": result["job_type"],
        "status": result["status"],
        "started_at": result["started_at"].isoformat() if result["started_at"] else None,
        "completed_at": result["completed_at"].isoformat() if result["completed_at"] else None,
    }
    # Attach live progress if this is the currently running fetch-data job.
    if _fetch_data_progress.get("run_id") == run_id:
        resp["tickers_done"] = _fetch_data_progress["tickers_done"]
        resp["total_tickers"] = _fetch_data_progress["total_tickers"]
    return resp


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
                "WHERE ut.snapshot_id = (SELECT MAX(id) FROM universe_snapshots) "
                "ORDER BY ut.ticker"
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
            tickers, listing_stats = await download_av_universe(http, av_api_key=AV_API_KEY)
            benchmarks = await get_benchmark_tickers(http)
        all_tickers = tickers + benchmarks
        print(
            f"[fetch-universe] downloaded {len(tickers)} universe + {len(benchmarks)} benchmarks "
            f"(filtered: {listing_stats.get('filtered_warrant_unit', 0)} warrants/units, "
            f"{listing_stats.get('filtered_non_stock', 0)} non-stock, "
            f"{listing_stats.get('filtered_exchange', 0)} wrong-exchange)"
        )
        await _checkpoint(run_id, "fetch-universe", started_at,
                          step="save", ticker_count=len(all_tickers))

        async with SessionLocal() as session:
            async with session.begin():
                snapshot_id = await save_universe_snapshot(session, "AV_LISTING", all_tickers)
        print(f"[fetch-universe] saved snapshot_id={snapshot_id} with {len(all_tickers)} tickers")
        await _finish_run(run_id, "success", ticker_count=len(all_tickers))
        await _write_trace_file(run_id, "fetch-universe", "success", started_at,
                                ticker_count=len(all_tickers), snapshot_id=snapshot_id,
                                listing_stats=listing_stats)
    except Exception as exc:
        traceback.print_exc()
        err = str(exc)[:1000]
        print(f"[fetch-universe] FAILED: {exc}")
        await _finish_run(run_id, "failed", error_message=err)
        await _write_trace_file(run_id, "fetch-universe", "failed", started_at, error_message=err)
        raise


async def _load_price_staleness() -> tuple[dict[str, date], date | None]:
    """Return (ticker→latest_date_in_db, spy_max_date).

    spy_max_date is the ground-truth for what the most recent available trading
    date is.  Any ticker whose latest_date already equals spy_max_date has
    up-to-date prices and can be skipped.
    """
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT ticker, MAX(date) AS latest FROM daily_prices GROUP BY ticker")
        )
        ticker_latest = {r.ticker: r.latest for r in rows.fetchall()}
    spy_max = ticker_latest.get("SPY")
    return ticker_latest, spy_max


async def _load_fund_staleness() -> dict[str, date]:
    """Return ticker→most_recent_fetched_at for fundamentals."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT ticker, MAX(fetched_at)::date AS last_fetched "
                "FROM fundamentals GROUP BY ticker"
            )
        )
        return {r.ticker: r.last_fetched for r in rows.fetchall()}


async def _run_fetch_data(run_id: str, tickers: list[str]) -> None:
    started_at = datetime.now(timezone.utc)
    await _start_run(run_id, "fetch-data")
    benchmark_set = set(BENCHMARK_TICKERS)
    # Fetch benchmark tickers (SPY etc.) FIRST so spy_max lands in the DB early.
    # If benchmarks are last and the run is interrupted, spy_max=None on the next
    # run and every ticker gets re-fetched from scratch.
    price_tickers = _build_benchmarks_first(tickers)
    fundamental_tickers = [t for t in tickers if t not in benchmark_set]
    fundamental_set = set(fundamental_tickers)
    today = date.today()

    # Check what's already in the DB so we can skip up-to-date tickers.
    ticker_latest, spy_max = await _load_price_staleness()
    fund_latest = await _load_fund_staleness()

    price_skip = sum(
        1 for t in price_tickers
        if t not in benchmark_set and spy_max and ticker_latest.get(t) == spy_max
    )
    fund_skip  = sum(1 for t in fundamental_tickers if _should_skip_fundamentals(t, fund_latest, today))
    print(
        f"[fetch-data] starting: {len(price_tickers)} price tickers "
        f"({price_skip} already current, spy_max={spy_max}), "
        f"{len(fundamental_tickers)} fundamental tickers ({fund_skip} already current today)"
    )
    _fetch_data_progress.update({"run_id": run_id, "tickers_done": 0, "total_tickers": len(price_tickers)})
    await _checkpoint(run_id, "fetch-data", started_at,
                      tickers_done=0, total_tickers=len(price_tickers),
                      price_rows=0, fund_rows=0, error_count=0,
                      price_skipped=price_skip, fund_skipped=fund_skip)

    price_ok = price_rows_written = fund_ok = err_count = 0
    price_skipped = fund_skipped = 0
    error_tickers: list[str] = []
    # avg_dollar_volume_20d computed from the last 20 price rows for each ticker,
    # since AV OVERVIEW does not reliably provide this field.
    _ticker_avg_dv: dict[str, float] = {}
    # Guards a one-time reload of spy_max after all benchmark tickers have been
    # processed. If the system was offline for multiple days, the initial spy_max
    # is the stale cached DB date. Every universe ticker's DB date matches that
    # same stale date → all would be incorrectly skipped. Reloading after benchmarks
    # gives the true current trading date for universe-ticker skip evaluation.
    _spy_max_reloaded = False
    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(price_tickers):
            if not _TICKER_RE.match(ticker):
                print(f"[fetch-data] skipping invalid ticker: {ticker!r}")
                continue
            _fetch_data_progress["tickers_done"] = i + 1
            label = f"({i+1}/{len(price_tickers)})"

            is_benchmark = ticker in benchmark_set

            # Once we move past the leading benchmark tickers into the universe,
            # reload spy_max so it reflects the freshly written SPY date.
            if not _spy_max_reloaded and not is_benchmark:
                _spy_max_reloaded = True
                ticker_latest, spy_max = await _load_price_staleness()

            # Benchmarks are never skipped — they must be fetched to establish the
            # current trading date. Universe tickers skip only when already current.
            if not is_benchmark and spy_max and ticker_latest.get(ticker) == spy_max:
                price_ok += 1
                price_skipped += 1
                # avg_dv will be read from DB if this ticker needs a fundamentals update
            else:
                try:
                    # Use compact (last 100 days) if we already have a price history; full otherwise.
                    use_compact = ticker_latest.get(ticker) is not None
                    rows = await client.get_daily_prices(ticker, compact=use_compact)
                    if rows:
                        async with SessionLocal() as session:
                            async with session.begin():
                                await _upsert_prices(session, ticker, rows)
                        price_rows_written += len(rows)
                        price_ok += 1
                        last_20 = sorted(rows, key=lambda r: r["date"])[-20:]
                        dv_vals = [(r["adjusted_close"] or 0) * (r["volume"] or 0) for r in last_20]
                        if dv_vals:
                            _ticker_avg_dv[ticker] = sum(dv_vals) / len(dv_vals)
                        mode = "compact" if use_compact else "full"
                        print(f"[fetch-data] {ticker} prices: {len(rows)} rows [{mode}] {label}")
                    else:
                        print(f"[fetch-data] {ticker} prices: no data {label}")
                except Exception as e:
                    err_count += 1
                    error_tickers.append(f"{ticker}:prices")
                    print(f"[fetch-data] {ticker} prices: error - {e}")

            if ticker in fundamental_set:
                # Skip fundamentals if fetched within the last 7 days — AV OVERVIEW is quarterly data.
                if _should_skip_fundamentals(ticker, fund_latest, today):
                    fund_ok += 1
                    fund_skipped += 1
                else:
                    try:
                        overview = await client.get_overview(ticker)
                        if overview:
                            # If price was skipped (already current), look up avg_dv from DB.
                            if ticker not in _ticker_avg_dv:
                                async with engine.connect() as dv_conn:
                                    dv_row = await dv_conn.execute(
                                        text(
                                            "SELECT AVG(adjusted_close * volume) AS avg_dv FROM ("
                                            "  SELECT adjusted_close, volume FROM daily_prices "
                                            "  WHERE ticker=:t ORDER BY date DESC LIMIT 20"
                                            ") sub"
                                        ),
                                        {"t": ticker},
                                    )
                                    dv_val = dv_row.scalar()
                                    _ticker_avg_dv[ticker] = float(dv_val) if dv_val is not None else None
                            overview["avg_volume"] = _ticker_avg_dv.get(ticker)
                            async with SessionLocal() as session:
                                async with session.begin():
                                    await _upsert_fundamentals(session, ticker, overview, today)
                            fund_ok += 1
                            print(f"[fetch-data] {ticker} fundamentals: upserted {label}")
                        else:
                            # Record the attempt so we don't retry this ticker every run.
                            # Inserts a null sentinel row; ON CONFLICT updates fetched_at so
                            # _load_fund_staleness sees it and skips for 7 days.
                            async with SessionLocal() as session:
                                async with session.begin():
                                    await session.execute(
                                        text(
                                            "INSERT INTO fundamentals (ticker, as_of_date, source) "
                                            "VALUES (:ticker, :today, 'no_data') "
                                            "ON CONFLICT (ticker, as_of_date) DO UPDATE SET fetched_at=NOW()"
                                        ),
                                        {"ticker": ticker, "today": today},
                                    )
                            print(f"[fetch-data] {ticker} fundamentals: no data {label}")
                    except Exception as e:
                        err_count += 1
                        error_tickers.append(f"{ticker}:fundamentals")
                        print(f"[fetch-data] {ticker} fundamentals: error - {e}")

            if (i + 1) % CHECKPOINT_EVERY == 0:
                print(
                    f"[fetch-data] progress {i+1}/{len(price_tickers)}: "
                    f"fetched={price_ok - price_skipped} skipped={price_skipped} "
                    f"fund_skipped={fund_skipped} errors={err_count}"
                )
                await _checkpoint(run_id, "fetch-data", started_at,
                                  tickers_done=i + 1, total_tickers=len(price_tickers),
                                  price_rows=price_rows_written, fund_rows=fund_ok,
                                  price_skipped=price_skipped, fund_skipped=fund_skipped,
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
                                price_skipped=price_skipped, fund_skipped=fund_skipped,
                                error_count=err_count, error_tickers=error_tickers)
        if error_tickers:
            print(f"[fetch-data] {err_count} errors: {', '.join(error_tickers)}")
        print(f"[fetch-data] done — {price_skipped} price / {fund_skipped} fund tickers skipped (already current)")
    except Exception as exc:
        traceback.print_exc()
        err = str(exc)[:1000]
        print(f"[fetch-data] FATAL: {exc}")
        await _finish_run(run_id, "failed", error_message=err)
        await _write_trace_file(run_id, "fetch-data", "failed", started_at, error_message=err)
        raise
    finally:
        _fetch_data_progress.clear()
        await client.close()


async def _run_fetch_prices(run_id: str, tickers: list[str]) -> None:
    started_at = datetime.now(timezone.utc)
    await _start_run(run_id, "fetch-prices")
    # Benchmarks first so SPY is written early — same reasoning as _run_fetch_data.
    all_tickers = _build_benchmarks_first(tickers)

    ticker_latest, spy_max = await _load_price_staleness()
    skip_count = sum(1 for t in all_tickers if spy_max and ticker_latest.get(t) == spy_max)
    print(f"[fetch-prices] starting for {len(all_tickers)} tickers ({skip_count} already current, spy_max={spy_max})")
    await _checkpoint(run_id, "fetch-prices", started_at,
                      tickers_done=0, total_tickers=len(all_tickers),
                      price_rows=0, error_count=0, skipped=skip_count)

    rows_written = err_count = tickers_ok = skipped = 0
    error_tickers: list[str] = []
    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(all_tickers):
            if not _TICKER_RE.match(ticker):
                print(f"[fetch-prices] skipping invalid ticker: {ticker!r}")
                continue
            if spy_max and ticker_latest.get(ticker) == spy_max:
                print(f"[fetch-prices] {ticker}: already current ({spy_max}) ({i+1}/{len(all_tickers)})")
                tickers_ok += 1
                skipped += 1
                continue
            try:
                use_compact = ticker_latest.get(ticker) is not None
                rows = await client.get_daily_prices(ticker, compact=use_compact)
                if not rows:
                    print(f"[fetch-prices] {ticker}: no data returned")
                else:
                    async with SessionLocal() as session:
                        async with session.begin():
                            await _upsert_prices(session, ticker, rows)
                    rows_written += len(rows)
                    tickers_ok += 1
                    mode = "compact" if use_compact else "full"
                    print(f"[fetch-prices] {ticker}: {len(rows)} rows [{mode}] ({i+1}/{len(all_tickers)})")
            except Exception as e:
                err_count += 1
                error_tickers.append(ticker)
                print(f"[fetch-prices] {ticker}: error - {e}")
            if (i + 1) % CHECKPOINT_EVERY == 0:
                await _checkpoint(run_id, "fetch-prices", started_at,
                                  tickers_done=i + 1, total_tickers=len(all_tickers),
                                  price_rows=rows_written, skipped=skipped, error_count=err_count)
        status = "partial_success" if err_count > 0 else "success"
        pcp = _coverage(tickers_ok, len(all_tickers))
        await _finish_run(run_id, status,
                          ticker_count=len(all_tickers), price_rows=rows_written, error_count=err_count,
                          price_coverage_pct=pcp)
        await _write_trace_file(run_id, "fetch-prices", status, started_at,
                                tickers_done=len(all_tickers), total_tickers=len(all_tickers),
                                price_rows=rows_written, skipped=skipped, error_count=err_count,
                                error_tickers=error_tickers, price_coverage_pct=pcp)
        if error_tickers:
            print(f"[fetch-prices] {err_count} errors: {', '.join(error_tickers)}")
        print(f"[fetch-prices] done — {skipped} tickers skipped (already current)")
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
    today = date.today()

    fund_latest = await _load_fund_staleness()
    skip_count = sum(1 for t in investable if fund_latest.get(t) == today)
    print(f"[fetch-fundamentals] starting for {len(investable)} investable tickers ({skip_count} already current today)")
    await _checkpoint(run_id, "fetch-fundamentals", started_at,
                      tickers_done=0, total_tickers=len(investable),
                      fund_rows=0, error_count=0, skipped=skip_count)

    fund_ok = err_count = skipped = 0
    error_tickers: list[str] = []
    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(investable):
            if not _TICKER_RE.match(ticker):
                print(f"[fetch-fundamentals] skipping invalid ticker: {ticker!r}")
                continue
            if fund_latest.get(ticker) == today:
                print(f"[fetch-fundamentals] {ticker}: already current (today) ({i+1}/{len(investable)})")
                fund_ok += 1
                skipped += 1
                continue
            try:
                overview = await client.get_overview(ticker)
                if not overview:
                    async with SessionLocal() as session:
                        async with session.begin():
                            await session.execute(
                                text(
                                    "INSERT INTO fundamentals (ticker, as_of_date, source) "
                                    "VALUES (:ticker, :today, 'no_data') "
                                    "ON CONFLICT (ticker, as_of_date) DO UPDATE SET fetched_at=NOW()"
                                ),
                                {"ticker": ticker, "today": today},
                            )
                    print(f"[fetch-fundamentals] {ticker}: no data returned")
                else:
                    async with engine.connect() as conn:
                        dv_row = await conn.execute(
                            text(
                                "SELECT AVG(adjusted_close * volume) FROM ("
                                "  SELECT adjusted_close, volume FROM daily_prices "
                                "  WHERE ticker = :ticker ORDER BY date DESC LIMIT 20"
                                ") t"
                            ),
                            {"ticker": ticker},
                        )
                        dv_val = dv_row.scalar()
                    overview["avg_volume"] = float(dv_val) if dv_val is not None else None

                    async with SessionLocal() as session:
                        async with session.begin():
                            await _upsert_fundamentals(session, ticker, overview, today)
                    fund_ok += 1
                    print(f"[fetch-fundamentals] {ticker}: upserted ({i+1}/{len(investable)})")
            except Exception as e:
                err_count += 1
                error_tickers.append(ticker)
                print(f"[fetch-fundamentals] {ticker}: error - {e}")
            if (i + 1) % CHECKPOINT_EVERY == 0:
                await _checkpoint(run_id, "fetch-fundamentals", started_at,
                                  tickers_done=i + 1, total_tickers=len(investable),
                                  fund_rows=fund_ok, skipped=skipped, error_count=err_count)
        status = "partial_success" if err_count > 0 else "success"
        fcp = _coverage(fund_ok, len(investable))
        await _finish_run(run_id, status,
                          ticker_count=len(investable), fund_rows=fund_ok, error_count=err_count,
                          fundamental_coverage_pct=fcp)
        await _write_trace_file(run_id, "fetch-fundamentals", status, started_at,
                                tickers_done=len(investable), total_tickers=len(investable),
                                fund_rows=fund_ok, skipped=skipped, error_count=err_count,
                                error_tickers=error_tickers)
        if error_tickers:
            print(f"[fetch-fundamentals] {err_count} errors: {', '.join(error_tickers)}")
        print(f"[fetch-fundamentals] done — {skipped} tickers skipped (already current)")
    except Exception as exc:
        traceback.print_exc()
        err = str(exc)[:1000]
        print(f"[fetch-fundamentals] FATAL: {exc}")
        await _finish_run(run_id, "failed", error_message=err)
        await _write_trace_file(run_id, "fetch-fundamentals", "failed", started_at, error_message=err)
        raise
    finally:
        await client.close()
