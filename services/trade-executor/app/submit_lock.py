"""Cross-intent approve-and-reserve serialization (audit finding #8).

Risk approval and the local creation of the reservation (the committed `pending`
`alpaca_orders` row) are NOT atomic across DIFFERENT intents. Two concurrent
submits for two distinct new-ticker entries can both run risk-service /check
BEFORE either commits its `pending` row, so neither sees the other's reservation,
both pass the same MAX_POSITIONS / position-pct / turnover gate, and both commit —
breaching the cap.

Risk-service already counts committed pending `alpaca_orders` rows
(OPEN_ORDER_STATUSES) and `delta_intents` as reservations in its projected-count
and turnover SQL, so a committed pending order row IS the reservation. The defect
is purely ORDERING: the executor records the order row AFTER calling risk.

Fix: serialize the critical section [risk-check -> record_order(committed)] per
(account, trading_day) with a Postgres SESSION-level advisory lock held on a
DEDICATED connection. A waiting submit only proceeds after the prior submit has
committed its reservation, so its /check sees that reservation and is correctly
rejected at capacity.

Design notes (see docs/risk-safety-rules.md "Atomic approve-and-reserve"):
  - Key = stable 64-bit signed hash of f"trade_submit:{account}:{trading_day}".
    Different accounts/days hash to different keys → do NOT block each other.
  - Bounded acquisition (pg_try_advisory_lock in a retry loop, total timeout
    SUBMIT_LOCK_TIMEOUT_SECS, default 30) so a hung risk call can't deadlock all
    submits. On timeout the context manager raises SubmitLockTimeout; the caller
    fails CLOSED (records the order 'failed', does NOT submit to the broker).
  - SESSION-level lock (pg_advisory_lock / _unlock), held across the section on its
    own connection; the reservation INSERT/commit runs in a SEPARATE engine.begin()
    txn. Advisory locks are independent of data transactions — what matters is the
    order: lock acquired -> /check -> reservation committed -> unlock.
  - Additive to the per-intent unique-index idempotency guard, not a replacement.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("trade-executor")

# Single-account system: the Alpaca account is fixed. Kept as a named constant so
# the key derivation is explicit and a future multi-account world can thread a real
# account id through without changing the hashing.
DEFAULT_ACCOUNT = "alpaca-paper"

try:
    SUBMIT_LOCK_TIMEOUT_SECS = max(0.0, float(os.getenv("SUBMIT_LOCK_TIMEOUT_SECS", "30")))
except ValueError:
    SUBMIT_LOCK_TIMEOUT_SECS = 30.0

# Poll interval for the bounded pg_try_advisory_lock retry loop. Short so a freed
# lock is re-acquired promptly; the per-section work is sub-second.
try:
    SUBMIT_LOCK_POLL_SECS = max(0.01, float(os.getenv("SUBMIT_LOCK_POLL_SECS", "0.1")))
except ValueError:
    SUBMIT_LOCK_POLL_SECS = 0.1

# Postgres advisory lock keys are bigint (signed 64-bit). Mask the hash into that
# range. Range: [-2^63, 2^63 - 1].
_INT64_MIN = -(2 ** 63)
_UINT64_MASK = (2 ** 64) - 1


class SubmitLockTimeout(Exception):
    """Raised when the per-(account, trading_day) advisory lock could not be
    acquired within SUBMIT_LOCK_TIMEOUT_SECS. The caller MUST fail closed (record
    the order as failed; do NOT submit to the broker)."""


def submit_lock_key(account: str, trading_day: str) -> int:
    """Derive a STABLE signed-64-bit advisory-lock key from (account, trading_day).

    Pure + deterministic so it is unit-testable and so two processes computing the
    key for the same (account, day) collide on the same lock. Distinct accounts or
    distinct days produce (with overwhelming probability) distinct keys and so do
    not serialize against each other.

    `trading_day` is normalized to a string; callers pass the same value the
    risk/turnover scoping uses (sim_date when present, else local CURRENT_DATE).
    """
    raw = f"trade_submit:{account}:{trading_day}"
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    unsigned = int.from_bytes(digest[:8], "big") & _UINT64_MASK
    # Map unsigned 64-bit into signed 64-bit range for Postgres bigint.
    return unsigned + _INT64_MIN


@asynccontextmanager
async def with_submit_lock(
    engine: AsyncEngine,
    account: str,
    trading_day: str,
    *,
    timeout_secs: Optional[float] = None,
    poll_secs: Optional[float] = None,
):
    """Async context manager that holds a Postgres SESSION-level advisory lock for
    (account, trading_day) on a DEDICATED connection for the body's duration.

    Acquisition is BOUNDED: pg_try_advisory_lock is polled until it succeeds or the
    total timeout elapses, then SubmitLockTimeout is raised (caller fails closed).
    The lock is ALWAYS released in `finally` (covering both normal exit and any
    exception raised inside the body — e.g. a risk-check error), and the dedicated
    connection is closed.

    Usage:
        async with with_submit_lock(engine, account, day):
            approved, ... = await _call_risk(...)
            # record_order(committed) in a separate engine.begin() txn
    """
    if timeout_secs is None:
        timeout_secs = SUBMIT_LOCK_TIMEOUT_SECS
    if poll_secs is None:
        poll_secs = SUBMIT_LOCK_POLL_SECS

    key = submit_lock_key(account, trading_day)
    conn = await engine.connect()
    acquired = False
    try:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_secs
        while True:
            got = (await conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": key}
            )).scalar()
            if got:
                acquired = True
                break
            if loop.time() >= deadline:
                raise SubmitLockTimeout(
                    f"could not acquire submit lock for account={account} "
                    f"trading_day={trading_day} within {timeout_secs:.1f}s"
                )
            await asyncio.sleep(poll_secs)
        try:
            yield
        finally:
            # Release the session-level lock. Best-effort: a failure here must not
            # mask an exception from the body, and the connection close below also
            # drops any session-held lock.
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("submit-lock unlock failed (key=%s): %s", key, exc)
    finally:
        # Closing the connection also releases any session-level advisory lock it
        # still holds (a hard guarantee even if the explicit unlock above failed).
        await conn.close()
        if acquired:
            logger.debug("submit lock released (account=%s day=%s)", account, trading_day)
