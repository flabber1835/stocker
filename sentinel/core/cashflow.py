"""External cash: recorded as an event, never inferred from a balance.

## Why NAV cannot be its own witness

Net asset value moves for two reasons and the number does not say which:

```text
NAV 100,000 -> 150,000 overnight
                 |
                 +--  a $50,000 wire arrived
                 +--  a position was marked up 50%
                 +--  a reconciliation break: something is wrong
```

Guess "P&L" and a deposit becomes +50% in a day, permanently, in every
performance number the system will ever produce. Guess "cash flow" and a
genuine break — a position that vanished, a fill nobody saw — receives a benign
label and stops being investigated. Both guesses are silent and neither is
recoverable afterwards, because the evidence that would settle it is the moment
that has passed.

So a flow is DECLARED — by an operator, or by a broker activity feed that says
CSD/CSW — and what cannot be attributed stays `UNEXPLAINED`. That is the same
rule the execution layer applies to a broker outcome it cannot resolve: an
uncertain result is UNKNOWN, never a confident wrong one.

Broker-native cash evidence has one extra distinction. A dividend, fee or
interest payment moves account cash and therefore belongs in the durable cash
evidence, but it is strategy economics rather than external capital. Issue #183
reserves a versioned broker flow-id/detail encoding for those rows; only rows
classified EXTERNAL participate in `net_external`. Operator-declared flows keep
their historical meaning: they are external capital.

## What a flow is not

```text
NOT strategy P&L        `strategy_pl` removes the net external flow. A deposit
                        is not a return and a withdrawal is not a loss
NOT a Wealth Core input the historical book is a function of PRICE history.
                        Peaks, ages, review clocks and cooldowns do not move
                        because money arrived
NOT a replay trigger    see `catchup.reproject`. The CURRENT target is re-sized
                        against the new NAV; nothing historical is recomputed
```

It is an input to EXECUTION — how much of the shadow the account can hold —
which is the one layer the membrane allows to read the broker at all.

## Signed, in one direction

`amount` is positive for a deposit and negative for a withdrawal, rather than a
magnitude plus a `direction` column. Two fields that must agree are two fields
that can disagree, and the disagreement here inverts a $50,000 correction.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

#: How far a NAV move may miss the explanation before it is UNEXPLAINED.
#: Cents, not percent: a proportional tolerance on a large account silently
#: absorbs a genuinely large discrepancy, which is precisely the size of break
#: worth catching. Rounding in marking is the only thing this needs to forgive.
DEFAULT_TOLERANCE = Decimal("1.00")


class Attribution(str, Enum):
    #: A flow was declared and it accounts for the move.
    DECLARED = "DECLARED"
    #: The move is within tolerance of the marked P&L. No flow involved.
    MARKET = "MARKET"
    #: NAV moved and nothing accounts for it. NOT a synonym for either of the
    #: above, and never resolved into one by default.
    UNEXPLAINED = "UNEXPLAINED"


@dataclass(frozen=True)
class CashFlow:
    flow_id: str
    session: date
    #: SIGNED. Positive is money in.
    amount: Decimal
    detail: str
    recorded_at: Optional[datetime] = None

    @property
    def is_deposit(self) -> bool:
        return self.amount > 0

    @property
    def is_external(self) -> bool:
        """Whether this cash movement is investor capital rather than P&L.

        Broker rows use a reserved encoding validated by the broker-cash layer.
        Everything else is an operator declaration and retains the pre-#183
        external-capital semantics.
        """
        from sentinel.execution.broker_cash import broker_flow_is_external
        return broker_flow_is_external(self.flow_id, self.detail)

    def to_dict(self) -> dict:
        return {"flow_id": self.flow_id, "session": self.session.isoformat(),
                "amount": str(self.amount), "detail": self.detail,
                "recorded_at": (self.recorded_at.isoformat()
                                if self.recorded_at else None)}


@dataclass(frozen=True)
class NavReconciliation:
    """Whether the balance change is accounted for, and by what."""

    session: date
    previous_nav: Decimal
    observed_nav: Decimal
    marked_pl: Decimal
    external: Decimal
    unexplained: Decimal
    attribution: Attribution

    @property
    def explained(self) -> bool:
        return self.attribution is not Attribution.UNEXPLAINED

    @property
    def move(self) -> Decimal:
        return self.observed_nav - self.previous_nav

    def to_dict(self) -> dict:
        return {"session": self.session.isoformat(),
                "previous_nav": str(self.previous_nav),
                "observed_nav": str(self.observed_nav),
                "move": str(self.move),
                "marked_pl": str(self.marked_pl),
                "external": str(self.external),
                "unexplained": str(self.unexplained),
                "attribution": self.attribution.value,
                "explained": self.explained}


def record(conn, *, session, amount: Decimal, detail: str,
           flow_id: Optional[str] = None) -> CashFlow:
    """Declare an external cash movement.

    `detail` is required and not defaulted. A flow with no stated origin is
    indistinguishable from a plug figure entered to make a reconciliation
    balance, and a plug that can be entered will be.
    """
    if not isinstance(amount, Decimal):
        raise TypeError("amount must be Decimal — this is money")
    if amount == 0:
        raise ValueError("a zero cash flow explains nothing and is not an event")
    if not (detail or "").strip():
        raise ValueError(
            "a cash flow needs a stated origin. Without one it cannot be told "
            "apart from a plug figure entered to make a reconciliation balance.")

    d = _d(session)
    fid = flow_id or f"cf-{uuid.uuid4().hex[:16]}"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_cash_flows (flow_id, session, amount, detail)"
            " VALUES (%s,%s,%s,%s) ON CONFLICT (flow_id) DO NOTHING",
            (fid, d.isoformat(), str(amount), detail))
    conn.commit()
    return CashFlow(flow_id=fid, session=d, amount=amount, detail=detail)


def flows_between(conn, start, end) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT flow_id, session, amount, detail, recorded_at"
            " FROM sentinel_cash_flows WHERE session BETWEEN %s AND %s"
            " ORDER BY session, recorded_at, flow_id",
            (_d(start).isoformat(), _d(end).isoformat()))
        return [CashFlow(flow_id=str(f), session=_d(s), amount=Decimal(str(a)),
                         detail=str(dt_), recorded_at=at)
                for f, s, a, dt_, at in cur.fetchall()]


def net_external(conn, start, end) -> Decimal:
    """Signed investor-capital flow. Internal broker cash remains strategy P&L."""
    return sum((f.amount for f in flows_between(conn, start, end)
                if f.is_external), Decimal(0))


def strategy_pl(conn, *, start, end, opening_nav: Decimal,
                closing_nav: Decimal) -> Decimal:
    """What the STRATEGY did, with external money removed.

        strategy_pl = (closing - opening) - net external

    Not a return, deliberately: a percentage needs a decision about which
    denominator a mid-period flow belongs to, and time-weighting that honestly
    requires a NAV mark on the flow date. This is the numerator, and it is the
    half that is unambiguous. See docs/sentinel-architecture.md before anyone
    quotes a percentage — CLAUDE.md's rule about a headline number applies.
    """
    return (closing_nav - opening_nav) - net_external(conn, start, end)


def reconcile_nav(conn, *, session, previous_nav: Decimal,
                  observed_nav: Decimal, marked_pl: Decimal,
                  tolerance: Decimal = DEFAULT_TOLERANCE) -> NavReconciliation:
    """Account for the balance change, or refuse to.

    The residual is what is left after BOTH explanations are applied:

        unexplained = (observed - previous) - marked_pl - declared flows

    Recorded durably, because the question "was Tuesday's move ever explained?"
    is asked days later by someone who was not there.
    """
    d = _d(session)
    external = net_external(conn, d, d)
    residual = (observed_nav - previous_nav) - marked_pl - external

    if abs(residual) > tolerance:
        attribution = Attribution.UNEXPLAINED
    elif external != 0:
        attribution = Attribution.DECLARED
        residual = Decimal(0)
    else:
        attribution = Attribution.MARKET
        residual = Decimal(0)

    rec = NavReconciliation(
        session=d, previous_nav=previous_nav, observed_nav=observed_nav,
        marked_pl=marked_pl, external=external, unexplained=residual,
        attribution=attribution)
    _persist(conn, rec)
    return rec


def _persist(conn, rec: NavReconciliation) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_nav_reconciliations (session, previous_nav,"
            " observed_nav, marked_pl, external, unexplained, attribution)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (session) DO UPDATE SET"
            "   previous_nav = EXCLUDED.previous_nav,"
            "   observed_nav = EXCLUDED.observed_nav,"
            "   marked_pl = EXCLUDED.marked_pl,"
            "   external = EXCLUDED.external,"
            "   unexplained = EXCLUDED.unexplained,"
            "   attribution = EXCLUDED.attribution,"
            "   reconciled_at = NOW()",
            (rec.session.isoformat(), str(rec.previous_nav),
             str(rec.observed_nav), str(rec.marked_pl), str(rec.external),
             str(rec.unexplained), rec.attribution.value))
    conn.commit()


def latest_reconciliation(conn) -> Optional[NavReconciliation]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session, previous_nav, observed_nav, marked_pl, external,"
            " unexplained, attribution FROM sentinel_nav_reconciliations"
            " ORDER BY session DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        return None
    return NavReconciliation(
        session=_d(row[0]), previous_nav=Decimal(str(row[1])),
        observed_nav=Decimal(str(row[2])), marked_pl=Decimal(str(row[3])),
        external=Decimal(str(row[4])), unexplained=Decimal(str(row[5])),
        attribution=Attribution(row[6]))


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


__all__ = ["Attribution", "CashFlow", "DEFAULT_TOLERANCE", "NavReconciliation",
           "flows_between", "latest_reconciliation", "net_external",
           "reconcile_nav", "record", "strategy_pl"]
