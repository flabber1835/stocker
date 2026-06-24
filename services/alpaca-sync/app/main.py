import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stock_strategy_shared.db import wait_for_db, warm_up_db_in_background  # noqa: F401
from stock_strategy_shared.broker import get_broker_adapter

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
# audit P1: if any broker position fails to parse/write, the snapshot is INCOMPLETE.
# Marking it 'success' undercounts MAX_POSITIONS downstream → over-entry → insufficient
# funds, and can make _size_exit refuse a position you actually hold. Fail the sync
# instead so freshness gates fall back to the last COMPLETE snapshot. Set false to
# revert to best-effort (record skipped but still succeed).
SYNC_FAIL_ON_SKIPPED_POSITIONS = os.getenv("SYNC_FAIL_ON_SKIPPED_POSITIONS", "true").lower() == "true"


class _PartialSyncError(Exception):
    """Raised when positions were skipped and SYNC_FAIL_ON_SKIPPED_POSITIONS is on —
    routes the run through the normal failed path so it is not trusted as fresh."""

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
    """Convert any numeric-ish value (Decimal, str, float) to float or None."""
    if v is None:
        return None
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def _iso(v) -> Optional[str]:
    """Convert datetime to ISO string or None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


_parse_float = _f  # alias for Alpaca API string → float conversions


async def _log_step(
    db, trace_id: str, step_name: str, status: str, started_at: datetime,
    input_summary: Optional[dict] = None, output_summary: Optional[dict] = None,
    error_message: Optional[str] = None,
) -> None:
    """Insert one execution_steps row for this trace."""
    await db.execute(
        text(
            "INSERT INTO execution_steps "
            "(step_id, trace_id, service, step_name, status, started_at, completed_at, "
            " input_summary, output_summary, error_message) "
            "VALUES (:sid, :tid, 'alpaca-sync', :step, :status, :started, :now, "
            "        CAST(:inp AS jsonb), CAST(:out AS jsonb), :err)"
        ),
        {
            "sid": str(uuid.uuid4()),
            "tid": trace_id,
            "step": step_name,
            "status": status,
            "started": started_at,
            "now": datetime.now(timezone.utc),
            "inp": json.dumps(input_summary) if input_summary else None,
            "out": json.dumps(output_summary) if output_summary else None,
            "err": error_message,
        },
    )


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------

# Broker access goes through the shared adapter (single source of broker
# knowledge: base URL, auth headers, endpoint shapes, and the broker-status →
# canonical-DB-token map). One broker per deployment, selected by BROKER env.
# The adapter is built per-call reading the CURRENT module config so tests that
# patch ALPACA_API_KEY/SECRET_KEY still take effect; http_provider routes
# transport through this module's `httpx` so `patch("app.main.httpx.AsyncClient")`
# keeps intercepting.
def _broker():
    return get_broker_adapter(
        api_key=ALPACA_API_KEY,
        secret_key=ALPACA_SECRET_KEY,
        base_url=ALPACA_BASE_URL,
        http_provider=lambda: httpx,
    )


async def _do_sync(
    run_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    started_at: Optional[datetime] = None,
) -> str:
    """Run a full Alpaca sync. Returns the run_id (str UUID).

    Each sync gets its own execution_trace with steps:
      fetch_account → fetch_positions → write_positions → sync_orders

    When run_id/trace_id/started_at are provided the caller has already inserted
    the rows (so they are committed before the HTTP response is sent); skip the
    INSERT in that case to avoid a duplicate-key error.
    """
    rows_preinserted = run_id is not None
    if run_id is None:
        run_id = str(uuid.uuid4())
    if trace_id is None:
        trace_id = str(uuid.uuid4())
    if started_at is None:
        started_at = datetime.now(timezone.utc)

    if not rows_preinserted:
        async with SessionLocal() as db:
            # Open trace + sync run together so every branch is auditable.
            await db.execute(
                text(
                    "INSERT INTO execution_traces "
                    "(trace_id, job_type, status, root_run_id, started_at) "
                    "VALUES (:tid, 'alpaca_sync', 'running', :rid, :now)"
                ),
                {"tid": trace_id, "rid": run_id, "now": started_at},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO alpaca_sync_runs (run_id, status, started_at, trace_id)
                    VALUES (:run_id, 'running', :started_at, :trace_id)
                    """
                ),
                {"run_id": run_id, "started_at": started_at, "trace_id": trace_id},
            )
            await db.commit()

    try:
        broker = _broker()

        # Step: fetch_account
        t0 = datetime.now(timezone.utc)
        acct = await broker.get_account()
        equity = acct.equity
        buying_power = acct.buying_power
        cash = acct.cash
        async with SessionLocal() as db:
            await _log_step(
                db, trace_id, "fetch_account", "success", t0,
                output_summary={"equity": equity, "buying_power": buying_power, "cash": cash},
            )
            await db.commit()

        # Step: fetch_positions
        t0 = datetime.now(timezone.utc)
        positions = await broker.get_positions()
        async with SessionLocal() as db:
            await _log_step(
                db, trace_id, "fetch_positions", "success", t0,
                output_summary={"position_count": len(positions)},
            )
            await db.commit()

        synced_at = datetime.now(timezone.utc)

        # Step: write_positions
        t0 = datetime.now(timezone.utc)
        inserted = 0
        skipped = 0
        async with SessionLocal() as db:
            for pos in positions:
                qty = pos.qty
                ticker = pos.ticker
                if qty is None or not ticker:
                    print(f"[alpaca-sync] Skipping position with missing qty/ticker: {pos.raw}")
                    skipped += 1
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
                        "avg_entry_price": pos.avg_entry_price,
                        "current_price": pos.current_price,
                        "market_value": pos.market_value,
                        "cost_basis": pos.cost_basis,
                        "unrealized_pl": pos.unrealized_pl,
                        "unrealized_plpc": pos.unrealized_plpc,
                        "side": pos.side,
                        "lastday_price": pos.lastday_price,
                        "change_today": pos.change_today,
                        "synced_at": synced_at,
                    },
                )
                inserted += 1

            await _log_step(
                db, trace_id, "write_positions", "success", t0,
                output_summary={"inserted": inserted, "skipped": skipped},
            )
            await db.commit()

        # Step: sync_orders — update alpaca_orders rows from Alpaca's live order list (non-fatal)
        t0 = datetime.now(timezone.utc)
        orders_updated = 0
        orders_skipped = 0
        try:
            # Fetch all orders (open + closed) up to 500; covers typical paper account.
            # Adapter returns normalized BrokerOrder objects with status already
            # mapped to canonical DB tokens (partial_fill, not partially_filled).
            broker_orders = await broker.list_orders(status="all", limit=500)

            # Build lookup: broker_order_id → BrokerOrder
            alpaca_map = {o.broker_order_id: o for o in broker_orders}

            # Load our submitted orders that have an Alpaca order ID
            async with SessionLocal() as db2:
                rows = (await db2.execute(text(
                    "SELECT id, alpaca_order_id FROM alpaca_orders "
                    "WHERE status = 'submitted' AND alpaca_order_id IS NOT NULL"
                ))).fetchall()

            for row in rows:
                ao = alpaca_map.get(str(row.alpaca_order_id))
                if ao is None:
                    orders_skipped += 1
                    continue
                alpaca_status = ao.raw_status
                new_status = ao.status
                if new_status is None:
                    orders_skipped += 1
                    continue  # still open (new, pending_new, accepted, held…)

                filled_qty = ao.filled_qty
                avg_fill = ao.avg_fill_price
                filled_at = ao.filled_at

                async with SessionLocal() as db2:
                    await db2.execute(
                        text(
                            "UPDATE alpaca_orders "
                            "SET status=:status, alpaca_status=:astatus, "
                            "    filled_qty=:fqty, avg_fill_price=:afill, filled_at=:fat "
                            "WHERE id=:id"
                        ),
                        {
                            "id": str(row.id),
                            "status": new_status,
                            "astatus": alpaca_status,
                            "fqty": filled_qty,
                            "afill": avg_fill,
                            "fat": filled_at,
                        },
                    )
                    await db2.commit()
                orders_updated += 1

            async with SessionLocal() as db2:
                await _log_step(
                    db2, trace_id, "sync_orders", "success", t0,
                    output_summary={
                        "alpaca_orders_fetched": len(broker_orders),
                        "local_submitted": len(rows),
                        "updated": orders_updated,
                        "skipped": orders_skipped,
                    },
                )
                await db2.commit()
        except Exception as ord_exc:
            print(f"[alpaca-sync] WARN: order status sync failed (non-fatal): {ord_exc}", flush=True)
            async with SessionLocal() as db2:
                await _log_step(
                    db2, trace_id, "sync_orders", "failed", t0,
                    error_message=str(ord_exc)[:500],
                )
                await db2.commit()

        # audit P1: an incomplete position snapshot must NOT be marked success.
        if skipped > 0 and SYNC_FAIL_ON_SKIPPED_POSITIONS:
            raise _PartialSyncError(
                f"{skipped} of {len(positions)} broker positions failed to parse/write "
                f"(inserted={inserted}); refusing to mark this sync 'success' — an "
                "incomplete snapshot would undercount positions downstream."
            )

        # Update sync run + trace to success
        completed_at = datetime.now(timezone.utc)
        async with SessionLocal() as db:
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
            await db.execute(
                text(
                    "UPDATE execution_traces SET status='success', completed_at=:now "
                    "WHERE trace_id=:tid"
                ),
                {"tid": trace_id, "now": completed_at},
            )
            await db.commit()

        print(f"[alpaca-sync] Sync completed: run_id={run_id}, positions={inserted}, orders_updated={orders_updated}")

    except Exception as exc:
        # Mark sync run + trace as failed
        error_msg = str(exc)[:500]
        print(f"[alpaca-sync] Sync failed: run_id={run_id}, error={error_msg}")
        async with SessionLocal() as db:
            await _log_step(
                db, trace_id, "fetch_or_write", "failed", started_at,
                error_message=error_msg,
            )
            await db.execute(
                text(
                    "UPDATE execution_traces SET status='failed', completed_at=:now, "
                    "notes=:notes WHERE trace_id=:tid"
                ),
                {"tid": trace_id, "now": datetime.now(timezone.utc), "notes": error_msg[:200]},
            )
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


async def _sync_with_lock(
    run_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    started_at: Optional[datetime] = None,
) -> tuple[str, str]:
    """Acquire the lock and run a sync. Returns (status, run_id).

    When run_id/trace_id/started_at are provided they are forwarded to _do_sync
    so the pre-inserted row is reused rather than creating a duplicate.
    """
    if _job_lock.locked():
        # The lock is already held by an in-flight sync. trigger_sync pre-inserted
        # a 'running' row + trace BEFORE scheduling this task, and _do_sync (which
        # flips them to success/failed) will NOT run on this path — so without this
        # they would orphan as forever-'running', misleading broker-freshness
        # consumers. Mark them failed here so the short-circuit is self-cleaning.
        if run_id:
            await _mark_run_superseded(run_id, trace_id)
        return "already_running", ""
    async with _job_lock:
        run_id = await _do_sync(run_id=run_id, trace_id=trace_id, started_at=started_at)
    return "started", run_id


async def _mark_run_superseded(run_id: str, trace_id: Optional[str]) -> None:
    """Flip a pre-inserted run+trace to failed when its sync never runs (lock held).
    Best-effort: a DB hiccup here must not crash the trigger task."""
    try:
        async with SessionLocal() as db:
            await db.execute(
                text(
                    "UPDATE alpaca_sync_runs SET status='failed', completed_at=NOW(), "
                    "error_message='superseded: a sync was already running' "
                    "WHERE run_id=:rid AND status='running'"
                ),
                {"rid": run_id},
            )
            if trace_id:
                await db.execute(
                    text(
                        "UPDATE execution_traces SET status='failed', completed_at=NOW(), "
                        "notes='superseded: a sync was already running' "
                        "WHERE trace_id=:tid AND status='running'"
                    ),
                    {"tid": trace_id},
                )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[alpaca-sync] WARN: could not mark superseded run {run_id} failed: {exc}", flush=True)


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------


async def _alpaca_sync_warm_up(engine_, session_factory):
    """Background warm-up: wait for DB, then clean up orphaned runs and (if creds
    are present) kick off the first sync. Runs as a task so lifespan can yield
    immediately, keeping the docker healthcheck happy on slow NAS boots."""
    try:
        await wait_for_db(engine_)
    except Exception as exc:
        print(f"[alpaca-sync] DB warm-up failed after retries: {exc}", flush=True)
        return
    try:
        async with session_factory() as db:
            result = await db.execute(
                text(
                    """
                    UPDATE alpaca_sync_runs
                    SET status = 'failed',
                        completed_at = NOW(),
                        error_message = 'orphaned on restart'
                    WHERE status = 'running'
                    """
                )
            )
            await db.execute(
                text(
                    """
                    UPDATE execution_traces
                    SET status = 'failed',
                        completed_at = NOW(),
                        notes = 'orphaned on restart'
                    WHERE status = 'running' AND job_type = 'alpaca_sync'
                    """
                )
            )
            await db.commit()
            orphaned = result.rowcount
            if orphaned:
                print(f"[alpaca-sync] Marked {orphaned} orphaned sync run(s) as failed", flush=True)
    except Exception as exc:
        print(f"[alpaca-sync] WARN: orphan-cleanup skipped: {exc}", flush=True)

    if _has_credentials:
        print(f"[alpaca-sync] Alpaca credentials configured, base_url={ALPACA_BASE_URL}", flush=True)
        asyncio.create_task(_sync_with_lock())
        asyncio.create_task(_periodic_sync_loop())
    else:
        print("[alpaca-sync] WARNING: ALPACA_API_KEY is not set or is 'demo' — sync disabled on startup", flush=True)


SYNC_INTERVAL_SECS = int(os.getenv("ALPACA_SYNC_INTERVAL_SECS", "300"))  # default 5 minutes


async def _periodic_sync_loop():
    """Re-sync Alpaca state every SYNC_INTERVAL_SECS so fills/cancels are picked up
    without requiring a service restart."""
    while True:
        try:
            await asyncio.sleep(SYNC_INTERVAL_SECS)
        except asyncio.CancelledError:
            return
        try:
            await _sync_with_lock()
        except Exception as exc:
            print(f"[alpaca-sync] periodic sync error: {exc}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, SessionLocal
    if not DATABASE_URL:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=3,
                                 connect_args={"timeout": 60})
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Run wait_for_db + orphan cleanup + first-sync trigger in the background so
    # lifespan can yield immediately. Blocking here causes the docker healthcheck
    # (start_period 20s + 5×5s = 45s) to fail before wait_for_db's 90s max
    # completes on slow NAS hardware, triggering a restart loop.
    asyncio.create_task(_alpaca_sync_warm_up(engine, SessionLocal))

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
    """Trigger a sync. Respects the concurrency lock.

    Pre-creates the alpaca_sync_runs row synchronously so the run_id is
    committed before the HTTP response is sent — the caller can query the row
    immediately without polling for it.
    """
    if _job_lock.locked():
        return {"status": "already_running"}
    run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO execution_traces "
                "(trace_id, job_type, status, root_run_id, started_at) "
                "VALUES (:tid, 'alpaca_sync', 'running', :rid, :now)"
            ),
            {"tid": trace_id, "rid": run_id, "now": started_at},
        )
        await db.execute(
            text(
                "INSERT INTO alpaca_sync_runs (run_id, status, started_at, trace_id) "
                "VALUES (:run_id, 'running', :started_at, :trace_id)"
            ),
            {"run_id": run_id, "started_at": started_at, "trace_id": trace_id},
        )
        await db.commit()
    asyncio.create_task(_sync_with_lock(run_id=run_id, trace_id=trace_id, started_at=started_at))
    return {"status": "started", "run_id": run_id}


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
