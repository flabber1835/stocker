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
    an admission before it settles.

    THAT SEPARATION USED TO BE DECORATIVE. `receivables` was a
    {security_id: amount} dict and `apply_dividends` accrued into it and settled
    it out again inside ONE call, on the ex-date — while `decide()` runs later
    in the same session and sizes admissions against `state.cash`. So the
    dividend WAS spendable on its own ex-date, which is exactly what
    `accrue_dividend`'s docstring says the receivable exists to prevent. Two
    ledger events, zero delay.

    Each receivable now carries `due_in`: the number of further sessions that
    must pass before it becomes cash. The list shape (rather than a dict keyed
    on security_id) is required, not stylistic — two dividends from the SAME
    security can be outstanding at once with different due dates, and a dict
    would silently merge them into one payment on one date.
    """
    events: list[LedgerEvent] = field(default_factory=list)
    receivables: list[dict] = field(default_factory=list)

    def receivable_total(self) -> float:
        """Money owed but not yet held. Deliberately NOT part of equity: a
        declared dividend cannot size a 4% admission until it settles."""
        return sum(float(r["amount"]) for r in self.receivables)

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
                        shares: int, per_share: float, cash: float,
                        due_in: int = 0) -> LedgerEvent:
        """A receivable, NOT cash (spec §2: "explicit receivable and cash ledger
        events"). Posting straight to cash would let an unsettled dividend fund
        an admission on the same session it was declared.

        The AMOUNT is fixed here, in dollars, from the share count on the
        EX-DATE. That is what makes a later split irrelevant to an outstanding
        receivable: the entitlement was earned by the shares held when the
        security went ex, and doubling the share count afterwards does not
        double the money owed. Recomputing at settlement from the then-current
        count would do exactly that.
        """
        amount = shares * float(per_share)
        self.receivables.append({
            "security_id": security_id, "ticker": ticker, "amount": amount,
            "accrued_session": session, "due_in": int(due_in)})
        return self.post(session=session, event_type=EventType.DIVIDEND_ACCRUED,
                         cash_before=cash, security_id=security_id, ticker=ticker,
                         price=per_share, reason="DIVIDEND_ACCRUED",
                         detail={"shares": shares, "amount": amount,
                                 "due_in": int(due_in)})

    def settle_due(self, *, session: str, cash: float
                   ) -> tuple[float, list[LedgerEvent]]:
        """Pay the receivables that have come due, then age the rest by one.

        Both halves in one call, and in this order, because they are one
        session's worth of the same clock — a caller that settled without ageing
        (or aged twice) would move every payment date, silently and by a
        different amount per dividend.

        Deterministic order: sorted by (security_id, accrued_session) rather
        than list order, so a hash over the resulting events cannot depend on
        the order the bars happened to arrive in.

        A receivable is paid REGARDLESS of whether the security is still held.
        A dividend earned before a delisting is money owed to the book, and
        cancelling it because the position has since left would lose real cash
        with no event explaining where it went.
        """
        out: list[LedgerEvent] = []
        due = [r for r in self.receivables if int(r["due_in"]) <= 0]
        rest = [r for r in self.receivables if int(r["due_in"]) > 0]
        for r in sorted(due, key=lambda r: (r["security_id"] or "",
                                            r["accrued_session"] or "")):
            ev = self.post(session=session, event_type=EventType.DIVIDEND_PAID,
                           cash_before=cash, cash_delta=float(r["amount"]),
                           security_id=r["security_id"], ticker=r.get("ticker"),
                           reason="DIVIDEND_PAID",
                           detail={"amount": float(r["amount"]),
                                   "accrued_session": r["accrued_session"]})
            cash = ev.cash_after
            out.append(ev)
        for r in rest:
            r["due_in"] = int(r["due_in"]) - 1
        self.receivables = rest
        return cash, out

    def to_dict(self) -> dict:
        """Serialise for a restart. `receivables` is included and must be — an
        accrued dividend that has not settled is money the book is owed, and
        dropping it across a restart silently loses cash that the reconciliation
        would then report as a divergence with no cause."""
        return {"events": [e.to_dict() for e in self.events],
                "receivables": [
                    {k: r[k] for k in sorted(r)}
                    for r in sorted(self.receivables,
                                    key=lambda r: (r["security_id"] or "",
                                                   r["accrued_session"] or "",
                                                   r["due_in"]))]}

    @classmethod
    def from_dict(cls, d: dict) -> "Ledger":
        raw = d.get("receivables") or []
        if isinstance(raw, dict):
            # The pre-lag shape: {security_id: amount}, with no due date because
            # settlement happened in the same call as accrual. Restored as
            # IMMEDIATELY DUE, which is what those receivables meant. Tolerated
            # rather than rejected so a state blob written by the old code
            # resumes instead of losing money the book was owed.
            raw = [{"security_id": k, "ticker": None, "amount": float(v),
                    "accrued_session": "", "due_in": 0} for k, v in sorted(raw.items())]
        return cls(events=[LedgerEvent(
                       session=e["session"],
                       event_type=EventType(e["event_type"]),
                       security_id=e["security_id"], ticker=e["ticker"],
                       shares_delta=e["shares_delta"], cash_delta=e["cash_delta"],
                       price=e["price"], fees=e["fees"],
                       cash_before=e["cash_before"], cash_after=e["cash_after"],
                       reason=e["reason"], detail=dict(e.get("detail") or {}))
                   for e in d.get("events", [])],
                   receivables=[{"security_id": r.get("security_id"),
                                 "ticker": r.get("ticker"),
                                 "amount": float(r["amount"]),
                                 "accrued_session": r.get("accrued_session") or "",
                                 "due_in": int(r.get("due_in", 0))}
                                for r in raw])

    def ledger_hash(self) -> str:
        """Events AND outstanding receivables.

        It used to cover the event log alone, which left money the book is OWED
        outside every hash. The consequence was concrete: a restart that dropped
        an unsettled receivable produced an IDENTICAL ledger hash at the
        boundary, and diverged only later — when the payment silently failed to
        appear. A hash that cannot see a difference until its downstream
        consequence shows up is worth much less than one that sees it at once,
        which is the entire argument for the seven ordered parity hashes.
        """
        from stock_strategy_shared.wealth_core.hashes import quantize
        blob = json.dumps(quantize(self.to_dict()), sort_keys=True,
                          separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def reconcile_cash(self, starting_cash: float) -> float:
        """Replay every cash delta. The independent path §15.7 asks for: if this
        disagrees with the running balance, the ledger and the simulator have
        diverged and the first differing event names where."""
        return starting_cash + sum(e.cash_delta for e in self.events)
