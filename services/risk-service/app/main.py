import os
import uuid
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from stock_strategy_shared.db import wait_for_db, warm_up_db_in_background

# ── Environment variables ────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")

# These constants exist for backward-compat with tests that monkeypatch them.
# At runtime, _safety_env() re-reads os.environ on every /check call so
# operators can flip KILL_SWITCH without restarting the container.
KILL_SWITCH = os.getenv("KILL_SWITCH", "false").lower() == "true"
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
try:
    MAX_ORDER_NOTIONAL = float(os.getenv("MAX_ORDER_NOTIONAL", "50000.0"))
except ValueError:
    MAX_ORDER_NOTIONAL = 50000.0
PAPER_ONLY = os.getenv("PAPER_ONLY", "true").lower() == "true"


_KILL_SWITCH_FILE = "/tmp/kill_switch"

def _safety_env() -> dict:
    """Re-read safety env vars on every /check call.

    os.getenv() reads the process environment which is frozen at container
    startup and cannot be changed by `docker exec -e`. To hot-flip the kill
    switch without a restart, create or remove the control file:

        docker exec stocker-risk-service-1 touch /tmp/kill_switch   # ON
        docker exec stocker-risk-service-1 rm    /tmp/kill_switch   # OFF

    The file takes precedence over the KILL_SWITCH env var when present.
    Tests should override via monkeypatch.setenv/os.environ mutation —
    module-level constants are kept as the startup snapshot for visibility
    but are not consulted here.
    """
    kill_switch_env = os.getenv("KILL_SWITCH", "false").lower() == "true"
    kill_switch = os.path.exists(_KILL_SWITCH_FILE) or kill_switch_env
    return {
        "kill_switch": kill_switch,
        "live_trading_enabled":
            os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true",
        "paper_only": os.getenv("PAPER_ONLY", "true").lower() == "true",
        "max_order_notional": float(os.getenv("MAX_ORDER_NOTIONAL", "50000.0")),
    }


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


async def _persist_decision(req: TradeCheckRequest, *, approved: bool, reason: str,
                            rule: str, env: dict) -> str:
    """Insert a risk_decisions row. Returns the decision_id (which becomes check_id).

    If the persist fails and the decision is APPROVED, this raises — the
    /check endpoint returns 503 to the trade-executor so a trade never
    proceeds without an audit row. Rejection persistence failures are logged
    but do not block the rejection from reaching the caller.
    """
    decision_id = str(uuid.uuid4())
    if engine is None:
        if approved:
            raise HTTPException(
                status_code=503,
                detail="risk-service: no DB engine — refusing to approve without audit",
            )
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
                    "kill_switch": env["kill_switch"],
                    "paper_only": env["paper_only"],
                    "live_trading_enabled": env["live_trading_enabled"],
                    "max_order_notional": env["max_order_notional"],
                },
            )
    except HTTPException:
        raise
    except Exception as exc:
        msg = f"failed to persist decision {decision_id}: {exc}"
        print(f"[risk-service] WARN: {msg}")
        if approved:
            raise HTTPException(
                status_code=503,
                detail=f"risk-service: {msg} — refusing to approve without audit",
            )
    return decision_id


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app_: FastAPI):
    global engine
    if DATABASE_URL:
        engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=3,
                                     connect_args={"timeout": 60})
        # Warm up the DB in the background — see warm_up_db_in_background docstring.
        # Blocking here would mean uvicorn doesn't accept /health until the ping
        # succeeds, causing the docker healthcheck (start_period=20s, ~45s total)
        # to fail on slow NAS hardware and trigger a restart loop.
        warm_up_db_in_background(engine, "risk-service")
    else:
        print("[risk-service] DATABASE_URL not set; decisions will NOT be persisted (degraded mode)")
    yield
    if engine is not None:
        await engine.dispose()


# ── Application ──────────────────────────────────────────────────────────────

app = FastAPI(title="risk-service", lifespan=lifespan)


# ── Endpoints ────────────────────────────────────────────────────────────────


async def _decide(req: TradeCheckRequest) -> tuple[bool, str, str, dict]:
    """Run rules in order; return (approved, reason, rule_triggered, env_snapshot)."""
    env = _safety_env()
    if env["kill_switch"]:
        return False, "Kill switch is active", "kill_switch", env
    if req.trade_type == "live" and not env["live_trading_enabled"]:
        return (
            False,
            "Live trading is not enabled; set LIVE_TRADING_ENABLED=true",
            "live_disabled",
            env,
        )
    if env["paper_only"] and req.trade_type == "live":
        return False, "Paper-only mode is active", "paper_only", env
    if req.qty <= 0:
        return False, "Invalid qty: must be > 0", "qty", env
    if req.notional <= 0:
        return False, "Invalid notional: must be > 0", "notional_zero", env
    if req.notional > env["max_order_notional"]:
        return (
            False,
            f"Order notional ${req.notional:.2f} exceeds limit ${env['max_order_notional']:.2f}",
            "notional_limit",
            env,
        )
    return True, "All risk checks passed", "ok", env


@app.post("/check", response_model=TradeCheckResponse)
async def check_trade(req: TradeCheckRequest) -> TradeCheckResponse:
    """Validate a proposed trade against safety rules.

    Each call is persisted to risk_decisions for audit. Returns a `check_id`
    which is the decision_id — alpaca_orders.risk_check_id references it.
    """
    approved, reason, rule, env = await _decide(req)
    decision_id = await _persist_decision(req, approved=approved, reason=reason, rule=rule, env=env)
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
