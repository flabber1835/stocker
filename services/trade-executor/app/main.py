import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger("trade-executor")
logging.basicConfig(level=logging.INFO)

# ── Environment variables ────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

engine: Optional[AsyncEngine] = None


async def wait_for_db(eng: AsyncEngine, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with eng.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database is ready.")
            return
        except Exception as exc:
            logger.warning("DB not ready yet (%s), retrying in 2s…", exc)
            await asyncio.sleep(2)
    raise RuntimeError("DB not available after timeout")


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


# ── Application ──────────────────────────────────────────────────────────────

app = FastAPI(title="trade-executor", lifespan=lifespan)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def _iso(v) -> Optional[str]:
    return v.isoformat() if v and hasattr(v, "isoformat") else None


# ── Pydantic models ──────────────────────────────────────────────────────────


class SubmitOrderRequest(BaseModel):
    intent_id: Optional[str] = None   # delta_intents.id (UUID string), nullable
    ticker: str
    action: Literal["entry", "exit"]
    side: Literal["buy", "sell"]
    qty: float
    notional: Optional[float] = None  # estimated dollar value at submission time
    mode: Literal["immediate", "scheduled"]
    risk_check_id: str
    risk_approved: bool
    risk_reason: str


# ── Endpoints ────────────────────────────────────────────────────────────────


async def _mark_failed(order_id: str, error_message: str) -> None:
    """Update an alpaca_orders row to status='failed' with an error message."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE alpaca_orders SET status='failed', error_message=:err "
                "WHERE id=:id"
            ),
            {"id": order_id, "err": error_message[:1000]},
        )


@app.post("/jobs/submit")
async def submit_order(req: SubmitOrderRequest) -> dict[str, Any]:
    """Validate, persist, and (if approved) submit an order to Alpaca."""

    order_type = "market"
    time_in_force = "opg" if req.mode == "scheduled" else "day"
    order_id = str(uuid.uuid4())

    # Idempotency guard: refuse if this intent already has an open or submitted order.
    # The DB also has a partial unique index, but checking here gives a cleaner response.
    if req.intent_id is not None:
        async with engine.connect() as conn:
            row = (await conn.execute(
                text(
                    "SELECT id, status FROM alpaca_orders "
                    "WHERE intent_id = :iid AND status IN ('pending','submitted') "
                    "LIMIT 1"
                ),
                {"iid": req.intent_id},
            )).first()
        if row is not None:
            return {
                "status": "duplicate",
                "reason": f"Intent {req.intent_id} already has an open order ({row.status})",
                "order_id": str(row.id),
                "alpaca_order_id": None,
                "alpaca_status": None,
            }

    # Insert audit row up front. Status reflects the outcome so we don't have a
    # 'pending' → 'risk_rejected' window where a duplicate INSERT can race.
    initial_status = "pending" if req.risk_approved else "risk_rejected"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO alpaca_orders (
                    id, intent_id, ticker, action, side, qty, notional,
                    order_type, time_in_force, status, mode,
                    risk_approved, risk_reason, created_at
                ) VALUES (
                    :id, :intent_id, :ticker, :action, :side, :qty, :notional,
                    :order_type, :time_in_force, :status, :mode,
                    :risk_approved, :risk_reason, NOW()
                )
                """
            ),
            {
                "id": order_id,
                "intent_id": req.intent_id,
                "ticker": req.ticker,
                "action": req.action,
                "side": req.side,
                "qty": req.qty,
                "notional": req.notional,
                "order_type": order_type,
                "time_in_force": time_in_force,
                "status": initial_status,
                "mode": req.mode,
                "risk_approved": req.risk_approved,
                "risk_reason": req.risk_reason,
            },
        )

    if not req.risk_approved:
        return {
            "status": "risk_rejected",
            "reason": req.risk_reason,
            "order_id": order_id,
            "alpaca_order_id": None,
            "alpaca_status": None,
        }

    # Short-circuit when Alpaca credentials are missing — never hit the API
    # with empty headers (every call would burn a 'failed' row otherwise).
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
        await _mark_failed(order_id, "Alpaca credentials not configured")
        return {
            "status": "failed",
            "order_id": order_id,
            "alpaca_order_id": None,
            "alpaca_status": None,
            "reason": "Alpaca credentials not configured",
        }

    # Alpaca paper trading accepts integer qty for "market" orders.
    qty_str = str(int(req.qty)) if req.qty >= 1 else str(req.qty)
    alpaca_payload = {
        "symbol": req.ticker,
        "qty": qty_str,
        "side": req.side,
        "type": "market",
        "time_in_force": time_in_force,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{ALPACA_BASE_URL}/v2/orders",
                json=alpaca_payload,
                headers={
                    "APCA-API-KEY-ID": ALPACA_API_KEY,
                    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
                },
            )
    except Exception as exc:
        await _mark_failed(order_id, f"Alpaca request failed: {exc}")
        return {
            "status": "failed",
            "order_id": order_id,
            "alpaca_order_id": None,
            "alpaca_status": None,
        }

    if resp.status_code in (200, 201):
        resp_data = resp.json()
        alpaca_order_id = resp_data.get("id")
        alpaca_status = resp_data.get("status")
        submitted_at = datetime.now(timezone.utc)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE alpaca_orders
                    SET status='submitted',
                        alpaca_order_id=:alpaca_order_id,
                        alpaca_status=:alpaca_status,
                        submitted_at=:submitted_at
                    WHERE id=:id
                    """
                ),
                {
                    "id": order_id,
                    "alpaca_order_id": alpaca_order_id,
                    "alpaca_status": alpaca_status,
                    "submitted_at": submitted_at,
                },
            )
        return {
            "status": "submitted",
            "order_id": order_id,
            "alpaca_order_id": alpaca_order_id,
            "alpaca_status": alpaca_status,
        }

    await _mark_failed(order_id, resp.text[:1000])
    return {
        "status": "failed",
        "order_id": order_id,
        "alpaca_order_id": None,
        "alpaca_status": None,
    }


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
                    risk_approved, risk_reason, alpaca_status,
                    submitted_at, filled_at, avg_fill_price, filled_qty,
                    error_message, created_at
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
