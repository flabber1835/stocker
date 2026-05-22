"""Trade executor — the only service permitted to submit Alpaca orders.

End-to-end responsibility for the approval click:
  1. Load delta intent (intent_id → ticker, action, weight)
  2. Size the order (entries: account_value × weight ÷ price; exits: full position)
  3. Call risk-service /check
  4. Persist alpaca_orders + execution_steps audit
  5. If risk-approved and credentials present: POST to Alpaca /v2/orders

Every approval click produces one execution_trace row with step-by-step audit so
the dashboard's trace viewer shows exactly why a trade was approved/rejected.
"""
import json
import logging
import math
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from stock_strategy_shared.db import wait_for_db

logger = logging.getLogger("trade-executor")
logging.basicConfig(level=logging.INFO)

# ── Environment variables ────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
RISK_SERVICE_URL = os.getenv("RISK_SERVICE_URL", "http://risk-service:8000")
EXIT_SYNC_MAX_AGE_HOURS = float(os.getenv("EXIT_SYNC_MAX_AGE_HOURS", "24"))
DEFAULT_MAX_POSITIONS = int(os.getenv("DEFAULT_MAX_POSITIONS", "30"))

engine: Optional[AsyncEngine] = None


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(application: FastAPI):
    global engine
    if not DATABASE_URL:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")
    engine = create_async_engine(DATABASE_URL, echo=False)
    await wait_for_db(engine)
    has_creds = bool(ALPACA_API_KEY and ALPACA_SECRET_KEY)
    logger.info(
        "Alpaca credentials: %s", "present" if has_creds else "NOT SET — orders will be rejected"
    )
    yield
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
    status: str           # 'submitted'|'risk_rejected'|'failed'|'duplicate'
    order_id: Optional[str] = None
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
        "SELECT id, ticker, action, rank, composite_score, current_weight "
        "FROM delta_intents WHERE id = :iid"
    ), {"iid": intent_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Intent {intent_id} not found")
    if row["action"] not in ("entry", "exit"):
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

    qty = floor(account_value × target_weight ÷ last_price). Refuses with 400
    when the target notional is less than the price of one share — silently
    rounding up to 1 share would massively overweight the position.
    """
    # Target weight: intent.current_weight (preferred) → portfolio_holdings → 1/DEFAULT_MAX_POSITIONS
    weight = intent_weight
    if weight is None or weight <= 0:
        ph = (await conn.execute(text(
            "SELECT ph.weight FROM portfolio_holdings ph "
            "JOIN portfolio_runs pr ON pr.run_id = ph.run_id "
            "WHERE ph.ticker = :t AND pr.status = 'success' "
            "ORDER BY pr.completed_at DESC NULLS LAST LIMIT 1"
        ), {"t": ticker})).mappings().first()
        if ph:
            weight = _f(ph["weight"])
    weight_source = (
        "intent" if intent_weight is not None and intent_weight > 0
        else ("portfolio_holdings" if weight else "default")
    )
    if not weight or weight <= 0:
        weight = 1.0 / DEFAULT_MAX_POSITIONS

    # Account value from latest successful sync. Refuse if older than
    # EXIT_SYNC_MAX_AGE_HOURS so a stale account_value can't size a wildly
    # wrong order (same threshold as _size_exit's position-staleness check).
    acct = (await conn.execute(text(
        "SELECT account_value, completed_at FROM alpaca_sync_runs "
        "WHERE status='success' ORDER BY completed_at DESC NULLS LAST LIMIT 1"
    ))).mappings().first()
    account_value = _f(acct["account_value"]) if acct else None
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

    if account_value is None or last_price is None or last_price <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot compute qty for {ticker}: "
                f"account_value={account_value}, last_price={last_price}"
            ),
        )

    target_notional = account_value * weight
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
        "sync_age_hours": round(sync_age_hours, 2) if sync_age_hours is not None else None,
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


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.post("/jobs/submit", response_model=TradeAttemptResponse)
async def submit_order(req: SubmitOrderRequest) -> TradeAttemptResponse:
    """Orchestrate the full approval flow for one delta intent.

    Steps (each persisted to execution_steps):
      load_intent → size_order → risk_check → submit_alpaca
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
                "WHERE intent_id = :iid AND status IN ('pending','submitted') "
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
        side = "buy" if action == "entry" else "sell"

        # ── Step 3: size order ────────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        async with engine.connect() as conn:
            if action == "exit":
                qty, notional, sizing_summary = await _size_exit(conn, ticker)
            else:
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
        risk_payload = {
            "ticker": ticker, "action": action, "side": side,
            "qty": qty, "notional": notional,
            "mode": req.mode, "trade_type": "paper",
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
        time_in_force = "opg" if req.mode == "scheduled" else "day"
        initial_status = "pending" if approved else "risk_rejected"
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
            alpaca_order_id, alpaca_status, alpaca_err = await _submit_to_alpaca(alpaca_payload)
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
        time_in_force = "opg" if mode == "scheduled" else "day"
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
