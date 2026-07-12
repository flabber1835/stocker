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

engine = create_async_engine(BT_DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=5)

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

async def _run_backfill(date_from: str, date_to: str, tickers: Optional[str],
                        job_type: str = "backfill") -> None:
    # Prices (SEP)
    rid = await _open_run(job_type, "bt_prices")
    try:
        params = {"date.gte": date_from, "date.lte": date_to}
        if tickers:
            params["ticker"] = tickers
        batch, total, dmin, dmax = [], 0, None, None
        async for raw in fetch_table("SEP", params=params):
            m = map_sep_row(raw)
            if m["adjusted_close"] is None:
                continue
            batch.append(m)
            dmin = m["date"] if dmin is None or m["date"] < dmin else dmin
            dmax = m["date"] if dmax is None or m["date"] > dmax else dmax
            if len(batch) >= 5000:
                total += await _upsert_prices(batch); batch = []
        total += await _upsert_prices(batch)
        await _close_run(rid, "success", total, dmin, dmax)
    except Exception as exc:
        await _close_run(rid, "failed", err=str(exc))
        raise

    # Fundamentals (SF1, ARQ) — compute YoY growth across successive filings.
    rid = await _open_run(job_type, "bt_fundamentals")
    try:
        params = {"dimension": "ARQ", "datekey.gte": date_from, "datekey.lte": date_to}
        if tickers:
            params["ticker"] = tickers
        # collect per ticker to compute YoY growth (this quarter vs ~4 filings ago)
        per_ticker: dict[str, list[dict]] = {}
        async for raw in fetch_table("SF1", params=params):
            m = map_sf1_row(raw)
            if m is None:
                continue
            per_ticker.setdefault(m["ticker"], []).append(m)
        out, total = [], 0
        for t, rows in per_ticker.items():
            rows.sort(key=lambda r: r["as_of_date"])
            for i, r in enumerate(rows):
                prior = rows[i - 4] if i >= 4 else None  # ~year-ago quarter
                r["revenue_growth"] = compute_growth(
                    r.get("_revenue"), prior.get("_revenue") if prior else None)
                r["eps_growth"] = compute_growth(
                    r.get("_eps"), prior.get("_eps") if prior else None)
                out.append(r)
        total = await _upsert_fundamentals(out)
        await _close_run(rid, "success", total)
    except Exception as exc:
        await _close_run(rid, "failed", err=str(exc))
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
        await _close_run(rid, "failed", err=str(exc))
        raise


@app.post("/jobs/backfill")
async def start_backfill(background_tasks: BackgroundTasks,
                         date_from: str, date_to: str,
                         tickers: Optional[str] = None):
    """Kick off a one-time historical load. date_from/date_to are ISO dates;
    tickers is an optional comma-separated subset (default: full Sharadar universe)."""
    try:
        date.fromisoformat(date_from); date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(status_code=400, detail="date_from/date_to must be ISO YYYY-MM-DD")
    background_tasks.add_task(_run_backfill, date_from, date_to, tickers)
    return {"status": "started", "date_from": date_from, "date_to": date_to,
            "tickers": tickers or "ALL", "mock": is_mock()}


# Re-fetch this many days behind MAX(date) on topup: upserts make the overlap
# free, and it picks up Sharadar restatements/late-published rows near the edge.
TOPUP_OVERLAP_DAYS = int(os.getenv("TOPUP_OVERLAP_DAYS", "5"))


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
    date_from = (max_date - timedelta(days=TOPUP_OVERLAP_DAYS)).isoformat()
    # Trading-calendar date, not container-UTC (audit F5): after the ET close,
    # UTC is already tomorrow — harmless with upserts, but ET keeps run rows
    # and Sharadar date params speaking the same calendar.
    from zoneinfo import ZoneInfo
    date_to = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    background_tasks.add_task(_run_backfill, date_from, date_to, None, "topup")
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
