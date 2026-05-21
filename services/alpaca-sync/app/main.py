import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stock_strategy_shared.db import wait_for_db

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

_has_credentials = bool(ALPACA_API_KEY) and ALPACA_API_KEY != "demo"

# ---------------------------------------------------------------------------
# Database (engine + SessionLocal are created lazily in lifespan)
# ---------------------------------------------------------------------------

engine = None  # type: ignore
SessionLocal = None  # type: ignore

# ---------------------------------------------------------------------------
# Concurrency guard
# ---------------------------------------------------------------------------

_job_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _f(v) -> Optional[float]:
    """Convert Decimal/None to float/None."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _iso(v) -> Optional[str]:
    """Convert datetime to ISO string or None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _parse_float(v) -> Optional[float]:
    """Safely convert Alpaca string numeric values to float."""
    if v is None:
        return None
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------


async def _do_sync() -> str:
    """Run a full Alpaca sync. Returns the run_id (str UUID)."""
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    async with SessionLocal() as db:
        # 1. Insert sync run row with status='running'
        await db.execute(
            text(
                """
                INSERT INTO alpaca_sync_runs (run_id, status, started_at)
                VALUES (:run_id, 'running', :started_at)
                """
            ),
            {"run_id": run_id, "started_at": started_at},
        )
        await db.commit()

    try:
        headers = {
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 2. Fetch account
            acct_resp = await client.get(f"{ALPACA_BASE_URL}/v2/account", headers=headers)
            acct_resp.raise_for_status()
            acct = acct_resp.json()

            # 3. Fetch positions
            pos_resp = await client.get(f"{ALPACA_BASE_URL}/v2/positions", headers=headers)
            pos_resp.raise_for_status()
            positions = pos_resp.json()

        # 4. Parse account fields
        equity = _parse_float(acct.get("equity"))
        buying_power = _parse_float(acct.get("buying_power"))
        cash = _parse_float(acct.get("cash"))

        synced_at = datetime.now(timezone.utc)

        # 5 & 6. Insert position rows (skip any with unparseable qty — NOT NULL in schema)
        inserted = 0
        async with SessionLocal() as db:
            for pos in positions:
                qty = _parse_float(pos.get("qty"))
                ticker = pos.get("symbol", "")
                if qty is None or not ticker:
                    print(f"[alpaca-sync] Skipping position with missing qty/ticker: {pos}")
                    continue
                await db.execute(
                    text(
                        """
                        INSERT INTO live_positions (
                            sync_run_id, ticker, qty, avg_entry_price,
                            current_price, market_value, cost_basis,
                            unrealized_pl, unrealized_plpc, side,
                            lastday_price, change_today, synced_at
                        ) VALUES (
                            :sync_run_id, :ticker, :qty, :avg_entry_price,
                            :current_price, :market_value, :cost_basis,
                            :unrealized_pl, :unrealized_plpc, :side,
                            :lastday_price, :change_today, :synced_at
                        )
                        """
                    ),
                    {
                        "sync_run_id": run_id,
                        "ticker": ticker,
                        "qty": qty,
                        "avg_entry_price": _parse_float(pos.get("avg_entry_price")),
                        "current_price": _parse_float(pos.get("current_price")),
                        "market_value": _parse_float(pos.get("market_value")),
                        "cost_basis": _parse_float(pos.get("cost_basis")),
                        "unrealized_pl": _parse_float(pos.get("unrealized_pl")),
                        "unrealized_plpc": _parse_float(pos.get("unrealized_plpc")),
                        "side": pos.get("side", "long"),
                        "lastday_price": _parse_float(pos.get("lastday_price")),
                        "change_today": _parse_float(pos.get("change_today")),
                        "synced_at": synced_at,
                    },
                )
                inserted += 1

            # 7. Update sync run to success
            completed_at = datetime.now(timezone.utc)
            await db.execute(
                text(
                    """
                    UPDATE alpaca_sync_runs
                    SET status = 'success',
                        completed_at = :completed_at,
                        account_value = :account_value,
                        buying_power = :buying_power,
                        cash = :cash,
                        position_count = :position_count
                    WHERE run_id = :run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "completed_at": completed_at,
                    "account_value": equity,
                    "buying_power": buying_power,
                    "cash": cash,
                    "position_count": inserted,
                },
            )
            await db.commit()

        print(f"[alpaca-sync] Sync completed: run_id={run_id}, positions={inserted}")

    except Exception as exc:
        # 8. Mark run as failed
        error_msg = str(exc)[:500]
        print(f"[alpaca-sync] Sync failed: run_id={run_id}, error={error_msg}")
        async with SessionLocal() as db:
            await db.execute(
                text(
                    """
                    UPDATE alpaca_sync_runs
                    SET status = 'failed',
                        completed_at = :completed_at,
                        error_message = :error_message
                    WHERE run_id = :run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "completed_at": datetime.now(timezone.utc),
                    "error_message": error_msg,
                },
            )
            await db.commit()

    return run_id


async def _sync_with_lock() -> tuple[str, str]:
    """Acquire the lock and run a sync. Returns (status, run_id)."""
    if _job_lock.locked():
        return "already_running", ""
    async with _job_lock:
        run_id = await _do_sync()
    return "started", run_id


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, SessionLocal
    if not DATABASE_URL:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Wait for DB with up to 60s (20 retries × 3s)
    await wait_for_db(engine, retries=20, delay=3.0)

    # Mark any orphaned 'running' runs as failed
    async with SessionLocal() as db:
        result = await db.execute(
            text(
                """
                UPDATE alpaca_sync_runs
                SET status = 'failed',
                    error_message = 'orphaned on restart'
                WHERE status = 'running'
                """
            )
        )
        await db.commit()
        orphaned = result.rowcount
        if orphaned:
            print(f"[alpaca-sync] Marked {orphaned} orphaned sync run(s) as failed")

    # Log credential status
    if _has_credentials:
        print(f"[alpaca-sync] Alpaca credentials configured, base_url={ALPACA_BASE_URL}")
        # Trigger background sync immediately
        asyncio.create_task(_sync_with_lock())
    else:
        print("[alpaca-sync] WARNING: ALPACA_API_KEY is not set or is 'demo' — sync disabled on startup")

    yield
    await engine.dispose()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="alpaca-sync", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "alpaca-sync",
        "has_credentials": _has_credentials,
    }


@app.post("/jobs/sync")
async def trigger_sync():
    """Trigger a sync. Respects the concurrency lock."""
    if _job_lock.locked():
        return {"status": "already_running"}
    asyncio.create_task(_sync_with_lock())
    return {"status": "started"}


@app.get("/runs/latest")
async def get_latest_run():
    """Return the most recent alpaca_sync_runs row."""
    async with SessionLocal() as db:
        result = await db.execute(
            text(
                """
                SELECT run_id, status, account_value, buying_power, cash,
                       position_count, error_message, started_at, completed_at
                FROM alpaca_sync_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
        )
        row = result.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="No sync runs found")

    return {
        "run_id": str(row.run_id),
        "status": row.status,
        "account_value": _f(row.account_value),
        "buying_power": _f(row.buying_power),
        "cash": _f(row.cash),
        "position_count": row.position_count,
        "error_message": row.error_message,
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
    }


@app.get("/positions")
async def get_positions():
    """Return positions from the latest successful sync run."""
    async with SessionLocal() as db:
        # Find latest successful run
        run_result = await db.execute(
            text(
                """
                SELECT run_id
                FROM alpaca_sync_runs
                WHERE status = 'success'
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
        )
        run_row = run_result.fetchone()

        if run_row is None:
            return []

        run_id = str(run_row.run_id)

        pos_result = await db.execute(
            text(
                """
                SELECT ticker, qty, avg_entry_price, current_price,
                       market_value, cost_basis, unrealized_pl, unrealized_plpc,
                       side, lastday_price, change_today, synced_at
                FROM live_positions
                WHERE sync_run_id = :run_id
                ORDER BY market_value DESC NULLS LAST
                """
            ),
            {"run_id": run_id},
        )
        rows = pos_result.fetchall()

    return [
        {
            "ticker": row.ticker,
            "qty": _f(row.qty),
            "avg_entry_price": _f(row.avg_entry_price),
            "current_price": _f(row.current_price),
            "market_value": _f(row.market_value),
            "cost_basis": _f(row.cost_basis),
            "unrealized_pl": _f(row.unrealized_pl),
            "unrealized_plpc": _f(row.unrealized_plpc),
            "side": row.side,
            "lastday_price": _f(row.lastday_price),
            "change_today": _f(row.change_today),
            "synced_at": _iso(row.synced_at),
        }
        for row in rows
    ]
