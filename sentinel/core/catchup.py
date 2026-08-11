"""Convergence after absence, and re-projection after external cash.

## The rule this enforces

```text
historical sessions advance DETERMINISTIC STATE.
historical EXECUTION INTENT is never replayed.
```

`docs/sentinel-execution-contract.md` states it; `executor._assert_current_plan`
refuses to run a superseded plan; and until now nothing PRODUCED the single
surviving intent that rule presupposes. The obvious implementation of "we were
offline for three days" walks the missed sessions and executes each one:

```text
Monday      controller wanted 0%       ->  liquidate
Tuesday     controller wanted 55%      ->  re-enter
Wednesday   controller wanted 100%     ->  rotate
Thursday    controller wants 100%      ->  ...
```

All four fire at Thursday's prices, against Thursday's book. Three round trips
of slippage and commission to arrive where one Thursday plan arrives directly —
and the first of them liquidates a live account because of what a Monday that
is over wanted.

So `catch_up` replays the state and emits ONE plan. Peaks, ages, review clocks,
cooldowns and exposure all advance exactly as they would have; the broker sees
a single intent, for now.

## The pointer is durable and advances WITH the state

`last_processed_session` is a row, written in the same transaction as the state
the session produced. Written after the whole loop instead, a crash replays
sessions that already advanced — and Wealth Core's state is path-dependent, so
a replayed session double-ages every episode. Written before, a crash SKIPS a
session, which is the silent one.

## Wealth Core is a SEAM here, not a dependency

`advance_state` and `decide` are injected. That is deliberate and it is not
abstraction for its own sake: Wealth Core is built and NOT ACTIVATED (see
docs/wealth-core-certification.md), and the exposure controller does not exist
yet — item E pins exposure at 1.00. Wiring either in here would mean this
module could not be tested or shipped until both land, and it would put a
NO-GO engine on the production path. The orchestration is the thing being built
and the thing being certified; what it drives is supplied by the caller.

## Re-projection is not replay

An external cash flow changes what is investable. It does not change what
Wealth Core did — the historical book is a function of PRICE history, and no
peak, age or cooldown moves because money arrived. `reproject` re-sizes the
CURRENT target against the new NAV and advances nothing.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable, Mapping, Optional

from sentinel.core.cashflow import Attribution, NavReconciliation
from sentinel.execution import journal
from sentinel.execution.plan import ExecutionPlan


class NavUnobserved(RuntimeError):
    """A re-projection was attempted with no NAV.

    Refused rather than defaulted. Sizing a basket against a guessed balance
    produces a confident wrong order, and the guess would be wrong by exactly
    the amount of the flow that prompted the re-projection.
    """


@dataclass
class CatchUpResult:
    sessions_replayed: int
    through: date
    plan: Optional[ExecutionPlan]
    superseded: int = 0
    state: object = None
    caveats: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"sessions_replayed": self.sessions_replayed,
                "through": self.through.isoformat(),
                "plan": self.plan.to_dict() if self.plan else None,
                "superseded_plans": self.superseded,
                "caveats": list(self.caveats)}


@dataclass
class Reprojection:
    """A re-sized current target, and what execution is permitted to do with it."""

    plan: Optional[ExecutionPlan]
    #: Desired shares minus held minus already-committed. The number that stops
    #: a re-projection during a partial fill from buying the position twice.
    remaining: dict = field(default_factory=dict)
    #: Securities with a WORKING order that must be cancelled and CONFIRMED
    #: cancelled before the new intent is sized against them. Never silently
    #: superseded: declaring a live order superseded abandons it.
    cancel_first: tuple = ()
    #: Only reductions may proceed. Set when the inputs are good enough to sell
    #: on and not good enough to buy on — the missed-open asymmetry.
    reduction_only: bool = False
    caveats: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"plan": self.plan.to_dict() if self.plan else None,
                "remaining": {k: str(v) for k, v in sorted(self.remaining.items())},
                "cancel_first": list(self.cancel_first),
                "reduction_only": self.reduction_only,
                "caveats": list(self.caveats)}


# ── the durable pointer ──────────────────────────────────────────────────────

#: One row, one meaning. A table with many rows would invite "the latest by
#: timestamp", and a clock is not an ordering of trading sessions.
_CURSOR = "catchup"


def last_processed_session(conn) -> Optional[date]:
    with conn.cursor() as cur:
        cur.execute("SELECT session FROM sentinel_processed_sessions"
                    " WHERE cursor_name = %s", (_CURSOR,))
        row = cur.fetchone()
    return None if row is None else _d(row[0])


def _mark_processed(conn, session: date) -> None:
    """NEVER MOVES BACKWARDS. A caller replaying an old window must not rewind
    the frontier of what has already advanced — that is how a session gets
    aged twice."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions (cursor_name, session)"
            " VALUES (%s,%s) ON CONFLICT (cursor_name) DO UPDATE SET"
            "   session = GREATEST(sentinel_processed_sessions.session,"
            "                      EXCLUDED.session),"
            "   updated_at = NOW()",
            (_CURSOR, session.isoformat()))


# ── catch-up ─────────────────────────────────────────────────────────────────

def catch_up(conn, *, through, missed, advance_state: Callable,
             decide: Callable, state=None) -> CatchUpResult:
    """Advance deterministic state across `missed`, then emit ONE plan.

    `advance_state(session, state) -> state` is the deterministic step: Wealth
    Core's session, and the controller's. It must not touch a broker.

    `decide(session, state) -> ExecutionPlan | None` is called ONCE, for the
    final session. Calling it per session and keeping the last would be the
    same result at four times the cost and would tempt someone to execute the
    intermediates.

    Sessions at or before `last_processed_session` are skipped: the state is
    path-dependent, so replaying one double-ages every episode in the book.
    """
    with journal.writer_lock(conn):
        return _catch_up_locked(conn, through=_d(through),
                                missed=[_d(m) for m in missed],
                                advance_state=advance_state, decide=decide,
                                state=state)


def _catch_up_locked(conn, *, through: date, missed, advance_state, decide,
                     state) -> CatchUpResult:
    done = last_processed_session(conn)
    owed = sorted(s for s in missed if done is None or s > done)

    replayed = 0
    for session in owed:
        # ONE TRANSACTION per session: the state the step produced and the
        # pointer that says it happened commit together or not at all. Split
        # them and a crash between the two either replays a session (double
        # ageing) or skips it (silent, permanent).
        state = advance_state(session.isoformat(), state)
        _mark_processed(conn, session)
        conn.commit()
        replayed += 1

    plan = decide(through.isoformat(), state)
    superseded = 0
    if plan is not None:
        journal.save_plan(conn, plan)
        superseded = journal.supersede_all_but(conn, plan.plan_id) or 0
        plan = journal.load_plan(conn, plan.plan_id)
    _mark_processed(conn, through)
    conn.commit()

    return CatchUpResult(sessions_replayed=replayed, through=through,
                         plan=plan, superseded=superseded, state=state)


# ── projection ───────────────────────────────────────────────────────────────

def project(*, weights: Mapping[str, Decimal], nav: Decimal,
            exposure: Decimal, marks: Mapping[str, Decimal]) -> dict:
    """Target WEIGHTS at a given NAV -> target SHARES.

        shares = floor(nav * weight * exposure / mark)

    EXPOSURE SCALES THE BASKET, NEVER THE MEMBERSHIP. Sentinel decides how much
    of Wealth Core's book to hold, never what is in it — 0.55 buys every name at
    0.55x, it does not buy 55% of the names.

    FLOORED, not rounded. Rounding up buys a share the account cannot fund at
    the margin, and across 25 slots those roundings accumulate into leverage the
    envelope is supposed to exclude. Decimal throughout: this reaches a broker.

    A security with no mark is OMITTED rather than sized at zero. Zero is a
    target — "hold none of this" — and it would liquidate a position because a
    price was missing.

    **OMISSION IS NOT SUFFICIENT ON ITS OWN**, and this function cannot make it
    so: to a downstream reader an absent key and a zero are the same thing.
    `compute_delta` reads a missing basket entry as `desired = 0` and sells the
    lot. Whoever composes this into a plan must decide what an omitted-but-held
    security should be — see `unpriceable` and `reproject`, which set it to the
    quantity currently held so no economic decision is made at all.
    """
    out: dict = {}
    for sid, w in weights.items():
        mark = marks.get(sid)
        if not mark or mark <= 0:
            continue
        qty = (Decimal(nav) * Decimal(w) * Decimal(exposure)) / Decimal(mark)
        out[sid] = qty.to_integral_value(rounding="ROUND_FLOOR")
    return out


def unpriceable(weights: Mapping[str, Decimal],
                marks: Mapping[str, Decimal]) -> tuple:
    """Securities Wealth Core still WANTS and nothing can price.

    Separated from `project` because the distinction it enables is not about
    projection at all — it is about telling two situations apart that both end
    up as "no entry in the target basket":

    ```text
    not in weights        Wealth Core no longer wants it   -> SELL ALL
    in weights, no mark   we cannot value it               -> HOLD, no decision
    ```

    Only the first is a reason to sell, and selling it needs no mark: the share
    count is exactly known. The second is a data outage wearing a target's
    clothing, and treating it as one liquidates a position because a price was
    missing — the failure `project`'s docstring forbids and, before this
    existed, `reproject` performed anyway.
    """
    return tuple(sorted(sid for sid in weights
                        if not marks.get(sid) or marks[sid] <= 0))


def reproject(conn, *, session, nav: Optional[Decimal],
              weights: Mapping[str, Decimal], exposure: Decimal,
              marks: Mapping[str, Decimal],
              held: Optional[Mapping[str, Decimal]] = None,
              committed: Optional[Mapping[str, Decimal]] = None,
              marks_stale: bool = False,
              nav_reconciliation: Optional[NavReconciliation] = None,
              advance_state: Optional[Callable] = None) -> Reprojection:
    """Re-size the CURRENT target against a new NAV. Advances NOTHING.

    This is the whole difference between a cash flow and a market event. The
    historical book is a function of price history; a deposit changes what is
    investable and nothing else, so no session is replayed and
    `last_processed_session` does not move. `advance_state` is accepted only so
    a caller can assert it is never called.
    """
    if nav is None:
        raise NavUnobserved(
            "no NAV was observed, so the basket cannot be sized. The account "
            "balance is the one input a re-projection cannot guess — and the "
            "guess would be wrong by exactly the flow that prompted it. Retry "
            "when the broker answers; the declared flow is already durable.")

    d = _d(session)
    held = {k: Decimal(v) for k, v in (held or {}).items()}
    committed = {k: Decimal(v) for k, v in (committed or {}).items()}
    caveats: list = []

    desired = project(weights=weights, nav=nav, exposure=exposure, marks=marks)

    # A SECURITY WE CANNOT PRICE HOLDS WHAT IT HOLDS.
    #
    # `project` omits it, correctly refusing to guess a quantity. Left omitted,
    # that refusal becomes the opposite instruction the moment anything reads
    # the basket: `compute_delta` sees no entry, takes `desired = 0`, and sells
    # the position — and the sweep below would independently arrive at the same
    # place. "We cannot value this" and "we want none of this" are different
    # facts and only the second is a reason to sell.
    #
    # `held + committed`, not `held` alone: 40 owned with 60 working is a
    # position of 100 in flight, and a target of 40 would cancel the difference
    # while a target that ignored `committed` would order it twice.
    blind = unpriceable(weights, marks)
    for sid in blind:
        outstanding = held.get(sid, Decimal(0)) + committed.get(sid, Decimal(0))
        if outstanding:
            desired[sid] = outstanding
    if blind:
        caveats.append(
            f"NO MARK for {list(blind)} — held quantities are carried unchanged "
            f"and no purchase is sized. The corpus cannot value these today; "
            f"that is a data outage, not a target of zero, and selling on it "
            f"would liquidate a position because a price was missing.")

    # ── may this re-projection INCREASE exposure? ────────────────────────────
    #
    # The missed-open asymmetry, applied to input quality rather than to time.
    # Both of these degrade the SIZE of an order without degrading the
    # direction, so selling remains safe and buying does not: a reduction sized
    # slightly wrong still reduces, while a purchase sized against a stale mark
    # or an unaccounted balance commits real money at an unknown quantity.
    reduction_only = False
    if marks_stale:
        reduction_only = True
        caveats.append(
            "marks are STALE — the corpus has not advanced to this session. "
            "Reductions proceed: a withdrawal creates an obligation the account "
            "must meet, and doing nothing is not the conservative choice it "
            "looks like. Increases are refused.")
    if (nav_reconciliation is not None
            and nav_reconciliation.attribution is Attribution.UNEXPLAINED):
        reduction_only = True
        caveats.append(
            f"NAV is UNEXPLAINED by {nav_reconciliation.unexplained} — neither "
            f"marked P&L nor a declared flow accounts for the move. De-risking "
            f"is always permitted; increasing exposure against a balance nobody "
            f"can account for is not.")

    # A HELD SECURITY THE TARGET DOES NOT MENTION IS AN EXPLICIT ZERO.
    #
    # Wealth Core dropped it, so it is sold — and selling needs no mark, the
    # share count is exactly known. Written into the basket rather than left
    # absent because absent and zero are the same thing to `compute_delta`, and
    # a plan that relies on a reader's default is a plan that does not say what
    # it means. That ambiguity is precisely what turned an unpriceable security
    # into a liquidation one branch above.
    for sid in held:
        desired.setdefault(sid, Decimal(0))

    remaining = {
        sid: qty - held.get(sid, Decimal(0)) - committed.get(sid, Decimal(0))
        for sid, qty in desired.items()}

    if reduction_only and any(v > 0 for v in remaining.values()):
        increases = {k: str(v) for k, v in sorted(remaining.items()) if v > 0}
        caveats.append(
            f"increase(s) {increases} REFUSED. No plan is emitted rather than a "
            f"reduced one: a plan carrying only half of an intent is a plan "
            f"whose fingerprint says it was fully satisfied when it was not.")
        return Reprojection(plan=None, remaining=remaining,
                            reduction_only=True, caveats=caveats)

    plan = ExecutionPlan(
        plan_id=f"reproj-{uuid.uuid4().hex[:12]}",
        decision_session=d, effective_session=d,
        target_exposure=Decimal(exposure), target_basket=desired,
        data_version=_current_version(conn))
    journal.save_plan(conn, plan)
    journal.supersede_all_but(conn, plan.plan_id)
    conn.commit()

    # WORKING ORDERS ARE CANCELLED, NOT SUPERSEDED. Supersession retires an
    # UNSENT intent; a live order at the broker is a real obligation, and
    # declaring it superseded abandons it — the shares still arrive and nothing
    # is expecting them.
    cancel_first = tuple(sorted(sid for sid, q in committed.items() if q))

    return Reprojection(plan=journal.load_plan(conn, plan.plan_id),
                        remaining=remaining, cancel_first=cancel_first,
                        reduction_only=reduction_only, caveats=caveats)


def _current_version(conn) -> Optional[int]:
    from sentinel.feed import publication

    pub = publication.current(conn)
    return pub.version if pub else None


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


__all__ = ["CatchUpResult", "NavUnobserved", "Reprojection", "catch_up",
           "last_processed_session", "project", "reproject"]
