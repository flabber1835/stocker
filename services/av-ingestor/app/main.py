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
import redis.asyncio as aioredis
from fastapi import BackgroundTasks, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .alpha_vantage import AVClient
from .universe import download_av_universe, get_benchmark_tickers, save_universe_snapshot
from stock_strategy_shared.db import wait_for_db
from stock_strategy_shared.tracing import RESTART_ABORT_MARKER, mark_orphaned_runs_failed
from stock_strategy_shared.corporate_actions import apply_corporate_actions

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")

REDIS_URL = os.getenv("REDIS_URL", "")

AV_API_KEY = os.getenv("AV_API_KEY", "demo")
if AV_API_KEY in ("", "demo"):
    print("[av-ingestor] WARNING: AV_API_KEY is 'demo' — using Alpha Vantage demo key, data will be very limited")
AV_RATE_LIMIT_RPM = int(os.getenv("AV_RATE_LIMIT_RPM", "75"))
MOCK_DATA = os.getenv("MOCK_DATA", "false").lower() == "true"
# When true, the fundamentals path also fetches AV BALANCE_SHEET for total_assets
# (the gross-profitability denominator). This ~doubles AV calls on the
# fundamentals refresh; turn off to save rate-limit budget if the gross-profit
# quality factor is not in use. Best-effort: a balance-sheet miss is non-fatal.
FETCH_BALANCE_SHEET = os.getenv("FETCH_BALANCE_SHEET", "true").lower() == "true"
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

CHECKPOINT_EVERY = 100

# Stale-running reclaim. A fetch job runs as a detached BackgroundTask; if the
# scheduler abandons the chain (or the task dies without the process restarting),
# its ingest_runs row can linger at status='running' forever, and _reserve_run's
# no-running-job check would then 409 every future fetch — wedging the chain until an av-ingestor
# restart runs mark_orphaned_runs_failed. A full fetch never exceeds ~3h, so a
# 'running' row older than this is presumed dead: we mark it failed (with the
# RESTART_ABORT_MARKER so the scheduler treats it as recoverable and re-triggers)
# and let the new job proceed. Set to 0 to disable.
STALE_INGEST_HOURS = float(os.getenv("STALE_INGEST_HOURS", "6"))

# Universe staleness filter — see migration 0007 and ticker_fetch_state.
# fetch-universe drops every ticker whose `MAX(date) IN daily_prices < spy_max`
# (i.e. AV had no row for today last time we asked), then re-probes a small
# rotating slice each run so halt-then-resume tickers eventually rejoin.
# PROBATION_ROTATION_DAYS — number of days the dropped pool is spread across.
# At default 30, each fetch-universe re-tries ~1/30th of stale tickers, so
# every excluded ticker gets one AV call ~once a month.
PROBATION_ROTATION_DAYS = int(os.getenv("PROBATION_ROTATION_DAYS", "30"))

# Stable 64-bit advisory-lock key for the ingest check-and-claim. Used with
# pg_advisory_xact_lock (transaction-scoped, auto-released at commit/rollback) so
# that if av-ingestor ever runs >1 worker/replica, two processes cannot both pass
# the no-running-job check and INSERT a 'running' row simultaneously — the
# cross-process complement to the in-process _job_lock. A single constant key is
# correct because _reserve_run already serializes ALL ingest job types through one
# "is any job running?" check (it never partitions by job_type), so every claim
# must contend on the same lock. Arbitrary fixed value; just needs to be stable
# and not collide with other advisory-lock users in the same DB.
INGEST_RESERVE_LOCK_KEY = 8472013465120011  # within int8 range

_TICKER_RE = re.compile(r"^[A-Z]{1,5}([.\-][A-Z0-9]{1,4})?$")

# In-memory progress for the currently running fetch-data job.
# Polled by /runs/latest so the dashboard can show real progress.
_fetch_data_progress: dict = {}  # {run_id, tickers_done, total_tickers}

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=5,
                             connect_args={"timeout": 60})
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


def _filter_stale_max_date(
    tickers: list,
    ticker_latest: dict,
    spy_max,
) -> tuple[list, list[str]]:
    """Drop tickers whose latest price date is behind `spy_max`.

    Returns (kept, dropped_tickers). `kept` preserves the input row shape
    (dict or str). Cold-start safety: if `spy_max` is None (no SPY data
    yet) or `ticker_latest` is empty, no filtering happens — every ticker
    is kept so the first ingestion can populate `daily_prices`.

    Why drop on this signal: it is the same empirical condition the per-
    ticker skip check uses (`ticker_latest[t] == spy_max`). If `MAX(date)`
    for a ticker is strictly less than SPY's `MAX(date)`, AV had no row
    for today the last time we asked. Keeping such tickers in the universe
    burns API throttle on every warm run for no new data. Re-probing
    happens via the rotation cohort (see _pick_probation_cohort).
    """
    if spy_max is None or not ticker_latest:
        return list(tickers), []
    kept: list = []
    dropped: list[str] = []
    for row in tickers:
        t = row.get("ticker") if isinstance(row, dict) else row
        if not t:
            kept.append(row)
            continue
        latest = ticker_latest.get(t)
        if latest is not None and latest < spy_max:
            dropped.append(t)
        else:
            kept.append(row)
    return kept, dropped


def _pick_probation_cohort(
    dropped_tickers: list[str],
    fetch_state: dict,
    today: date,
    rotation_days: int,
) -> list[str]:
    """Return the slice of dropped tickers to re-probe in this run.

    Picks `ceil(len(dropped) / rotation_days)` tickers, prioritising those
    whose `last_consulted_date` is oldest (or absent — never consulted).
    With `rotation_days=30` and 3000 stale names, ~100 are probed per
    fetch-universe run, so every stuck ticker gets one AV consultation
    roughly once a month. A halted-then-resumed ticker rejoins the
    universe on the run after AV first returns fresh data for it.
    """
    if not dropped_tickers or rotation_days <= 0:
        return []
    cohort_size = -(-len(dropped_tickers) // rotation_days)  # ceil div
    EPOCH = date(1900, 1, 1)

    def _last_consulted(t: str):
        state = fetch_state.get(t)
        if not state:
            return EPOCH
        return state.get("last_consulted_date") or EPOCH

    # Sort by (oldest-consulted-first, then ticker for determinism).
    ordered = sorted(dropped_tickers, key=lambda t: (_last_consulted(t), t))
    return ordered[:cohort_size]


def _build_benchmarks_first(universe_tickers: list[str]) -> list[str]:
    """Return the ordered ticker list with benchmarks first, then universe (deduped).

    Benchmarks are always moved to the front regardless of whether they appear in the
    universe list. This ensures SPY is fetched first so spy_max lands in the DB before
    any universe-ticker skip evaluation.
    """
    benchmark_set = set(BENCHMARK_TICKERS)
    without_benchmarks = [t for t in universe_tickers if t not in benchmark_set]
    return list(BENCHMARK_TICKERS) + without_benchmarks


def _coverage(ok: int, total: int) -> Optional[float]:
    return ok / total if total else None


async def _upsert_prices(session, ticker: str, rows: list[dict]) -> None:
    """Upsert daily price rows for a single ticker.

    raw_adjusted_close is set to AV's adjusted close (the immutable split/div-adjusted
    source); adjusted_close is initialised to the same value and later re-derived
    spinoff-adjusted by apply_spinoff_adjustments() for tickers in corporate_actions.
    """
    await session.execute(
        text(
            "INSERT INTO daily_prices "
            "    (ticker, date, open, high, low, close, adjusted_close, raw_adjusted_close, volume) "
            "VALUES "
            "    (:ticker, :date, :open, :high, :low, :close, :adjusted_close, :adjusted_close, :volume) "
            "ON CONFLICT (ticker, date) DO UPDATE SET "
            "    open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, "
            "    close=EXCLUDED.close, adjusted_close=EXCLUDED.adjusted_close, "
            "    raw_adjusted_close=EXCLUDED.raw_adjusted_close, "
            "    volume=EXCLUDED.volume, fetched_at=NOW()"
        ),
        [{"ticker": ticker, "date": date.fromisoformat(r["date"]),
          "open": r["open"], "high": r["high"], "low": r["low"],
          "close": r["close"],
          "adjusted_close": r["adjusted_close"] if r.get("adjusted_close") and 0 < r["adjusted_close"] < 1_000_000 else None,
          "volume": r["volume"]} for r in rows],
    )


async def apply_spinoff_adjustments(session, ticker: str | None = None) -> int:
    """Re-derive adjusted_close = raw_adjusted_close × Π(spinoff gap factors) for every
    ticker in corporate_actions (or just ``ticker`` if given). Idempotent: always
    recomputed from the immutable raw_adjusted_close + the curated ex-dates, so it is
    safe to run on every fetch and on startup. Returns the number of rows updated.
    """
    q = "SELECT ticker, ex_date FROM corporate_actions"
    params: dict = {}
    if ticker is not None:
        q += " WHERE ticker = :t"
        params["t"] = ticker
    rows = (await session.execute(text(q), params)).fetchall()
    if not rows:
        return 0
    ex_by_ticker: dict[str, list] = {}
    for r in rows:
        ex_by_ticker.setdefault(r.ticker, []).append(r.ex_date)

    total = 0
    for tk, ex_dates in ex_by_ticker.items():
        price_rows = (await session.execute(
            text("SELECT date, raw_adjusted_close FROM daily_prices "
                 "WHERE ticker = :t AND raw_adjusted_close IS NOT NULL ORDER BY date"),
            {"t": tk},
        )).fetchall()
        raw = {r.date: float(r.raw_adjusted_close) for r in price_rows}
        if not raw:
            continue
        adj = apply_corporate_actions(raw, list(ex_dates))
        # Only write rows whose adjusted value actually changes from raw (the pre-ex
        # window); post-ex rows already equal raw from _upsert_prices.
        updates = [
            {"t": tk, "d": d, "a": round(v, 4)}
            for d, v in adj.items()
            if v is not None and abs(v - raw[d]) > 1e-9
        ]
        if updates:
            await session.execute(
                text("UPDATE daily_prices SET adjusted_close = :a "
                     "WHERE ticker = :t AND date = :d"),
                updates,
            )
            total += len(updates)
    if total:
        print(f"[av-ingestor] spinoff adjustment: rewrote {total} adjusted_close row(s) "
              f"for {len(ex_by_ticker)} ticker(s)", flush=True)
    return total



async def _enrich_total_assets(client, ticker: str, overview: dict) -> None:
    """Best-effort: add total_assets (the gross-profitability denominator) from AV
    BALANCE_SHEET into the overview dict. Gated by FETCH_BALANCE_SHEET and fully
    non-fatal — a miss leaves total_assets unset (→ NULL), and the quality factor
    falls back to ROE for that ticker rather than breaking."""
    if not FETCH_BALANCE_SHEET:
        return
    try:
        bs = await client.get_balance_sheet(ticker)
        if bs and bs.get("total_assets") is not None:
            overview["total_assets"] = bs["total_assets"]
        # Shares now vs ~1y ago → net-issuance factor (optional; None stays NULL).
        if bs and bs.get("shares_outstanding") is not None:
            overview["shares_outstanding"] = bs["shares_outstanding"]
        if bs and bs.get("shares_outstanding_prior") is not None:
            overview["shares_outstanding_prior"] = bs["shares_outstanding_prior"]
    except Exception as e:  # noqa: BLE001 — balance sheet is optional enrichment
        print(f"[fundamentals] {ticker}: balance-sheet fetch failed (non-fatal) - {e}")


async def _upsert_fundamentals(session, ticker: str, overview: dict, today: date) -> None:
    """Upsert fundamental data for a single ticker. Pops 'sector' from overview dict.

    Tolerates overview dicts without the gross_profit/total_assets keys (e.g. a
    caller that didn't fetch the balance sheet) by defaulting them to NULL.
    """
    sector = overview.pop("sector", None)
    params = {
        "ticker": ticker,
        "as_of_date": today,
        "gross_profit": None,
        "total_assets": None,
        "shares_outstanding": None,
        "shares_outstanding_prior": None,
        **overview,
    }
    await session.execute(
        text(
            "INSERT INTO fundamentals "
            "    (ticker, as_of_date, source, pe_ratio, pb_ratio, roe, debt_to_equity, "
            "     revenue_growth, eps_growth, market_cap, avg_volume, gross_profit, total_assets, "
            "     shares_outstanding, shares_outstanding_prior) "
            "VALUES "
            "    (:ticker, :as_of_date, 'alpha_vantage', :pe_ratio, :pb_ratio, :roe, :debt_to_equity, "
            "     :revenue_growth, :eps_growth, :market_cap, :avg_volume, :gross_profit, :total_assets, "
            "     :shares_outstanding, :shares_outstanding_prior) "
            "ON CONFLICT (ticker, as_of_date) DO UPDATE SET "
            "    source='alpha_vantage', "
            "    pe_ratio=EXCLUDED.pe_ratio, pb_ratio=EXCLUDED.pb_ratio, "
            "    roe=EXCLUDED.roe, debt_to_equity=EXCLUDED.debt_to_equity, "
            "    revenue_growth=EXCLUDED.revenue_growth, eps_growth=EXCLUDED.eps_growth, "
            "    market_cap=EXCLUDED.market_cap, avg_volume=EXCLUDED.avg_volume, "
            "    gross_profit=EXCLUDED.gross_profit, total_assets=EXCLUDED.total_assets, "
            "    shares_outstanding=EXCLUDED.shares_outstanding, "
            "    shares_outstanding_prior=EXCLUDED.shares_outstanding_prior, "
            "    fetched_at=NOW()"
        ),
        params,
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
    # Synchronous: block until orphan cleanup done. DB is up in restart scenario,
    # so this completes quickly and prevents re-triggers from racing the cleanup.
    try:
        await wait_for_db(engine)
        async with engine.begin() as conn:
            await mark_orphaned_runs_failed(conn, "ingest_runs", trace_job_type="fetch-data")
        print("[av-ingestor] DB connected; orphan cleanup done", flush=True)
        # Re-derive spinoff-adjusted prices on startup so a deploy fixes existing data
        # (e.g. FDX) immediately, without waiting for the next fetch. Idempotent + cheap
        # (only corporate_actions tickers); never fatal.
        try:
            async with engine.begin() as conn:
                await apply_spinoff_adjustments(conn)
        except Exception as exc:  # noqa: BLE001
            print(f"[av-ingestor] WARN: spinoff adjustment skipped on startup: {exc}", flush=True)
    except Exception as exc:
        # Table may not exist yet on first boot while init.sql is still running.
        print(f"[av-ingestor] WARN: orphan cleanup skipped: {exc}", flush=True)

    yield
    await engine.dispose()


app = FastAPI(title="av-ingestor", lifespan=lifespan)

# Serialises concurrent job-start requests so the TOCTOU check-then-insert is atomic.
# In-process FAST PATH: a single-process service (Docker) is fully covered by this.
# The cross-process complement is INGEST_RESERVE_LOCK_KEY (pg_advisory_xact_lock
# taken inside _reserve_run's transaction) for the >1-worker/replica case.
_job_lock = asyncio.Lock()


# ── Run lifecycle helpers ────────────────────────────────

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
    session_date: Optional[date] = None,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ingest_runs SET status=:status, completed_at=:now, "
                "ticker_count=:tc, price_rows=:pr, fund_rows=:fr, "
                "error_count=:ec, error_message=:err, "
                "price_coverage_pct=:pcp, fundamental_coverage_pct=:fcp, "
                "session_date=:sd "
                "WHERE run_id=:rid"
            ),
            {
                "status": status, "now": datetime.now(timezone.utc),
                "tc": ticker_count, "pr": price_rows, "fr": fund_rows,
                "ec": error_count, "err": error_message,
                "pcp": round(price_coverage_pct, 4) if price_coverage_pct is not None else None,
                "fcp": round(fundamental_coverage_pct, 4) if fundamental_coverage_pct is not None else None,
                "sd": session_date,
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


# ── Redis Streams publishing ─────────────────────────────────────────────────

PIPELINE_STREAM = "stocker:pipeline_events"


async def _publish_fetch_complete(run_date: str, run_id: str) -> None:
    """Publish a fetch_data.complete event to the pipeline Redis stream.

    Non-blocking: failures are logged and swallowed so they never affect
    the ingest run's own success/failure status.
    """
    if not REDIS_URL:
        print("[av-ingestor] REDIS_URL not set — skipping pipeline event publish")
        return
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            await r.xadd(
                PIPELINE_STREAM,
                {
                    "event": "fetch_data.complete",
                    "run_date": run_date,
                    "run_id": run_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
            print(f"[av-ingestor] published fetch_data.complete to {PIPELINE_STREAM} (run_date={run_date})")
        finally:
            await r.aclose()
    except Exception as exc:
        print(f"[av-ingestor] WARNING: failed to publish pipeline event: {exc}")


# ── Endpoints ──────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "av-ingestor"}


def _is_stale_running(started_at: Optional[datetime], now: datetime,
                      stale_hours: float = STALE_INGEST_HOURS) -> bool:
    """Pure predicate: is a 'running' ingest row old enough to presume dead?

    A live fetch finishes well under a few hours, so a 'running' row older than
    `stale_hours` is an abandoned/crashed task. Returns False when reclaim is
    disabled (stale_hours <= 0) or the timestamp is missing.
    """
    if stale_hours <= 0 or started_at is None:
        return False
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    age_h = (now - started_at).total_seconds() / 3600.0
    return age_h > stale_hours


async def _reserve_run(job_type: str) -> str:
    """Atomically gate-and-claim a run slot, returning the new run_id.

    Bug C1 fix (duplicate-fetch race): the no-running-job check and the INSERT of
    the 'running' ingest_runs row MUST happen in the same locked critical section
    (one DB transaction). Previously the check ran here under _job_lock but the
    'running' row was INSERTed later by _start_run inside the background task,
    AFTER the lock was released and the HTTP response returned — so two requests
    arriving close together both saw no running row and both launched a full
    fetch (two concurrent jobs hammering Alpha Vantage, double-writing prices,
    "fetch starts at 0 again"). Inserting the row here, before the lock is
    released, makes a second concurrent caller see the running row and get a 409.

    Caller MUST hold _job_lock. Raises HTTPException(409) if a live job is
    running; reclaims a presumed-dead stale orphan (STALE_INGEST_HOURS) the same
    way the old _assert_no_running_job did, then claims a fresh slot.

    The returned run_id is for an already-INSERTed 'running' row — the background
    task must NOT call _start_run again.
    """
    async with engine.begin() as conn:
        # Cross-process guard (multi-worker/replica hazard): the in-process
        # _job_lock only serializes claims WITHIN one process. A transaction-scoped
        # advisory lock makes the check-and-claim atomic across processes too — a
        # second process blocks here until the first commits/rolls back (the lock
        # auto-releases at txn end, so there is nothing to release manually and no
        # leak risk). A single process behaves exactly as before: it takes the lock
        # uncontended and proceeds. pg_advisory_xact_lock returns void.
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": INGEST_RESERVE_LOCK_KEY},
        )
        row = await conn.execute(
            text(
                "SELECT run_id, started_at FROM ingest_runs "
                "WHERE status='running' ORDER BY started_at DESC LIMIT 1"
            )
        )
        existing = row.mappings().first()
        if existing is not None:
            # Reclaim a presumed-dead orphan: a 'running' row older than
            # STALE_INGEST_HOURS can never be a live job (a full fetch finishes
            # well under that), so it is an abandoned/crashed task whose process
            # never restarted. Mark it failed with the restart-abort marker so the
            # scheduler re-triggers it, and let the new job proceed instead of
            # 409-wedging.
            if _is_stale_running(existing["started_at"], datetime.now(timezone.utc)):
                await conn.execute(
                    text(
                        "UPDATE ingest_runs SET status='failed', completed_at=NOW(), "
                        "error_message=:msg WHERE run_id=:rid"
                    ),
                    {
                        "msg": f"{RESTART_ABORT_MARKER} reclaimed stale running job "
                               f"(> {STALE_INGEST_HOURS}h old)",
                        "rid": existing["run_id"],
                    },
                )
                print(
                    f"[av-ingestor] reclaimed stale running ingest run {existing['run_id']}",
                    flush=True,
                )
            else:
                raise HTTPException(
                    status_code=409,
                    detail="Another ingest job is already running. Wait for it to complete.",
                )
        # Insert the 'running' row in the SAME transaction (and the SAME locked
        # critical section) as the check above, so a second concurrent caller sees
        # it and is rejected with 409. The background task no longer calls
        # _start_run — this row already exists.
        run_id = str(uuid.uuid4())
        await conn.execute(
            text(
                "INSERT INTO ingest_runs (run_id, job_type, status, started_at) "
                "VALUES (:run_id, :job_type, 'running', :now)"
            ),
            {"run_id": run_id, "job_type": job_type, "now": datetime.now(timezone.utc)},
        )
    return run_id


@app.post("/jobs/fetch-universe")
async def fetch_universe(background_tasks: BackgroundTasks):
    async with _job_lock:
        run_id = await _reserve_run("fetch-universe")
        background_tasks.add_task(_run_fetch_universe, run_id)
    return {"status": "started", "job": "fetch-universe", "run_id": run_id}


@app.post("/jobs/fetch-data")
async def fetch_data(background_tasks: BackgroundTasks):
    async with _job_lock:
        tickers, snapshot_id = await _get_universe_tickers()
        run_id = await _reserve_run("fetch-data")
        background_tasks.add_task(_run_fetch_data, run_id, tickers)
    return {"status": "started", "job": "fetch-data", "run_id": run_id, "ticker_count": len(tickers), "snapshot_id": snapshot_id}


@app.post("/jobs/fetch-prices")
async def fetch_prices(background_tasks: BackgroundTasks):
    async with _job_lock:
        tickers, snapshot_id = await _get_universe_tickers()
        run_id = await _reserve_run("fetch-prices")
        background_tasks.add_task(_run_fetch_prices, run_id, tickers)
    return {"status": "started", "job": "fetch-prices", "run_id": run_id, "ticker_count": len(tickers), "snapshot_id": snapshot_id}


@app.post("/jobs/fetch-fundamentals")
async def fetch_fundamentals(background_tasks: BackgroundTasks):
    async with _job_lock:
        tickers, snapshot_id = await _get_universe_tickers()
        run_id = await _reserve_run("fetch-fundamentals")
        background_tasks.add_task(_run_fetch_fundamentals, run_id, tickers)
    return {"status": "started", "job": "fetch-fundamentals", "run_id": run_id, "snapshot_id": snapshot_id}


@app.get("/runs/latest")
async def get_latest_run():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, job_type, status, ticker_count, price_rows, fund_rows, "
                "       error_count, error_message, session_date, started_at, completed_at "
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
        "error_message": result["error_message"],
        # The trading session this fetch advanced to (MAX SPY date). The scheduler
        # compares this against the target session to decide if fetch-data is done.
        "session_date": result["session_date"].isoformat() if result["session_date"] else None,
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
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="run_id must be a valid UUID")
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
    # The 'running' ingest_runs row was already INSERTed atomically by
    # _reserve_run under _job_lock (Bug C1 fix) — do not re-insert here.
    await _checkpoint(run_id, "fetch-universe", started_at, step="download")
    print("[fetch-universe] starting")
    try:
        async with httpx.AsyncClient() as http:
            tickers, listing_stats = await download_av_universe(http, av_api_key=AV_API_KEY)
        # Drop tickers whose latest price date in daily_prices is behind
        # spy_max — AV had no row for today the last time we asked. They
        # are re-admitted via the probation cohort below: a 1/N slice
        # (default 1/30) of dropped tickers is injected into the new
        # snapshot so a halted-then-resumed ticker rejoins after one
        # successful fetch.
        ticker_latest, spy_max = await _load_price_staleness()
        fetch_state = await _load_ticker_fetch_state()
        today = datetime.now(timezone.utc).date()
        tickers, dropped_stale = _filter_stale_max_date(
            tickers, ticker_latest, spy_max,
        )
        probation = _pick_probation_cohort(
            dropped_stale, fetch_state, today, PROBATION_ROTATION_DAYS,
        )
        if probation:
            # Re-admit by ticker. The probation cohort is just tickers; the
            # downstream save_universe_snapshot only needs the ticker symbol.
            probation_set = set(probation)
            tickers = tickers + [{"ticker": t} for t in probation]
            print(
                f"[fetch-universe] probation cohort: re-admitting "
                f"{len(probation)}/{len(dropped_stale)} stale tickers for re-probe "
                f"(rotation_days={PROBATION_ROTATION_DAYS})"
            )
        benchmarks = await get_benchmark_tickers()
        all_tickers = tickers + benchmarks
        print(
            f"[fetch-universe] downloaded {len(tickers)} universe + {len(benchmarks)} benchmarks "
            f"(filtered: {listing_stats.get('filtered_warrant_unit', 0)} warrants/units, "
            f"{listing_stats.get('filtered_non_stock', 0)} non-stock, "
            f"{listing_stats.get('filtered_exchange', 0)} wrong-exchange, "
            f"{len(dropped_stale)} stale max_date<spy_max, "
            f"{len(probation)} re-admitted for probation)"
        )
        if dropped_stale:
            never_returning = [t for t in dropped_stale if t not in (set(probation) if probation else set())]
            sample = ",".join(never_returning[:10])
            more = f" (+{len(never_returning) - 10} more)" if len(never_returning) > 10 else ""
            print(f"[fetch-universe] stale-skipped sample: {sample}{more}")
        await _checkpoint(run_id, "fetch-universe", started_at,
                          step="save", ticker_count=len(all_tickers))

        async with SessionLocal() as session:
            async with session.begin():
                snapshot_id = await save_universe_snapshot(session, "AV_LISTING", all_tickers)
        print(f"[fetch-universe] saved snapshot_id={snapshot_id} with {len(all_tickers)} tickers")
        await _finish_run(run_id, "success", ticker_count=len(all_tickers))
        # BUG 10: strip large row arrays (10k+ rows each) before writing to trace to
        # avoid bloating the artifact with multi-MB JSON files.
        trace_stats = {k: v for k, v in listing_stats.items() if k not in ("raw_listing", "filtered_rows", "accepted_tickers")}
        trace_stats["filtered_stale_max_date"] = len(dropped_stale)
        trace_stats["probation_readmitted"] = len(probation)
        await _write_trace_file(run_id, "fetch-universe", "success", started_at,
                                ticker_count=len(all_tickers), snapshot_id=snapshot_id,
                                listing_stats=trace_stats)
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
    """Return ticker→most_recent_fetched_at (UTC date) for fundamentals."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT ticker, (MAX(fetched_at) AT TIME ZONE 'UTC')::date AS last_fetched "
                "FROM fundamentals GROUP BY ticker"
            )
        )
        return {r.ticker: r.last_fetched for r in rows.fetchall()}


async def _load_ticker_fetch_state() -> dict[str, dict]:
    """Return ticker→{last_consulted_date}."""
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            "SELECT ticker, last_consulted_date FROM ticker_fetch_state"
        ))
        return {
            r.ticker: {"last_consulted_date": r.last_consulted_date}
            for r in rows.fetchall()
        }


async def _mark_consulted(ticker: str, today: date) -> None:
    """Record that AV was asked about this ticker today.

    Used by the probation-rotation logic in fetch-universe to pick
    "oldest-consulted-first" candidates for re-probing.
    """
    async with SessionLocal() as session:
        async with session.begin():
            await session.execute(text(
                "INSERT INTO ticker_fetch_state (ticker, last_consulted_date) "
                "VALUES (:t, :d) "
                "ON CONFLICT (ticker) DO UPDATE SET "
                "  last_consulted_date=EXCLUDED.last_consulted_date, "
                "  updated_at=NOW()"
            ), {"t": ticker, "d": today})


async def _load_investable_tickers() -> frozenset[str] | None:
    """Return tickers scored in the latest successful factor run, or None on cold start.

    None → no factor run exists yet; fetch fundamentals for everything.
    A frozenset → skip fundamentals for tickers absent from factor_scores if they
    were checked within 30 days (vs the normal 7-day window for investable tickers).
    Tickers only appear in factor_scores if they passed price/liquidity filters, so
    this correctly identifies the ~3,000 investable names out of ~6,600 in the universe.
    """
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT DISTINCT fs.ticker "
                "FROM factor_scores fs "
                "JOIN factor_runs fr ON fr.run_id = fs.run_id "
                "WHERE fr.status = 'success' "
                "  AND fr.completed_at = ("
                "    SELECT MAX(completed_at) FROM factor_runs WHERE status = 'success'"
                "  )"
            )
        )
        tickers = frozenset(r[0] for r in rows.fetchall())
    return tickers if tickers else None


async def _run_fetch_data(run_id: str, tickers: list[str]) -> None:
    started_at = datetime.now(timezone.utc)
    # The 'running' ingest_runs row was already INSERTed atomically by
    # _reserve_run under _job_lock (Bug C1 fix) — do not re-insert here.
    benchmark_set = set(BENCHMARK_TICKERS)
    # Fetch benchmark tickers (SPY etc.) FIRST so spy_max lands in the DB early.
    # If benchmarks are last and the run is interrupted, spy_max=None on the next
    # run and every ticker gets re-fetched from scratch.
    price_tickers = _build_benchmarks_first(tickers)
    fundamental_tickers = [t for t in tickers if t not in benchmark_set]
    fundamental_set = set(fundamental_tickers)
    today = datetime.now(timezone.utc).date()

    # Check what's already in the DB so we can skip up-to-date tickers.
    ticker_latest, spy_max = await _load_price_staleness()
    fund_latest = await _load_fund_staleness()
    investable_tickers = await _load_investable_tickers()

    price_skip = sum(
        1 for t in price_tickers
        if t not in benchmark_set and spy_max and ticker_latest.get(t) == spy_max
    )
    fund_skip = sum(
        1 for t in fundamental_tickers
        if _should_skip_fundamentals(
            t, fund_latest, today,
            max_age_days=7 if (investable_tickers is None or t in investable_tickers) else 30,
        )
    )
    if investable_tickers is not None:
        non_inv = sum(1 for t in fundamental_tickers if t not in investable_tickers)
        print(
            f"[fetch-data] starting: {len(price_tickers)} price tickers "
            f"({price_skip} already current, spy_max={spy_max}), "
            f"{len(fundamental_tickers)} fundamental tickers ({fund_skip} already current, "
            f"{non_inv} non-investable on 30d window)"
        )
    else:
        print(
            f"[fetch-data] starting: {len(price_tickers)} price tickers "
            f"({price_skip} already current, spy_max={spy_max}), "
            f"{len(fundamental_tickers)} fundamental tickers ({fund_skip} already current today) "
            f"[cold start — fetching all]"
        )
    _fetch_data_progress.update({"run_id": run_id, "tickers_done": 0, "total_tickers": len(price_tickers)})
    await _checkpoint(run_id, "fetch-data", started_at,
                      tickers_done=0, total_tickers=len(price_tickers),
                      price_rows=0, fund_rows=0, error_count=0,
                      price_skipped=price_skip, fund_skipped=fund_skip)

    price_ok = price_rows_written = fund_ok = err_count = 0
    price_skipped = fund_skipped = 0
    error_tickers: list[str] = []
    price_error_tickers: list[str] = []  # subset that failed price fetch — retried once after the main loop
    # avg_dollar_volume_20d computed from the last 20 price rows for each ticker,
    # since AV OVERVIEW does not reliably provide this field.
    _ticker_avg_dv: dict[str, float] = {}
    # Guards a one-time reload of spy_max after all benchmark tickers have been
    # processed. If the system was offline for multiple days, the initial spy_max
    # is the stale cached DB date. Every universe ticker's DB date matches that
    # same stale date → all would be incorrectly skipped. Reloading after benchmarks
    # gives the true current trading date for universe-ticker skip evaluation.
    _spy_max_reloaded = False
    _spy_fetch_failed = False  # BUG 8: if SPY fails, invalidate spy_max after reload
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
                if _spy_fetch_failed:
                    # SPY couldn't be written — old spy_max is stale. Clear it so
                    # no universe ticker is incorrectly skipped.
                    print("[fetch-data] WARNING: SPY fetch failed; disabling skip optimisation for this run")
                    spy_max = None

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
                        # Filter to only rows newer than what's already in the DB.
                        # Compact fetches 100 days but we typically only need the last 1-2;
                        # upserting all 100 would rewrite identical rows unnecessarily.
                        latest_in_db = ticker_latest.get(ticker)
                        new_rows = (
                            [r for r in rows if date.fromisoformat(r["date"]) > latest_in_db]
                            if latest_in_db else rows
                        )
                        if new_rows:
                            async with SessionLocal() as session:
                                async with session.begin():
                                    await _upsert_prices(session, ticker, new_rows)
                            price_rows_written += len(new_rows)
                        price_ok += 1
                        last_20 = sorted(rows, key=lambda r: r["date"])[-20:]
                        # BUG 5: skip rows with NULL close to avoid diluting avg_dv with zeros
                        dv_vals = [
                            r["close"] * (r["volume"] or 0)
                            for r in last_20
                            if r.get("close")
                        ]
                        if dv_vals:
                            _ticker_avg_dv[ticker] = sum(dv_vals) / len(dv_vals)
                        mode = "compact" if use_compact else "full"
                        print(f"[fetch-data] {ticker} prices: {len(new_rows)}/{len(rows)} new rows [{mode}] {label}")
                    else:
                        print(f"[fetch-data] {ticker} prices: no data {label}")
                    # Record the consultation regardless of whether AV returned
                    # data — used by fetch-universe to pick oldest-consulted
                    # tickers for probation re-probing.
                    if not is_benchmark:
                        try:
                            await _mark_consulted(ticker, today)
                        except Exception as fs_exc:
                            print(f"[fetch-data] {ticker} fetch_state update failed: {fs_exc}")
                except Exception as e:
                    err_count += 1
                    error_tickers.append(f"{ticker}:prices")
                    if not is_benchmark:
                        price_error_tickers.append(ticker)
                    if is_benchmark and ticker == "SPY":
                        _spy_fetch_failed = True
                    print(f"[fetch-data] {ticker} prices: error - {e}")
                    if not is_benchmark:
                        try:
                            await _mark_consulted(ticker, today)
                        except Exception as fs_exc:
                            print(f"[fetch-data] {ticker} fetch_state update failed: {fs_exc}")

            if ticker in fundamental_set:
                # Investable tickers: 7-day window (AV OVERVIEW is quarterly, weekly is plenty).
                # Non-investable tickers (failed price/liquidity in last factor run): 30-day window.
                # Cold start (investable_tickers is None): always use 7-day window.
                fund_max_age = 7 if (investable_tickers is None or ticker in investable_tickers) else 30
                if _should_skip_fundamentals(ticker, fund_latest, today, max_age_days=fund_max_age):
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
                            await _enrich_total_assets(client, ticker, overview)
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

        # ── Fetch cleanup: retry transient price-fetch failures ONCE ──────────
        # Most price errors are transient (AV rate-limit "Note", a dropped TLS
        # connection) and clear on a second attempt — real names like VRSN/RHI/IAC
        # shouldn't sit in the error list for a flake. A persistent failure
        # (delisted/odd ticker) errors again and stays counted. Bounded to the
        # handful that failed, and the client throttles internally.
        if price_error_tickers:
            retry_list = list(price_error_tickers)
            print(f"[fetch-data] cleanup: retrying {len(retry_list)} price errors once")
            recovered: list[str] = []
            for rt in retry_list:
                try:
                    rows = await client.get_daily_prices(rt, compact=(ticker_latest.get(rt) is not None))
                    if not rows:
                        continue
                    latest_in_db = ticker_latest.get(rt)
                    new_rows = (
                        [r for r in rows if date.fromisoformat(r["date"]) > latest_in_db]
                        if latest_in_db else rows
                    )
                    if new_rows:
                        async with SessionLocal() as session:
                            async with session.begin():
                                await _upsert_prices(session, rt, new_rows)
                        price_rows_written += len(new_rows)
                    price_ok += 1
                    recovered.append(rt)
                    print(f"[fetch-data] cleanup: {rt} recovered ({len(new_rows)} rows)")
                except Exception as e:  # noqa: BLE001 — persistent failure stays counted
                    print(f"[fetch-data] cleanup: {rt} still failing - {e}")
            if recovered:
                err_count -= len(recovered)
                recovered_labels = {f"{rt}:prices" for rt in recovered}
                error_tickers = [e for e in error_tickers if e not in recovered_labels]
                print(f"[fetch-data] cleanup: recovered {len(recovered)}/{len(retry_list)} price errors")

        # Re-derive spinoff-adjusted prices for corporate_actions tickers now that this
        # run's new bars are written (idempotent; only the curated ticker set).
        try:
            async with engine.begin() as conn:
                await apply_spinoff_adjustments(conn)
        except Exception as exc:  # noqa: BLE001
            print(f"[fetch-data] WARN: spinoff adjustment skipped: {exc}", flush=True)

        status = "partial_success" if err_count > 0 else "success"
        pcp = _coverage(price_ok, len(price_tickers))
        fcp = _coverage(fund_ok, len(fundamental_tickers))
        # session_date = the trading session this run advanced prices to (MAX SPY
        # date, reloaded after benchmarks above). The scheduler keys the daily
        # chain on this session, so it must be the DATA date, not wall-clock today.
        # None when SPY could not be written (skip optimisation disabled) — the
        # scheduler then treats fetch-data as not-yet-advanced and waits.
        await _finish_run(run_id, status,
                          ticker_count=len(price_tickers), price_rows=price_rows_written,
                          fund_rows=fund_ok, error_count=err_count,
                          price_coverage_pct=pcp, fundamental_coverage_pct=fcp,
                          session_date=spy_max)
        await _write_trace_file(run_id, "fetch-data", status, started_at,
                                tickers_done=len(price_tickers), total_tickers=len(price_tickers),
                                price_rows=price_rows_written, fund_rows=fund_ok,
                                price_skipped=price_skipped, fund_skipped=fund_skipped,
                                error_count=err_count, error_tickers=error_tickers)
        if error_tickers:
            print(f"[fetch-data] {err_count} errors: {', '.join(error_tickers)}")
        print(f"[fetch-data] done — {price_skipped} price / {fund_skipped} fund tickers skipped (already current)")
        # Publish pipeline event so the pipeline service can auto-start factor/rank/delta.
        # Published for both "success" and "partial_success" — either is actionable.
        asyncio.create_task(_publish_fetch_complete(str(today), run_id))
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
    # The 'running' ingest_runs row was already INSERTed atomically by
    # _reserve_run under _job_lock (Bug C1 fix) — do not re-insert here.
    # Benchmarks first so SPY is written early — same reasoning as _run_fetch_data.
    all_tickers = _build_benchmarks_first(tickers)

    ticker_latest, spy_max = await _load_price_staleness()
    benchmark_set = set(BENCHMARK_TICKERS)
    skip_count = sum(
        1 for t in all_tickers
        if t not in benchmark_set and spy_max and ticker_latest.get(t) == spy_max
    )
    print(f"[fetch-prices] starting for {len(all_tickers)} tickers ({skip_count} already current, spy_max={spy_max})")
    await _checkpoint(run_id, "fetch-prices", started_at,
                      tickers_done=0, total_tickers=len(all_tickers),
                      price_rows=0, error_count=0, skipped=skip_count)

    rows_written = err_count = tickers_ok = skipped = 0
    error_tickers: list[str] = []
    _spy_max_reloaded = False
    _spy_fetch_failed = False  # BUG 8: if SPY fails, invalidate spy_max after reload
    client = AVClient(api_key=AV_API_KEY, rate_limit_rpm=AV_RATE_LIMIT_RPM, mock_mode=MOCK_DATA)
    try:
        for i, ticker in enumerate(all_tickers):
            if not _TICKER_RE.match(ticker):
                print(f"[fetch-prices] skipping invalid ticker: {ticker!r}")
                continue
            is_benchmark = ticker in benchmark_set
            # Reload spy_max once we leave the benchmark block, same as _run_fetch_data.
            if not _spy_max_reloaded and not is_benchmark:
                _spy_max_reloaded = True
                ticker_latest, spy_max = await _load_price_staleness()
                if _spy_fetch_failed:
                    print("[fetch-prices] WARNING: SPY fetch failed; disabling skip optimisation for this run")
                    spy_max = None
            # Benchmarks are never skipped; universe tickers skip only when already current.
            if not is_benchmark and spy_max and ticker_latest.get(ticker) == spy_max:
                tickers_ok += 1
                skipped += 1
                continue
            try:
                use_compact = ticker_latest.get(ticker) is not None
                rows = await client.get_daily_prices(ticker, compact=use_compact)
                if not rows:
                    print(f"[fetch-prices] {ticker}: no data returned")
                else:
                    latest_in_db = ticker_latest.get(ticker)
                    new_rows = (
                        [r for r in rows if date.fromisoformat(r["date"]) > latest_in_db]
                        if latest_in_db else rows
                    )
                    if new_rows:
                        async with SessionLocal() as session:
                            async with session.begin():
                                await _upsert_prices(session, ticker, new_rows)
                    rows_written += len(new_rows)
                    tickers_ok += 1
                    mode = "compact" if use_compact else "full"
                    print(f"[fetch-prices] {ticker}: {len(new_rows)}/{len(rows)} new rows [{mode}] ({i+1}/{len(all_tickers)})")
            except Exception as e:
                err_count += 1
                error_tickers.append(ticker)
                if is_benchmark and ticker == "SPY":
                    _spy_fetch_failed = True
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
    # The 'running' ingest_runs row was already INSERTed atomically by
    # _reserve_run under _job_lock (Bug C1 fix) — do not re-insert here.
    investable = [t for t in tickers if t not in set(BENCHMARK_TICKERS)]
    today = datetime.now(timezone.utc).date()

    fund_latest = await _load_fund_staleness()
    investable_tickers = await _load_investable_tickers()
    skip_count = sum(
        1 for t in investable
        if _should_skip_fundamentals(
            t, fund_latest, today,
            max_age_days=7 if (investable_tickers is None or t in investable_tickers) else 30,
        )
    )
    if investable_tickers is not None:
        non_inv = sum(1 for t in investable if t not in investable_tickers)
        print(
            f"[fetch-fundamentals] starting for {len(investable)} tickers "
            f"({skip_count} already current, {non_inv} non-investable on 30d window)"
        )
    else:
        print(f"[fetch-fundamentals] starting for {len(investable)} investable tickers ({skip_count} already current)")
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
            fund_max_age = 7 if (investable_tickers is None or ticker in investable_tickers) else 30
            if _should_skip_fundamentals(ticker, fund_latest, today, max_age_days=fund_max_age):
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
                    await _enrich_total_assets(client, ticker, overview)

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
