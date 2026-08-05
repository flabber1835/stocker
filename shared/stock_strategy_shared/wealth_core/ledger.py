"""Wealth Core v1 — the trusted ledger. PURE.

Every cash and share movement is an EXPLICIT event. Nothing is folded into a
price: a split changes the share count through a SPLIT event, a dividend becomes
a receivable and then cash, a write-off is a WRITE_OFF event that a human caused.
That is what makes the daily path reconstructible from the ledger alone, which
the acceptance criteria require.

The rule that shapes the design: an event is the ONLY way a number changes. If
equity moved, there is a row explaining it. A confirmed worthlessness that
changed equity without a WRITE_OFF row would be indistinguishable from a pricing
error, and the whole point of §16's reconciliation is to tell those apart.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    SPLIT = "SPLIT"
    DIVIDEND_ACCRUED = "DIVIDEND_ACCRUED"      # receivable created
    DIVIDEND_PAID = "DIVIDEND_PAID"            # receivable -> cash
    CASH_MERGER = "CASH_MERGER"                # shares -> cash proceeds
    CONVERSION = "CONVERSION"                  # shares -> delivered security
    WRITE_OFF = "WRITE_OFF"                    # confirmed worthless, THEN zero
    TERMINAL_LIQUIDATION = "TERMINAL_LIQUIDATION"
    TERMINAL_MARK = "TERMINAL_MARK"


@dataclass(frozen=True)
class LedgerEvent:
    session: str
    event_type: EventType
    security_id: str | None
    ticker: str | None
    shares_delta: float
    cash_delta: float
    price: float | None
    fees: float
    cash_before: float
    cash_after: float
    reason: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"session": self.session, "event_type": self.event_type.value,
                "security_id": self.security_id, "ticker": self.ticker,
                "shares_delta": self.shares_delta, "cash_delta": self.cash_delta,
                "price": self.price, "fees": self.fees,
                "cash_before": self.cash_before, "cash_after": self.cash_after,
                "reason": self.reason,
                "detail": {k: self.detail[k] for k in sorted(self.detail)}}


@dataclass
class Ledger:
    """Append-only. `receivables` is separate from cash on purpose: a declared
    dividend is owed but not yet held, and treating it as cash would let it fund
    an admission before it settles."""
    events: list[LedgerEvent] = field(default_factory=list)
    receivables: dict[str, float] = field(default_factory=dict)

    def post(self, *, session: str, event_type: EventType, cash_before: float,
             shares_delta: float = 0.0, cash_delta: float = 0.0,
             security_id: str | None = None, ticker: str | None = None,
             price: float | None = None, fees: float = 0.0, reason: str = "",
             detail: dict | None = None) -> LedgerEvent:
        ev = LedgerEvent(session=session, event_type=event_type,
                         security_id=security_id, ticker=ticker,
                         shares_delta=shares_delta, cash_delta=cash_delta,
                         price=price, fees=fees, cash_before=cash_before,
                         cash_after=cash_before + cash_delta, reason=reason,
                         detail=detail or {})
        self.events.append(ev)
        return ev

    def accrue_dividend(self, *, session: str, security_id: str, ticker: str,
                        shares: int, per_share: float, cash: float) -> LedgerEvent:
        """A receivable, NOT cash (spec §2: "explicit receivable and cash ledger
        events"). Posting straight to cash would let an unsettled dividend fund
        an admission on the same session it was declared."""
        amount = shares * float(per_share)
        self.receivables[security_id] = self.receivables.get(security_id, 0.0) + amount
        return self.post(session=session, event_type=EventType.DIVIDEND_ACCRUED,
                         cash_before=cash, security_id=security_id, ticker=ticker,
                         price=per_share, reason="DIVIDEND_ACCRUED",
                         detail={"shares": shares, "amount": amount})

    def settle_receivables(self, *, session: str, cash: float) -> tuple[float, list[LedgerEvent]]:
        """Pay every outstanding receivable into cash. Deterministic order —
        the events land in the ledger, and a hash over them must not depend on
        dict iteration."""
        out: list[LedgerEvent] = []
        for sec in sorted(self.receivables):
            amt = self.receivables[sec]
            ev = self.post(session=session, event_type=EventType.DIVIDEND_PAID,
                           cash_before=cash, cash_delta=amt, security_id=sec,
                           reason="DIVIDEND_PAID", detail={"amount": amt})
            cash = ev.cash_after
            out.append(ev)
        self.receivables.clear()
        return cash, out

    def ledger_hash(self) -> str:
        blob = json.dumps([e.to_dict() for e in self.events], sort_keys=True,
                          separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def reconcile_cash(self, starting_cash: float) -> float:
        """Replay every cash delta. The independent path §15.7 asks for: if this
        disagrees with the running balance, the ledger and the simulator have
        diverged and the first differing event names where."""
        return starting_cash + sum(e.cash_delta for e in self.events)
