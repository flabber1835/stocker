"""
bt-data — the backtester's own data service. Fetches Sharadar SEP (prices),
SF1 (point-in-time fundamentals), and TICKERS (universe) into bt-postgres.

Runs ONLY on the separate backtest machine (docker-compose.backtest.yml). It has
no connection to the live trading stack — its own DB (BT_DATABASE_URL), its own
provider (Sharadar), no Alpaca, no Alpha Vantage.

Endpoints:
  GET  /health                 — liveness
  POST /jobs/backfill          — one-time historical load (prices+fundamentals+universe)
  POST /jobs/topup             — incremental load since the latest stored date
  GET  /data/coverage          — DATA-DEPTH REPORT (GO/NO-GO: earliest viable start)
  GET  /runs/latest            — last fetch job status
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.sharadar_client import fetch_table, is_mock
from app.sharadar_adapter import (
    map_sep_row, map_sf1_row, map_tickers_row, compute_growth,
)

BT_DATABASE_URL = os.environ.get("BT_DATABASE_URL", "")
if not BT_DATABASE_URL:
    raise RuntimeError("Missing required env var: BT_DATABASE_URL (backtester's own DB)")

# DB-side timeouts so a blocked/runaway query can NEVER hang the backfill
# forever (root cause of the "chunk running for 65+ min, no error, no progress"
# wedge): a Postgres lock-wait has no default timeout, so an INSERT…ON CONFLICT
# blocked behind a stray/idle-in-transaction session awaited indefinitely with
# nothing to raise or log. With these, a blocked upsert raises after
# LOCK_TIMEOUT_MS (→ chunk fails with a real repr error → the resumable retry
# self-heals) and any runaway statement dies after STATEMENT_TIMEOUT_MS. Both
# are generous vs. real work (a 5k-row batch upsert is sub-second; the biggest
# read is the coverage aggregate), so they only ever fire on a genuine stall.
# asyncpg applies them as per-connection server settings.
LOCK_TIMEOUT_MS = os.getenv("BT_DB_LOCK_TIMEOUT_MS", "60000")          # 60s
STATEMENT_TIMEOUT_MS = os.getenv("BT_DB_STATEMENT_TIMEOUT_MS", "600000")  # 10 min
IDLE_TX_TIMEOUT_MS = os.getenv("BT_DB_IDLE_TX_TIMEOUT_MS", "120000")   # 2 min

engine = create_async_engine(
    BT_DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=5,
    connect_args={"server_settings": {
        "lock_timeout": LOCK_TIMEOUT_MS,
        "statement_timeout": STATEMENT_TIMEOUT_MS,
        # also reap a connection this service itself leaves idle-in-transaction
        # (the classic lock holder that wedges the OTHER writer)
        "idle_in_transaction_session_timeout": IDLE_TX_TIMEOUT_MS,
    }})

_INIT_SQL = Path(__file__).resolve().parent.parent / "sql" / "init_bt.sql"


async def _ensure_schema() -> None:
    """Idempotently create the bt_* tables (so the service is self-sufficient even
    if no migrator ran on the backtest box)."""
    sql = _INIT_SQL.read_text()
    async with engine.begin() as conn:
        for stmt in [s.strip() for s in sql.split(";\n") if s.strip()]:
            await conn.execute(text(stmt))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Retry briefly so a cold bt-postgres can finish starting.
    import asyncio
    for attempt in range(30):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            break
        except Exception:
            await asyncio.sleep(2)
    try:
        await _ensure_schema()
        print("[bt-data] schema ensured", flush=True)
    except Exception as exc:
        print(f"[bt-data] WARN schema ensure failed: {exc}", flush=True)
    yield


app = FastAPI(title="bt-data", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "bt-data", "mock": is_mock()}


# ── Fetch-run bookkeeping ──────────────────────────────────────────────────────

async def _open_run(job_type: str, table_name: str) -> str:
    rid = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO bt_data_runs (run_id, job_type, table_name, status) "
            "VALUES (:r, :j, :t, 'running')"
        ), {"r": rid, "j": job_type, "t": table_name})
    return rid


def _d(v):
    """Coerce an ISO date string (or date) to datetime.date for asyncpg DATE
    binding. asyncpg rejects str for DATE columns — it needs a real date object."""
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


async def _close_run(rid: str, status: str, rows: int = 0,
                     dmin: Optional[str] = None, dmax: Optional[str] = None,
                     err: Optional[str] = None) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE bt_data_runs SET status=:s, rows_written=:n, date_min=:dmin, "
            "date_max=:dmax, completed_at=:now, error_message=:e WHERE run_id=:r"
        ), {"s": status, "n": rows, "dmin": _d(dmin), "dmax": _d(dmax),
            "now": datetime.now(timezone.utc), "e": (err or "")[:2000] or None, "r": rid})


# ── Writers (upserts) ──────────────────────────────────────────────────────────

async def _upsert_prices(rows: list[dict]) -> int:
    if not rows:
        return 0
    for r in rows:
        r["date"] = _d(r["date"])
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO bt_prices (ticker, date, open, high, low, close, adjusted_close, volume) "
            "VALUES (:ticker, :date, :open, :high, :low, :close, :adjusted_close, :volume) "
            "ON CONFLICT (ticker, date) DO UPDATE SET "
            "  adjusted_close=EXCLUDED.adjusted_close, close=EXCLUDED.close, volume=EXCLUDED.volume"
        ), rows)
    return len(rows)


async def _upsert_fundamentals(rows: list[dict]) -> int:
    if not rows:
        return 0
    # strip the helper underscore fields before insert + coerce the date key
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    for r in clean:
        r["as_of_date"] = _d(r["as_of_date"])
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO bt_fundamentals (ticker, as_of_date, fiscal_period, pe_ratio, "
            "  pb_ratio, roe, debt_to_equity, revenue_growth, eps_growth) "
            "VALUES (:ticker, :as_of_date, :fiscal_period, :pe_ratio, :pb_ratio, :roe, "
            "  :debt_to_equity, :revenue_growth, :eps_growth) "
            "ON CONFLICT (ticker, as_of_date) DO UPDATE SET "
            "  pe_ratio=EXCLUDED.pe_ratio, pb_ratio=EXCLUDED.pb_ratio, roe=EXCLUDED.roe, "
            "  debt_to_equity=EXCLUDED.debt_to_equity, revenue_growth=EXCLUDED.revenue_growth, "
            "  eps_growth=EXCLUDED.eps_growth"
        ), clean)
    return len(clean)


async def _upsert_universe(rows: list[dict]) -> int:
    if not rows:
        return 0
    for r in rows:
        r["snapshot_date"] = _d(r["snapshot_date"])
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO bt_universe (snapshot_date, ticker, name, sector) "
            "VALUES (:snapshot_date, :ticker, :name, :sector) "
            "ON CONFLICT (snapshot_date, ticker) DO UPDATE SET "
            "  name=EXCLUDED.name, sector=EXCLUDED.sector"
        ), rows)
    return len(rows)


# ── Backfill ───────────────────────────────────────────────────────────────────

def year_chunks(date_from: str, date_to: str) -> list[tuple[str, str]]:
    """Pure: split [date_from, date_to] into calendar-year slices (inclusive).
    The SEP price fetch is ~3000 cursor pages over hours; chunking makes each
    slice a separately-committed, separately-resumable unit so a failure loses
    ONE chunk, not the whole night."""
    f, t = date.fromisoformat(date_from), date.fromisoformat(date_to)
    out = []
    y = f.year
    while y <= t.year:
        cf = max(f, date(y, 1, 1))
        ct = min(t, date(y, 12, 31))
        out.append((cf.isoformat(), ct.isoformat()))
        y += 1
    return out


# Completed-chunk markers live in bt_data_runs as job_type='backfill_chunk'
# success rows whose error_message carries 'CHUNK:<from>..<to>:<tickers|ALL>'
# (zero schema change; error_message is unused on success rows). A re-POSTed
# backfill skips chunks already marked complete — resume instead of
# restart-from-zero. A skip additionally requires the DATA to actually be
# present in the chunk's range, so a TRUNCATE (clean restart) self-invalidates
# stale markers instead of skipping everything into an empty table.
_CHUNK_PREFIX = "CHUNK:"


async def _completed_chunks(table: str) -> set:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT error_message FROM bt_data_runs "
            "WHERE job_type='backfill_chunk' AND table_name=:t "
            "AND status='success' AND error_message LIKE :pfx"),
            {"t": table, "pfx": _CHUNK_PREFIX + "%"})).fetchall()
    return {r[0] for r in rows}


async def _chunk_has_data(cf: str, ct: str) -> bool:
    async with engine.connect() as conn:
        return bool((await conn.execute(text(
            "SELECT EXISTS(SELECT 1 FROM bt_prices WHERE date BETWEEN :f AND :t)"),
            {"f": _d(cf), "t": _d(ct)})).scalar())


# Watchdog ceiling per year-chunk (~28 min typical). A hang trips this →
# TimeoutError → chunk fails → resume. Never fires on legitimate work.
CHUNK_TIMEOUT_SECS = float(os.getenv("BT_CHUNK_TIMEOUT_SECS", "2700"))  # 45 min


async def _load_price_chunk(cf: str, ct: str, tickers: Optional[str]):
    """Fetch+upsert one year of SEP prices. Returns (rows, dmin, dmax).
    Pulled out so the caller can wrap it in asyncio.wait_for (the watchdog)."""
    params = {"date.gte": cf, "date.lte": ct}
    if tickers:
        params["ticker"] = tickers
    batch, ctotal, cdmin, cdmax = [], 0, None, None
    async for raw in fetch_table("SEP", params=params):
        m = map_sep_row(raw)
        if m["adjusted_close"] is None:
            continue
        batch.append(m)
        cdmin = m["date"] if cdmin is None or m["date"] < cdmin else cdmin
        cdmax = m["date"] if cdmax is None or m["date"] > cdmax else cdmax
        if len(batch) >= 5000:
            ctotal += await _upsert_prices(batch); batch = []
    ctotal += await _upsert_prices(batch)
    return ctotal, cdmin, cdmax


# Benchmark ETFs (SPY etc.) are NOT in Sharadar SEP — that table is individual
# EQUITIES only. Funds/ETFs live in the SFP (Sharadar Fund Prices) table. The
# backtester needs SPY for regime detection + benchmark, so it is fetched
# separately from SFP into the same bt_prices table (identical column shape, so
# map_sep_row applies unchanged). Without this the full equity load still leaves
# spy.rows=0 and coverage go=false.
BENCHMARK_TICKERS = os.getenv("BT_BENCHMARK_TICKERS", "SPY,QQQ,IWM,SOXX")


async def _load_benchmarks(date_from: str, date_to: str) -> int:
    """Fetch benchmark ETFs from SFP → bt_prices. Fail-soft: a benchmark-fetch
    problem (e.g. SFP not in the subscription) must NOT discard the equity load;
    it's recorded as a failed bt_benchmarks run and re-tried by re-POST."""
    rid = await _open_run("backfill", "bt_benchmarks")
    try:
        params = {"date.gte": date_from, "date.lte": date_to,
                  "ticker": BENCHMARK_TICKERS}
        batch, total = [], 0
        async for raw in fetch_table("SFP", params=params):
            m = map_sep_row(raw)          # SFP shares SEP's price column shape
            if m["adjusted_close"] is None:
                continue
            batch.append(m)
            if len(batch) >= 5000:
                total += await _upsert_prices(batch); batch = []
        total += await _upsert_prices(batch)
        await _close_run(rid, "success", total, err=f"BENCHMARKS:{BENCHMARK_TICKERS}")
        print(f"[bt-data] benchmarks {BENCHMARK_TICKERS} DONE ({total} rows)", flush=True)
        return total
    except Exception as exc:
        await _close_run(rid, "failed", err=repr(exc)[:1500])
        print(f"[bt-data] benchmark fetch FAILED (equity data intact): {exc}",
              flush=True)
        return 0


async def _run_backfill(date_from: str, date_to: str, tickers: Optional[str],
                        job_type: str = "backfill") -> None:
    # Prices (SEP) — chunked by calendar year, resumable. Each chunk commits
    # and marks itself complete; a re-run after ANY failure skips completed
    # chunks instead of re-downloading 20 years from scratch.
    rid = await _open_run(job_type, "bt_prices")
    try:
        chunks = year_chunks(date_from, date_to)
        done = await _completed_chunks("bt_prices") if job_type == "backfill" else set()
        total, dmin, dmax = 0, None, None
        for cf, ct in chunks:
            marker = f"{_CHUNK_PREFIX}{cf}..{ct}:{tickers or 'ALL'}"
            if marker in done and await _chunk_has_data(cf, ct):
                print(f"[bt-data] prices chunk {cf}..{ct} already complete — skipped",
                      flush=True)
                continue
            crid = await _open_run("backfill_chunk", "bt_prices")
            try:
                # Per-chunk watchdog: a normal year is ~28 min, so this ceiling
                # never trips on real work but GUARANTEES no chunk can hang the
                # backfill forever, whatever the cause (DB lock, stuck read,
                # anything). asyncio.wait_for cancels the coroutine on timeout →
                # the chunk fails with a real error → the resume picks it up.
                ctotal, cdmin, cdmax = await asyncio.wait_for(
                    _load_price_chunk(cf, ct, tickers), timeout=CHUNK_TIMEOUT_SECS)
                await _close_run(crid, "success", ctotal, cdmin, cdmax, err=marker)
                done.add(marker)
                print(f"[bt-data] prices chunk {cf}..{ct} DONE ({ctotal} rows)",
                      flush=True)
            except Exception as exc:
                await _close_run(crid, "failed", err=repr(exc)[:1500])
                raise
            total += ctotal
            dmin = cdmin if dmin is None or (cdmin and cdmin < dmin) else dmin
            dmax = cdmax if dmax is None or (cdmax and cdmax > dmax) else dmax
        await _close_run(rid, "success", total, dmin, dmax)
    except Exception as exc:
        # repr, not str: several exception types (ReadTimeout, MemoryError)
        # stringify to '' — the "failed with no error message" mystery rows.
        await _close_run(rid, "failed", err=repr(exc)[:1500])
        raise

    # Benchmark ETFs (SPY etc.) from SFP — the SEP load above is equities-only.
    await _load_benchmarks(date_from, date_to)

    # Fundamentals (SF1, ARQ) — compute YoY growth across successive filings.
    rid = await _open_run(job_type, "bt_fundamentals")
    try:
        params = {"dimension": "ARQ", "datekey.gte": date_from, "datekey.lte": date_to}
        if tickers:
            params["ticker"] = tickers
        # Group by ticker to compute YoY growth (this quarter vs ~4 filings ago),
        # but upsert PER TICKER and free each block as we go — never hold two
        # full-universe copies in memory at once (the whole-universe SF1 buffer
        # was an OOM risk after prices finished on a RAM-tight NAS).
        per_ticker: dict[str, list[dict]] = {}
        async for raw in fetch_table("SF1", params=params):
            m = map_sf1_row(raw)
            if m is None:
                continue
            per_ticker.setdefault(m["ticker"], []).append(m)
        total = 0
        for t in list(per_ticker.keys()):
            rows = per_ticker.pop(t)          # free this ticker's block after use
            rows.sort(key=lambda r: r["as_of_date"])
            for i, r in enumerate(rows):
                prior = rows[i - 4] if i >= 4 else None  # ~year-ago quarter
                r["revenue_growth"] = compute_growth(
                    r.get("_revenue"), prior.get("_revenue") if prior else None)
                r["eps_growth"] = compute_growth(
                    r.get("_eps"), prior.get("_eps") if prior else None)
            total += await _upsert_fundamentals(rows)
        await _close_run(rid, "success", total)
    except Exception as exc:
        await _close_run(rid, "failed", err=repr(exc)[:1500])
        raise

    # Universe snapshot (TICKERS, as-of date_to). One snapshot for the backfill end;
    # the engine treats it as the listed set (delisted names still in bt_prices).
    rid = await _open_run(job_type, "bt_universe")
    try:
        rows, total = [], 0
        async for raw in fetch_table("TICKERS"):
            m = map_tickers_row(raw, date_to)
            if m:
                rows.append(m)
        total = await _upsert_universe(rows)
        await _close_run(rid, "success", total)
    except Exception as exc:
        await _close_run(rid, "failed", err=repr(exc)[:1500])
        raise


# In-process guard: a backfill/topup is a long single-writer job. Without this,
# a repeated POST spawns ANOTHER background task, and N of them then starve the
# 8-connection pool and lock each other row-by-row on bt_prices upserts — the
# "five running tasks, zero progress" pileup. The flag lives in the process, so
# a container restart (which kills all tasks) correctly clears it; stale
# 'running' rows in bt_data_runs (orphaned by a restart) do NOT falsely block a
# fresh job. Check-then-set is atomic under asyncio (no await between them).
_job_active = False


@app.post("/jobs/backfill")
async def start_backfill(background_tasks: BackgroundTasks,
                         date_from: str, date_to: str,
                         tickers: Optional[str] = None):
    """Kick off a one-time historical load. date_from/date_to are ISO dates;
    tickers is an optional comma-separated subset (default: full Sharadar universe).

    Refuses (returns already_running) if a backfill/topup is already in flight —
    re-POSTing does NOT spawn a competing task."""
    global _job_active
    try:
        date.fromisoformat(date_from); date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(status_code=400, detail="date_from/date_to must be ISO YYYY-MM-DD")
    if _job_active:
        return {"status": "already_running",
                "detail": "a backfill/topup is already in progress — not spawning another"}
    _job_active = True

    async def _guarded():
        global _job_active
        try:
            await _run_backfill(date_from, date_to, tickers)
        finally:
            _job_active = False

    background_tasks.add_task(_guarded)
    return {"status": "started", "date_from": date_from, "date_to": date_to,
            "tickers": tickers or "ALL", "mock": is_mock()}


# Re-fetch this many days behind MAX(date) on topup: upserts make the overlap
# free, and it picks up Sharadar restatements/late-published rows near the edge.
TOPUP_OVERLAP_DAYS = int(os.getenv("TOPUP_OVERLAP_DAYS", "5"))


@app.post("/jobs/fetch-benchmarks")
async def start_fetch_benchmarks(background_tasks: BackgroundTasks,
                                 date_from: str = "2004-01-01",
                                 date_to: Optional[str] = None):
    """Load ONLY the benchmark ETFs (SPY etc.) from SFP into bt_prices — the
    fast fix for 'equities loaded but spy.rows=0 / go=false', without re-running
    the full backfill. Idempotent (upserts)."""
    global _job_active
    if _job_active:
        return {"status": "already_running",
                "detail": "a backfill/topup is already in progress"}
    from zoneinfo import ZoneInfo
    dt = date_to or datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    _job_active = True

    async def _guarded():
        global _job_active
        try:
            await _load_benchmarks(date_from, dt)
        finally:
            _job_active = False

    background_tasks.add_task(_guarded)
    return {"status": "started", "job": "fetch-benchmarks",
            "tickers": BENCHMARK_TICKERS, "date_from": date_from, "date_to": dt,
            "mock": is_mock()}


@app.post("/jobs/topup")
async def start_topup(background_tasks: BackgroundTasks):
    """Incremental load: resume from the latest stored price date (minus a small
    restatement overlap) through today. Refused (409) while the DB is empty —
    topup extends a backfill, it cannot substitute for one; run /jobs/backfill
    first. bt-scheduler fires this nightly."""
    async with engine.connect() as conn:
        max_date = (await conn.execute(text("SELECT MAX(date) FROM bt_prices"))).scalar()
    if max_date is None:
        raise HTTPException(status_code=409,
                            detail="bt_prices is empty — run /jobs/backfill first")
    global _job_active
    if _job_active:
        return {"status": "already_running",
                "detail": "a backfill/topup is already in progress — not spawning another"}
    date_from = (max_date - timedelta(days=TOPUP_OVERLAP_DAYS)).isoformat()
    # Trading-calendar date, not container-UTC (audit F5): after the ET close,
    # UTC is already tomorrow — harmless with upserts, but ET keeps run rows
    # and Sharadar date params speaking the same calendar.
    from zoneinfo import ZoneInfo
    date_to = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    _job_active = True

    async def _guarded():
        global _job_active
        try:
            await _run_backfill(date_from, date_to, None, "topup")
        finally:
            _job_active = False

    background_tasks.add_task(_guarded)
    return {"status": "started", "job_type": "topup", "date_from": date_from,
            "date_to": date_to, "mock": is_mock()}


# ── Data-depth report (GO/NO-GO gate) ──────────────────────────────────────────

@app.get("/data/coverage")
async def coverage():
    """Report how deep the stored data goes — the GO/NO-GO gate for choosing a
    backtest start date. A backtest start needs ~1yr of prior price history for
    momentum/low-vol/covariance, plus fundamentals coverage for value/quality/growth.
    """
    async with engine.connect() as conn:
        px = (await conn.execute(text(
            "SELECT COUNT(*) n, COUNT(DISTINCT ticker) tickers, "
            "       MIN(date) dmin, MAX(date) dmax FROM bt_prices"
        ))).mappings().first()
        fn = (await conn.execute(text(
            "SELECT COUNT(*) n, COUNT(DISTINCT ticker) tickers, "
            "       MIN(as_of_date) dmin, MAX(as_of_date) dmax FROM bt_fundamentals"
        ))).mappings().first()
        spy = (await conn.execute(text(
            "SELECT MIN(date) dmin, MAX(date) dmax, COUNT(*) n "
            "FROM bt_prices WHERE ticker='SPY'"
        ))).mappings().first()

    px_min = px["dmin"]
    earliest_start = None
    if px_min is not None:
        # need ~400 calendar days of lookback before the first tradeable day
        from datetime import timedelta as _td
        earliest_start = (px_min + _td(days=400)).isoformat()

    return {
        "prices": {"rows": px["n"], "tickers": px["tickers"],
                   "date_min": str(px["dmin"]) if px["dmin"] else None,
                   "date_max": str(px["dmax"]) if px["dmax"] else None},
        "fundamentals": {"rows": fn["n"], "tickers": fn["tickers"],
                         "date_min": str(fn["dmin"]) if fn["dmin"] else None,
                         "date_max": str(fn["dmax"]) if fn["dmax"] else None},
        "spy": {"rows": spy["n"],
                "date_min": str(spy["dmin"]) if spy["dmin"] else None,
                "date_max": str(spy["dmax"]) if spy["dmax"] else None},
        "earliest_viable_start": earliest_start,
        "go": bool(px["n"] and spy["n"] and earliest_start),
        "notes": "earliest_viable_start = first price date + ~400d lookback; "
                 "SPY required for regime + benchmark.",
    }


@app.get("/runs/latest")
async def runs_latest():
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT run_id, job_type, table_name, status, rows_written, date_min, "
            "date_max, started_at, completed_at, error_message "
            "FROM bt_data_runs ORDER BY started_at DESC LIMIT 10"
        ))).mappings().fetchall()
    return {"runs": [dict(r) for r in rows]}
