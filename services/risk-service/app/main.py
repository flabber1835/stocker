import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator
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


def _safe_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _safe_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# Planned controls — all default to permissive sentinel values so existing
# deployments don't see new rejections without an explicit opt-in by setting
# a stricter env var.
MAX_DAILY_TURNOVER_PCT = _safe_float("MAX_DAILY_TURNOVER_PCT", 0.50)
MAX_DAILY_LOSS_PCT     = _safe_float("MAX_DAILY_LOSS_PCT",     0.10)
MAX_POSITION_PCT       = _safe_float("MAX_POSITION_PCT",       0.15)
MAX_POSITIONS          = _safe_int(  "MAX_POSITIONS",          35)
MAX_DATA_AGE_HOURS     = _safe_float("MAX_DATA_AGE_HOURS",     96.0)
MAX_SYNC_AGE_HOURS     = _safe_float("MAX_SYNC_AGE_HOURS",     24.0)

# Trading-day zone for the daily-loss baseline. The "day" the loss cap resets on
# must be the TRADING day (ET), not the UTC calendar day: CURRENT_DATE in Postgres
# (UTC session) rolls over at ~19:00–20:00 ET, mid-session for late-ET trading, so
# a UTC-day baseline could compare a position against the WRONG day's opening
# equity. We compute the reset date in this zone and pass it as a bound param.
RISK_TZ_NAME = os.getenv("RISK_TZ", "America/New_York")
try:
    from zoneinfo import ZoneInfo
    _RISK_TZ = ZoneInfo(RISK_TZ_NAME)
except Exception:
    _RISK_TZ = None


def _trading_day_today() -> str:
    """Today's calendar date in the trading zone (ET), ISO format. Used as the
    daily-loss baseline reset boundary instead of Postgres CURRENT_DATE (UTC)."""
    if _RISK_TZ is not None:
        return datetime.now(_RISK_TZ).date().isoformat()
    return datetime.now().date().isoformat()


_KILL_SWITCH_FILE = "/tmp/kill_switch"


def _is_kill_switch_active() -> bool:
    """Return True if the kill switch is active (file or env var)."""
    return os.path.exists(_KILL_SWITCH_FILE) or (
        os.getenv("KILL_SWITCH", "false").lower() == "true"
    )


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
    return {
        "kill_switch": _is_kill_switch_active(),
        "live_trading_enabled":
            os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true",
        "paper_only": os.getenv("PAPER_ONLY", "true").lower() == "true",
        "max_order_notional":     _safe_float("MAX_ORDER_NOTIONAL", 50000.0),
        "max_daily_turnover_pct": _safe_float("MAX_DAILY_TURNOVER_PCT", 0.50),
        "max_daily_loss_pct":     _safe_float("MAX_DAILY_LOSS_PCT",  0.10),
        "max_position_pct":       _safe_float("MAX_POSITION_PCT",    0.15),
        "max_positions":          _safe_int(  "MAX_POSITIONS",       35),
        "max_data_age_hours":     _safe_float("MAX_DATA_AGE_HOURS",  96.0),
        "max_sync_age_hours":     _safe_float("MAX_SYNC_AGE_HOURS",  24.0),
    }


engine: Optional[AsyncEngine] = None

# ── Pydantic models ──────────────────────────────────────────────────────────


_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,20}$")


class TradeCheckRequest(BaseModel):
    ticker: str
    action: Literal["entry", "exit", "buy_add", "sell_trim"]
    side: Literal["buy", "sell"]
    qty: float
    notional: float
    mode: Literal["immediate", "scheduled"]
    trade_type: Literal["paper", "live"] = "paper"
    sim_date: Optional[str] = None  # ISO date; if provided, used for turnover cap scoping

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        v = v.upper().strip()
        if not _TICKER_RE.match(v):
            raise ValueError(
                "ticker must be 1-20 uppercase alphanumeric characters (dots and hyphens allowed)"
            )
        return v


class TradeCheckResponse(BaseModel):
    approved: bool
    reason: str
    check_id: str           # also the risk_decisions.decision_id
    rule_triggered: str     # 'kill_switch'|'live_disabled'|'paper_only'|'qty'|
                            # 'notional_zero'|'notional_limit'|'daily_turnover_limit'|
                            # 'daily_loss_limit'|'max_positions_limit'|'max_position_pct_limit'|
                            # 'data_staleness'|'sync_staleness'|'ok'


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

    # ── Planned safety controls (Phase 6+): DB-dependent, defense-in-depth ─────
    # All these queries are wrapped in a single try/except so a transient DB
    # error degrades safely (skip the check, log a warning) rather than blocking
    # legitimate trades. The earlier in-memory checks (kill_switch, qty, etc.)
    # always run regardless of DB health.
    if engine is not None:
        try:
            # Alpaca-availability: refuse ALL actions if the last successful sync
            # is too old. A stale broker view means qty / buying_power / live
            # positions are wrong; sizing decisions made against them could
            # double-spend cash or sell positions we no longer hold.
            max_sync_age = env["max_sync_age_hours"]
            if max_sync_age > 0:
                async with engine.connect() as conn:
                    sync_row = (await conn.execute(text(
                        "SELECT completed_at FROM alpaca_sync_runs "
                        "WHERE status='success' "
                        "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
                    ))).first()
                if sync_row is None or sync_row[0] is None:
                    return (
                        False,
                        "No successful alpaca-sync on record — broker state unknown",
                        "sync_staleness",
                        env,
                    )
                age_h = (datetime.now(timezone.utc) - sync_row[0]).total_seconds() / 3600.0
                if age_h > max_sync_age:
                    return (
                        False,
                        (
                            f"Latest alpaca-sync is {age_h:.1f}h old "
                            f"(> {max_sync_age:.0f}h threshold) — broker state stale"
                        ),
                        "sync_staleness",
                        env,
                    )

            # Factor-data staleness: refuse buys (entry, buy_add) when the
            # rankings driving the decision are too old. Sells are not gated —
            # an exit signal on stale data is conservative (close a position we
            # may no longer want); a buy on stale data could be wildly wrong.
            max_data_age = env["max_data_age_hours"]
            if req.action in ("entry", "buy_add") and max_data_age > 0:
                async with engine.connect() as conn:
                    pl_row = (await conn.execute(text(
                        "SELECT completed_at FROM pipeline_runs "
                        "WHERE status='success' "
                        "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
                    ))).first()
                if pl_row is None or pl_row[0] is None:
                    return (
                        False,
                        "No successful pipeline run on record — rankings unavailable",
                        "data_staleness",
                        env,
                    )
                age_h = (datetime.now(timezone.utc) - pl_row[0]).total_seconds() / 3600.0
                if age_h > max_data_age:
                    return (
                        False,
                        (
                            f"Latest successful pipeline run completed {age_h:.1f}h ago "
                            f"(> {max_data_age:.0f}h threshold) — rankings stale"
                        ),
                        "data_staleness",
                        env,
                    )

            # Daily-loss cap: refuse ALL actions if today's account value is
            # down more than MAX_DAILY_LOSS_PCT vs the day's opening baseline.
            # Baseline: earliest successful sync from "today" — sim_date in a
            # compressed simulation, else the current TRADING day in ET. We bucket
            # each sync by its ET calendar date (completed_at AT TIME ZONE RISK_TZ)
            # and match the ET "today" passed as a bound param, rather than using
            # Postgres CURRENT_DATE (UTC), whose rollover at ~19–20:00 ET would put
            # the baseline on the wrong side of a late-ET session.
            max_loss_pct = env["max_daily_loss_pct"]
            if max_loss_pct > 0 and max_loss_pct < 1.0:
                async with engine.connect() as conn:
                    if req.sim_date:
                        baseline_row = (await conn.execute(text(
                            "SELECT account_value FROM alpaca_sync_runs "
                            "WHERE status='success' "
                            "AND DATE(completed_at AT TIME ZONE 'UTC') = :sim_date::date "
                            "ORDER BY completed_at ASC LIMIT 1"
                        ), {"sim_date": req.sim_date})).first()
                    else:
                        baseline_row = (await conn.execute(text(
                            "SELECT account_value FROM alpaca_sync_runs "
                            "WHERE status='success' "
                            "AND DATE(completed_at AT TIME ZONE :risk_tz) = :trading_day::date "
                            "ORDER BY completed_at ASC LIMIT 1"
                        ), {"risk_tz": RISK_TZ_NAME, "trading_day": _trading_day_today()})).first()
                    current_row = (await conn.execute(text(
                        "SELECT account_value FROM alpaca_sync_runs "
                        "WHERE status='success' "
                        "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
                    ))).first()
                baseline = float(baseline_row[0]) if baseline_row and baseline_row[0] else None
                current = float(current_row[0]) if current_row and current_row[0] else None
                # If no same-day baseline exists, fall back to the latest sync value as
                # the opening baseline — ensures the loss cap fires even on the first
                # trade of the day when alpaca-sync hasn't run yet today.
                if baseline is None:
                    baseline = current
                if baseline and baseline > 0 and current is not None:
                    loss_pct = (baseline - current) / baseline
                    if loss_pct > max_loss_pct:
                        return (
                            False,
                            (
                                f"Daily loss limit: account ${current:.0f} vs baseline "
                                f"${baseline:.0f} = {loss_pct:.1%} loss (> {max_loss_pct:.0%})"
                            ),
                            "daily_loss_limit",
                            env,
                        )

            # Max-positions count: refuse entries when live_positions has
            # already reached MAX_POSITIONS and this ticker isn't already held
            # (a buy_add on an existing position keeps the count unchanged, so
            # entries are the only action that can grow the portfolio).
            max_positions = env["max_positions"]
            if req.action == "entry" and max_positions > 0:
                async with engine.connect() as conn:
                    pos_row = (await conn.execute(text(
                        "SELECT "
                        "  (SELECT COUNT(DISTINCT lp.ticker) FROM live_positions lp "
                        "   JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
                        "   WHERE sr.status='success' "
                        "   AND sr.completed_at = (SELECT MAX(completed_at) FROM alpaca_sync_runs WHERE status='success')) "
                        "+ "
                        "  (SELECT COUNT(DISTINCT ao.ticker) FROM alpaca_orders ao "
                        "   WHERE ao.status = 'pending' AND ao.action = 'entry' "
                        "   AND ao.ticker NOT IN ("
                        "     SELECT lp2.ticker FROM live_positions lp2 "
                        "     JOIN alpaca_sync_runs sr2 ON sr2.run_id = lp2.sync_run_id "
                        "     WHERE sr2.status='success' "
                        "     AND sr2.completed_at = (SELECT MAX(completed_at) FROM alpaca_sync_runs WHERE status='success')"
                        "   ))"
                    ))).first()
                    held = (await conn.execute(text(
                        "SELECT 1 FROM live_positions lp "
                        "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
                        "WHERE lp.ticker = :t AND sr.status='success' "
                        "AND sr.completed_at = ("
                        "  SELECT MAX(completed_at) FROM alpaca_sync_runs WHERE status='success'"
                        ") LIMIT 1"
                    ), {"t": req.ticker})).first()
                current_positions = int(pos_row[0]) if pos_row else 0
                already_held = held is not None
                if not already_held and current_positions >= max_positions:
                    return (
                        False,
                        (
                            f"Portfolio at capacity: {current_positions} live positions "
                            f"(limit {max_positions}); entry for {req.ticker} blocked. "
                            f"Exit a position before adding a new one."
                        ),
                        "max_positions_limit",
                        env,
                    )

            # Per-position size cap: refuse entry / buy_add if filling would
            # push the ticker above MAX_POSITION_PCT of account_value. Catches
            # the price-drift case where an existing position has appreciated
            # past portfolio-builder's max_position_weight; without this gate
            # a buy_add would compound the over-concentration.
            max_pos_pct = env["max_position_pct"]
            if req.action in ("entry", "buy_add") and max_pos_pct > 0 and max_pos_pct < 1.0:
                async with engine.connect() as conn:
                    acct_row = (await conn.execute(text(
                        "SELECT account_value FROM alpaca_sync_runs "
                        "WHERE status='success' "
                        "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
                    ))).first()
                    held_row = (await conn.execute(text(
                        "SELECT lp.market_value FROM live_positions lp "
                        "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
                        "WHERE lp.ticker = :t AND sr.status='success' "
                        "AND sr.completed_at = ("
                        "  SELECT MAX(completed_at) FROM alpaca_sync_runs WHERE status='success'"
                        ") LIMIT 1"
                    ), {"t": req.ticker})).first()
                account_value = float(acct_row[0]) if acct_row and acct_row[0] else None
                current_mv = float(held_row[0]) if held_row and held_row[0] else 0.0
                if account_value and account_value > 0:
                    new_mv = current_mv + req.notional
                    new_pct = new_mv / account_value
                    if new_pct > max_pos_pct:
                        return (
                            False,
                            (
                                f"Position size limit: {req.ticker} would be "
                                f"{new_pct:.1%} of portfolio after this {req.action} "
                                f"(${new_mv:.0f} / ${account_value:.0f}), "
                                f"exceeds {max_pos_pct:.0%} cap"
                            ),
                            "max_position_pct_limit",
                            env,
                        )
        except Exception as exc:
            print(f"[risk-service] WARN: planned-control check failed (skipped): {exc}")

    # Daily sell-side turnover cap: reject exits/sell_trims once today's sell
    # notional exceeds max_daily_turnover_pct of portfolio value. Only sells
    # (exits + sell_trims) count — buys deploying idle cash are not portfolio
    # churn. This prevents flipping half the portfolio in one day on a regime
    # change while allowing unconstrained initial capital deployment.
    #
    # sim_date: when provided (e.g. from a compressed harness simulation where
    # multiple pipeline dates are processed on the same wall-clock day), scope
    # the count to orders that share the same sim_date rather than today's
    # wall-clock date. Orders carry the sim_date via risk_decisions.created_at
    # binned by the sim_date stored in their linked pipeline run's chain_date
    # (looked up through alpaca_orders.intent_id → delta_intents.run_id →
    # pipeline_runs.chain_date). Falls back to wall-clock date if sim_date absent.
    #
    # Skipped when DB is unavailable.
    max_daily_pct = env["max_daily_turnover_pct"]
    if req.action in ("exit", "sell_trim") and engine is not None and max_daily_pct < 1.0:
        try:
            async with engine.connect() as conn:
                if req.sim_date:
                    # Use delta_runs.run_date to scope per simulation day
                    today_row = (await conn.execute(text(
                        "SELECT COALESCE(SUM(ao.notional), 0) "
                        "FROM alpaca_orders ao "
                        "JOIN delta_intents di ON di.id = ao.intent_id "
                        "JOIN delta_runs dr ON dr.run_id = di.run_id "
                        "WHERE dr.run_date = :sim_date "
                        "AND ao.action IN ('exit', 'sell_trim') "
                        "AND ao.status NOT IN ('cancelled', 'rejected', 'risk_rejected')"
                    ), {"sim_date": req.sim_date})).first()
                else:
                    today_row = (await conn.execute(text(
                        "SELECT COALESCE(SUM(notional), 0) FROM alpaca_orders "
                        "WHERE DATE(COALESCE(submitted_at, created_at) AT TIME ZONE 'UTC') = CURRENT_DATE "
                        "AND action IN ('exit', 'sell_trim') "
                        "AND status NOT IN ('cancelled', 'rejected', 'risk_rejected')"
                    ))).first()
                acct_row = (await conn.execute(text(
                    "SELECT account_value FROM alpaca_sync_runs "
                    "WHERE status='success' ORDER BY completed_at DESC NULLS LAST LIMIT 1"
                ))).first()
            today_sell_notional = float(today_row[0]) if today_row else 0.0
            account_value = float(acct_row[0]) if acct_row and acct_row[0] else None
            if account_value and account_value > 0:
                limit = account_value * max_daily_pct
                if today_sell_notional + req.notional > limit:
                    date_ref = req.sim_date or "today (wall clock)"
                    return (
                        False,
                        (
                            f"Daily sell-side turnover limit [{date_ref}]: "
                            f"sell notional so far ${today_sell_notional:.0f} "
                            f"+ this order ${req.notional:.0f} "
                            f"= ${today_sell_notional + req.notional:.0f} "
                            f"exceeds {max_daily_pct:.0%} of portfolio "
                            f"(${account_value:.0f} × {max_daily_pct:.0%} = ${limit:.0f})"
                        ),
                        "daily_turnover_limit",
                        env,
                    )
        except Exception as exc:
            print(f"[risk-service] WARN: daily turnover check failed (skipped): {exc}")
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
        "kill_switch": _is_kill_switch_active(),
        "paper_only": PAPER_ONLY,
        "live_trading_enabled": LIVE_TRADING_ENABLED,
        "max_order_notional": MAX_ORDER_NOTIONAL,
        "max_daily_turnover_pct": MAX_DAILY_TURNOVER_PCT,
        "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
        "max_position_pct": MAX_POSITION_PCT,
        "max_positions": MAX_POSITIONS,
        "max_data_age_hours": MAX_DATA_AGE_HOURS,
        "max_sync_age_hours": MAX_SYNC_AGE_HOURS,
        "persistence": engine is not None,
    }
