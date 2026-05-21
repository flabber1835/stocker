import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger("trade-executor")
logging.basicConfig(level=logging.INFO)

# ── Environment variables ────────────────────────────────────────────────────

DATABASE_URL = os.environ["DATABASE_URL"]
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# ── DB helpers ───────────────────────────────────────────────────────────────

engine: AsyncEngine = create_async_engine(DATABASE_URL, echo=False)


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
    await wait_for_db(engine)
    has_creds = bool(ALPACA_API_KEY and ALPACA_SECRET_KEY)
    logger.info(
        "Alpaca credentials: %s", "present" if has_creds else "NOT SET — orders will fail"
    )
    yield
    await engine.dispose()


# ── Application ──────────────────────────────────────────────────────────────

app = FastAPI(title="trade-executor", lifespan=lifespan)


# ── Pydantic models ──────────────────────────────────────────────────────────


class SubmitOrderRequest(BaseModel):
    intent_id: Optional[str] = None   # delta_intents.id (UUID string), nullable
    ticker: str
    action: str        # "entry" or "exit"
    side: str          # "buy" or "sell"
    qty: float
    mode: str          # "immediate" or "scheduled"
    risk_check_id: str # from risk-service /check response
    risk_approved: bool
    risk_reason: str


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.post("/jobs/submit")
async def submit_order(req: SubmitOrderRequest) -> dict[str, Any]:
    """Validate, persist, and (if approved) submit an order to Alpaca."""

    # 1. Validate action / side
    if req.action not in ("entry", "exit"):
        raise HTTPException(status_code=422, detail="action must be 'entry' or 'exit'")
    if req.side not in ("buy", "sell"):
        raise HTTPException(status_code=422, detail="side must be 'buy' or 'sell'")

    # 2. Compute order params
    order_type = "market"
    time_in_force = "opg" if req.mode == "scheduled" else "day"

    order_id = str(uuid.uuid4())
    intent_id = req.intent_id  # may be None

    # 3. Insert pending row
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO alpaca_orders (
                    id, intent_id, ticker, action, side, qty,
                    order_type, time_in_force, status, mode,
                    risk_approved, risk_reason, created_at
                ) VALUES (
                    :id, :intent_id, :ticker, :action, :side, :qty,
                    :order_type, :time_in_force, 'pending', :mode,
                    :risk_approved, :risk_reason, NOW()
                )
                """
            ),
            {
                "id": order_id,
                "intent_id": intent_id,
                "ticker": req.ticker,
                "action": req.action,
                "side": req.side,
                "qty": req.qty,
                "order_type": order_type,
                "time_in_force": time_in_force,
                "mode": req.mode,
                "risk_approved": req.risk_approved,
                "risk_reason": req.risk_reason,
            },
        )

    # 4. Risk rejected — update status and return early
    if not req.risk_approved:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE alpaca_orders SET status='risk_rejected' WHERE id=:id"
                ),
                {"id": order_id},
            )
        return {
            "status": "risk_rejected",
            "reason": req.risk_reason,
            "order_id": order_id,
        }

    # 5. Build Alpaca order payload
    qty_str = str(round(req.qty)) if req.qty >= 1 else str(req.qty)
    alpaca_payload = {
        "symbol": req.ticker,
        "qty": qty_str,
        "side": req.side,
        "type": "market",
        "time_in_force": time_in_force,
    }

    # 6. POST to Alpaca
    alpaca_order_id: Optional[str] = None
    alpaca_status: Optional[str] = None

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

        if resp.status_code in (200, 201):
            # 7. Success
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
        else:
            # 8. Alpaca returned an error
            error_text = resp.text
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        """
                        UPDATE alpaca_orders
                        SET status='failed', error_message=:error_message
                        WHERE id=:id
                        """
                    ),
                    {"id": order_id, "error_message": error_text},
                )
            return {
                "status": "failed",
                "order_id": order_id,
                "alpaca_order_id": None,
                "alpaca_status": None,
            }

    except Exception as exc:
        # Network or unexpected error
        error_text = str(exc)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE alpaca_orders
                    SET status='failed', error_message=:error_message
                    WHERE id=:id
                    """
                ),
                {"id": order_id, "error_message": error_text},
            )
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

    return [dict(row) for row in rows]


@app.get("/health")
async def health() -> dict:
    has_credentials = bool(ALPACA_API_KEY and ALPACA_SECRET_KEY)
    return {
        "status": "ok",
        "service": "trade-executor",
        "has_credentials": has_credentials,
    }
