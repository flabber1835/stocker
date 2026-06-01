"""Trade executor — the only service permitted to submit Alpaca orders.

End-to-end responsibility for the approval click:
  1. Load delta intent (intent_id → ticker, action, weight)
  2. Size the order (entries/buy_adds: account_value × weight ÷ price;
     sell_trims: account_value × weight ÷ price; exits: full position)
  3. Call risk-service /check
  4. Persist alpaca_orders + execution_steps audit
  5. If risk-approved and credentials present: POST to Alpaca /v2/orders
     (time_in_force="day" — regular market order, accepted 24/7, queues for
     the next session when submitted outside market hours)

Every approval click produces one execution_trace row with step-by-step audit so
the dashboard's trace viewer shows exactly why a trade was approved/rejected.
"""
import asyncio
import json
import logging
import math
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from stock_strategy_shared.db import wait_for_db

from app.drain import DeferredOrder, plan_drain

logger = logging.getLogger("trade-executor")
logging.basicConfig(level=logging.INFO)

# ── Environment variables ────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
RISK_SERVICE_URL = os.getenv("RISK_SERVICE_URL", "http://risk-service:8000")
try:
    EXIT_SYNC_MAX_AGE_HOURS = float(os.getenv("EXIT_SYNC_MAX_AGE_HOURS", "24"))
except ValueError:
    EXIT_SYNC_MAX_AGE_HOURS = 24.0
try:
    DEFAULT_MAX_POSITIONS = int(os.getenv("DEFAULT_MAX_POSITIONS", "30"))
except ValueError:
    DEFAULT_MAX_POSITIONS = 30
try:
    DEFERRED_WORKER_INTERVAL_SECS = int(os.getenv("DEFERRED_WORKER_INTERVAL_SECS", "60"))
except ValueError:
    DEFERRED_WORKER_INTERVAL_SECS = 60
try:
    # How long the drain waits for a submitted sell to fill before it stops
    # blocking buys (a halted sell must not wedge the book forever).
    SELL_FILL_TIMEOUT_SECS = float(os.getenv("SELL_FILL_TIMEOUT_SECS", "300"))
except ValueError:
    SELL_FILL_TIMEOUT_SECS = 300.0


engine: Optional[AsyncEngine] = None


# ── Lifespan ─────────────────────────────────────────────────────────────────


async def _trade_executor_warm_up():
    """Background DB warm-up + orphan-order cleanup so lifespan can yield
    immediately and the docker healthcheck succeeds on slow NAS boots."""
    try:
        await wait_for_db(engine)
    except Exception as exc:
        logger.warning("DB warm-up failed after retries: %s", exc)
        return
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE alpaca_orders SET status='failed', "
                "error_message='service restarted before submission' "
                "WHERE status='pending'"
            ))
        logger.info("DB connected; persistence enabled")
    except Exception as exc:
        logger.warning("orphan-order cleanup skipped: %s", exc)


async def _submit_deferred_order(row: dict) -> tuple[str, Optional[str]]:
    """Submit a single deferred order to Alpaca. Returns (new_status, error_or_None).

    Called by the background worker. Mirrors the inline submit_alpaca block in
    submit_order() but operates on already-persisted rows rather than building
    a payload from scratch.
    """
    order_id = str(row["id"])
    payload = {
        "symbol": row["ticker"],
        "qty": str(int(row["qty"])) if float(row["qty"]) >= 1 else str(row["qty"]),
        "side": row["side"],
        "type": row.get("order_type") or "market",
        "time_in_force": row.get("time_in_force") or "day",
    }
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
        return "failed", "Alpaca credentials not configured"
    # Re-check the kill switch before submitting a deferred order — the kill
    # switch may have been activated after this order entered deferred state.
    try:
        async with httpx.AsyncClient(timeout=5.0) as _ks_client:
            _ks_resp = await _ks_client.get(f"{RISK_SERVICE_URL}/health")
            if _ks_resp.status_code == 200:
                _ks_data = _ks_resp.json()
                if _ks_data.get("kill_switch"):
                    return "failed", "Kill switch active — deferred order blocked"
    except Exception:
        pass  # Risk service unreachable — allow order (fail-open, consistent with main path)
    try:
        # Single submission entrypoint — exits route to close-position, everything
        # else to /v2/orders. Shared with the immediate submit_order() path so the
        # two can never diverge.
        alpaca_order_id, alpaca_status, alpaca_err = await _submit_for_action(
            row.get("action"), row["ticker"], payload
        )
    except Exception as exc:
        return "failed", f"Alpaca request failed: {exc}"[:1000]
    if alpaca_err is not None:
        return "failed", alpaca_err
    # Success
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE alpaca_orders SET status='submitted', alpaca_order_id=:aid, "
                "alpaca_status=:astatus, submitted_at=:s, deferred_until=NULL, "
                "error_message=NULL WHERE id=:id"
            ),
            {"id": order_id, "aid": alpaca_order_id,
             "astatus": alpaca_status, "s": datetime.now(timezone.utc)},
        )
    return "submitted", None


def _parse_alpaca_dt(raw) -> Optional[datetime]:
    """Parse an Alpaca ISO timestamp (e.g. '2026-06-01T09:30:00-04:00')."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _alpaca_read_headers() -> dict:
    return {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}


async def _get_alpaca_clock() -> Optional[dict]:
    """GET /v2/clock → {is_open, next_open, next_close}. None if creds missing or
    unreachable (caller treats unknown state as 'do not submit blind')."""
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{ALPACA_BASE_URL}/v2/clock", headers=_alpaca_read_headers())
        if r.status_code == 200:
            d = r.json()
            return {
                "is_open": bool(d.get("is_open")),
                "next_open": _parse_alpaca_dt(d.get("next_open")),
                "next_close": _parse_alpaca_dt(d.get("next_close")),
            }
    except Exception as exc:
        logger.warning("Alpaca clock fetch failed: %s", exc)
    return None


async def _get_alpaca_buying_power() -> Optional[float]:
    """GET /v2/account → buying_power (float). None on failure."""
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{ALPACA_BASE_URL}/v2/account", headers=_alpaca_read_headers())
        if r.status_code == 200:
            return _f(r.json().get("buying_power"))
    except Exception as exc:
        logger.warning("Alpaca account fetch failed: %s", exc)
    return None


async def _get_alpaca_order(alpaca_order_id: str) -> Optional[dict]:
    """GET /v2/orders/{id} → the order dict. None on failure."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{ALPACA_BASE_URL}/v2/orders/{alpaca_order_id}",
                headers=_alpaca_read_headers(),
            )
        if r.status_code == 200:
            return r.json()
    except Exception as exc:
        logger.warning("Alpaca order fetch failed for %s: %s", alpaca_order_id, exc)
    return None


async def _reconcile_unfilled_sells() -> None:
    """Poll Alpaca for sells that were submitted but not yet marked filled, and
    flip them to status='filled' so the drain's gate can see credited buying power.

    The drain does this itself (rather than waiting for the periodic alpaca-sync)
    so buys release within a pass or two of the sells filling. The UPDATE mirrors
    alpaca-sync's reconciliation and is idempotent."""
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT id, alpaca_order_id FROM alpaca_orders "
            "WHERE status='submitted' AND side='sell' AND filled_at IS NULL "
            "  AND alpaca_order_id IS NOT NULL"
        ))).mappings().fetchall()
    for row in rows:
        info = await _get_alpaca_order(row["alpaca_order_id"])
        if info and info.get("status") == "filled":
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE alpaca_orders SET status='filled', filled_at=:fat, "
                    "avg_fill_price=:afp, filled_qty=:fq, alpaca_status='filled' "
                    "WHERE id=:id"
                ), {
                    "id": str(row["id"]),
                    "fat": _parse_alpaca_dt(info.get("filled_at")) or datetime.now(timezone.utc),
                    "afp": _f(info.get("filled_avg_price")),
                    "fq": _f(info.get("filled_qty")),
                })


def _row_to_deferred(row: dict) -> DeferredOrder:
    return DeferredOrder(
        id=str(row["id"]),
        side=row["side"],
        notional=_f(row["notional"]),
        submitted_at=row["submitted_at"],
        expires_at=row["expires_at"],
    )


async def _submit_one_deferred(order_id: str) -> None:
    """Load a still-deferred order and submit it; mark failed on error."""
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT id, intent_id, ticker, action, side, qty, notional, "
            "       order_type, time_in_force, mode, trace_id "
            "FROM alpaca_orders WHERE id=:id AND status='deferred'"
        ), {"id": order_id})).mappings().first()
    if row is None:
        return  # already handled (e.g. concurrent pass)
    new_status, err = await _submit_deferred_order(dict(row))
    if new_status == "submitted":
        logger.info("Drain submitted order %s (%s %s)", row["id"], row["side"], row["ticker"])
    else:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE alpaca_orders SET status='failed', error_message=:err WHERE id=:id"),
                {"id": order_id, "err": err},
            )
        logger.warning("Drain: order %s failed: %s", order_id, err)


async def _drain_pass() -> None:
    """One fill-gated drain pass (see docs/architecture.md Option B).

    Sells-first, all sells filled before any buy, buys released one at a time
    within live buying power, unfunded buys expired at their session close. All
    state lives in alpaca_orders so the pass is stateless across restarts."""
    clock = await _get_alpaca_clock()
    is_open = bool(clock and clock["is_open"])
    now = datetime.now(timezone.utc)

    # Poll fills for submitted sells so the gate sees credited buying power.
    if is_open:
        await _reconcile_unfilled_sells()

    _cols = "id, side, notional, submitted_at, expires_at"
    async with engine.connect() as conn:
        d_sells = (await conn.execute(text(
            f"SELECT {_cols} FROM alpaca_orders WHERE status='deferred' AND side='sell' "
            "AND (deferred_until IS NULL OR deferred_until <= NOW()) ORDER BY created_at ASC"
        ))).mappings().fetchall()
        u_sells = (await conn.execute(text(
            f"SELECT {_cols} FROM alpaca_orders WHERE status='submitted' AND side='sell' "
            "AND filled_at IS NULL"
        ))).mappings().fetchall()
        d_buys = (await conn.execute(text(
            f"SELECT {_cols} FROM alpaca_orders WHERE status='deferred' AND side='buy' "
            "AND (deferred_until IS NULL OR deferred_until <= NOW()) ORDER BY created_at ASC"
        ))).mappings().fetchall()

    if not (d_sells or u_sells or d_buys):
        return  # nothing queued

    # Only fetch buying power when buys could actually release this pass.
    buying_power = None
    if is_open and not d_sells and not u_sells:
        buying_power = await _get_alpaca_buying_power()

    decision = plan_drain(
        is_open=is_open,
        now=now,
        deferred_sells=[_row_to_deferred(dict(r)) for r in d_sells],
        unfilled_submitted_sells=[_row_to_deferred(dict(r)) for r in u_sells],
        deferred_buys=[_row_to_deferred(dict(r)) for r in d_buys],
        buying_power=buying_power,
        sell_fill_timeout_secs=SELL_FILL_TIMEOUT_SECS,
    )

    for oid in decision.expire:
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE alpaca_orders SET status='expired', "
                "error_message='unfunded at session close' "
                "WHERE id=:id AND status='deferred'"
            ), {"id": oid})
        logger.info("Drain expired unfunded queued order %s", oid)

    for oid in decision.submit_sells:
        await _submit_one_deferred(oid)
    for oid in decision.submit_buys:
        await _submit_one_deferred(oid)


async def _deferred_order_worker() -> None:
    """Background worker: runs one fill-gated drain pass every
    DEFERRED_WORKER_INTERVAL_SECS. Stateless across restarts (state lives in
    alpaca_orders)."""
    await asyncio.sleep(5)
    while True:
        try:
            if engine is not None:
                await _drain_pass()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Deferred order worker error: %s", exc)
        await asyncio.sleep(DEFERRED_WORKER_INTERVAL_SECS)


@asynccontextmanager
async def lifespan(application: FastAPI):
    global engine
    if not DATABASE_URL:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")
    engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True,
                                 pool_size=2, max_overflow=3, connect_args={"timeout": 60})
    asyncio.create_task(_trade_executor_warm_up())
    worker_task = asyncio.create_task(_deferred_order_worker())
    has_creds = bool(ALPACA_API_KEY and ALPACA_SECRET_KEY)
    logger.info(
        "Alpaca credentials: %s", "present" if has_creds else "NOT SET — orders will be rejected"
    )
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


app = FastAPI(title="trade-executor", lifespan=lifespan)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def _iso(v) -> Optional[str]:
    return v.isoformat() if v and hasattr(v, "isoformat") else None


async def _log_step(
    conn, trace_id: str, step_name: str, status: str, started_at: datetime,
    input_summary: Optional[dict] = None, output_summary: Optional[dict] = None,
    error_message: Optional[str] = None,
) -> None:
    """Insert one row into execution_steps for this trace."""
    await conn.execute(
        text(
            "INSERT INTO execution_steps "
            "(step_id, trace_id, service, step_name, status, started_at, completed_at, "
            " input_summary, output_summary, error_message) "
            "VALUES (:sid, :tid, 'trade-executor', :step, :status, :started, :now, "
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


# ── Pydantic models ──────────────────────────────────────────────────────────


class SubmitOrderRequest(BaseModel):
    """The trade-executor takes the minimal input: the intent and the mode.

    Everything else — ticker, action, qty, notional, risk approval — is computed
    or fetched inside this service so the API layer cannot drift from the order.
    """
    intent_id: str        # delta_intents.id (UUID)
    mode: Literal["immediate", "scheduled"]


class TradeAttemptResponse(BaseModel):
    status: str           # 'submitted'|'deferred'|'risk_rejected'|'failed'|'duplicate'
    order_id: Optional[str] = None
    deferred_until: Optional[str] = None  # ISO timestamp when worker will retry
    alpaca_order_id: Optional[str] = None
    alpaca_status: Optional[str] = None
    ticker: Optional[str] = None
    action: Optional[str] = None
    side: Optional[str] = None
    qty: Optional[float] = None
    notional: Optional[float] = None
    risk_approved: Optional[bool] = None
    risk_reason: Optional[str] = None
    risk_check_id: Optional[str] = None
    trace_id: Optional[str] = None
    reason: Optional[str] = None


# ── Sizing logic ─────────────────────────────────────────────────────────────


async def _load_intent(conn, intent_id: str) -> dict:
    row = (await conn.execute(text(
        "SELECT di.id, di.ticker, di.action, di.rank, di.composite_score, "
        "       di.current_weight, di.actual_weight, di.weight_drift, di.run_id, "
        "       dr.run_date AS sim_date "
        "FROM delta_intents di "
        "LEFT JOIN delta_runs dr ON dr.run_id = di.run_id "
        "WHERE di.id = :iid"
    ), {"iid": intent_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Intent {intent_id} not found")
    TRADEABLE_ACTIONS = {"entry", "exit", "buy_add", "sell_trim"}
    if row["action"] not in TRADEABLE_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Intent action '{row['action']}' is not tradeable",
        )
    return dict(row)


async def _size_exit(conn, ticker: str) -> tuple[float, float, dict]:
    """Return (qty, notional, summary) for an exit.

    Refuses if the latest successful alpaca-sync is older than EXIT_SYNC_MAX_AGE_HOURS,
    so we never sell shares we may no longer own.
    """
    pos = (await conn.execute(text(
        "SELECT lp.qty, lp.current_price, sr.completed_at "
        "FROM live_positions lp "
        "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
        "WHERE lp.ticker = :t AND sr.status = 'success' "
        "ORDER BY sr.completed_at DESC NULLS LAST LIMIT 1"
    ), {"t": ticker})).mappings().first()
    if pos is None or _f(pos["qty"]) is None:
        raise HTTPException(
            status_code=400,
            detail=f"No live position found for {ticker} — run alpaca-sync first",
        )
    sync_age_hours = None
    if pos["completed_at"] is not None:
        sync_age_hours = (
            datetime.now(timezone.utc) - pos["completed_at"]
        ).total_seconds() / 3600.0
    if sync_age_hours is not None and sync_age_hours > EXIT_SYNC_MAX_AGE_HOURS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Latest alpaca-sync is {sync_age_hours:.1f}h old "
                f"(> {EXIT_SYNC_MAX_AGE_HOURS}h); refusing to size exit. "
                "Re-sync before approving."
            ),
        )
    qty = abs(_f(pos["qty"]))
    current_price = _f(pos["current_price"]) or 0.0
    notional = qty * current_price
    return qty, notional, {
        "source": "live_positions",
        "current_price": current_price,
        "sync_age_hours": round(sync_age_hours, 2) if sync_age_hours is not None else None,
    }


async def _size_entry(conn, ticker: str, intent_weight: Optional[float]) -> tuple[float, float, dict]:
    """Return (qty, notional, summary) for an entry.

    qty = floor(account_value × target_weight ÷ last_price). Sizing uses
    account_value (total equity) so that a fully-invested portfolio replacing
    one exited position gets an entry sized to the correct equity weight —
    buying_power is ~0 in that state and would produce a tiny under-sized order.
    With MOO orders, exits and entries fire at the same open so cash flow
    nets out correctly without an explicit buying_power cap.
    Refuses with 400 when the target notional is less than the price of one
    share — silently rounding up to 1 share would massively overweight the
    position.
    """
    # Target weight: intent.current_weight (preferred) → portfolio_holdings → 1/DEFAULT_MAX_POSITIONS
    weight = intent_weight
    if weight is None or not math.isfinite(weight) or weight <= 0:
        ph = (await conn.execute(text(
            "SELECT ph.weight FROM portfolio_holdings ph "
            "JOIN portfolio_runs pr ON pr.run_id = ph.run_id "
            "WHERE ph.ticker = :t AND pr.status = 'success' "
            "ORDER BY pr.completed_at DESC NULLS LAST LIMIT 1"
        ), {"t": ticker})).mappings().first()
        if ph:
            weight = _f(ph["weight"])
    weight_source = (
        "intent" if intent_weight is not None and math.isfinite(intent_weight) and intent_weight > 0
        else ("portfolio_holdings" if weight and math.isfinite(weight) and weight > 0 else "default")
    )
    if weight is None or not math.isfinite(weight) or weight <= 0:
        weight = 1.0 / DEFAULT_MAX_POSITIONS

    # Account funds from latest successful sync. Refuse if older than
    # EXIT_SYNC_MAX_AGE_HOURS so a stale snapshot can't size a wildly
    # wrong order (same threshold as _size_exit's position-staleness check).
    # buying_power is used for entry sizing (Alpaca already deducts cash
    # reserved for pending orders); account_value is kept in the summary
    # for audit/observability.
    acct = (await conn.execute(text(
        "SELECT account_value, buying_power, completed_at FROM alpaca_sync_runs "
        "WHERE status='success' ORDER BY completed_at DESC NULLS LAST LIMIT 1"
    ))).mappings().first()
    account_value = _f(acct["account_value"]) if acct else None
    buying_power = _f(acct["buying_power"]) if acct else None
    sizing_basis = account_value if account_value is not None else buying_power
    sync_age_hours = None
    if acct and acct["completed_at"] is not None:
        sync_age_hours = (
            datetime.now(timezone.utc) - acct["completed_at"]
        ).total_seconds() / 3600.0
        if sync_age_hours > EXIT_SYNC_MAX_AGE_HOURS:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Latest alpaca-sync is {sync_age_hours:.1f}h old "
                    f"(> {EXIT_SYNC_MAX_AGE_HOURS}h); refusing to size entry. "
                    "Re-sync before approving."
                ),
            )

    # Price: prefer intraday live_positions.current_price, fall back to daily close.
    price_source = "live_positions"
    live_px = (await conn.execute(text(
        "SELECT lp.current_price FROM live_positions lp "
        "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
        "WHERE lp.ticker = :t AND sr.status = 'success' "
        "ORDER BY sr.completed_at DESC NULLS LAST LIMIT 1"
    ), {"t": ticker})).mappings().first()
    last_price = _f(live_px["current_price"]) if live_px else None
    if last_price is None or last_price <= 0:
        price_source = "daily_prices"
        price_row = (await conn.execute(text(
            "SELECT close FROM daily_prices "
            "WHERE ticker = :t ORDER BY date DESC LIMIT 1"
        ), {"t": ticker})).mappings().first()
        last_price = _f(price_row["close"]) if price_row else None

    if sizing_basis is None or last_price is None or last_price <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot compute qty for {ticker}: "
                f"account_value={account_value}, buying_power={buying_power}, "
                f"last_price={last_price}"
            ),
        )

    target_notional = sizing_basis * weight
    qty_int = math.floor(target_notional / last_price)
    if qty_int < 1:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Target notional ${target_notional:.2f} is below the price of "
                f"one share (${last_price:.2f}). Position too small to enter."
            ),
        )
    qty = float(qty_int)
    notional = qty * last_price
    return qty, notional, {
        "weight": weight,
        "weight_source": weight_source,
        "account_value": account_value,
        "buying_power": buying_power,
        "sizing_basis": "account_value" if account_value is not None else "buying_power",
        "sync_age_hours": round(sync_age_hours, 2) if sync_age_hours is not None else None,
        "last_price": last_price,
        "price_source": price_source,
        "target_notional": target_notional,
    }


async def _size_partial(conn, ticker: str, intent: dict) -> tuple[float, float, dict]:
    """Size a buy_add or sell_trim order (partial rebalance).

    buy_add:   buy  (target_weight - actual_weight) * account_value / price shares
    sell_trim: sell (actual_weight - target_weight) * account_value / price shares

    Floored to whole shares. Refuses if the drift rounds to < 1 share.
    """
    action = intent["action"]
    target_weight = _f(intent["current_weight"])
    actual_weight = _f(intent.get("actual_weight"))

    # Fallback: if actual_weight was not stored in the intent (e.g. because
    # live_positions.market_value was unavailable when the delta ran), compute
    # it directly from the current live position at submit time.
    if actual_weight is None:
        live_pos = (await conn.execute(text(
            "SELECT lp.market_value, sr.account_value "
            "FROM live_positions lp "
            "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
            "WHERE lp.ticker = :t AND sr.status = 'success' "
            "ORDER BY sr.completed_at DESC NULLS LAST LIMIT 1"
        ), {"t": ticker})).mappings().first()
        if live_pos:
            mv = _f(live_pos["market_value"])
            av = _f(live_pos["account_value"])
            if mv is not None and av and av > 0:
                actual_weight = mv / av

    if target_weight is None or actual_weight is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot size {action} for {ticker}: "
                "missing target_weight or actual_weight in intent. "
                "Re-run the pipeline to refresh drift data."
            ),
        )
    if not math.isfinite(target_weight) or not math.isfinite(actual_weight) or actual_weight < 0 or target_weight < 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot size {action} for {ticker}: "
                f"invalid weights target={target_weight} actual={actual_weight}. "
                "Re-run the pipeline to refresh drift data."
            ),
        )

    # Account funds + staleness check (reuse EXIT_SYNC_MAX_AGE_HOURS).
    # All buy-side actions (entry, buy_add) size against account_value per spec:
    #   floor(account_value × weight / last_price)
    # A fully-invested portfolio has buying_power ≈ $0, so sizing against
    # buying_power would make every rebalancing buy_add fail. We use
    # account_value (total equity) instead; a separate buying_power guard
    # below refuses the trade if the notional clearly exceeds available cash.
    acct = (await conn.execute(text(
        "SELECT account_value, buying_power, completed_at FROM alpaca_sync_runs "
        "WHERE status='success' ORDER BY completed_at DESC NULLS LAST LIMIT 1"
    ))).mappings().first()
    if acct is None or _f(acct["account_value"]) is None:
        raise HTTPException(status_code=400, detail=f"No account data available to size {action} for {ticker}")
    account_value = _f(acct["account_value"])
    buying_power = _f(acct["buying_power"])
    sizing_basis = account_value
    sizing_basis_name = "account_value"
    if acct["completed_at"] is not None:
        sync_age_hours = (datetime.now(timezone.utc) - acct["completed_at"]).total_seconds() / 3600.0
        if sync_age_hours > EXIT_SYNC_MAX_AGE_HOURS:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Latest alpaca-sync is {sync_age_hours:.1f}h old "
                    f"(> {EXIT_SYNC_MAX_AGE_HOURS}h); refusing to size {action}. "
                    "Re-sync before approving."
                ),
            )

    # Current price — prefer live_positions, fall back to daily_prices
    live_px = (await conn.execute(text(
        "SELECT lp.current_price FROM live_positions lp "
        "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
        "WHERE lp.ticker = :t AND sr.status = 'success' "
        "ORDER BY sr.completed_at DESC NULLS LAST LIMIT 1"
    ), {"t": ticker})).mappings().first()
    last_price = _f(live_px["current_price"]) if live_px else None
    price_source = "live_positions"
    if last_price is None or last_price <= 0:
        price_row = (await conn.execute(text(
            "SELECT close FROM daily_prices WHERE ticker = :t ORDER BY date DESC LIMIT 1"
        ), {"t": ticker})).mappings().first()
        last_price = _f(price_row["close"]) if price_row else None
        price_source = "daily_prices"
    if last_price is None or last_price <= 0:
        raise HTTPException(status_code=400, detail=f"No price found for {ticker}")

    drift_weight = (target_weight - actual_weight) if action == "buy_add" else (actual_weight - target_weight)
    target_notional = drift_weight * sizing_basis
    qty_int = math.floor(target_notional / last_price)
    if qty_int < 1:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Drift notional ${target_notional:.2f} is below the price of one share (${last_price:.2f}). "
                f"Drift too small to trade ({drift_weight:.2%} × ${sizing_basis:,.0f})."
            ),
        )
    qty = float(qty_int)
    # Sell-side over-sell guard: a sell_trim sizes from the drift recorded when the
    # delta ran, but the broker position may have shrunk since (a prior partial
    # fill, a corporate action, or a stale sync). Selling more than is currently
    # held → Alpaca "insufficient qty available". Clamp the trim to the shares
    # actually held now (floored to whole shares), and refuse if the position is
    # already gone. Exits don't pass through here — they use close-position.
    if action == "sell_trim":
        held_now = (await conn.execute(text(
            "SELECT lp.qty FROM live_positions lp "
            "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
            "WHERE lp.ticker = :t AND sr.status = 'success' "
            "ORDER BY sr.completed_at DESC NULLS LAST LIMIT 1"
        ), {"t": ticker})).mappings().first()
        held_qty = math.floor(abs(_f(held_now["qty"]))) if (held_now and _f(held_now["qty"]) is not None) else 0
        if held_qty < 1:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot sell_trim {ticker}: no shares currently held "
                    "(position closed or sync stale). Re-sync before approving."
                ),
            )
        if qty > held_qty:
            qty = float(held_qty)
            qty_int = held_qty
    # Cash sufficiency guard for buy-side actions: if the target notional
    # clearly exceeds buying_power (with 5% tolerance for rounding), refuse
    # early rather than letting the risk-service or Alpaca reject it with a
    # cryptic error.  Exits and sell_trims are not affected (they free cash).
    if action in ("entry", "buy_add") and buying_power is not None:
        target_notional_check = drift_weight * account_value
        if target_notional_check > buying_power * 1.05:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient buying power for {action} {ticker}: "
                    f"notional ${target_notional_check:.0f} > buying_power ${buying_power:.0f}. "
                    "Wait for pending sells to settle or reduce position size."
                ),
            )
    notional = qty * last_price
    return qty, notional, {
        "target_weight": target_weight,
        "actual_weight": actual_weight,
        "drift_weight": drift_weight,
        "account_value": account_value,
        "buying_power": buying_power,
        "sizing_basis": sizing_basis_name,
        "last_price": last_price,
        "price_source": price_source,
        "target_notional": target_notional,
    }


# ── Risk-service call ────────────────────────────────────────────────────────


async def _call_risk(payload: dict) -> tuple[bool, str, str, str]:
    """Call risk-service /check. Returns (approved, reason, check_id, rule_triggered)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(f"{RISK_SERVICE_URL}/check", json=payload)
        r.raise_for_status()
        data = r.json()
    return (
        bool(data.get("approved", False)),
        str(data.get("reason", "")),
        str(data.get("check_id", uuid.uuid4())),
        str(data.get("rule_triggered", "unknown")),
    )


# ── Alpaca submission ────────────────────────────────────────────────────────


async def _submit_to_alpaca(payload: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """POST an order to Alpaca. Returns (alpaca_order_id, alpaca_status, error)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{ALPACA_BASE_URL}/v2/orders",
            json=payload,
            headers={
                "APCA-API-KEY-ID": ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
            },
        )
    if resp.status_code in (200, 201):
        data = resp.json()
        return data.get("id"), data.get("status"), None
    return None, None, resp.text[:1000]


async def _close_position_alpaca(symbol: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Close 100% of a position via Alpaca DELETE /v2/positions/{symbol}.

    Same return shape as _submit_to_alpaca: (alpaca_order_id, alpaca_status, error).

    Used for full exits instead of a qty-based sell. Alpaca computes the exact held
    quantity at execution time, so this cannot over-sell a fractional position — it
    fixes the bug where a stored qty rounded up past the true holding (e.g.
    live_positions.qty NUMERIC(16,6) storing Alpaca's 0.878611682 as 0.878612) made
    Alpaca reject the order with "insufficient qty available". It is also immune to
    drift between the last alpaca-sync and submission.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(
            f"{ALPACA_BASE_URL}/v2/positions/{symbol}",
            headers={
                "APCA-API-KEY-ID": ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
            },
        )
    if resp.status_code in (200, 201):
        data = resp.json()
        return data.get("id"), data.get("status"), None
    if resp.status_code == 404:
        # Position is already flat — the exit's goal (be out of the name) is met.
        # Treat as a benign success rather than a spurious failure.
        return None, "position_already_closed", None
    return None, None, resp.text[:1000]


async def _submit_for_action(
    action: str, ticker: str, payload: dict
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Single Alpaca-submission entrypoint for BOTH submit paths (the immediate
    submit_order() click path and the deferred-order worker).

    This is the one place that decides HOW an action reaches Alpaca:
      - exit      → DELETE /v2/positions/{symbol} (close-position). Alpaca computes
                    the exact held qty at execution, so it never over-sells a
                    fractional position ("insufficient qty available") and is immune
                    to drift since the last sync.
      - all else  → POST /v2/orders with the sized payload.

    Centralising this prevents the two submit paths from diverging — the exact bug
    where the deferred path got the close-position fix but the immediate path did
    not. Returns the same (alpaca_order_id, alpaca_status, error) shape as both
    underlying helpers.
    """
    if action == "exit":
        return await _close_position_alpaca(ticker)
    return await _submit_to_alpaca(payload)


# ── Endpoints ────────────────────────────────────────────────────────────────


async def _is_already_held(conn, ticker: str) -> tuple[bool, Optional[float]]:
    """Return (True, qty) if ticker is held at the broker in the LATEST successful
    sync (qty > 0), else (False, None).

    Deliberately scopes to the latest sync run — not the most recent sync that
    included this ticker — so a position closed in the latest sync is correctly
    reported as not held.

    Returns (False, None) when:
    - no successful sync exists yet
    - the latest sync is stale (> EXIT_SYNC_MAX_AGE_HOURS); lets _size_entry's
      dedicated stale-sync guard surface the clearer "sync too old" error instead.
    """
    row = (await conn.execute(text(
        "SELECT lp.qty, sr.completed_at "
        "FROM live_positions lp "
        "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
        "WHERE sr.run_id = ("
        "  SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
        "  ORDER BY completed_at DESC NULLS LAST LIMIT 1"
        ") AND lp.ticker = :t AND lp.qty > 0"
    ), {"t": ticker})).mappings().first()
    if row is None:
        return False, None
    if row["completed_at"] is not None:
        age_hours = (
            datetime.now(timezone.utc) - row["completed_at"]
        ).total_seconds() / 3600.0
        if age_hours > EXIT_SYNC_MAX_AGE_HOURS:
            return False, None
    qty = _f(row["qty"])
    if qty is None or qty <= 0:
        return False, None
    return True, qty


@app.post("/jobs/submit", response_model=TradeAttemptResponse)
async def submit_order(req: SubmitOrderRequest) -> TradeAttemptResponse:
    """Orchestrate the full approval flow for one delta intent.

    Steps (each persisted to execution_steps):
      load_intent → already_held_check (entry only) → size_order → risk_check → submit_alpaca
    """
    # Validate intent_id as UUID up front
    try:
        uuid.UUID(req.intent_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="intent_id must be a UUID")

    trace_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    # Open a trace at the top so every branch gets audited.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO execution_traces "
                "(trace_id, job_type, status, started_at) "
                "VALUES (:tid, 'trade_approval', 'running', :now)"
            ),
            {"tid": trace_id, "now": started_at},
        )

    try:
        # ── Step 1: idempotency check ─────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        async with engine.connect() as conn:
            existing = (await conn.execute(text(
                "SELECT id, status FROM alpaca_orders "
                "WHERE intent_id = :iid AND status IN ('pending','submitted','deferred') "
                "LIMIT 1"
            ), {"iid": req.intent_id})).mappings().first()
        if existing:
            async with engine.begin() as conn:
                await _log_step(
                    conn, trace_id, "idempotency_check", "skipped", t0,
                    input_summary={"intent_id": req.intent_id},
                    output_summary={"existing_order_id": str(existing["id"]),
                                    "existing_status": existing["status"]},
                )
                await conn.execute(
                    text("UPDATE execution_traces SET status='success', completed_at=:now, "
                         "notes='duplicate' WHERE trace_id=:tid"),
                    {"tid": trace_id, "now": datetime.now(timezone.utc)},
                )
            return TradeAttemptResponse(
                status="duplicate",
                order_id=str(existing["id"]),
                trace_id=trace_id,
                reason=f"Intent {req.intent_id} already has an open order ({existing['status']})",
            )

        # ── Step 2: load intent ───────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        async with engine.connect() as conn:
            intent = await _load_intent(conn, req.intent_id)
        async with engine.begin() as conn:
            await _log_step(
                conn, trace_id, "load_intent", "success", t0,
                input_summary={"intent_id": req.intent_id},
                output_summary={
                    "ticker": intent["ticker"],
                    "action": intent["action"],
                    "rank": intent["rank"],
                    "current_weight": _f(intent["current_weight"]),
                },
            )

        ticker = intent["ticker"]
        action = intent["action"]
        side = "buy" if action in ("entry", "buy_add") else "sell"

        # ── Step 2b: already-held guard (entry only) ──────────────────────────
        # A new delta run can fire before alpaca-sync captures a fill, producing
        # a stale entry intent for a ticker the broker already holds.  Blocking
        # here prevents a duplicate buy order that would double the position.
        # buy_add / exit / sell_trim are intentionally for held tickers — exempt.
        if action == "entry":
            t0 = datetime.now(timezone.utc)
            async with engine.connect() as conn:
                is_held, held_qty = await _is_already_held(conn, ticker)
            if is_held:
                err = (
                    f"{ticker} is already held at the broker (qty={held_qty:.4g}). "
                    "Duplicate entry blocked — a new delta run saw this ticker as "
                    "un-held before alpaca-sync captured the fill. "
                    "Use buy_add if the position is underweight."
                )
                async with engine.begin() as conn:
                    await _log_step(
                        conn, trace_id, "already_held_check", "failed", t0,
                        input_summary={"ticker": ticker, "action": "entry"},
                        output_summary={"qty_held": held_qty},
                        error_message=err,
                    )
                    await _record_order(
                        conn, order_id=order_id, intent_id=req.intent_id,
                        ticker=ticker, action=action, side=side,
                        qty=0.0, notional=0.0, mode=req.mode, trace_id=trace_id,
                        risk_approved=False, risk_reason=err,
                        risk_check_id=None, status="failed",
                        error_message=err,
                    )
                    await conn.execute(
                        text("UPDATE execution_traces SET status='failed', "
                             "completed_at=:now, notes='already_held' "
                             "WHERE trace_id=:tid"),
                        {"tid": trace_id, "now": datetime.now(timezone.utc)},
                    )
                return TradeAttemptResponse(
                    status="failed", order_id=order_id, trace_id=trace_id,
                    ticker=ticker, action=action, side=side,
                    qty=0.0, notional=0.0,
                    risk_approved=False, risk_reason=err,
                    risk_check_id=None, reason=err,
                )

        # ── Step 3: size order ────────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        async with engine.connect() as conn:
            if action == "exit":
                qty, notional, sizing_summary = await _size_exit(conn, ticker)
            elif action in ("buy_add", "sell_trim"):
                qty, notional, sizing_summary = await _size_partial(conn, ticker, intent)
            else:  # entry
                qty, notional, sizing_summary = await _size_entry(
                    conn, ticker, _f(intent["current_weight"])
                )
        async with engine.begin() as conn:
            await _log_step(
                conn, trace_id, "size_order", "success", t0,
                input_summary={"ticker": ticker, "action": action, "mode": req.mode},
                output_summary={"qty": qty, "notional": notional, **sizing_summary},
            )

        # ── Step 4: risk check ────────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        sim_date = intent.get("sim_date")
        risk_payload = {
            "ticker": ticker, "action": action, "side": side,
            "qty": qty, "notional": notional,
            "mode": req.mode, "trade_type": "paper",
            **({"sim_date": str(sim_date)} if sim_date else {}),
        }
        try:
            approved, reason, check_id, rule = await _call_risk(risk_payload)
        except Exception as exc:
            async with engine.begin() as conn:
                await _log_step(
                    conn, trace_id, "risk_check", "failed", t0,
                    input_summary=risk_payload, error_message=str(exc),
                )
                # Persist a failed attempt audit row before giving up.
                await _record_order(
                    conn, order_id=order_id, intent_id=req.intent_id,
                    ticker=ticker, action=action, side=side, qty=qty,
                    notional=notional, mode=req.mode, trace_id=trace_id,
                    risk_approved=False, risk_reason="risk service unreachable",
                    risk_check_id=None, status="failed",
                    error_message=f"risk-service error: {exc}",
                )
                await conn.execute(
                    text("UPDATE execution_traces SET status='failed', completed_at=:now, "
                         "notes='risk_service_unreachable' WHERE trace_id=:tid"),
                    {"tid": trace_id, "now": datetime.now(timezone.utc)},
                )
            raise HTTPException(
                status_code=502,
                detail=f"Risk service unavailable (attempt recorded as order {order_id}): {exc}",
            )

        async with engine.begin() as conn:
            await _log_step(
                conn, trace_id, "risk_check", "success", t0,
                input_summary=risk_payload,
                output_summary={
                    "approved": approved, "rule_triggered": rule,
                    "reason": reason, "check_id": check_id,
                },
            )

        # ── Step 5: persist alpaca_orders row ─────────────────────────────────
        t0 = datetime.now(timezone.utc)
        order_type = "market"
        time_in_force = "day"
        initial_status = "pending" if approved else "risk_rejected"
        try:
            async with engine.begin() as conn:
                await _record_order(
                    conn, order_id=order_id, intent_id=req.intent_id,
                    ticker=ticker, action=action, side=side, qty=qty,
                    notional=notional, mode=req.mode, trace_id=trace_id,
                    risk_approved=approved, risk_reason=reason,
                    risk_check_id=check_id, status=initial_status,
                    order_type=order_type, time_in_force=time_in_force,
                )
                await _log_step(
                    conn, trace_id, "record_order", "success", t0,
                    input_summary={"order_id": order_id, "initial_status": initial_status},
                )
        except IntegrityError:
            # A concurrent submit raced and won the DB unique constraint
            # idx_alpaca_orders_intent_open. Treat as duplicate — same as the
            # idempotency check above, just caught at the DB layer.
            async with engine.connect() as conn:
                dupe = (await conn.execute(text(
                    "SELECT id, status FROM alpaca_orders "
                    "WHERE intent_id=:iid AND status IN ('pending','submitted','deferred') "
                    "LIMIT 1"
                ), {"iid": req.intent_id})).mappings().first()
            return TradeAttemptResponse(
                status="duplicate",
                order_id=str(dupe["id"]) if dupe else order_id,
                trace_id=trace_id,
                reason=f"Concurrent submit: intent {req.intent_id} already has an open order",
            )

        if not approved:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE execution_traces SET status='success', completed_at=:now, "
                         "notes='risk_rejected' WHERE trace_id=:tid"),
                    {"tid": trace_id, "now": datetime.now(timezone.utc)},
                )
            return TradeAttemptResponse(
                status="risk_rejected", order_id=order_id, ticker=ticker, action=action,
                side=side, qty=qty, notional=notional, risk_approved=False,
                risk_reason=reason, risk_check_id=check_id, trace_id=trace_id,
                reason=reason,
            )

        # ── Step 5b: scheduled mode → enqueue for the fill-gated open drain ────
        # The approval is a GREENLIGHT, not a submission. The drain worker submits
        # during market hours only, sells-first, fill-gated, one buy at a time.
        # deferred_until = next open (so the drain waits for the session); when the
        # market is already open, deferred_until=NULL so the next pass picks it up.
        # expires_at = that session's close (an unfunded buy expires, never carries
        # to the next day). See docs/architecture.md Option B.
        if req.mode == "scheduled":
            clock = await _get_alpaca_clock()
            if clock is None:
                deferred_until, expires_at = None, None          # no creds/unreachable → drain ASAP
            elif clock["is_open"]:
                deferred_until, expires_at = None, clock["next_close"]
            else:
                deferred_until, expires_at = clock["next_open"], clock["next_close"]
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE alpaca_orders SET status='deferred', deferred_until=:du, "
                    "expires_at=:ea WHERE id=:id"
                ), {"id": order_id, "du": deferred_until, "ea": expires_at})
                await _log_step(
                    conn, trace_id, "enqueue_deferred", "success",
                    datetime.now(timezone.utc),
                    output_summary={"deferred_until": _iso(deferred_until),
                                    "expires_at": _iso(expires_at)},
                )
                await conn.execute(text(
                    "UPDATE execution_traces SET status='success', completed_at=:now, "
                    "notes='queued_for_open' WHERE trace_id=:tid"
                ), {"tid": trace_id, "now": datetime.now(timezone.utc)})
            return TradeAttemptResponse(
                status="deferred", order_id=order_id, ticker=ticker, action=action,
                side=side, qty=qty, notional=notional, risk_approved=True,
                risk_reason=reason, risk_check_id=check_id, trace_id=trace_id,
                deferred_until=_iso(deferred_until), reason="queued for market open",
            )

        # ── Step 6: submit to Alpaca ──────────────────────────────────────────
        if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
            err = "Alpaca credentials not configured"
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE alpaca_orders SET status='failed', error_message=:err "
                         "WHERE id=:id"),
                    {"id": order_id, "err": err},
                )
                await _log_step(
                    conn, trace_id, "submit_alpaca", "skipped",
                    datetime.now(timezone.utc), error_message=err,
                )
                await conn.execute(
                    text("UPDATE execution_traces SET status='failed', completed_at=:now, "
                         "notes='no_credentials' WHERE trace_id=:tid"),
                    {"tid": trace_id, "now": datetime.now(timezone.utc)},
                )
            return TradeAttemptResponse(
                status="failed", order_id=order_id, trace_id=trace_id,
                ticker=ticker, action=action, side=side, qty=qty, notional=notional,
                risk_approved=True, risk_reason=reason, risk_check_id=check_id,
                reason=err,
            )

        t0 = datetime.now(timezone.utc)
        qty_str = str(int(qty)) if qty >= 1 else str(qty)
        alpaca_payload = {
            "symbol": ticker, "qty": qty_str, "side": side,
            "type": "market", "time_in_force": time_in_force,
        }
        try:
            # Single submission entrypoint (shared with the deferred-order worker):
            # exits route to close-position, everything else to /v2/orders.
            alpaca_order_id, alpaca_status, alpaca_err = await _submit_for_action(
                action, ticker, alpaca_payload
            )
        except Exception as exc:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE alpaca_orders SET status='failed', error_message=:err "
                         "WHERE id=:id"),
                    {"id": order_id, "err": f"Alpaca request failed: {exc}"[:1000]},
                )
                await _log_step(
                    conn, trace_id, "submit_alpaca", "failed", t0,
                    input_summary=alpaca_payload, error_message=str(exc),
                )
                await conn.execute(
                    text("UPDATE execution_traces SET status='failed', completed_at=:now, "
                         "notes='alpaca_unreachable' WHERE trace_id=:tid"),
                    {"tid": trace_id, "now": datetime.now(timezone.utc)},
                )
            return TradeAttemptResponse(
                status="failed", order_id=order_id, trace_id=trace_id,
                ticker=ticker, action=action, side=side, qty=qty, notional=notional,
                risk_approved=True, risk_reason=reason, risk_check_id=check_id,
                reason=f"Alpaca request failed: {exc}",
            )

        if alpaca_err is not None:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE alpaca_orders SET status='failed', error_message=:err "
                         "WHERE id=:id"),
                    {"id": order_id, "err": alpaca_err},
                )
                await _log_step(
                    conn, trace_id, "submit_alpaca", "failed", t0,
                    input_summary=alpaca_payload, error_message=alpaca_err,
                )
                await conn.execute(
                    text("UPDATE execution_traces SET status='failed', completed_at=:now, "
                         "notes='alpaca_error' WHERE trace_id=:tid"),
                    {"tid": trace_id, "now": datetime.now(timezone.utc)},
                )
            return TradeAttemptResponse(
                status="failed", order_id=order_id, trace_id=trace_id,
                ticker=ticker, action=action, side=side, qty=qty, notional=notional,
                risk_approved=True, risk_reason=reason, risk_check_id=check_id,
                reason=alpaca_err,
            )

        # Success
        submitted_at = datetime.now(timezone.utc)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE alpaca_orders SET status='submitted', "
                    "alpaca_order_id=:aid, alpaca_status=:astatus, submitted_at=:s "
                    "WHERE id=:id"
                ),
                {
                    "id": order_id, "aid": alpaca_order_id,
                    "astatus": alpaca_status, "s": submitted_at,
                },
            )
            await _log_step(
                conn, trace_id, "submit_alpaca", "success", t0,
                input_summary=alpaca_payload,
                output_summary={
                    "alpaca_order_id": alpaca_order_id,
                    "alpaca_status": alpaca_status,
                },
            )
            await conn.execute(
                text("UPDATE execution_traces SET status='success', completed_at=:now "
                     "WHERE trace_id=:tid"),
                {"tid": trace_id, "now": submitted_at},
            )

        return TradeAttemptResponse(
            status="submitted", order_id=order_id, alpaca_order_id=alpaca_order_id,
            alpaca_status=alpaca_status, ticker=ticker, action=action, side=side,
            qty=qty, notional=notional, risk_approved=True, risk_reason=reason,
            risk_check_id=check_id, trace_id=trace_id,
        )

    except HTTPException as http_exc:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE execution_traces SET status='failed', completed_at=:now, "
                    "notes=:notes WHERE trace_id=:tid"
                ),
                {
                    "tid": trace_id,
                    "now": datetime.now(timezone.utc),
                    "notes": f"http_{http_exc.status_code}",
                },
            )
        raise
    except Exception as exc:
        logger.exception("submit_order failed for intent_id=%s", req.intent_id)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE execution_traces SET status='failed', completed_at=:now, "
                    "notes='unexpected_error' WHERE trace_id=:tid"
                ),
                {"tid": trace_id, "now": datetime.now(timezone.utc)},
            )
        raise HTTPException(status_code=500, detail=f"Trade approval failed: {exc}")


async def _record_order(
    conn, *, order_id: str, intent_id: str, ticker: str, action: str, side: str,
    qty: float, notional: float, mode: str, trace_id: str,
    risk_approved: bool, risk_reason: str, risk_check_id: Optional[str],
    status: str, order_type: str = "market", time_in_force: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Insert (or audit) an alpaca_orders row."""
    if time_in_force is None:
        time_in_force = "day"
    await conn.execute(
        text(
            """
            INSERT INTO alpaca_orders (
                id, intent_id, ticker, action, side, qty, notional,
                order_type, time_in_force, status, mode,
                risk_approved, risk_reason, risk_check_id, trace_id,
                error_message, created_at
            ) VALUES (
                :id, :intent_id, :ticker, :action, :side, :qty, :notional,
                :order_type, :time_in_force, :status, :mode,
                :risk_approved, :risk_reason, :risk_check_id, :trace_id,
                :error_message, NOW()
            )
            """
        ),
        {
            "id": order_id, "intent_id": intent_id, "ticker": ticker,
            "action": action, "side": side, "qty": qty, "notional": notional,
            "order_type": order_type, "time_in_force": time_in_force,
            "status": status, "mode": mode, "risk_approved": risk_approved,
            "risk_reason": risk_reason[:1000] if risk_reason else "",
            "risk_check_id": risk_check_id, "trace_id": trace_id,
            "error_message": error_message[:1000] if error_message else None,
        },
    )


class CancelAllResponse(BaseModel):
    status: str
    alpaca_cancel_count: int
    alpaca_errors: list[dict[str, Any]]
    local_orders_updated: int
    trace_id: Optional[str] = None
    reason: Optional[str] = None


@app.post("/jobs/cancel-all-orders", response_model=CancelAllResponse)
async def cancel_all_orders(confirm: str = "") -> CancelAllResponse:
    """Cancel every open order at Alpaca and mark local rows as canceled.

    Operational tool for freeing up buying_power that's reserved by queued
    or pending MOO orders. Calls Alpaca's `DELETE /v2/orders` (multi-status)
    and updates local `alpaca_orders` rows whose status is in
    ('pending','submitted','accepted','new','partially_filled') to 'canceled'.

    Safety:
      - Requires `?confirm=yes` query param to avoid accidental wipes
      - Short-circuits with `no_credentials` if ALPACA_API_KEY is unset
      - Records one execution_traces row + one execution_steps audit

    Returns 207-style summary: how many Alpaca cancels, how many local rows
    updated, plus any per-order errors from Alpaca's response.
    """
    if confirm != "yes":
        raise HTTPException(
            status_code=400,
            detail="Refusing to cancel-all without ?confirm=yes — this would "
                   "delete every queued/pending order at Alpaca.",
        )

    trace_id = str(uuid.uuid4())
    t0 = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO execution_traces (trace_id, job_type, status, started_at) "
                 "VALUES (:tid, 'cancel_all_orders', 'running', :now)"),
            {"tid": trace_id, "now": t0},
        )

    # Short-circuit when credentials are missing (test / paper-trade-only setups)
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
        async with engine.begin() as conn:
            await _log_step(
                conn, trace_id, "alpaca_cancel_all", "skipped", t0,
                error_message="Alpaca credentials not configured",
            )
            await conn.execute(
                text("UPDATE execution_traces SET status='failed', completed_at=:now, "
                     "notes='no_credentials' WHERE trace_id=:tid"),
                {"tid": trace_id, "now": datetime.now(timezone.utc)},
            )
        return CancelAllResponse(
            status="no_credentials", alpaca_cancel_count=0,
            alpaca_errors=[], local_orders_updated=0,
            trace_id=trace_id, reason="Alpaca credentials not configured",
        )

    # ── Call Alpaca DELETE /v2/orders ────────────────────────────────────────
    alpaca_results: list[dict[str, Any]] = []
    alpaca_errors: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(
                f"{ALPACA_BASE_URL}/v2/orders",
                headers={
                    "APCA-API-KEY-ID": ALPACA_API_KEY,
                    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
                },
            )
        # Alpaca returns 207 multi-status with a list of {id, status} items
        if resp.status_code in (200, 207):
            try:
                alpaca_results = resp.json()
                if not isinstance(alpaca_results, list):
                    alpaca_results = []
            except Exception:
                alpaca_results = []
            for r in alpaca_results:
                code = r.get("status") if isinstance(r, dict) else None
                # 2xx → success, anything else → record as error
                if code is None or not (200 <= int(code) < 300):
                    alpaca_errors.append({"id": r.get("id"), "status": code, "body": r.get("body")})
            cancel_count = len(alpaca_results) - len(alpaca_errors)
        else:
            cancel_count = 0
            alpaca_errors.append({"http_status": resp.status_code, "body": resp.text[:500]})
    except Exception as exc:
        cancel_count = 0
        alpaca_errors.append({"error": str(exc)[:500]})

    # ── Update local rows ────────────────────────────────────────────────────
    open_statuses = ("pending", "submitted", "accepted", "new", "partially_filled")
    async with engine.begin() as conn:
        result = await conn.execute(
            text("UPDATE alpaca_orders SET status='canceled', "
                 "error_message=COALESCE(error_message, '') || ' [canceled by /jobs/cancel-all-orders]' "
                 "WHERE status = ANY(:open)"),
            {"open": list(open_statuses)},
        )
        local_updated = result.rowcount or 0
        await _log_step(
            conn, trace_id, "alpaca_cancel_all", "success", t0,
            input_summary={"open_statuses": list(open_statuses)},
            output_summary={
                "alpaca_cancel_count": cancel_count,
                "alpaca_errors": alpaca_errors[:10],   # cap audit row size
                "local_orders_updated": local_updated,
            },
        )
        await conn.execute(
            text("UPDATE execution_traces SET status='success', completed_at=:now "
                 "WHERE trace_id=:tid"),
            {"tid": trace_id, "now": datetime.now(timezone.utc)},
        )

    return CancelAllResponse(
        status="ok" if not alpaca_errors else "partial",
        alpaca_cancel_count=cancel_count,
        alpaca_errors=alpaca_errors[:20],
        local_orders_updated=local_updated,
        trace_id=trace_id,
    )


@app.get("/orders/recent")
async def recent_orders() -> list[dict[str, Any]]:
    """Return the 20 most recently created orders."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT
                    id, intent_id, alpaca_order_id, ticker, action, side,
                    qty, notional, order_type, time_in_force, status, mode,
                    risk_approved, risk_reason, risk_check_id, trace_id,
                    alpaca_status, submitted_at, filled_at, avg_fill_price,
                    filled_qty, error_message, created_at
                FROM alpaca_orders
                ORDER BY created_at DESC
                LIMIT 20
                """
            )
        )
        rows = result.mappings().all()
    return [
        {
            "id":              str(r["id"]),
            "intent_id":       str(r["intent_id"]) if r["intent_id"] else None,
            "alpaca_order_id": r["alpaca_order_id"],
            "ticker":          r["ticker"],
            "action":          r["action"],
            "side":            r["side"],
            "qty":             _f(r["qty"]),
            "notional":        _f(r["notional"]),
            "order_type":      r["order_type"],
            "time_in_force":   r["time_in_force"],
            "status":          r["status"],
            "mode":            r["mode"],
            "risk_approved":   r["risk_approved"],
            "risk_reason":     r["risk_reason"],
            "risk_check_id":   str(r["risk_check_id"]) if r["risk_check_id"] else None,
            "trace_id":        str(r["trace_id"]) if r["trace_id"] else None,
            "alpaca_status":   r["alpaca_status"],
            "submitted_at":    _iso(r["submitted_at"]),
            "filled_at":       _iso(r["filled_at"]),
            "avg_fill_price":  _f(r["avg_fill_price"]),
            "filled_qty":      _f(r["filled_qty"]),
            "error_message":   r["error_message"],
            "created_at":      _iso(r["created_at"]),
        }
        for r in rows
    ]


@app.get("/health")
async def health() -> dict:
    has_credentials = bool(ALPACA_API_KEY and ALPACA_SECRET_KEY)
    return {
        "status": "ok",
        "service": "trade-executor",
        "has_credentials": has_credentials,
    }
