import os
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

# ── Environment variables ────────────────────────────────────────────────────

KILL_SWITCH = os.getenv("KILL_SWITCH", "false").lower() == "true"
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
MAX_ORDER_NOTIONAL = float(os.getenv("MAX_ORDER_NOTIONAL", "50000.0"))
PAPER_ONLY = os.getenv("PAPER_ONLY", "true").lower() == "true"

# ── Pydantic models ──────────────────────────────────────────────────────────


class TradeCheckRequest(BaseModel):
    ticker: str
    action: str        # "entry" or "exit"
    side: str          # "buy" or "sell"
    qty: float
    notional: float    # estimated dollar value
    mode: str          # "immediate" or "scheduled"
    trade_type: str = "paper"  # "paper" or "live"


class TradeCheckResponse(BaseModel):
    approved: bool
    reason: str
    check_id: str      # uuid4 string


# ── Application ──────────────────────────────────────────────────────────────

app = FastAPI(title="risk-service")


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.post("/check", response_model=TradeCheckResponse)
async def check_trade(req: TradeCheckRequest) -> TradeCheckResponse:
    """Run safety checks against a proposed trade.

    Checks are evaluated in order; the first failure is returned immediately.
    """
    check_id = str(uuid.uuid4())

    # 1. Kill switch
    if KILL_SWITCH:
        return TradeCheckResponse(
            approved=False,
            reason="Kill switch is active",
            check_id=check_id,
        )

    # 2. Live-trading guard
    if req.trade_type == "live" and not LIVE_TRADING_ENABLED:
        return TradeCheckResponse(
            approved=False,
            reason="Live trading is not enabled; set LIVE_TRADING_ENABLED=true",
            check_id=check_id,
        )

    # 3. Paper-only mode guard
    if PAPER_ONLY and req.trade_type == "live":
        return TradeCheckResponse(
            approved=False,
            reason="Paper-only mode is active",
            check_id=check_id,
        )

    # 4. Quantity must be positive
    if req.qty <= 0:
        return TradeCheckResponse(
            approved=False,
            reason="Invalid qty: must be > 0",
            check_id=check_id,
        )

    # 5. Notional limit
    if req.notional > MAX_ORDER_NOTIONAL:
        return TradeCheckResponse(
            approved=False,
            reason=(
                f"Order notional ${req.notional:.2f} exceeds limit "
                f"${MAX_ORDER_NOTIONAL:.2f}"
            ),
            check_id=check_id,
        )

    # All checks passed
    return TradeCheckResponse(
        approved=True,
        reason="All risk checks passed",
        check_id=check_id,
    )


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "risk-service",
        "kill_switch": KILL_SWITCH,
        "paper_only": PAPER_ONLY,
    }
