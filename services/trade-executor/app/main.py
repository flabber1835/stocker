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
# Bind the retry-relevant exception classes at import so they survive tests that
# patch the whole `httpx` module (patching te_main.httpx must not turn the except
# tuple into Mocks). `httpx.AsyncClient` is still used qualified elsewhere.
from httpx import HTTPStatusError as _HttpxStatusError
from httpx import TransportError as _HttpxTransportError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from stock_strategy_shared.db import wait_for_db
from stock_strategy_shared.order_status import OPEN_ORDER_STATUSES, open_status_sql
from stock_strategy_shared.broker import ALREADY_CLOSED_STATUS, get_broker_adapter

from app.drain import DeferredOrder, plan_drain
from app.submit_lock import (
    DEFAULT_ACCOUNT,
    SUBMIT_LOCK_TIMEOUT_SECS,
    SubmitLockTimeout,
    with_submit_lock,
)

logger = logging.getLogger("trade-executor")
logging.basicConfig(level=logging.INFO)

# ── Environment variables ────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# The real-money Alpaca trading endpoint. Anything else — paper-api, the test
# harness's alpaca-sim, localhost — cannot reach a live account.
_LIVE_ALPACA_HOSTS = {"api.alpaca.markets"}


def trade_type_for_base_url(base_url: str | None) -> str:
    """'live' iff the configured endpoint is the REAL Alpaca trading API.

    This label — not the endpoint — is what risk-service's LIVE_TRADING_ENABLED
    and PAPER_ONLY gates key off. It used to be hardcoded 'paper' on every risk
    check, which made those gates decorative: pointing ALPACA_BASE_URL at the
    live API traded real money straight through the paper-labeled path. Deriving
    it from the endpoint makes going live a deliberate two-key turn: switch the
    URL *and* flip LIVE_TRADING_ENABLED=true / PAPER_ONLY=false, or every order
    is rejected. Unknown hosts stay 'paper' — they can't reach the real broker,
    and labeling the sim 'live' would wedge the test harness.
    """
    from urllib.parse import urlparse
    host = (urlparse(base_url or "").hostname or "").lower()
    return "live" if host in _LIVE_ALPACA_HOSTS else "paper"


def _current_trade_type() -> str:
    # Env re-read per call (same philosophy as risk-service's per-/check re-read).
    return trade_type_for_base_url(
        os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"))
RISK_SERVICE_URL = os.getenv("RISK_SERVICE_URL", "http://risk-service:8000")
# Retry the risk-service /check call on TRANSIENT transport errors / 5xx so a brief
# blip (e.g. risk-service restarting on a redeploy mid-approval) does not fail the
# attempt. Confirmed in prod: a batch of clicks during a risk-service redeploy left
# 12 closes "failed: risk-service error: All connection attempts failed". Bounded
# short so the dashboard's approve fetch does not time out; a real risk REJECTION
# (HTTP 200, approved=false) is NOT retried — only transport failures / 5xx.
try:
    RISK_CALL_RETRIES = max(1, int(os.getenv("RISK_CALL_RETRIES", "3")))
except ValueError:
    RISK_CALL_RETRIES = 3
try:
    RISK_CALL_BACKOFF_SECS = float(os.getenv("RISK_CALL_BACKOFF_SECS", "0.4"))
except ValueError:
    RISK_CALL_BACKOFF_SECS = 0.4
try:
    EXIT_SYNC_MAX_AGE_HOURS = float(os.getenv("EXIT_SYNC_MAX_AGE_HOURS", "24"))
except ValueError:
    EXIT_SYNC_MAX_AGE_HOURS = 24.0
try:
    # Max age (calendar days) of the daily_prices fallback close used to SIZE a BUY
    # (entry / buy_add). The fallback is `ORDER BY date DESC LIMIT 1` with no bound,
    # so a delisted/halted name with only a stale close would otherwise size a buy
    # off a price that no longer reflects the market. Default 7 days (weekend +
    # holiday safe). Sells are NOT bounded by this — de-risking on a stale price is
    # safe. The live-position price (intraday) is always preferred over this.
    MAX_PRICE_AGE_DAYS = int(os.getenv("MAX_PRICE_AGE_DAYS", "7"))
except ValueError:
    MAX_PRICE_AGE_DAYS = 7
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

# audit P1: when a deferred buy is sized a few shares over the cash its funding sells
# freed, the drain trims it to what buying power affords rather than expiring it
# unfunded — but only if the trimmed order is still >= this fraction of the intended
# shares (otherwise it waits/expires rather than placing a token fill). 0 disables
# the floor (always trim to fit); 1.0 disables re-sizing (original expire behavior).
try:
    DRAIN_BUY_MIN_FILL_RATIO = float(os.getenv("DRAIN_BUY_MIN_FILL_RATIO", "0.5"))
except ValueError:
    DRAIN_BUY_MIN_FILL_RATIO = 0.5

# audit P1: bounded expiry for a buy deferred while the Alpaca clock was unreachable
# (so it can't sit 'deferred' forever and block re-proposal of the ticker).
try:
    CLOCK_NONE_EXPIRY_HOURS = float(os.getenv("CLOCK_NONE_EXPIRY_HOURS", "24"))
except ValueError:
    CLOCK_NONE_EXPIRY_HOURS = 24.0

# audit P1: reaper for orphaned 'pending' alpaca_orders — a row committed inside the
# submit lock but never advanced (process died between the reservation commit and the
# broker submit, or an abandoned request). Without this they linger until the next
# restart's warm-up, counting as open orders (blocking re-proposal + consuming a
# projected MAX_POSITIONS slot). Reaped to 'failed' once older than this.
try:
    PENDING_REAP_MINUTES = float(os.getenv("PENDING_REAP_MINUTES", "15"))
except ValueError:
    PENDING_REAP_MINUTES = 15.0


engine: Optional[AsyncEngine] = None


# ── Open / working order statuses ─────────────────────────────────────────────
# An order is "open" (still in flight, not terminal) when it occupies one of
# these statuses. The set MUST include both our LOCAL pre-broker states
# (pending/submitted/deferred) AND the Alpaca-working states that alpaca-sync
# maps live broker orders into (accepted/new/partial_fill). A working-but-
# unfilled order in accepted/new/partial_fill still reserves shares / cash
# and represents an in-flight intent — omitting it from the idempotency SELECT
# and the in-flight ticker guards let a re-proposed intent slip through and
# double-submit. Imported from the SHARED canonical set so the token we QUERY is
# the token alpaca-sync WRITES (it persists `partial_fill`, NOT the broker spelling
# `partially_filled` this set used to query — a partially-filled order was therefore
# invisible to the idempotency guard → double-submit).
# Comma-separated single-quoted literals for inlining into a `status IN (...)`
# clause (these are fixed, code-controlled constants — never user input).
_OPEN_STATUS_SQL = open_status_sql()

# Sentinel alpaca_status returned by _close_position_alpaca on a 404 (the position
# was already flat at the broker). The exit's goal — be out of the name — is met,
# but there is NO broker order, so the local row must NOT enter the 'submitted'
# lifecycle (it has alpaca_order_id NULL and would otherwise read as an in-flight
# submitted order forever). Instead it gets the TERMINAL no-op status 'closed'.
# 'closed' (not 'position_already_closed') because alpaca_orders.status is
# VARCHAR(20) — the longer token would be truncated/rejected.
# Single-sourced from the broker adapter (broker.close_position returns this when
# the position is already flat). Keep the local name — tests/callers reference it.
_ALREADY_CLOSED_ALPACA_STATUS = ALREADY_CLOSED_STATUS
_CLOSED_NOOP_STATUS = "closed"

# Event signalled by /jobs/enqueue(-batch) so the single-consumer approval worker
# drains a fresh approval immediately instead of waiting a full
# DEFERRED_WORKER_INTERVAL_SECS tick. Created lazily (must be bound to the running
# loop) — see _queue_kick_event(). Best-effort: a missed kick is recovered by the
# next periodic tick, so correctness never depends on the signal landing.
_queue_kick: Optional[asyncio.Event] = None


def _queue_kick_event() -> asyncio.Event:
    global _queue_kick
    if _queue_kick is None:
        _queue_kick = asyncio.Event()
    return _queue_kick


# Cap on how many approved intents one worker pass drains, so a single pass can't
# run unbounded; the loop re-enters immediately while work remains.
try:
    APPROVAL_QUEUE_BATCH = max(1, int(os.getenv("APPROVAL_QUEUE_BATCH", "200")))
except ValueError:
    APPROVAL_QUEUE_BATCH = 200


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
        # Deterministic idempotency key (= the alpaca_orders row id). If the process
        # crashes AFTER Alpaca accepts but BEFORE we flip status to 'submitted', the
        # next drain pass re-loads this still-'deferred' row and would re-submit —
        # Alpaca rejects a second order with the same client_order_id, so the dup is
        # blocked broker-side instead of placing a real second order.
        "client_order_id": order_id,
    }
    if not _has_broker_credentials():
        return "failed", "Broker credentials not configured"

    # ── Re-run the FULL risk gate before submitting a deferred order ──────────
    # The order was risk-approved at approval time, possibly hours earlier; the
    # deferred drain submits it at the next market open. Every DB-backed control
    # (daily-loss, sync-staleness, position/turnover caps, kill switch) could have
    # changed in the interim, so we re-call risk-service /check — the SAME call the
    # immediate path uses — and only submit if STILL approved. This path fails
    # CLOSED: if risk-service is unreachable or returns not-approved, we do NOT
    # submit. Defaulting to safety, an off-hours queued order never bypasses the
    # gate. (Previously this re-checked only the kill switch and was fail-OPEN —
    # submitting on any risk-service error — which let a stale approval slip past
    # every other control.)
    risk_payload = {
        "ticker": row["ticker"], "action": row.get("action"), "side": row["side"],
        "qty": float(row["qty"]), "notional": float(row["notional"]),
        "mode": row.get("mode") or "scheduled", "trade_type": _current_trade_type(),
        **({"sim_date": str(row["sim_date"])} if row.get("sim_date") else {}),
    }
    try:
        approved, reason, check_id, _rule = await _call_risk(risk_payload)
    except Exception as exc:
        # Fail CLOSED — risk-service unreachable means we cannot confirm safety.
        return "failed", f"Risk re-check unavailable — deferred order not submitted: {exc}"[:1000]
    if not approved:
        return "failed", f"Risk re-check rejected deferred order: {reason}"[:1000]
    if not check_id:
        # Approved but no audit id — same hard-failure rule as the immediate path.
        return "failed", ("Risk re-check approved but returned no check_id — "
                          "refusing to submit deferred order without audit trail")
    # Record the FRESH risk decision on the order so the audit trail reflects the
    # gate that actually authorized the submission (not the stale approval-time one).
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE alpaca_orders SET risk_check_id=:cid, risk_approved=TRUE, "
                 "risk_reason=:reason WHERE id=:id"),
            {"id": order_id, "cid": check_id, "reason": (reason or "")[:1000]},
        )
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
    # Success. Mirror the immediate path: a close-position 404 (already flat) is a
    # TERMINAL no-op — record 'closed', NOT 'submitted' (no broker order exists).
    already_closed = (
        alpaca_order_id is None and alpaca_status == _ALREADY_CLOSED_ALPACA_STATUS
    )
    final_status = _CLOSED_NOOP_STATUS if already_closed else "submitted"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE alpaca_orders SET status=:st, alpaca_order_id=:aid, "
                "alpaca_status=:astatus, submitted_at=:s, deferred_until=NULL, "
                "error_message=NULL WHERE id=:id"
            ),
            {"id": order_id, "st": final_status, "aid": alpaca_order_id,
             "astatus": alpaca_status, "s": datetime.now(timezone.utc)},
        )
    return final_status, None


def _parse_alpaca_dt(raw) -> Optional[datetime]:
    """Parse an Alpaca ISO timestamp (e.g. '2026-06-01T09:30:00-04:00')."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _broker():
    """Build the deployment's active broker adapter (BROKER env) — broker-agnostic.

    The executor's business logic never names a broker; it goes through this seam and
    `_has_broker_credentials()`. Only the Alpaca BRANCH here injects Alpaca config
    (from the module globals, so test patches of te_main.ALPACA_* still take effect);
    a future IBKR adapter self-reads its own IBKR_* env, so adding it is purely
    "implement IBKRBrokerAdapter + a factory branch" — no change to the trader.

    Built per-call so test patches take effect, and http_provider routes transport
    through this module's `httpx` so `patch.object(te_main, "httpx")` keeps
    intercepting adapter calls.
    """
    broker = os.getenv("BROKER", "alpaca").strip().lower()
    kwargs: dict = {}
    if broker in ("", "alpaca"):
        kwargs = dict(
            api_key=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY,
            base_url=ALPACA_BASE_URL,
        )
    return get_broker_adapter(http_provider=lambda: httpx, **kwargs)


def _has_broker_credentials() -> bool:
    """Broker-agnostic credential gate. Delegates to the active adapter's
    has_credentials() so the executor never hard-codes a broker's env var names —
    an IBKR deployment with IBKR creds (and no ALPACA_*) is correctly 'has creds'."""
    return _broker().has_credentials()


async def _get_alpaca_clock() -> Optional[dict]:
    """GET /v2/clock → {is_open, next_open, next_close}. None if creds missing or
    unreachable.

    A None return means UNKNOWN market state. Callers MUST treat unknown as
    do-not-submit-blind for BUYS: _route_to_drain routes a buy to the fill-gated
    drain (never an inline real order) when the clock is unknown, so a buy can't
    fire ahead of its funding sell / outside hours. Sells are still allowed inline
    (a de-risking close must never be trapped by a clock outage)."""
    if not _has_broker_credentials():
        return None
    try:
        return await _broker().get_clock()
    except Exception as exc:
        logger.warning("Alpaca clock fetch failed: %s", exc)
    return None


def _route_to_drain(mode: str, clock: Optional[dict], side: Optional[str] = None) -> bool:
    """Decide whether an approved order enqueues for the fill-gated open drain
    (True) or submits inline right now as a market order (False).

      - scheduled         → always the drain (the after-close cron path).
      - immediate + OPEN  → SELLS submit inline NOW (they fill in seconds and free
                            buying power); BUYS go to the drain. A rotation approved
                            during market hours fires the buys within seconds of the
                            sells, before the sells' proceeds settle — so an inline
                            buy sees stale buying power (~the pre-rotation free cash)
                            and Alpaca rejects it "insufficient buying power". The
                            drain releases each buy only once live buying power covers
                            it (sells-first, fill-gated), so a fully-invested rotation
                            self-funds instead of failing. A discretionary buy with
                            spare cash is released on the next drain tick (seconds).
      - immediate + CLOSED→ fall back to the drain. An off-hours 'immediate' click
                            must not bypass the drain's sells-first, fill-gated
                            buying-power sequencing — a raw queued buy could fire
                            ahead of its funding sell at the open and be rejected.
      - immediate + clock unknown (no creds/unreachable) → fail-safe: BUYS route
                            to the drain (never submit a real BUY blind to market
                            state — an inline buy on an unknown clock can fire ahead
                            of its funding sell / outside hours and be rejected
                            "insufficient buying power"). SELLS still submit inline
                            (de-risking / emergency close must always be allowed).
                            When creds are missing, Step 6's credential guard records
                            the outcome regardless of which branch is taken.
    """
    if mode == "scheduled":
        return True
    if mode == "immediate":
        if clock is None:
            # Unknown market state — do not submit a BUY blind; drain it (fail-safe).
            # Sells stay inline so a close is never trapped by a clock outage.
            return side == "buy"
        if not clock.get("is_open", False):
            return True
        # Market open: sells inline (fund the book fast), buys via the drain so
        # they release only within real buying power.
        return side == "buy"
    return False


async def _get_alpaca_buying_power() -> Optional[float]:
    """GET /v2/account → buying_power (float). None on failure."""
    if not _has_broker_credentials():
        return None
    try:
        acct = await _broker().get_account()
        return acct.buying_power if acct else None
    except Exception as exc:
        logger.warning("Alpaca account fetch failed: %s", exc)
    return None


async def _get_alpaca_order(alpaca_order_id: str) -> Optional[dict]:
    """GET /v2/orders/{id} → the order dict. None on failure."""
    try:
        return await _broker().get_order(alpaca_order_id)
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
        qty=_f(row.get("qty")) if isinstance(row, dict) else _f(row["qty"]),
    )


async def _submit_one_deferred(order_id: str) -> None:
    """Load a still-deferred order and submit it; mark failed on error."""
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT ao.id, ao.intent_id, ao.ticker, ao.action, ao.side, ao.qty, "
            "       ao.notional, ao.order_type, ao.time_in_force, ao.mode, ao.trace_id, "
            "       dr.run_date AS sim_date "
            "FROM alpaca_orders ao "
            "LEFT JOIN delta_intents di ON di.id = ao.intent_id "
            "LEFT JOIN delta_runs dr ON dr.run_id = di.run_id "
            "WHERE ao.id=:id AND ao.status='deferred'"
        ), {"id": order_id})).mappings().first()
    if row is None:
        return  # already handled (e.g. concurrent pass)
    new_status, err = await _submit_deferred_order(dict(row))
    if new_status in ("submitted", _CLOSED_NOOP_STATUS):
        logger.info("Drain %s order %s (%s %s)",
                    new_status, row["id"], row["side"], row["ticker"])
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

    _cols = "id, side, notional, submitted_at, expires_at, qty"
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
        min_fill_ratio=DRAIN_BUY_MIN_FILL_RATIO,
    )

    # Apply any buying-power-driven re-sizes BEFORE submission so _submit_one_deferred
    # reads the trimmed qty/notional. Trimming down is strictly within the approved
    # order (fewer shares, less notional) so it needs no re-approval; audited via the
    # row's error_message note and the recomputed notional.
    for oid, new_qty in decision.resized.items():
        async with engine.begin() as conn:
            row = (await conn.execute(text(
                "SELECT qty, notional FROM alpaca_orders WHERE id=:id AND status='deferred'"
            ), {"id": oid})).mappings().first()
            if row is None:
                continue
            old_qty = _f(row["qty"]) or 0.0
            old_notional = _f(row["notional"]) or 0.0
            price = (old_notional / old_qty) if old_qty > 0 else 0.0
            new_notional = round(new_qty * price, 2)
            await conn.execute(text(
                "UPDATE alpaca_orders SET qty=:q, notional=:n, "
                "error_message=:msg WHERE id=:id AND status='deferred'"
            ), {"q": new_qty, "n": new_notional, "id": oid,
                "msg": f"resized {old_qty:g}->{new_qty:g} shares to fit buying power"})
        logger.info("Drain re-sized buy %s: %g -> %g shares (fit BP)", oid, old_qty, new_qty)

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


async def _reap_orphaned_pending() -> None:
    """Reconcile-or-fail 'pending' alpaca_orders older than PENDING_REAP_MINUTES
    (audit P1 + F2).

    A 'pending' row is the committed reservation written inside the submit lock just
    before the broker submit. It can become orphaned in TWO ways:
      (a) the process died BEFORE the broker POST → the order never existed at the
          broker → it is genuinely failed and should be reaped; OR
      (b) the broker ACCEPTED the order but the pending→submitted UPDATE lost its
          transaction (a DB blip in that window) → the row is 'pending' with a NULL
          alpaca_order_id while a LIVE order works at the broker. Blindly failing it
          (the old behaviour) mislabels a live order as 'failed' and, because the
          broker id was never recorded, alpaca-sync can never reconcile it.

    Every submit sets client_order_id = the alpaca_orders row id, so we can tell the
    two apart: list the broker's orders and, for each orphan, recover it to the
    broker's real status (case b) instead of failing it; only orphans the broker has
    NEVER heard of are reaped 'failed' (case a). 'deferred'/'submitted' rows are NOT
    touched (the drain owns their lifecycle)."""
    if PENDING_REAP_MINUTES <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=PENDING_REAP_MINUTES)
    async with engine.connect() as conn:
        candidates = (await conn.execute(text(
            "SELECT id FROM alpaca_orders WHERE status='pending' AND created_at < :cutoff"
        ), {"cutoff": cutoff})).mappings().fetchall()
    if not candidates:
        return

    # Reconcile by client_order_id (= the row id). No credentials → the order could
    # never have been submitted (submit short-circuits without them), so every
    # candidate is a genuine case (a) and is safely reaped below.
    by_client: dict[str, object] = {}
    if _has_broker_credentials():
        try:
            for o in await _broker().list_orders(status="all", limit=500):
                coid = (getattr(o, "raw", None) or {}).get("client_order_id")
                if coid:
                    by_client[str(coid)] = o
        except Exception as exc:  # noqa: BLE001 — reconcile is best-effort; fall through to reap
            logger.warning("reaper: broker list_orders failed, cannot reconcile: %s", exc)

    recovered: list[str] = []
    reaped: list[str] = []
    now = datetime.now(timezone.utc)
    for c in candidates:
        oid = str(c["id"])
        bo = by_client.get(oid)
        if bo is not None:
            # Case (b): the broker HAS our order — recover the lost transition to the
            # broker's real (canonical) status instead of falsely killing a live order.
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE alpaca_orders SET status=:st, alpaca_order_id=:aid, "
                    "alpaca_status=:astatus, submitted_at=COALESCE(submitted_at, :now), "
                    "error_message='RECOVERED: broker had order; pending->submitted UPDATE was lost' "
                    "WHERE id=:id AND status='pending'"
                ), {"id": oid, "st": (getattr(bo, "status", None) or "submitted"),
                    "aid": getattr(bo, "broker_order_id", None),
                    "astatus": getattr(bo, "raw_status", None), "now": now})
            recovered.append(oid)
        else:
            # Case (a): the broker never heard of it → genuine pre-submit orphan.
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE alpaca_orders SET status='failed', "
                    "error_message='REAPED: pending older than threshold "
                    "(orphaned pre-submit; broker had no such order)' "
                    "WHERE id=:id AND status='pending'"
                ), {"id": oid})
            reaped.append(oid)
    if recovered:
        logger.warning("Reaper RECOVERED %d live order(s) mislabeled 'pending': %s",
                       len(recovered), recovered)
    if reaped:
        logger.warning("Reaped %d orphaned pending order(s): %s", len(reaped), reaped)


# SQL for the worker's hot scan, at module scope so the integration tier runs THIS
# exact query against the real schema (a column typo / mis-scoped predicate fails in
# CI, not production). Selects approved-but-unprocessed intents OF THE LATEST delta
# run that have no OPEN order yet, oldest approval first.
_APPROVED_PENDING_SQL = (
    "SELECT di.id, di.approval_mode "
    "FROM delta_intents di "
    "WHERE di.approved_at IS NOT NULL "
    "  AND (di.approval_processed_at IS NULL "
    "       OR di.approval_processed_at < di.approved_at) "
    "  AND di.run_id = ("
    "      SELECT run_id FROM delta_runs ORDER BY run_date DESC, started_at DESC LIMIT 1"
    "  ) "
    "  AND NOT EXISTS ("
    "      SELECT 1 FROM alpaca_orders ao "
    f"     WHERE ao.intent_id = di.id AND ao.status IN ({_OPEN_STATUS_SQL})"
    "  ) "
    "ORDER BY di.approved_at ASC "
    "LIMIT :lim"
)


async def _select_approved_pending(conn, limit: int):
    """Rows the approval worker should process this pass (see _APPROVED_PENDING_SQL)."""
    return (await conn.execute(text(_APPROVED_PENDING_SQL), {"lim": limit})).mappings().fetchall()


async def _process_approved_queue() -> int:
    """Drain durable approvals (delta_intents.approved_at) — the SINGLE CONSUMER.

    Approval is a fast, durable enqueue (/jobs/enqueue marks approved_at); this
    worker is the only thing that turns an approval into an order, ONE AT A TIME, by
    calling the unchanged per-intent orchestration (submit_order). Single consumer ⇒
    the per-(account,trading_day) submit lock is never contended ⇒ never times out
    (the trader-flakiness root cause). See docs/architecture.md "Design Decision:
    approval = durable enqueue + single-consumer drain".

    Scoped to the LATEST delta run so a superseded proposal is never executed; skips
    intents that already have an OPEN order (idempotency). Each processed approval is
    stamped approval_processed_at REGARDLESS of outcome, so a DEAD result doesn't
    loop — a re-approval (new approved_at > processed_at) is what retries it.
    Returns the number of approvals processed this pass."""
    async with engine.connect() as conn:
        rows = await _select_approved_pending(conn, APPROVAL_QUEUE_BATCH)

    processed = 0
    for r in rows:
        intent_id = str(r["id"])
        mode = r["approval_mode"] if r["approval_mode"] in ("immediate", "scheduled") else "immediate"
        try:
            resp = await submit_order(SubmitOrderRequest(intent_id=intent_id, mode=mode))
            logger.info("Approval worker processed intent %s → %s", intent_id, resp.status)
        except HTTPException as exc:
            # submit_order records its own 'failed' order row before raising (e.g.
            # risk-service unreachable); treat as processed so it doesn't loop.
            logger.warning("Approval worker: intent %s failed (%s)", intent_id, exc.detail)
        except Exception as exc:
            logger.exception("Approval worker: intent %s errored: %s", intent_id, exc)
        # Stamp processed regardless of outcome — retry is an explicit re-approval.
        try:
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE delta_intents SET approval_processed_at = NOW() WHERE id = :id"
                ), {"id": intent_id})
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Approval worker: could not stamp processed for %s: %s",
                             intent_id, exc)
        processed += 1
    return processed


async def _deferred_order_worker() -> None:
    """Background worker (SINGLE CONSUMER): drains durable approvals, then runs one
    fill-gated drain pass, every DEFERRED_WORKER_INTERVAL_SECS — or immediately when
    /jobs/enqueue kicks the queue event. Stateless across restarts (all state lives
    in delta_intents.approved_at + alpaca_orders)."""
    await asyncio.sleep(5)
    kick = _queue_kick_event()
    while True:
        # Clear BEFORE processing so a kick that arrives WHILE we work is preserved
        # for the next wait (clearing after would erase it → the new approval would
        # wait a full interval). A spurious extra pass is a cheap no-op.
        kick.clear()
        try:
            if engine is not None:
                # Drain approvals first; loop the queue phase while a full batch keeps
                # coming back so a big rotation clears in one wake rather than one-per-tick.
                while await _process_approved_queue() >= APPROVAL_QUEUE_BATCH:
                    pass
                await _drain_pass()
                await _reap_orphaned_pending()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Deferred order worker error: %s", exc)
        # Wake on the next enqueue kick OR after the periodic interval (whichever
        # first). The timeout keeps the fill-gated drain ticking with no new approvals.
        try:
            await asyncio.wait_for(kick.wait(), timeout=DEFERRED_WORKER_INTERVAL_SECS)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(application: FastAPI):
    global engine
    if not DATABASE_URL:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")
    # Pool sizing (audit #8 — atomic approve-and-reserve): each submit that holds
    # the per-(account, trading_day) advisory lock pins a DEDICATED connection for
    # the lock AND needs a SECOND connection for the reservation INSERT/commit (a
    # separate engine.begin() txn). With the old pool_size=2/max_overflow=3 a couple
    # of concurrent lock-holding submits could pin all connections on their lock and
    # starve their own reservation insert (self-deadlock). Bump modestly so a
    # lock-holding submit always has a free connection for its reservation.
    engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True,
                                 pool_size=5, max_overflow=10, connect_args={"timeout": 60})
    asyncio.create_task(_trade_executor_warm_up())
    worker_task = asyncio.create_task(_deferred_order_worker())
    has_creds = _has_broker_credentials()
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


def _refuse_if_stale_buy_price(ticker: str, price_row, action: str) -> None:
    """Refuse (HTTP 422) to size a BUY off a stale daily_prices fallback close.

    `price_row` is the `{close, date}` mapping (or None) from the daily_prices
    fallback. When MAX_PRICE_AGE_DAYS > 0 and the row's date is older than that many
    calendar days, raise — sizing a buy on a price that no longer reflects the
    market (a delisted/halted name with only an old print) would place a wrong-sized
    order. No-op when MAX_PRICE_AGE_DAYS <= 0, the row is missing (the caller's own
    'no price' guard handles that), or the date is absent. Sells never call this.
    """
    if MAX_PRICE_AGE_DAYS <= 0 or price_row is None:
        return
    px_date = price_row.get("date") if hasattr(price_row, "get") else None
    if px_date is None:
        return
    today = datetime.now(timezone.utc).date()
    # px_date may be a date or datetime depending on the column; normalize.
    if hasattr(px_date, "date") and not isinstance(px_date, type(today)):
        px_date = px_date.date()
    age_days = (today - px_date).days
    if age_days > MAX_PRICE_AGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Refusing to size {action} for {ticker}: only a stale daily price "
                f"is available ({px_date}, {age_days}d old > {MAX_PRICE_AGE_DAYS}d "
                f"MAX_PRICE_AGE_DAYS). A buy must not be sized off a stale close."
            ),
        )


async def _size_exit(conn, ticker: str) -> tuple[float, float, dict]:
    """Return (qty, notional, summary) for an exit.

    Sizes the sell from the ticker's position in the LATEST successful alpaca-sync.

    CRITICAL — scope to the latest sync RUN, not "the most recent sync that
    contained this ticker". The naive `WHERE ticker=:t ORDER BY completed_at DESC
    LIMIT 1` reaches back across every sync until it finds one with the ticker, so a
    position CLOSED since the last targeted run still returns a stale qty from an
    old sync — and we submit a sell for shares we no longer own (Alpaca rejects
    "available: 0"). Confirmed in production: a delta proposal from 04:07 outlived
    the position close; syncs advanced to 13:48 showing 0 shares; this query still
    resurrected the old qty and re-fired the exit hourly. Mirrors the (correct)
    latest-sync scoping in _is_already_held — that guard protects entries; this is
    the same protection for exits.

    Refuses (HTTP 409) if:
      - the ticker is NOT held with qty>0 in the latest successful sync (position
        already closed) — never sell a ghost position;
      - the latest sync is older than EXIT_SYNC_MAX_AGE_HOURS (stale broker state).
    """
    pos = (await conn.execute(text(
        "SELECT lp.qty, lp.current_price, lp.market_value, sr.completed_at "
        "FROM live_positions lp "
        "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
        "WHERE sr.run_id = ("
        "  SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
        "  ORDER BY completed_at DESC NULLS LAST LIMIT 1"
        ") AND lp.ticker = :t"
    ), {"t": ticker})).mappings().first()
    # Not in the latest sync (or zero/negative qty) → position is already flat.
    # Refuse rather than size a phantom sell. 409 so the caller records it as a
    # clean refusal, not a generic bad request.
    qty_raw = _f(pos["qty"]) if pos is not None else None
    if pos is None or qty_raw is None or abs(qty_raw) <= 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{ticker} is not held (qty>0) in the latest alpaca-sync — "
                f"position already closed; refusing to size exit. The proposal is "
                f"stale; it will clear on the next delta run."
            ),
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
    qty = abs(qty_raw)
    current_price = _f(pos["current_price"]) or 0.0
    notional = qty * current_price
    # A de-risking exit must never be blocked by a missing local display price.
    # If current_price is absent (notional = qty × 0 = 0) the risk-service's
    # notional_zero guard would otherwise reject the close BEFORE its is_close
    # exemption — and the exit itself is sized qty-only at the broker anyway. So
    # when the price-derived notional is non-positive, fall back to the position's
    # last-known market_value (the broker's own dollar valuation) for a positive
    # AUDIT notional. The risk-service close-exemption is the primary guarantee;
    # this keeps the recorded notional meaningful instead of $0.
    notional_source = "qty_x_current_price"
    if notional <= 0:
        mv = _f(pos["market_value"])
        if mv is not None and abs(mv) > 0:
            notional = abs(mv)
            notional_source = "market_value_fallback"
    return qty, notional, {
        "source": "live_positions_latest_sync",
        "current_price": current_price,
        "notional_source": notional_source,
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
    # Target weight: intent.current_weight (preferred) → portfolio_holdings →
    # equal share of the CURRENT book → 1/DEFAULT_MAX_POSITIONS (last resort)
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
        # L2: derive the fallback from the ACTUAL latest target book size instead
        # of the hardcoded DEFAULT_MAX_POSITIONS (=30), which silently drifted from
        # the active config (max_positions: 35) — a fallback-path entry was sized
        # 1/30 instead of ~1/35. Equal share of the book the strategy is actually
        # running; the constant remains only as the cold-start last resort.
        book_n = (await conn.execute(text(
            "SELECT COUNT(*) FROM portfolio_holdings WHERE run_id = ("
            "  SELECT run_id FROM portfolio_runs WHERE status='success' "
            "  ORDER BY completed_at DESC NULLS LAST LIMIT 1)"
        ))).scalar()
        if book_n and int(book_n) > 0:
            weight = 1.0 / int(book_n)
            weight_source = "book_equal_weight"
        else:
            weight = 1.0 / DEFAULT_MAX_POSITIONS

    # Account funds from latest successful sync. Refuse if older than
    # EXIT_SYNC_MAX_AGE_HOURS so a stale snapshot can't size a wildly
    # wrong order (same threshold as _size_exit's position-staleness check).
    # account_value (total equity) is the sizing basis — see `sizing_basis` below
    # and the docstring: qty = floor(account_value × weight / last_price). A
    # fully-invested book replacing an exited name has ~0 buying_power, so sizing on
    # buying_power would under-size the replacement; the same-open MOO nets the cash.
    # buying_power is loaded only as a fallback when account_value is missing.
    acct = (await conn.execute(text(
        "SELECT account_value, buying_power, completed_at FROM alpaca_sync_runs "
        "WHERE status='success' ORDER BY completed_at DESC NULLS LAST LIMIT 1"
    ))).mappings().first()
    account_value = _f(acct["account_value"]) if acct else None
    buying_power = _f(acct["buying_power"]) if acct else None
    sizing_basis = account_value if account_value is not None else buying_power
    # Sync freshness gate (audit P0): an entry is an OPENING trade — fail CLOSED on
    # an unknown-age snapshot. Previously a sync row with NULL completed_at silently
    # SKIPPED this guard and sized off a possibly-stale account_value. A missing row
    # OR a NULL completion time both mean "freshness cannot be established" → refuse.
    if acct is None or acct["completed_at"] is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "No fresh alpaca-sync available (missing run or no completion "
                "timestamp); refusing to size entry. Re-sync before approving."
            ),
        )
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
            "SELECT close, date FROM daily_prices "
            "WHERE ticker = :t ORDER BY date DESC LIMIT 1"
        ), {"t": ticker})).mappings().first()
        last_price = _f(price_row["close"]) if price_row else None
        # BUY-side freshness bound: an entry is always a buy, so refuse to size off a
        # stale daily close (delisted/halted name with only an old print). Sizing a
        # buy on a price that no longer reflects the market produces a wrong-sized
        # order. The live-position price above is always preferred.
        _refuse_if_stale_buy_price(ticker, price_row, "entry")

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
        # Scope to the SINGLE latest successful sync run (not "the most recent sync
        # that contained this ticker") — see _size_exit / _is_already_held. The naive
        # `ORDER BY completed_at DESC LIMIT 1` reaches back across syncs to ANY run
        # holding the ticker, so a name absent from the LATEST sync (already closed /
        # rotated out) gets resurrected from an older run and mis-sized. (audit #5)
        live_pos = (await conn.execute(text(
            "SELECT lp.market_value, sr.account_value "
            "FROM live_positions lp "
            "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
            "WHERE sr.run_id = ("
            "  SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
            "  ORDER BY completed_at DESC NULLS LAST LIMIT 1"
            ") AND lp.ticker = :t"
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
    # account_value (total equity) instead — and, like entries, do NOT add a
    # buying_power hard-reject (see the note at the buy_add notional line below):
    # buys queue-and-net against the same-open sells, with the delta's _cap_buys
    # as the upstream cash gate.
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
    if acct["completed_at"] is None:
        # Unknown freshness (audit P0): a 'success' row with no completion time can no
        # longer SKIP the staleness gate. Fail CLOSED on the OPENING side (buy_add) —
        # sizing an add off an unknown-age snapshot is unsafe. A reducing sell_trim is
        # allowed through (de-risking must never be trapped, like an exit).
        if action == "buy_add":
            raise HTTPException(
                status_code=409,
                detail=(
                    "No fresh alpaca-sync (no completion timestamp); refusing to "
                    f"size {action}. Re-sync before approving."
                ),
            )
    else:
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

    # Current price — prefer live_positions (scoped to the latest sync run, audit #5),
    # fall back to daily_prices.
    live_px = (await conn.execute(text(
        "SELECT lp.current_price FROM live_positions lp "
        "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
        "WHERE sr.run_id = ("
        "  SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
        "  ORDER BY completed_at DESC NULLS LAST LIMIT 1"
        ") AND lp.ticker = :t"
    ), {"t": ticker})).mappings().first()
    last_price = _f(live_px["current_price"]) if live_px else None
    price_source = "live_positions"
    if last_price is None or last_price <= 0:
        price_row = (await conn.execute(text(
            "SELECT close, date FROM daily_prices WHERE ticker = :t ORDER BY date DESC LIMIT 1"
        ), {"t": ticker})).mappings().first()
        last_price = _f(price_row["close"]) if price_row else None
        price_source = "daily_prices"
        # BUY-side freshness bound: only a buy_add must refuse a stale fallback close
        # (don't over-restrict a sell_trim — de-risking on a stale price is safe).
        if action == "buy_add":
            _refuse_if_stale_buy_price(ticker, price_row, "buy_add")
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
        # Scoped to the latest sync run (audit #5): a ticker absent from the latest
        # sync must read as not-held (held_qty 0) → refuse, not resurrect an old qty.
        held_now = (await conn.execute(text(
            "SELECT lp.qty FROM live_positions lp "
            "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
            "WHERE sr.run_id = ("
            "  SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
            "  ORDER BY completed_at DESC NULLS LAST LIMIT 1"
            ") AND lp.ticker = :t"
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
    # NOTE: no buying_power hard-reject here, by design. A buy_add sizes against
    # account_value exactly like an entry (_size_entry), and like an entry it
    # QUEUES-AND-NETS at the next open: on a fully-invested book buying_power ≈ $0,
    # and the same-open exits/sell_trims free the cash before the deferred drain
    # submits this buy (fill-gated drain, Option B). A pre-emptive
    # `notional > buying_power` guard here contradicted that — it hard-rejected
    # every rebalance buy_add on a fully-invested book (the exact failure the
    # account_value-sizing comment above warns about), so a legitimate top-up that
    # the same-open GOOG sell would fund (e.g. LRCX) failed instead of deferring.
    # The cash gate that defers genuinely-unfundable buys lives upstream in the
    # delta (_cap_buys, which credits same-cycle exit proceeds); Alpaca is the final
    # backstop at submission. So buy_adds are treated identically to entries.
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


async def _call_risk(payload: dict) -> tuple[bool, str, Optional[str], str]:
    """Call risk-service /check. Returns (approved, reason, check_id, rule_triggered).

    check_id is the risk_decisions.decision_id the risk-service persisted; it is
    the FK target of alpaca_orders.risk_check_id (the audit guarantee "which rule
    approved this trade?"). We return it verbatim — or None when the response
    omits it. We deliberately do NOT fabricate a random UUID on a missing
    check_id: a fabricated id points at no risk_decisions row, so an APPROVED
    order would record a dangling risk_check_id and (with the FK now VALIDATEd)
    would fail to insert or, worse, silently lose its audit trail. Callers treat
    "approved but no check_id" as a hard failure and refuse to submit.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(RISK_CALL_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{RISK_SERVICE_URL}/check", json=payload)
                r.raise_for_status()
                data = r.json()
            raw_check_id = data.get("check_id")
            check_id = str(raw_check_id) if raw_check_id else None
            return (
                bool(data.get("approved", False)),
                str(data.get("reason", "")),
                check_id,
                str(data.get("rule_triggered", "unknown")),
            )
        except (_HttpxTransportError, _HttpxStatusError) as exc:
            # Retry only TRANSIENT failures: any transport error (connect/timeout/
            # protocol) or a 5xx. A 4xx is a real client error and is NOT retried.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            transient = isinstance(exc, _HttpxTransportError) or (
                status is not None and 500 <= status < 600
            )
            last_exc = exc
            if transient and attempt < RISK_CALL_RETRIES - 1:
                delay = RISK_CALL_BACKOFF_SECS * (2 ** attempt)
                logger.warning(
                    "risk-service /check transient failure (attempt %d/%d): %s — retrying in %.2fs",
                    attempt + 1, RISK_CALL_RETRIES, exc, delay,
                )
                await asyncio.sleep(delay)
                continue
            raise
    # Exhausted retries on a transient error — re-raise the last one for the caller's
    # existing 502 handler (records a failed attempt; closes can be re-approved).
    raise last_exc  # type: ignore[misc]


# ── Alpaca submission ────────────────────────────────────────────────────────


async def _submit_to_alpaca(payload: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """POST an order to the broker. Returns (broker_order_id, broker_status, error).

    Transport goes through the shared broker adapter (Phase 2b) — the single seam
    the IBKR adapter will implement. Behavior is unchanged for Alpaca."""
    return await _broker().submit_order(payload)


async def _close_position_alpaca(symbol: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Close 100% of a position via the broker adapter (DELETE /v2/positions/{symbol}
    for Alpaca). Same return shape as _submit_to_alpaca; a 404/already-flat maps to
    (None, _ALREADY_CLOSED_ALPACA_STATUS, None).

    Used for full exits instead of a qty-based sell. The broker computes the exact
    held quantity at execution time, so this cannot over-sell a fractional position
    ("insufficient qty available") and is immune to drift between the last
    alpaca-sync and submission.
    """
    return await _broker().close_position(symbol)


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


async def _open_sell_order_for_ticker(
    conn, ticker: str, exclude_intent_id: str
) -> Optional[dict]:
    """Return an OPEN (pending/submitted/deferred) SELL order for `ticker` from a
    DIFFERENT intent, or None.

    Guards against a duplicate in-flight sell. A position whose sell order is
    still UNFILLED has its shares reserved at the broker (available qty = 0),
    while the latest alpaca-sync still shows it HELD (qty > 0) — so _size_exit /
    _size_partial would size a SECOND sell from the held qty and submit it, and
    Alpaca rejects "insufficient qty available (available: 0)". The Step-1
    idempotency check only dedupes the SAME intent_id; a re-proposed exit from a
    *new* delta run is a new intent_id and slips through. This catches the same
    ticker across intents.

    Scoped to side='sell' so an open BUY (buy_add) on the ticker never blocks a
    sell, and excludes `exclude_intent_id` (this intent's own row is already
    handled by the Step-1 guard).
    """
    row = (await conn.execute(text(
        "SELECT id, intent_id, action, status FROM alpaca_orders "
        "WHERE ticker = :t AND side = 'sell' "
        f"AND status IN ({_OPEN_STATUS_SQL}) "
        "AND intent_id IS DISTINCT FROM :iid "
        "ORDER BY created_at DESC LIMIT 1"
    ), {"t": ticker, "iid": exclude_intent_id})).mappings().first()
    return dict(row) if row is not None else None


async def _open_buy_order_for_ticker(
    conn, ticker: str, exclude_intent_id: str
) -> Optional[dict]:
    """Return an OPEN (pending/submitted/deferred) BUY order for `ticker` from a
    DIFFERENT intent, or None — the buy-side mirror of _open_sell_order_for_ticker.

    Guards against a duplicate in-flight BUY across delta runs. The Step-1
    idempotency check only dedupes the SAME intent_id; a re-proposed entry/buy_add
    from a *new* delta run is a new intent_id and slips through. The already-held
    guard (Step 2b) only fires once alpaca-sync has captured the FILL — so a buy
    order that is submitted but NOT YET FILLED (e.g. a day order queued after the
    close, which never fills until the next open) leaves the position un-held, and
    a re-run would stack a SECOND buy. Dedupe on ticker+side so it can't.
    """
    row = (await conn.execute(text(
        "SELECT id, intent_id, action, status FROM alpaca_orders "
        "WHERE ticker = :t AND side = 'buy' "
        f"AND status IN ({_OPEN_STATUS_SQL}) "
        "AND intent_id IS DISTINCT FROM :iid "
        "ORDER BY created_at DESC LIMIT 1"
    ), {"t": ticker, "iid": exclude_intent_id})).mappings().first()
    return dict(row) if row is not None else None


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
                f"WHERE intent_id = :iid AND status IN ({_OPEN_STATUS_SQL}) "
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

        # ── Step 2b2: in-flight buy guard (buy-side only) ─────────────────────
        # Symmetric to the in-flight sell guard below. A buy order that is
        # SUBMITTED but not yet FILLED (e.g. a day order queued after the close)
        # leaves the position un-held, so the already-held guard (Step 2b) can't
        # see it; a re-proposed entry/buy_add from a NEW delta run is a new
        # intent_id and slips past the Step-1 idempotency check. Dedupe on
        # ticker+side so a re-run can't stack a second buy. Clears once the
        # in-flight buy fills or is canceled.
        if side == "buy":
            t0 = datetime.now(timezone.utc)
            async with engine.connect() as conn:
                inflight = await _open_buy_order_for_ticker(conn, ticker, req.intent_id)
            if inflight:
                reason = (
                    f"{ticker} already has an open buy order "
                    f"({inflight['action']}, {inflight['status']}, order {inflight['id']}); "
                    f"skipping duplicate {action} to avoid doubling the position — it "
                    f"clears once the in-flight buy fills or is canceled."
                )
                async with engine.begin() as conn:
                    await _log_step(
                        conn, trace_id, "inflight_buy_check", "skipped", t0,
                        input_summary={"ticker": ticker, "action": action},
                        output_summary={
                            "existing_order_id": str(inflight["id"]),
                            "existing_action": inflight["action"],
                            "existing_status": inflight["status"],
                        },
                    )
                    await conn.execute(
                        text("UPDATE execution_traces SET status='success', completed_at=:now, "
                             "notes='duplicate_inflight_buy' WHERE trace_id=:tid"),
                        {"tid": trace_id, "now": datetime.now(timezone.utc)},
                    )
                return TradeAttemptResponse(
                    status="duplicate", order_id=str(inflight["id"]), trace_id=trace_id,
                    ticker=ticker, action=action, side=side, reason=reason,
                )

        # ── Step 2c: in-flight sell guard (sell-side only) ────────────────────
        # A ticker with an UNFILLED sell order has its shares reserved at the
        # broker (available qty 0) while the latest sync still shows it HELD, so a
        # SECOND exit/sell_trim would be sized from the held qty and rejected by
        # Alpaca "insufficient qty available (available: 0)". Step 1 only dedupes
        # the same intent_id; a re-proposed exit from a NEW delta run is a new
        # intent_id and slips through. Skip the duplicate sell instead.
        if side == "sell":
            t0 = datetime.now(timezone.utc)
            async with engine.connect() as conn:
                inflight = await _open_sell_order_for_ticker(conn, ticker, req.intent_id)
            if inflight:
                reason = (
                    f"{ticker} already has an open sell order "
                    f"({inflight['action']}, {inflight['status']}, order {inflight['id']}); "
                    f"its shares are reserved at the broker. Skipping duplicate {action} "
                    f"to avoid an 'available: 0' rejection — it clears once the in-flight "
                    f"sell fills or is canceled."
                )
                async with engine.begin() as conn:
                    await _log_step(
                        conn, trace_id, "inflight_sell_check", "skipped", t0,
                        input_summary={"ticker": ticker, "action": action},
                        output_summary={
                            "existing_order_id": str(inflight["id"]),
                            "existing_action": inflight["action"],
                            "existing_status": inflight["status"],
                        },
                    )
                    await conn.execute(
                        text("UPDATE execution_traces SET status='success', completed_at=:now, "
                             "notes='duplicate_inflight_sell' WHERE trace_id=:tid"),
                        {"tid": trace_id, "now": datetime.now(timezone.utc)},
                    )
                return TradeAttemptResponse(
                    status="duplicate", order_id=str(inflight["id"]), trace_id=trace_id,
                    ticker=ticker, action=action, side=side, reason=reason,
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

        # ── Steps 4–5 under the cross-intent approve-and-reserve lock (audit #8) ──
        # Serialize [risk-check → record the reservation] per (account, trading_day)
        # with a Postgres advisory lock: a concurrent intent only runs its risk-check
        # AFTER this one's `pending` order (the reservation risk-service counts in its
        # MAX_POSITIONS/turnover SQL) is committed, so the cap can't be breached by a
        # race. The broker submission (Steps 5b/6) runs AFTER the lock releases — the
        # reservation is already visible, so the lock need not span the slow HTTP call.
        # SubmitLockTimeout → fail CLOSED (record 'failed', never submit).
        # See submit_lock.py / docs/risk-safety-rules.md.
        sim_date = intent.get("sim_date")
        trading_day = str(sim_date) if sim_date else datetime.now(timezone.utc).date().isoformat()
        try:
            async with with_submit_lock(engine, DEFAULT_ACCOUNT, trading_day):
                # ── Step 4: risk check ────────────────────────────────────────
                t0 = datetime.now(timezone.utc)
                risk_payload = {
                    "ticker": ticker, "action": action, "side": side,
                    "qty": qty, "notional": notional,
                    "mode": req.mode, "trade_type": _current_trade_type(),
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

                # An APPROVED decision MUST carry a check_id (the risk_decisions.decision_id
                # that alpaca_orders.risk_check_id references for audit). A missing check_id
                # means we cannot tie this order to the rule that approved it — treat it as
                # a hard failure and refuse to submit, rather than fabricating an id that
                # points at no decision. (A rejection with no check_id is harmless — we're
                # not submitting anyway.)
                if approved and not check_id:
                    err = "risk-service approved but returned no check_id — refusing to submit without audit trail"
                    async with engine.begin() as conn:
                        await _record_order(
                            conn, order_id=order_id, intent_id=req.intent_id,
                            ticker=ticker, action=action, side=side, qty=qty,
                            notional=notional, mode=req.mode, trace_id=trace_id,
                            risk_approved=False, risk_reason=err,
                            risk_check_id=None, status="failed",
                            error_message=err,
                        )
                        await conn.execute(
                            text("UPDATE execution_traces SET status='failed', completed_at=:now, "
                                 "notes='risk_no_check_id' WHERE trace_id=:tid"),
                            {"tid": trace_id, "now": datetime.now(timezone.utc)},
                        )
                    raise HTTPException(status_code=502, detail=err)

                # ── Step 4b (ATOMIC per-ticker dedup re-check) ────────────────
                # The Step 2b2/2c in-flight guards above run OUTSIDE this lock — a
                # fast path that avoids sizing/risk work for the common duplicate.
                # But that check-then-act is racy: two concurrent same-ticker /
                # different-intent approvals both pass it before either records, and
                # (unlike intent_id) there is NO DB unique index on ticker to catch
                # the loser. Re-check HERE, under the submit lock, which serializes
                # ALL account submits: a concurrent same-ticker approval has either
                # already committed its order (we see it and skip) or has not yet
                # acquired the lock (it will see OURS). This makes the per-ticker
                # dedup atomic with the reservation. Only matters when we're about
                # to create an OPEN order (approved → 'pending'); a 'risk_rejected'
                # row is not open and can't duplicate a live position.
                if approved:
                    async with engine.connect() as conn:
                        dup = (await _open_buy_order_for_ticker(conn, ticker, req.intent_id)
                               if side == "buy"
                               else await _open_sell_order_for_ticker(conn, ticker, req.intent_id))
                    if dup is not None:
                        async with engine.begin() as conn:
                            await _log_step(
                                conn, trace_id, "inflight_recheck", "skipped", t0,
                                input_summary={"ticker": ticker, "action": action},
                                output_summary={"existing_order_id": str(dup["id"]),
                                                "existing_status": dup["status"]},
                            )
                            await conn.execute(
                                text("UPDATE execution_traces SET status='success', "
                                     "completed_at=:now, notes='duplicate_inflight_recheck' "
                                     "WHERE trace_id=:tid"),
                                {"tid": trace_id, "now": datetime.now(timezone.utc)},
                            )
                        return TradeAttemptResponse(
                            status="duplicate", order_id=str(dup["id"]), trace_id=trace_id,
                            ticker=ticker, action=action, side=side,
                            reason=(f"{ticker} already has an open {side} order "
                                    f"({dup['status']}, order {dup['id']}); concurrent "
                                    f"duplicate {action} skipped (atomic in-lock re-check)."),
                        )

                # ── Step 5: persist alpaca_orders row (THE reservation) ───────
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
                except IntegrityError as exc:
                    # ONLY the intent-open partial unique index (idx_alpaca_orders_
                    # intent_open) means "a concurrent submit for this intent already
                    # reserved an open order" → a legitimate duplicate. Any OTHER
                    # integrity violation (an FK on risk_check_id, a NOT NULL/CHECK,
                    # etc.) is a REAL error and must NOT be masked as 'duplicate' —
                    # that would hide the fault and skip the failed audit row. F3.
                    if "idx_alpaca_orders_intent_open" in str(getattr(exc, "orig", exc)):
                        async with engine.connect() as conn:
                            dupe = (await conn.execute(text(
                                "SELECT id, status FROM alpaca_orders "
                                f"WHERE intent_id=:iid AND status IN ({_OPEN_STATUS_SQL}) "
                                "LIMIT 1"
                            ), {"iid": req.intent_id})).mappings().first()
                        return TradeAttemptResponse(
                            status="duplicate",
                            order_id=str(dupe["id"]) if dupe else order_id,
                            trace_id=trace_id,
                            reason=f"Concurrent submit: intent {req.intent_id} already has an open order",
                        )
                    # Non-dup integrity error: record a failed audit row (risk_check_id
                    # NULL so an FK-on-risk_check_id failure can't recur) and surface the
                    # real error. Nothing was submitted — the reservation INSERT rolled
                    # back — so this is fail-safe, just correctly labeled 'failed'.
                    err = f"record_order integrity error (not a duplicate): {getattr(exc, 'orig', exc)}"[:1000]
                    async with engine.begin() as conn:
                        await _record_order(
                            conn, order_id=order_id, intent_id=req.intent_id,
                            ticker=ticker, action=action, side=side, qty=qty,
                            notional=notional, mode=req.mode, trace_id=trace_id,
                            risk_approved=False, risk_reason=err,
                            risk_check_id=None, status="failed", error_message=err,
                        )
                        await conn.execute(
                            text("UPDATE execution_traces SET status='failed', completed_at=:now, "
                                 "notes='record_order_integrity_error' WHERE trace_id=:tid"),
                            {"tid": trace_id, "now": datetime.now(timezone.utc)},
                        )
                    return TradeAttemptResponse(
                        status="failed", order_id=order_id, trace_id=trace_id,
                        ticker=ticker, action=action, side=side, qty=qty, notional=notional,
                        risk_approved=False, risk_reason=err, risk_check_id=None, reason=err,
                    )
        except SubmitLockTimeout as exc:
            # Could not serialize within the timeout — fail CLOSED: record the attempt
            # and do NOT submit (submitting un-serialized risks the very cap breach the
            # lock exists to prevent).
            err = f"submit serialization lock timed out after {SUBMIT_LOCK_TIMEOUT_SECS:.0f}s: {exc}"
            async with engine.begin() as conn:
                await _record_order(
                    conn, order_id=order_id, intent_id=req.intent_id,
                    ticker=ticker, action=action, side=side, qty=qty,
                    notional=notional, mode=req.mode, trace_id=trace_id,
                    risk_approved=False, risk_reason=err,
                    risk_check_id=None, status="failed", error_message=err,
                )
                await conn.execute(
                    text("UPDATE execution_traces SET status='failed', completed_at=:now, "
                         "notes='submit_lock_timeout' WHERE trace_id=:tid"),
                    {"tid": trace_id, "now": datetime.now(timezone.utc)},
                )
            return TradeAttemptResponse(
                status="failed", order_id=order_id, trace_id=trace_id,
                ticker=ticker, action=action, side=side, qty=qty, notional=notional,
                risk_approved=False, risk_reason=err, risk_check_id=None, reason=err,
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

        # ── Step 5b: submission routing (drain vs inline) ─────────────────────
        # scheduled → fill-gated open drain. immediate → submit inline NOW when the
        # market is open ("Approve now"), else fall back to the drain off-hours.
        # The approval is a GREENLIGHT; the drain worker submits during market hours
        # only, sells-first, fill-gated, one buy at a time. deferred_until = next
        # open (so the drain waits for the session); when the market is already open,
        # deferred_until=NULL so the next pass picks it up. expires_at = that
        # session's close (an unfunded buy expires, never carries to the next day).
        # See docs/architecture.md Option B.
        clock = await _get_alpaca_clock() if req.mode in ("scheduled", "immediate") else None
        if _route_to_drain(req.mode, clock, side=side):
            if clock is None:
                # Clock unreachable → drain ASAP, but stamp a BOUNDED expiry (audit P1).
                # Previously expires_at=None meant the buy could NEVER expire and sat
                # 'deferred' forever, blocking re-proposal of the ticker via the
                # in-flight-buy guard until a manual cancel. A fallback window lets the
                # next daily chain rebuild instead of wedging the name.
                deferred_until, expires_at = None, (
                    datetime.now(timezone.utc) + timedelta(hours=CLOCK_NONE_EXPIRY_HOURS)
                )
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

        # ── Step 6: submit to the broker ──────────────────────────────────────
        if not _has_broker_credentials():
            err = "Broker credentials not configured"
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
            # Deterministic idempotency key (= alpaca_orders row id) so a retry
            # after a crash-in-window can't place a duplicate broker order.
            "client_order_id": order_id,
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

        # Success. A close-position 404 (position already flat) returns no broker
        # order id with alpaca_status='position_already_closed' and alpaca_err=None.
        # That is a TERMINAL no-op — not a submission — so it must NOT enter the
        # 'submitted' lifecycle (a NULL alpaca_order_id 'submitted' row would read as
        # an in-flight order forever and could be re-submitted). Record 'closed'.
        already_closed = (
            alpaca_order_id is None
            and alpaca_status == _ALREADY_CLOSED_ALPACA_STATUS
        )
        final_status = _CLOSED_NOOP_STATUS if already_closed else "submitted"
        submitted_at = datetime.now(timezone.utc)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE alpaca_orders SET status=:st, "
                    "alpaca_order_id=:aid, alpaca_status=:astatus, submitted_at=:s "
                    "WHERE id=:id"
                ),
                {
                    "id": order_id, "st": final_status, "aid": alpaca_order_id,
                    "astatus": alpaca_status, "s": submitted_at,
                },
            )
            await _log_step(
                conn, trace_id, "submit_alpaca", "success", t0,
                input_summary=alpaca_payload,
                output_summary={
                    "alpaca_order_id": alpaca_order_id,
                    "alpaca_status": alpaca_status,
                    "local_status": final_status,
                },
            )
            await conn.execute(
                text("UPDATE execution_traces SET status='success', completed_at=:now "
                     "WHERE trace_id=:tid"),
                {"tid": trace_id, "now": submitted_at},
            )

        return TradeAttemptResponse(
            status=final_status, order_id=order_id, alpaca_order_id=alpaca_order_id,
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


# ── Durable approval enqueue (the dashboard/api fast path) ────────────────────
# Approval is a fast, durable marker on delta_intents drained by the single-consumer
# worker (_process_approved_queue) — NOT a synchronous size→risk→submit on the
# request path. This is the trader-flakiness root-cause fix: no lock contention, no
# HTTP-timeout cascade, refresh-durable. See docs/architecture.md "Design Decision:
# approval = durable enqueue + single-consumer drain".


class EnqueueRequest(BaseModel):
    intent_id: str
    mode: Literal["immediate", "scheduled"]


class EnqueueBatchRequest(BaseModel):
    intent_ids: list[str]
    mode: Literal["immediate", "scheduled"]


class EnqueueResult(BaseModel):
    intent_id: str
    status: str                 # 'queued' | 'duplicate' | 'not_found' | 'invalid'
    reason: Optional[str] = None


class EnqueueBatchResponse(BaseModel):
    results: list[EnqueueResult]
    queued: int


async def _enqueue_one(conn, intent_id: str, mode: str) -> EnqueueResult:
    """Mark a single intent approved (idempotent). Caller owns the txn so a batch is
    atomic. Does NOT size/risk/submit — the worker does, one at a time."""
    try:
        uuid.UUID(intent_id)
    except (ValueError, AttributeError):
        return EnqueueResult(intent_id=intent_id, status="invalid",
                             reason="intent_id must be a UUID")
    # Idempotency: a pre-existing OPEN order means this intent is already in flight.
    existing = (await conn.execute(text(
        "SELECT status FROM alpaca_orders "
        f"WHERE intent_id = :iid AND status IN ({_OPEN_STATUS_SQL}) LIMIT 1"
    ), {"iid": intent_id})).mappings().first()
    if existing:
        return EnqueueResult(intent_id=intent_id, status="duplicate",
                             reason=f"intent already has an open order ({existing['status']})")
    # Mark approved. approval_processed_at reset to NULL so the worker (re)processes
    # exactly once; re-approving a dead attempt is a legitimate retry.
    updated = (await conn.execute(text(
        "UPDATE delta_intents SET approved_at = NOW(), approval_mode = :mode, "
        "approval_processed_at = NULL WHERE id = :iid RETURNING id"
    ), {"iid": intent_id, "mode": mode})).first()
    if updated is None:
        return EnqueueResult(intent_id=intent_id, status="not_found",
                             reason="no such delta_intent")
    return EnqueueResult(intent_id=intent_id, status="queued")


@app.post("/jobs/enqueue", response_model=EnqueueResult)
async def enqueue_order(req: EnqueueRequest) -> EnqueueResult:
    """Durably approve ONE intent and wake the worker. Returns in milliseconds."""
    async with engine.begin() as conn:
        result = await _enqueue_one(conn, req.intent_id, req.mode)
    if result.status == "queued":
        _queue_kick_event().set()
    return result


@app.post("/jobs/enqueue-batch", response_model=EnqueueBatchResponse)
async def enqueue_orders(req: EnqueueBatchRequest) -> EnqueueBatchResponse:
    """Durably approve a SET of intents atomically and wake the worker ONCE.

    Refresh-durable: the whole selection is persisted before any risk/broker work, so
    a browser refresh mid-batch can't strand the tail (the old client-side
    Promise.all / for-await failure mode)."""
    results: list[EnqueueResult] = []
    async with engine.begin() as conn:
        for iid in req.intent_ids:
            results.append(await _enqueue_one(conn, iid, req.mode))
    queued = sum(1 for r in results if r.status == "queued")
    if queued:
        _queue_kick_event().set()
    return EnqueueBatchResponse(results=results, queued=queued)


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
    local_cancel_failed: int = 0  # rows whose broker cancel was NOT confirmed
    trace_id: Optional[str] = None
    reason: Optional[str] = None


class CancelDeferredResponse(BaseModel):
    status: str
    cancelled: int
    trace_id: Optional[str] = None


@app.post("/jobs/cancel-deferred", response_model=CancelDeferredResponse)
async def cancel_deferred() -> CancelDeferredResponse:
    """Purge un-sent (status='deferred') orders — a LOCAL-only cancel.

    Deferred orders were approved but never sent to the broker (no
    alpaca_order_id; the fill-gated drain would submit them at the next open), so
    flipping them to 'canceled' here is risk-free — no Alpaca call, nothing to
    unwind. The scheduler calls this just before each delta step so a freshly
    built target supersedes the previous cycle's queued-but-unsent orders: without
    it, a stale deferred sell both fires wrongly at the open AND blocks the new
    delta from re-queueing the correct decision (the duplicate guards treat
    'deferred' as an open order). Submitted/at-broker orders are intentionally NOT
    touched — those go through /jobs/cancel-all-orders (a real broker cancel).
    """
    trace_id = str(uuid.uuid4())
    t0 = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO execution_traces (trace_id, job_type, status, started_at) "
                 "VALUES (:tid, 'cancel_deferred', 'running', :now)"),
            {"tid": trace_id, "now": t0},
        )
        result = await conn.execute(
            text("UPDATE alpaca_orders SET status='canceled', deferred_until=NULL, "
                 "error_message=COALESCE(error_message, '') || ' [superseded by new delta run]' "
                 "WHERE status='deferred'")
        )
        n = result.rowcount or 0
        await _log_step(
            conn, trace_id, "cancel_deferred", "success", t0,
            output_summary={"cancelled": n},
        )
        await conn.execute(
            text("UPDATE execution_traces SET status='success', completed_at=:now WHERE trace_id=:tid"),
            {"tid": trace_id, "now": datetime.now(timezone.utc)},
        )
    return CancelDeferredResponse(status="ok", cancelled=n, trace_id=trace_id)


@app.post("/jobs/cancel-all-orders", response_model=CancelAllResponse)
async def cancel_all_orders(confirm: str = "") -> CancelAllResponse:
    """Cancel every open order at Alpaca and mark local rows as canceled.

    Operational tool for freeing up buying_power that's reserved by queued
    or pending MOO orders. Calls Alpaca's `DELETE /v2/orders` (multi-status)
    and updates local `alpaca_orders` rows whose status is in
    ('pending','submitted','accepted','new','partial_fill') to 'canceled'.

    Safety:
      - Requires `?confirm=yes` query param to avoid accidental wipes
      - Short-circuits with `no_credentials` if the active broker has none
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
    if not _has_broker_credentials():
        async with engine.begin() as conn:
            await _log_step(
                conn, trace_id, "alpaca_cancel_all", "skipped", t0,
                error_message="Broker credentials not configured",
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
    # Track per-order broker outcome by Alpaca order id so the LOCAL update only
    # marks 'canceled' the rows the broker CONFIRMED. confirmed_ids / failed_ids
    # hold the Alpaca order ids; an id absent from confirmed_ids never gets the
    # terminal 'canceled' (it would falsely claim the order is dead while it may
    # still be live at the broker). `whole_call_failed` means we have NO per-order
    # info at all (HTTP non-2xx or transport exception) → every submitted local
    # row is treated as unconfirmed.
    alpaca_results: list[dict[str, Any]] = []
    alpaca_errors: list[dict[str, Any]] = []
    confirmed_ids: set[str] = set()
    failed_ids: set[str] = set()
    whole_call_failed = False
    try:
        # Transport via the broker adapter (Phase 2b). Returns
        # (http_status, parsed_body, text); parsed_body is the per-order
        # multi-status list (Alpaca 207) or None.
        status_code, body, body_text = await _broker().cancel_all_orders()
        # Alpaca returns 207 multi-status with a list of {id, status} items
        if status_code in (200, 207):
            alpaca_results = body if isinstance(body, list) else []
            for r in alpaca_results:
                if not isinstance(r, dict):
                    continue
                code = r.get("status")
                oid = r.get("id")
                ok = code is not None and 200 <= int(code) < 300
                if ok:
                    if oid is not None:
                        confirmed_ids.add(str(oid))
                else:
                    # 2xx → success, anything else → record as error AND mark the
                    # broker order id as a CONFIRMED FAILURE so the local row is
                    # NOT flipped to 'canceled'.
                    alpaca_errors.append({"id": oid, "status": code, "body": r.get("body")})
                    if oid is not None:
                        failed_ids.add(str(oid))
            cancel_count = len(confirmed_ids)
        else:
            cancel_count = 0
            whole_call_failed = True
            alpaca_errors.append({"http_status": status_code, "body": (body_text or "")[:500]})
    except Exception as exc:
        cancel_count = 0
        whole_call_failed = True
        alpaca_errors.append({"error": str(exc)[:500]})

    # ── Update local rows ────────────────────────────────────────────────────
    # Non-deferred working states (deferred orders have their own purge path).
    # 'partial_fill' is the token alpaca-sync persists (NOT 'partially_filled').
    #
    # CRITICAL (audit #11): only mark a local row 'canceled' when its broker cancel
    # was CONFIRMED. A row whose broker cancel FAILED or whose outcome is UNKNOWN
    # must NOT claim 'canceled' — the broker order may still be live. Such rows get
    # the distinct non-terminal status 'cancel_failed' so a follow-up can retry and
    # the dashboard never shows a falsely-dead order.
    #   - alpaca_order_id IN confirmed_ids                → 'canceled'
    #   - alpaca_order_id IS NULL (never reached broker)  → 'canceled' (nothing live)
    #   - anything else (failed / unknown / whole-call)   → 'cancel_failed'
    open_statuses = ("pending", "submitted", "accepted", "new", "partial_fill")
    async with engine.begin() as conn:
        if whole_call_failed:
            # No per-order info: local-only rows (no broker order) can still be
            # canceled; everything with a broker order id is unconfirmed.
            canceled_res = await conn.execute(
                text("UPDATE alpaca_orders SET status='canceled', "
                     "error_message=COALESCE(error_message, '') || ' [canceled by /jobs/cancel-all-orders]' "
                     "WHERE status = ANY(:open) AND alpaca_order_id IS NULL"),
                {"open": list(open_statuses)},
            )
            failed_res = await conn.execute(
                text("UPDATE alpaca_orders SET status='cancel_failed', "
                     "error_message=COALESCE(error_message, '') || ' [cancel-all: broker cancel unconfirmed]' "
                     "WHERE status = ANY(:open) AND alpaca_order_id IS NOT NULL"),
                {"open": list(open_statuses)},
            )
        else:
            canceled_res = await conn.execute(
                text("UPDATE alpaca_orders SET status='canceled', "
                     "error_message=COALESCE(error_message, '') || ' [canceled by /jobs/cancel-all-orders]' "
                     "WHERE status = ANY(:open) "
                     "AND (alpaca_order_id IS NULL OR alpaca_order_id = ANY(:confirmed))"),
                {"open": list(open_statuses), "confirmed": list(confirmed_ids)},
            )
            failed_res = await conn.execute(
                text("UPDATE alpaca_orders SET status='cancel_failed', "
                     "error_message=COALESCE(error_message, '') || ' [cancel-all: broker cancel unconfirmed]' "
                     "WHERE status = ANY(:open) "
                     "AND alpaca_order_id IS NOT NULL "
                     "AND NOT (alpaca_order_id = ANY(:confirmed))"),
                {"open": list(open_statuses), "confirmed": list(confirmed_ids)},
            )
        local_updated = canceled_res.rowcount or 0
        local_cancel_failed = failed_res.rowcount or 0
        await _log_step(
            conn, trace_id, "alpaca_cancel_all", "success", t0,
            input_summary={"open_statuses": list(open_statuses)},
            output_summary={
                "alpaca_cancel_count": cancel_count,
                "alpaca_errors": alpaca_errors[:10],   # cap audit row size
                "local_orders_updated": local_updated,
                "local_cancel_failed": local_cancel_failed,
            },
        )
        await conn.execute(
            text("UPDATE execution_traces SET status='success', completed_at=:now "
                 "WHERE trace_id=:tid"),
            {"tid": trace_id, "now": datetime.now(timezone.utc)},
        )

    return CancelAllResponse(
        status="ok" if not alpaca_errors and not local_cancel_failed else "partial",
        alpaca_cancel_count=cancel_count,
        alpaca_errors=alpaca_errors[:20],
        local_orders_updated=local_updated,
        local_cancel_failed=local_cancel_failed,
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
    has_credentials = _has_broker_credentials()
    return {
        "status": "ok",
        "service": "trade-executor",
        "has_credentials": has_credentials,
    }
