import math
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
from stock_strategy_shared.order_status import (
    OPEN_ORDER_STATUSES,
    TURNOVER_STATUSES,
    open_status_sql,
)

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
# Shared resolver: honors the canonical STOCKER_TZ first, then RISK_TZ (back-compat).
# Previously risk-service read ONLY RISK_TZ, so a deploy that set SCHEDULE_TZ/STOCKER_TZ
# left risk-service on its own default — a divergence from scheduler/pipeline. Fails
# fast on missing tzdata rather than silently using UTC. RISK_TZ_NAME is still the
# IANA name string (str(ZoneInfo) == the key) for the SQL `AT TIME ZONE :risk_tz`.
from stock_strategy_shared.trading_tz import resolve_trading_tz
_RISK_TZ = resolve_trading_tz("RISK_TZ")
RISK_TZ_NAME = str(_RISK_TZ)


def _trading_day_today() -> str:
    """Today's calendar date in the trading zone (ET), ISO format. Used as the
    daily-loss baseline reset boundary instead of Postgres CURRENT_DATE (UTC).
    Uses the module-local `datetime` (patchable in tests) with the shared-resolved
    zone — only the TZ resolution is shared, not the clock read."""
    return datetime.now(_RISK_TZ).date().isoformat()


# Order statuses that mean "queued or in-flight at the broker" (NOT terminal:
# filled / canceled / expired / risk_rejected / failed are excluded). Mirrors
# SHARED canonical open-order set (stock_strategy_shared.order_status) — the SAME
# tokens alpaca-sync persists, so "what we write" == "what we query". Used by the
# MAX_POSITIONS gate to net the rotation: an `exit` order in one of these states is
# a held name on its way out (it vacates at the same open the entry fills at), so it
# must not count against capacity. Includes 'deferred' (the after-close cron approves
# exits FIRST → flips them to 'deferred' BEFORE entries are risk-checked) and
# 'partial_fill' (previously this set used the broker spelling 'partially_filled',
# which alpaca-sync never writes — so a partially-exited position was miscounted).
_OPEN_ORDER_STATUSES = OPEN_ORDER_STATUSES
_OPEN_STATUS_SQL = open_status_sql()

# Projected post-rotation position count for the MAX_POSITIONS gate:
#   held_distinct − held names being EXITED this cycle + queued new-ticker entries.
# This SQL is the DB-side implementation of the canonical rule in
# shared/stock_strategy_shared/capacity.py (projected_book_count). The delta
# engine's _allocate_capacity applies the SAME rule (in Python) using the SAME
# in-flight order inputs, so "the planner admits an entry" ⇔ "this gate approves
# it" — keep the two in sync if either changes.
# Bound param :sim_date (ISO string, may be NULL). NOTE run_date::text = :sim_date,
# NOT run_date = :sim_date — asyncpg infers a bare `run_date = $1` placeholder as a
# DATE and raises DataError on a str ("'str' has no attribute 'toordinal'"); the
# fail-closed wrapper then turns that into "Safety control unavailable" and rejects
# every entry. Casting the column forces $1 to text. Defined at module scope (not
# inline) so the Postgres integration test executes THIS exact SQL, not a copy that
# could silently drift — the unit tests use a mock engine that never runs SQL, so a
# query-level defect (type mismatch, bad column, unbalanced parens) is invisible to
# them. See tests/risk_service/test_max_positions_sql_pg.py.
_PROJECTED_POSITIONS_SQL = (
    "SELECT "
    "  (SELECT COUNT(DISTINCT lp.ticker) FROM live_positions lp "
    "   JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
    "   WHERE sr.status='success' "
    "   AND sr.completed_at = (SELECT MAX(completed_at) FROM alpaca_sync_runs WHERE status='success')) "
    "- "
    "  (SELECT COUNT(DISTINCT lp3.ticker) FROM live_positions lp3 "
    "   JOIN alpaca_sync_runs sr3 ON sr3.run_id = lp3.sync_run_id "
    "   WHERE sr3.status='success' "
    "   AND sr3.completed_at = (SELECT MAX(completed_at) FROM alpaca_sync_runs WHERE status='success') "
    "   AND ( lp3.ticker IN ("
    "       SELECT ao3.ticker FROM alpaca_orders ao3 "
    f"      WHERE ao3.action = 'exit' AND ao3.status IN ({_OPEN_STATUS_SQL})"
    "     ) OR lp3.ticker IN ("
    "       SELECT di.ticker FROM delta_intents di "
    "       WHERE di.action = 'exit' AND di.run_id = ("
    "         SELECT run_id FROM delta_runs WHERE run_date::text = :sim_date "
    "         ORDER BY started_at DESC NULLS LAST LIMIT 1"
    "       )"
    "     ) )) "
    "+ "
    "  (SELECT COUNT(DISTINCT ao.ticker) FROM alpaca_orders ao "
    f"   WHERE ao.status IN ({_OPEN_STATUS_SQL}) AND ao.action = 'entry' "
    # EXCLUDE the candidate being checked. At the FIRST risk check its order row does
    # not exist yet, so it is naturally absent from this count; at the DEFERRED
    # RE-CHECK its own 'deferred' row DOES exist and would be counted here — making the
    # re-check one stricter than the admission check (and than the planner, which
    # admits when projected-INCLUDING-candidate <= max). That off-by-one rejected an
    # entry that legitimately fills the book to exactly max_positions ("Portfolio at
    # capacity" on the 35th). Excluding the candidate makes projected mean "the book
    # WITHOUT this entry", so `projected >= max` ⇔ "no room", consistent across both
    # checks and with the planner's `projected_with_candidate <= max` rule.
    "   AND ao.ticker <> :ticker "
    "   AND ao.ticker NOT IN ("
    "     SELECT lp2.ticker FROM live_positions lp2 "
    "     JOIN alpaca_sync_runs sr2 ON sr2.run_id = lp2.sync_run_id "
    "     WHERE sr2.status='success' "
    "     AND sr2.completed_at = (SELECT MAX(completed_at) FROM alpaca_sync_runs WHERE status='success')"
    "   ))"
)


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


def _control_error(name: str, exc: Exception, *, is_close: bool, env: dict):
    """Per-control fail-closed handler.

    Each DB-dependent safety control runs in its OWN try/except (not one shared
    block) so a defect or transient error in one control is contained and
    DIAGNOSABLE — the rejection names the specific control (e.g.
    `max_positions_unavailable`) instead of a generic `control_unavailable`,
    and a failure in one control does not abort evaluation of the others.

    Semantics (unchanged from the old shared handler, just per-control):
      - OPENING risk (entry / buy_add): fail CLOSED — return a rejection tuple so
        the trade is refused; we must never approve when a safety control could
        not be evaluated.
      - CLOSES (exit / sell_trim): EXEMPT — log and return None so the caller
        continues; reducing/closing risk can never be trapped by a control outage.
    """
    print(f"[risk-service] ERROR: control '{name}' unavailable: {exc}")
    if not is_close:
        return (
            False,
            f"Safety control '{name}' unavailable (database error) — "
            f"trade rejected to default to safety",
            f"{name}_unavailable",
            env,
        )
    print(f"[risk-service] exit/sell_trim EXEMPT from '{name}' unavailability — allowing close")
    return None


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

    @field_validator("qty", "notional")
    @classmethod
    def validate_finite(cls, v: float) -> float:
        # Defense-in-depth: reject NaN/inf at the schema boundary so a malformed
        # request can never reach _decide. _decide ALSO re-checks (so a directly
        # constructed request — e.g. in tests or internal callers — is still safe).
        if not math.isfinite(v):
            raise ValueError("must be a finite number (NaN/inf not allowed)")
        return v


class TradeCheckResponse(BaseModel):
    approved: bool
    reason: str
    check_id: str           # also the risk_decisions.decision_id
    rule_triggered: str     # 'kill_switch'|'live_disabled'|'paper_only'|'qty'|
                            # 'non_finite_qty'|'non_finite_notional'|
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
        # Pool sizing (audit P0): each /check serially checks out a connection up to
        # ~6 times (one per DB-dependent control + the persist txn). The old 2/3 (=5
        # max) starved under concurrent /check (e.g. the drain re-check overlapping an
        # approval) while a control's query waited on the pool past the 30s checkout
        # timeout → the control threw → spurious "Safety control unavailable" fail-
        # closed rejects. Bump so a burst of concurrent checks can't exhaust the pool.
        engine = create_async_engine(DATABASE_URL, pool_pre_ping=True,
                                     pool_size=10, max_overflow=20,
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
    # Non-finite (NaN / +inf / -inf) qty or notional must be rejected BEFORE any
    # numeric comparison: NaN fails every `<=` / `>` test, so a NaN qty/notional
    # would slip past the `<=0` and `>max` gates and reach approve. inf would pass
    # `>0` but break sizing and downstream math. Default to safety and reject.
    if not math.isfinite(req.qty):
        return False, "Invalid qty: must be a finite number", "non_finite_qty", env
    if not math.isfinite(req.notional):
        return False, "Invalid notional: must be a finite number", "non_finite_notional", env
    if req.qty <= 0:
        return False, "Invalid qty: must be > 0", "qty", env
    # notional_zero is a BUY-side guard only. A de-risking CLOSE (exit / sell_trim)
    # must never be blocked by a missing/zero notional — the local display price can
    # be absent (notional = qty × 0 = 0) while the position is genuinely held and we
    # MUST be allowed to close it. The exit is sized qty-only at the broker
    # (close-position computes the exact held qty), so a zero notional here is an
    # audit-display gap, not a real "$0 order". Entries/buy_adds still reject $0.
    is_close = req.action in ("exit", "sell_trim")
    if req.notional <= 0 and not is_close:
        return False, "Invalid notional: must be > 0", "notional_zero", env
    if req.notional > env["max_order_notional"]:
        return (
            False,
            f"Order notional ${req.notional:.2f} exceeds limit ${env['max_order_notional']:.2f}",
            "notional_limit",
            env,
        )

    # ── Planned safety controls (Phase 6+): DB-dependent, defense-in-depth ─────
    # These are SAFETY-CRITICAL gates (sync staleness, data staleness, daily loss,
    # max positions, max-position-pct). They depend on the DB to read broker /
    # pipeline / account state. A DB error means we CANNOT verify a control — so we
    # DEFAULT TO SAFETY and REJECT opening risk, fail-CLOSED, rather than silently
    # skipping and approving (the prior fail-OPEN behavior, which let trades through
    # whenever the DB hiccupped). The earlier in-memory checks (kill_switch, qty,
    # notional) always run regardless of DB health.
    #
    # PER-CONTROL ISOLATION: each control runs in its OWN try/except via
    # `_control_error`, NOT one shared block. Previously a single defect anywhere in
    # the block (e.g. a sim_date type mismatch in the max-positions query) aborted
    # ALL controls and rejected every entry with a generic "control unavailable".
    # Now a failure is contained and DIAGNOSABLE — the rejection names the specific
    # control (`<name>_unavailable`) and the other controls still evaluate. A
    # `return (False, ...)` inside a control is a real rule rejection and propagates
    # as-is; only an unexpected exception trips that control's fail-closed handler.
    #
    # An exit or a sell_trim must ALWAYS be allowed — reducing/closing risk can never
    # be trapped by a system condition (a DB outage, a stale broker sync, or a daily
    # loss halt). So closes are exempt from the DB-dependent controls below; opening
    # risk (entry / buy_add) stays fail-closed. The kill switch + qty/notional
    # validity above still apply to everything.
    # (is_close already computed above for the notional_zero close-exemption.)
    if engine is not None:
        try:
            # Alpaca-availability: refuse ALL actions if the last successful sync
            # is too old. A stale broker view means qty / buying_power / live
            # positions are wrong; sizing decisions made against them could
            # double-spend cash or sell positions we no longer hold.
            max_sync_age = env["max_sync_age_hours"]
            if max_sync_age > 0 and not is_close:
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
        except Exception as exc:
            rej = _control_error("sync_staleness", exc, is_close=is_close, env=env)
            if rej is not None:
                return rej

        try:
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
        except Exception as exc:
            rej = _control_error("data_staleness", exc, is_close=is_close, env=env)
            if rej is not None:
                return rej

        try:
            # Daily-loss cap: refuse ALL actions if today's account value is
            # down more than MAX_DAILY_LOSS_PCT vs the day's opening baseline.
            # Baseline: earliest successful sync from "today" — sim_date in a
            # compressed simulation, else the current TRADING day in ET. We bucket
            # each sync by its ET calendar date (completed_at AT TIME ZONE RISK_TZ)
            # and match the ET "today" passed as a bound param, rather than using
            # Postgres CURRENT_DATE (UTC), whose rollover at ~19–20:00 ET would put
            # the baseline on the wrong side of a late-ET session.
            max_loss_pct = env["max_daily_loss_pct"]
            if max_loss_pct > 0 and max_loss_pct < 1.0 and not is_close:
                async with engine.connect() as conn:
                    if req.sim_date:
                        # Bucket sim-day syncs by the SAME ET trading zone as the
                        # non-sim branch. (Previously this bucketed AT TIME ZONE
                        # 'UTC', which could put a late-ET sync on the wrong sim
                        # day vs the ET-keyed non-sim path — an inconsistency.)
                        baseline_row = (await conn.execute(text(
                            "SELECT account_value FROM alpaca_sync_runs "
                            "WHERE status='success' "
                            "AND to_char(completed_at AT TIME ZONE :risk_tz, 'YYYY-MM-DD') = :sim_date "
                            "ORDER BY completed_at ASC LIMIT 1"
                        ), {"risk_tz": RISK_TZ_NAME, "sim_date": req.sim_date})).first()
                    else:
                        baseline_row = (await conn.execute(text(
                            "SELECT account_value FROM alpaca_sync_runs "
                            "WHERE status='success' "
                            "AND to_char(completed_at AT TIME ZONE :risk_tz, 'YYYY-MM-DD') = :trading_day "
                            "ORDER BY completed_at ASC LIMIT 1"
                        ), {"risk_tz": RISK_TZ_NAME, "trading_day": _trading_day_today()})).first()
                    current_row = (await conn.execute(text(
                        "SELECT account_value FROM alpaca_sync_runs "
                        "WHERE status='success' "
                        "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
                    ))).first()
                baseline = float(baseline_row[0]) if baseline_row and baseline_row[0] else None
                current = float(current_row[0]) if current_row and current_row[0] else None
                # No same-day opening baseline → we cannot compute the day's loss.
                # We must NOT fall back to current equity as the baseline: that makes
                # loss_pct = 0 and silently NEUTRALIZES the cap on the first trade of
                # a down day (exactly when the protection matters). Default to safety
                # and REJECT — "loss control unavailable" — until a same-day sync
                # establishes the opening baseline. (We still need a current value to
                # report; if even that is missing, broker state is unknown → reject.)
                if current is None:
                    return (
                        False,
                        "Daily loss control unavailable: no account value on record — broker state unknown",
                        "daily_loss_limit",
                        env,
                    )
                if baseline is None:
                    return (
                        False,
                        (
                            "Daily loss control unavailable: no same-day opening baseline sync "
                            "to compare against — refusing to trade until today's baseline is established"
                        ),
                        "daily_loss_limit",
                        env,
                    )
                if baseline > 0:
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
        except Exception as exc:
            rej = _control_error("daily_loss", exc, is_close=is_close, env=env)
            if rej is not None:
                return rej

        try:
            # Max-positions count: refuse entries when the PROJECTED post-rotation
            # book would reach MAX_POSITIONS and this ticker isn't already held.
            #
            # The count must be the projected book AFTER this cycle's queued orders
            # settle at the same market open, NOT the raw current broker book — they
            # are all `day` orders queued for one open, so exits and entries net out.
            #
            #   projected = held_distinct                          (latest alpaca-sync)
            #             − held names being EXITED this cycle      (on their way out)
            #             + queued NEW-ticker `entry` orders        (on their way in)
            #
            # Without the exit subtraction a full rotation (e.g. 42 held → 30 target:
            # 34 exits + 22 entries) self-wedges: every entry is rejected because the
            # gate counts the 34 names that are simultaneously being exited (42 ≥ 35),
            # even though the post-open book is only 30.
            #
            # "Being exited this cycle" is detected from TWO sources, OR'd, because an
            # exit ORDER does not exist yet when the entry is checked — the after-close
            # auto-approve does NOT submit exits strictly before entries, so an entry
            # checked early in the pass sees zero deferred exits and (with order-only
            # netting) computes the full 42, rejects, and — since auto-approve never
            # retries a `risk_rejected` row — stays wedged even after the 33 exits
            # later defer. The race was confirmed in prod: rejections stamped
            # "42 projected" while a later snapshot showed held=42, held_exiting=33.
            # So we also net the exit INTENTS from delta_intents for this run, which
            # exist the instant the delta step completes (before ANY approval) and are
            # therefore order-independent:
            #   (a) held names with a queued `exit` ORDER (_OPEN_ORDER_STATUSES), OR
            #   (b) held names with an `exit` INTENT in the latest delta run for
            #       sim_date (the run this entry belongs to; sim_date = its
            #       delta_runs.run_date, passed by the trade-executor).
            # When sim_date is absent (cold-start / manual without a run) the
            # delta-intent subquery is empty and only the order source applies.
            # Execution-time over-commit is still backstopped by the trade-executor
            # drain's fill-gate + buying-power check.
            max_positions = env["max_positions"]
            if req.action == "entry" and max_positions > 0:
                async with engine.connect() as conn:
                    pos_row = (await conn.execute(
                        text(_PROJECTED_POSITIONS_SQL),
                        {"sim_date": req.sim_date, "ticker": req.ticker},
                    )).first()
                    held = (await conn.execute(text(
                        "SELECT 1 FROM live_positions lp "
                        "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
                        "WHERE lp.ticker = :t AND sr.status='success' "
                        "AND sr.completed_at = ("
                        "  SELECT MAX(completed_at) FROM alpaca_sync_runs WHERE status='success'"
                        ") LIMIT 1"
                    ), {"t": req.ticker})).first()
                # Clamp at 0: in a heavy rotation the netted projection can go
                # transiently negative (more queued exits than the snapshot held,
                # e.g. a sync lag); a negative count must never satisfy the cap in
                # a way that confuses the message — it just means "plenty of room".
                current_positions = max(0, int(pos_row[0])) if pos_row else 0
                already_held = held is not None
                if not already_held and current_positions >= max_positions:
                    return (
                        False,
                        (
                            f"Portfolio at capacity: {current_positions} projected positions "
                            f"after queued exits/entries settle (limit {max_positions}); "
                            f"entry for {req.ticker} blocked. "
                            f"Exit a position before adding a new one."
                        ),
                        "max_positions_limit",
                        env,
                    )
        except Exception as exc:
            rej = _control_error("max_positions", exc, is_close=is_close, env=env)
            if rej is not None:
                return rej

        try:
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
            rej = _control_error("max_position_pct", exc, is_close=is_close, env=env)
            if rej is not None:
                return rej

    # Daily sell-side turnover cap: throttle DISCRETIONARY churn. ONLY `sell_trim`
    # counts and is capped — EXITS ARE EXEMPT (policy: a de-risking close / a
    # builder-dropped rotation must NEVER be blocked by a turnover throttle; you
    # always want to be able to fully exit a name). Buys deploying idle cash are
    # not churn either. So the cap only limits how much DISCRETIONARY trimming
    # happens in a day, preventing churn without ever wedging a needed exit. This
    # also closes the planner/gate divergence (F1): the delta engine doesn't model
    # turnover, so if exits were capped a big rotation (mostly exits) would emit
    # exits the gate then rejected ("failed" rows, multi-day silent completion).
    # Exempting exits removes that class; only sell_trims remain capped, and a
    # single build rarely trims > the cap.
    #
    # sim_date: when provided (e.g. from a compressed harness simulation where
    # multiple pipeline dates are processed on the same wall-clock day), scope
    # the count to orders that share the same sim_date rather than today's
    # wall-clock date. Orders carry the sim_date via risk_decisions.created_at
    # binned by the sim_date stored in their linked pipeline run's chain_date
    # (looked up through alpaca_orders.intent_id → delta_intents.run_id →
    # pipeline_runs.chain_date). Falls back to wall-clock date if sim_date absent.
    #
    # TOCTOU note (C2): the trade-executor records each order as 'pending' BEFORE
    # it calls /check for the NEXT order and before it submits, so a not-yet-
    # submitted sell already sits in alpaca_orders as 'pending'. We therefore sum
    # the IN-FLIGHT/WORKING and FILLED sell notional via an explicit positive
    # status list (SHARED TURNOVER_STATUSES = open set + 'filled') rather than a
    # NOT-IN exclusion — so a concurrent/queued sell that hasn't filled yet still
    # counts against the cap, closing the window where two sells could both pass.
    # CRITICALLY this now includes 'deferred' (the normal after-close queued-sell
    # state — previously omitted, so a full rotation of deferred sells slipped past
    # the cap) and the correct 'partial_fill' token (was 'partially_filled', which
    # alpaca-sync never writes). Terminal non-fills (failed/expired/canceled) are
    # excluded so they don't inflate the sum.
    #
    # Skipped when DB is unavailable.
    _TURNOVER_STATUSES = TURNOVER_STATUSES
    _turnover_status_sql = ", ".join(f"'{s}'" for s in _TURNOVER_STATUSES)
    max_daily_pct = env["max_daily_turnover_pct"]
    if req.action == "sell_trim" and engine is not None and max_daily_pct < 1.0:
        try:
            async with engine.connect() as conn:
                if req.sim_date:
                    # Use delta_runs.run_date to scope per simulation day.
                    # Compare run_date::text = :sim_date (NOT run_date = :sim_date):
                    # sim_date arrives as an ISO string and asyncpg infers a bare
                    # `run_date = $1` placeholder as a DATE type, then rejects the
                    # str with "DataError: 'str' has no attribute 'toordinal'".
                    # Casting the column to text forces $1 to text. (This query
                    # silently swallowed that error via the outer except for the
                    # whole life of the sim_date turnover path — see git history.)
                    today_row = (await conn.execute(text(
                        "SELECT COALESCE(SUM(ao.notional), 0) "
                        "FROM alpaca_orders ao "
                        "JOIN delta_intents di ON di.id = ao.intent_id "
                        "JOIN delta_runs dr ON dr.run_id = di.run_id "
                        "WHERE dr.run_date::text = :sim_date "
                        "AND ao.action = 'sell_trim' "
                        f"AND ao.status IN ({_turnover_status_sql})"
                    ), {"sim_date": req.sim_date})).first()
                else:
                    today_row = (await conn.execute(text(
                        "SELECT COALESCE(SUM(notional), 0) FROM alpaca_orders "
                        "WHERE DATE(COALESCE(submitted_at, created_at) AT TIME ZONE 'UTC') = CURRENT_DATE "
                        "AND action = 'sell_trim' "
                        f"AND status IN ({_turnover_status_sql})"
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
