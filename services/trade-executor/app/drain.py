"""Pure decision logic for the fill-gated market-open order drain (Option B).

Kept separate from main.py so the sells-first / fill-gate / buying-power
sequencing is unit-testable without Alpaca or a database. main.py performs the
I/O (poll fills, fetch the account, submit orders, update rows); this module only
DECIDES what to do from a plain snapshot of the current queue.

See docs/architecture.md "Design Decision: fill-gated market-open order draining".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class DeferredOrder:
    id: str
    side: str                          # 'buy' | 'sell'
    notional: Optional[float]
    submitted_at: Optional[datetime]   # set once submitted (drives the sell fill timeout)
    expires_at: Optional[datetime]     # session close stamped at enqueue; None = never expires


@dataclass
class DrainDecision:
    submit_sells: list[str] = field(default_factory=list)
    submit_buys: list[str] = field(default_factory=list)
    expire: list[str] = field(default_factory=list)
    waiting_on_sells: bool = False     # buys held this pass because sells aren't all filled


def _sell_timed_out(submitted_at: Optional[datetime], now: datetime, timeout_secs: float) -> bool:
    """A submitted sell that hasn't filled within the timeout stops blocking buys.

    Market sells fill within seconds of the open; a sell still unfilled after the
    timeout is an exceptional halt, and must not wedge the whole book forever. The
    dependent buy then simply won't fit the (un-credited) buying power and expires.
    """
    if submitted_at is None:
        return False
    return (now - submitted_at).total_seconds() > timeout_secs


def plan_drain(
    *,
    is_open: bool,
    now: datetime,
    deferred_sells: list[DeferredOrder],            # status='deferred', side='sell', due
    unfilled_submitted_sells: list[DeferredOrder],  # status='submitted', side='sell', filled_at IS NULL
    deferred_buys: list[DeferredOrder],             # status='deferred', side='buy', due (OLDEST FIRST)
    buying_power: Optional[float],
    sell_fill_timeout_secs: float,
) -> DrainDecision:
    """Decide a single drain pass.

    Order of operations:
      1. Expire any deferred BUY past its session-close `expires_at`, regardless of
         market state — a stale buy never carries to the next day (the next daily
         chain rebuilds a fresh target).
      2. When the market is CLOSED, do nothing else; queued orders wait for the open.
      3. When OPEN: submit every not-yet-submitted SELL. Hold ALL buys until every
         sell is filled (or has exceeded the fill timeout). Once sells are done,
         release buys oldest-first, one at a time, each only if live buying_power
         covers its notional — subtracting as we go so a single pass never
         over-commits the same cash.
    """
    decision = DrainDecision()
    decision.expire = [
        b.id for b in deferred_buys if b.expires_at is not None and b.expires_at <= now
    ]

    if not is_open:
        decision.waiting_on_sells = bool(deferred_sells or unfilled_submitted_sells)
        return decision

    # Market open — submit all queued sells first.
    decision.submit_sells = [s.id for s in deferred_sells]

    blocking_sells = [
        s for s in unfilled_submitted_sells
        if not _sell_timed_out(s.submitted_at, now, sell_fill_timeout_secs)
    ]
    # If we just queued sells this pass they are not submitted yet, so buys must
    # also wait at least until the next pass when those sells can fill.
    decision.waiting_on_sells = bool(deferred_sells) or bool(blocking_sells)
    if decision.waiting_on_sells:
        return decision

    # All sells filled (or timed out): release buys within available buying power.
    if buying_power is None:
        return decision
    bp = float(buying_power)
    expired = set(decision.expire)
    for b in deferred_buys:               # caller passes oldest-first
        if b.id in expired or b.notional is None:
            continue
        if b.notional <= bp + 1e-6:
            decision.submit_buys.append(b.id)
            bp -= b.notional
    return decision
