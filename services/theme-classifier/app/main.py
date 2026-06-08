"""theme-classifier — standalone thematic-universe service (AI-infra).

Fully decoupled from the trading pipeline: reads daily_prices/fundamentals
READ-ONLY, writes ONLY the theme_exposures table, and is referenced by nothing in
ranking / portfolio-builder / delta / risk / trade-executor. The dashboard's
read-only Theme tab consumes GET /exposures.

Cadence: recomputes monthly (REFRESH_DAYS) via a background task, plus on startup
if the latest snapshot is stale. POST /jobs/run forces an immediate recompute.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from stock_strategy_shared.db import wait_for_db  # noqa: F401

from app.compute import AI_INFRA, run_and_store

DATABASE_URL = os.getenv("DATABASE_URL", "")
REFRESH_DAYS = int(os.getenv("THEME_REFRESH_DAYS", "30"))
DEFAULT_MIN_EXPOSURE = float(os.getenv("THEME_MIN_EXPOSURE", "0.35"))

# Only AI-infra for now; the table + endpoints are theme-keyed so more can be added.
THEMES = {AI_INFRA.theme: AI_INFRA}

engine = None  # set in lifespan
_job_lock = asyncio.Lock()
_last_error: str | None = None


async def _latest_meta(theme: str) -> dict | None:
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT max(as_of_date) AS as_of, max(computed_at) AS computed_at, count(*) AS n "
            "FROM theme_exposures WHERE theme = :t"
        ), {"t": theme})).mappings().first()
    if not row or row["as_of"] is None:
        return None
    return {"as_of_date": str(row["as_of"]),
            "computed_at": row["computed_at"].isoformat() if row["computed_at"] else None,
            "scored": int(row["n"])}


async def _run_theme(theme: str) -> dict | None:
    """Compute + store one theme. Stores any error in _last_error; never raises (so
    background tasks don't leave 'never retrieved' exceptions). Returns summary or None."""
    global _last_error
    cfg = THEMES[theme]
    async with _job_lock:
        try:
            summary = await run_and_store(engine, cfg)
            _last_error = None
            print(f"[theme-classifier] computed '{theme}': {summary}", flush=True)
            return summary
        except Exception as exc:  # noqa: BLE001
            _last_error = f"{type(exc).__name__}: {exc}"
            print(f"[theme-classifier] compute FAILED for '{theme}': {_last_error}", flush=True)
            return None


async def _refresher():
    """Run on startup if stale, then check daily and recompute every REFRESH_DAYS."""
    await asyncio.sleep(5)
    while True:
        try:
            for theme in THEMES:
                meta = await _latest_meta(theme)
                stale = meta is None
                if meta and meta["computed_at"]:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(meta["computed_at"])
                    stale = age.days >= REFRESH_DAYS
                if stale:
                    print(f"[theme-classifier] computing '{theme}' (stale={stale})", flush=True)
                    await _run_theme(theme)
        except Exception as exc:  # noqa: BLE001
            print(f"[theme-classifier] refresh error: {exc}", flush=True)
        await asyncio.sleep(24 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    await wait_for_db(engine)
    task = asyncio.create_task(_refresher())
    yield
    task.cancel()
    await engine.dispose()


app = FastAPI(title="theme-classifier", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "theme-classifier"}


@app.get("/exposures")
async def exposures(theme: str = "ai_infra", min: float = DEFAULT_MIN_EXPOSURE):
    """Latest snapshot members with exposure >= min, ranked desc. Read-only."""
    if theme not in THEMES:
        raise HTTPException(404, f"unknown theme: {theme}")
    meta = await _latest_meta(theme)
    if meta is None:
        return {"theme": theme, "as_of_date": None, "computed_at": None,
                "min_exposure": min, "count": 0, "members": []}
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT ticker, exposure, in_seed, avg_dollar_vol FROM theme_exposures "
            "WHERE theme = :t AND as_of_date = :d AND exposure >= :m "
            "ORDER BY exposure DESC"
        ), {"t": theme, "d": meta["as_of_date"], "m": min})).mappings().all()
    members = [{"rank": i + 1, "ticker": r["ticker"], "exposure": float(r["exposure"]),
                "in_seed": bool(r["in_seed"]),
                "avg_dollar_vol_m": round(float(r["avg_dollar_vol"]) / 1e6, 1)
                if r["avg_dollar_vol"] is not None else None}
               for i, r in enumerate(rows)]
    return {"theme": theme, "as_of_date": meta["as_of_date"],
            "computed_at": meta["computed_at"], "min_exposure": min,
            "count": len(members), "members": members}


@app.get("/runs/latest")
async def runs_latest(theme: str = "ai_infra"):
    meta = await _latest_meta(theme) or {}
    return {"theme": theme, "last_error": _last_error, **meta}


@app.post("/jobs/run")
async def jobs_run(theme: str = "ai_infra"):
    """Non-blocking: kick the compute as a background task and return immediately so
    the HTTP call doesn't hold open for the ~minute of work. Poll /exposures or
    /runs/latest for completion."""
    if theme not in THEMES:
        raise HTTPException(404, f"unknown theme: {theme}")
    if _job_lock.locked():
        return {"status": "already_running", "theme": theme}
    asyncio.create_task(_run_theme(theme))
    return {"status": "started", "theme": theme}
