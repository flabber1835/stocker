import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# ── Environment variables ────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")
KILL_SWITCH = os.getenv("KILL_SWITCH", "false").lower() == "true"
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
MAX_ORDER_NOTIONAL = float(os.getenv("MAX_ORDER_NOTIONAL", "50000.0"))
PAPER_ONLY = os.getenv("PAPER_ONLY", "true").lower() == "true"

engine: Optional[AsyncEngine] = None

# ── Pydantic models ──────────────────────────────────────────────────────────


class TradeCheckRequest(BaseModel):
    ticker: str
    action: Literal["entry", "exit"]
    side: Literal["buy", "sell"]
    qty: float
    notional: float
    mode: Literal["immediate", "scheduled"]
    trade_type: Literal["paper", "live"] = "paper"


class TradeCheckResponse(BaseModel):
    approved: bool
    reason: str
    check_id: str           # also the risk_decisions.decision_id
    rule_triggered: str     # 'kill_switch' | 'live_disabled' | 'paper_only' | 'qty' | 'notional_zero' | 'notional_limit' | 'ok'


# ── Database helpers ─────────────────────────────────────────────────────────


async def _wait_for_db(eng: AsyncEngine, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with eng.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception:
            await asyncio.sleep(2)
    raise RuntimeError("DB not available after timeout")


async def _persist_decision(req: TradeCheckRequest, *, approved: bool, reason: str,
                            rule: str) -> str:
    """Insert a risk_decisions row. Returns the decision_id (which becomes check_id).

    If DB is unavailable (e.g. during test setup with no DB), falls back to a
    generated UUID with no persistence — the caller still gets a check_id but
    there is no audit trail. This keeps risk-service callable in degraded mode.
    """
    decision_id = str(uuid.uuid4())
    if engine is None:
        return decision_id
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO risk_decisions (
                        decision_id, ticker, action, side, qty, notional, mode,
                        trade_type, approved, rule_triggered, reason,
                        kill_switch, paper_only, live_trading_enabled, max_order_notional
                    ) VALUES (
                        :decision_id, :ticker, :action, :side, :qty, :notional, :mode,
                        :trade_type, :approved, :rule, :reason,
                        :kill_switch, :paper_only, :live_trading_enabled, :max_order_notional
                    )
                    """
                ),
                {
                    "decision_id": decision_id,
                    "ticker": req.ticker,
                    "action": req.action,
                    "side": req.side,
                    "qty": req.qty,
                    "notional": req.notional,
                    "mode": req.mode,
                    "trade_type": req.trade_type,
                    "approved": approved,
                    "rule": rule,
                    "reason": reason,
                    "kill_switch": KILL_SWITCH,
                    "paper_only": PAPER_ONLY,
                    "live_trading_enabled": LIVE_TRADING_ENABLED,
                    "max_order_notional": MAX_ORDER_NOTIONAL,
                },
            )
    except Exception as exc:
        print(f"[risk-service] WARN: failed to persist decision {decision_id}: {exc}")
    return decision_id


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app_: FastAPI):
    global engine
    if DATABASE_URL:
        engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=5)
        await _wait_for_db(engine)
        print("[risk-service] DB connected; decisions will be persisted to risk_decisions")
    else:
        print("[risk-service] DATABASE_URL not set; decisions will NOT be persisted (degraded mode)")
    yield
    if engine is not None:
        await engine.dispose()


# ── Application ──────────────────────────────────────────────────────────────

app = FastAPI(title="risk-service", lifespan=lifespan)


# ── Endpoints ────────────────────────────────────────────────────────────────


async def _decide(req: TradeCheckRequest) -> tuple[bool, str, str]:
    """Run rules in order; return (approved, reason, rule_triggered)."""
    if KILL_SWITCH:
        return False, "Kill switch is active", "kill_switch"
    if req.trade_type == "live" and not LIVE_TRADING_ENABLED:
        return (
            False,
            "Live trading is not enabled; set LIVE_TRADING_ENABLED=true",
            "live_disabled",
        )
    if PAPER_ONLY and req.trade_type == "live":
        return False, "Paper-only mode is active", "paper_only"
    if req.qty <= 0:
        return False, "Invalid qty: must be > 0", "qty"
    if req.notional <= 0:
        return False, "Invalid notional: must be > 0", "notional_zero"
    if req.notional > MAX_ORDER_NOTIONAL:
        return (
            False,
            f"Order notional ${req.notional:.2f} exceeds limit ${MAX_ORDER_NOTIONAL:.2f}",
            "notional_limit",
        )
    return True, "All risk checks passed", "ok"


@app.post("/check", response_model=TradeCheckResponse)
async def check_trade(req: TradeCheckRequest) -> TradeCheckResponse:
    """Validate a proposed trade against safety rules.

    Each call is persisted to risk_decisions for audit. Returns a `check_id`
    which is the decision_id — alpaca_orders.risk_check_id references it.
    """
    approved, reason, rule = await _decide(req)
    decision_id = await _persist_decision(req, approved=approved, reason=reason, rule=rule)
    return TradeCheckResponse(
        approved=approved,
        reason=reason,
        check_id=decision_id,
        rule_triggered=rule,
    )


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "risk-service",
        "kill_switch": KILL_SWITCH,
        "paper_only": PAPER_ONLY,
        "live_trading_enabled": LIVE_TRADING_ENABLED,
        "max_order_notional": MAX_ORDER_NOTIONAL,
        "persistence": engine is not None,
    }
