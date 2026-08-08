"""Wealth Core v1 — terminal corporate actions and final-session accounting.
PURE: no DB, no clock, no I/O.

THE ONE RULE EVERYTHING HERE FOLLOWS: never invent terminal proceeds.

A terminal action is the moment a holding stops being a security and becomes
some combination of cash, a different security, and nothing. Each of those has a
number attached, and the number comes from the deal terms — never from the last
print, never from a recovery rate, never from zero. When the terms are not fully
known the action is NOT applied: the holding stays unresolved, `resolved_equity`
stays None, and admissions stop until somebody supplies them. That is worse to
operate and the only version that cannot silently mis-state the book.

WHY INCOMPLETE TERMS BLOCK RATHER THAN APPROXIMATE. Every alternative produces a
complete, plausible run:

    assume 100% cash at last price   flatters every distressed holding
    assume zero                      invents a total loss AND, because every
                                     admission is 4% of equity, permanently
                                     shrinks every position opened afterwards
    skip the event                   leaves shares in a security that no longer
                                     exists, marked at a price that will never
                                     update again

None of them raise. The block does.

THE CONVERSION PEAK, which is the subtle one. An episode's trailing stop is
anchored on a peak in the OLD security's price domain, and after a conversion
the closes arrive in the NEW one. Resetting the peak would silently loosen a
risk control at the exact moment a holding changes identity; carrying it
unchanged would compare prices on two unrelated scales. Both are wrong in the
direction of doing nothing when a position falls.

So the peak is rescaled by the exchange ratio, and the justification is that the
stop protects POSITION VALUE rather than per-share price. At the peak the
position was worth `shares_in x peak_old`; after conversion the same value
spread over `shares_in x ratio` shares is `peak_old / ratio` per share. Dividing
by the ratio therefore preserves the exact drawdown the stop measures. The entry
prices are rescaled the same way and for the same reason.

FINAL-SESSION REPORTING keeps three things apart that are routinely added
together:

    marked      open positions valued at their final VALID close. Not a trade.
    liquidated  positions the strategy actually closed during the run.
    forced      a HYPOTHETICAL liquidation of whatever was still open.

The third is the one that corrupts comparisons. Selling the whole book on the
last session is not something the strategy did, and folding its costs into the
headline return charges a strategy for a trade it never made — while omitting it
entirely reports a book as if it were cash. So it is computed, reported, and
kept in its own ledger that the run's own ledger never sees.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.marks import Mark, MarkStatus
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState


class TerminalKind(str, Enum):
    CASH_MERGER = "CASH_MERGER"
    """Acquired for cash. Shares leave, actual deal proceeds arrive."""

    WRITE_OFF = "WRITE_OFF"
    """Confirmed worthless. The ONLY path on which zero is a fact rather than an
    assumption, which is why it needs no economic terms and every other kind
    does."""

    CONVERSION = "CONVERSION"
    """Security-for-security. Shares of one issuer become shares of another at a
    stated ratio; the episode CONTINUES because it is the same economic
    holding."""

    CASH_PLUS_STOCK = "CASH_PLUS_STOCK"
    """Mixed consideration: cash per old share AND delivered shares. Not
    expressible as either of the two above, and approximating it as whichever
    leg is larger misprices the position by the other leg."""


class TermsIncomplete(ValueError):
    """The deal terms cannot support an application without invention.

    Raised only by the strict helpers; the run path RECORDS the condition on the
    portfolio state instead, because a terminal action with missing terms is an
    operational situation to be resolved, not a crash.
    """


@dataclass(frozen=True)
class TerminalTerms:
    """The complete economic terms of one terminal action.

    Every optional field is optional because some KINDS do not use it — never
    because it may be omitted for a kind that does. `completeness()` is the
    single place that distinction is enforced.
    """
    session: str
    security_id: str
    kind: TerminalKind
    cash_per_share: float | None = None
    delivered_security_id: str | None = None
    delivered_ticker: str | None = None
    delivered_issuer_id: str | None = None
    exchange_ratio: float | None = None
    # Price per DELIVERED share used to settle a fractional entitlement. Required
    # only when the conversion actually produces a fraction — demanding it
    # unconditionally would block clean 1:2 conversions that never round.
    cash_in_lieu_price_per_delivered_share: float | None = None
    reference: str = ""

    def completeness(self, shares_in: int) -> tuple[bool, str]:
        """(complete, reason). `shares_in` matters: whether a conversion needs a
        cash-in-lieu price is a property of THIS holding's share count, not of
        the deal."""
        k = self.kind
        if k is TerminalKind.WRITE_OFF:
            return True, ""
        if k is TerminalKind.CASH_MERGER:
            if not _nonneg(self.cash_per_share):
                return False, "MISSING_CASH_PER_SHARE"
            return True, ""
        if k in (TerminalKind.CONVERSION, TerminalKind.CASH_PLUS_STOCK):
            if k is TerminalKind.CASH_PLUS_STOCK and not _nonneg(self.cash_per_share):
                return False, "MISSING_CASH_PER_SHARE"
            if not (self.delivered_security_id and self.delivered_ticker
                    and self.delivered_issuer_id):
                return False, "MISSING_DELIVERED_SECURITY"
            if not _positive(self.exchange_ratio):
                return False, "MISSING_EXCHANGE_RATIO"
            _, frac = _split_entitlement(shares_in, self.exchange_ratio)
            if frac > 0 and not _nonneg(self.cash_in_lieu_price_per_delivered_share):
                # The fraction is REAL money that has to land somewhere
                # attributable. Dropping it silently loses value; rounding the
                # share count up invents shares nobody delivered.
                return False, "MISSING_CASH_IN_LIEU_PRICE"
            return True, ""
        return False, f"UNKNOWN_KIND_{k}"


def _positive(x) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0


def _nonneg(x) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f >= 0


def _split_entitlement(shares_in: int, ratio: float) -> tuple[int, float]:
    """Whole delivered shares and the leftover fraction.

    `math.floor` on the product, and the fraction is what is left — NOT
    `round()`. Rounding a 0.6 entitlement up delivers a share the acquirer never
    issued, and the position would be permanently one share heavier than the
    broker's.
    """
    exact = shares_in * float(ratio)
    whole = int(math.floor(exact + 1e-9))
    return whole, max(0.0, exact - whole)


# ── applying a terminal action ───────────────────────────────────────────────

def apply_terminal(state: PortfolioState, terms: TerminalTerms, *, ledger: Ledger,
                   session: str, cfg: WealthCoreConfig) -> dict:
    """Apply one terminal action, or RECORD that it cannot be applied.

    Returns a result dict either way. The caller does not have to check an
    exception to find out that the book is now blocked — that fact is on the
    portfolio state, where a restart will find it too.
    """
    slot_id = next((s for s, ep in sorted(state.episodes.items())
                    if ep.security_id == terms.security_id), None)
    if slot_id is None:
        return {"applied": False, "reason": "NOT_HELD",
                "security_id": terms.security_id}

    ep = state.episodes[slot_id]
    ok, why = terms.completeness(ep.current_shares)
    if not ok:
        # BLOCKED, not approximated, and recorded on the STATE so it survives a
        # restart. `resolved_equity` goes None on the next mark, which stops
        # admissions until somebody supplies the terms.
        state.unresolved_terminals[terms.security_id] = why
        return {"applied": False, "reason": why, "blocked": True,
                "security_id": terms.security_id, "kind": terms.kind.value}

    state.unresolved_terminals.pop(terms.security_id, None)

    if terms.kind is TerminalKind.WRITE_OFF:
        return _apply_write_off(state, slot_id, ep, ledger, session)
    if terms.kind is TerminalKind.CASH_MERGER:
        return _apply_cash(state, slot_id, ep, ledger, session,
                           float(terms.cash_per_share), terms)
    return _apply_conversion(state, slot_id, ep, ledger, session, terms, cfg)


def _release(state: PortfolioState, slot_id: int, ep: HoldingEpisode) -> None:
    state.episodes.pop(slot_id)
    state.slots[slot_id].start_cooldown()
    state.security_cooldowns[ep.security_id] = 0


def _apply_write_off(state, slot_id, ep, ledger, session) -> dict:
    ledger.post(session=session, event_type=EventType.WRITE_OFF,
                cash_before=state.cash, security_id=ep.security_id,
                ticker=ep.ticker, shares_delta=-ep.current_shares, price=0.0,
                reason="CONFIRMED_WORTHLESS", detail={"shares": ep.current_shares})
    _release(state, slot_id, ep)
    return {"applied": True, "kind": "WRITE_OFF", "security_id": ep.security_id,
            "proceeds": 0.0}


def _apply_cash(state, slot_id, ep, ledger, session, per_share, terms) -> dict:
    proceeds = ep.current_shares * per_share
    ledger.post(session=session, event_type=EventType.CASH_MERGER,
                cash_before=state.cash, cash_delta=proceeds,
                security_id=ep.security_id, ticker=ep.ticker,
                shares_delta=-ep.current_shares, price=per_share,
                reason="CASH_MERGER",
                detail={"shares": ep.current_shares, "reference": terms.reference})
    state.cash += proceeds
    _release(state, slot_id, ep)
    return {"applied": True, "kind": "CASH_MERGER", "security_id": ep.security_id,
            "proceeds": proceeds}


def _apply_conversion(state: PortfolioState, slot_id: int, ep: HoldingEpisode,
                      ledger: Ledger, session: str, terms: TerminalTerms,
                      cfg: WealthCoreConfig) -> dict:
    """Transfer the episode into the delivered security.

    The episode CONTINUES: same slot, same age, same review flag. A conversion
    is not an exit and treating it as one would restart the holding period,
    resetting both the review clock and the trailing-stop peak for a position
    the strategy never chose to leave.
    """
    ratio = float(terms.exchange_ratio)
    cash_leg = float(terms.cash_per_share or 0.0) * ep.current_shares
    delivered, frac = _split_entitlement(ep.current_shares, ratio)
    lieu = (frac * float(terms.cash_in_lieu_price_per_delivered_share)
            if frac > 0 else 0.0)

    before_shares, before_sec = ep.current_shares, ep.security_id
    ledger.post(session=session, event_type=EventType.CONVERSION,
                cash_before=state.cash, cash_delta=cash_leg + lieu,
                security_id=ep.security_id, ticker=ep.ticker,
                shares_delta=delivered - before_shares,
                price=terms.cash_per_share, reason=terms.kind.value,
                detail={"delivered_security_id": terms.delivered_security_id,
                        "delivered_ticker": terms.delivered_ticker,
                        "exchange_ratio": ratio,
                        "shares_in": before_shares,
                        "shares_delivered": delivered,
                        "fractional_entitlement": round(frac, 10),
                        "cash_in_lieu": round(lieu, 10),
                        "cash_consideration": round(cash_leg, 10),
                        "reference": terms.reference})
    state.cash += cash_leg + lieu

    if delivered <= 0:
        # The entitlement rounded to nothing: this is economically a cash
        # settlement, and the position must LEAVE rather than persist at zero
        # shares in a security that would then be marked forever.
        _release(state, slot_id, ep)
        return {"applied": True, "kind": terms.kind.value, "converted": False,
                "security_id": before_sec, "cash_in_lieu": lieu,
                "cash_consideration": cash_leg}

    # Per-share accounting state rescales by the ratio, which preserves POSITION
    # value exactly — see the module docstring on why the peak must move.
    # Provenance BEFORE the identity is overwritten — after this block there is
    # no other record that these shares were once a different company.
    ep.source_lots = list(ep.source_lots) + [{
        "kind": terms.kind.value, "session": session,
        "from_security_id": before_sec, "from_ticker": ep.ticker,
        "shares_in": before_shares, "exchange_ratio": ratio,
        "shares_delivered": delivered,
        "cash_consideration": round(cash_leg, 10),
        "cash_in_lieu": round(lieu, 10),
        "to_security_id": terms.delivered_security_id,
        "to_ticker": terms.delivered_ticker,
        "reference": terms.reference}]
    ep.security_id = terms.delivered_security_id
    ep.ticker = terms.delivered_ticker
    ep.issuer_id = terms.delivered_issuer_id
    ep.current_shares = delivered
    ep.initial_shares = max(1, int(round(ep.initial_shares * ratio)))
    ep.entry_raw_open = ep.entry_raw_open / ratio
    ep.entry_split_adjusted_price = ep.entry_split_adjusted_price / ratio
    if ep.episode_peak_split_adjusted_close is not None:
        ep.episode_peak_split_adjusted_close = \
            ep.episode_peak_split_adjusted_close / ratio
    state.slots[slot_id].occupied_by = ep.security_id

    return {"applied": True, "kind": terms.kind.value, "converted": True,
            "security_id": before_sec,
            "delivered_security_id": ep.security_id,
            "shares_delivered": delivered, "cash_in_lieu": lieu,
            "cash_consideration": cash_leg}


# ── final-session accounting ─────────────────────────────────────────────────

@dataclass
class FinalReport:
    """Three separate numbers, never one.

    `marked_equity` is what the book is worth. `forced_liquidation_equity` is
    what it would fetch if sold on the last session — a different question, with
    transaction costs the strategy never paid, reported next to it rather than
    instead of it.
    """
    session: str
    cash: float
    marked_positions: list[dict] = field(default_factory=list)
    unmarkable_positions: list[dict] = field(default_factory=list)
    liquidated_during_run: list[dict] = field(default_factory=list)
    forced_liquidation: list[dict] = field(default_factory=list)
    # TWO SEPARATE LEDGERS, and neither is the run's. The run ledger records
    # what CHANGED the book; a mark changes nothing and a hypothetical sale
    # never happened. Posting either into the run ledger also made it depend on
    # where the run stopped, so a resumed run could not reproduce an
    # uninterrupted one — caught by the restart test.
    mark_ledger: Ledger | None = None
    forced_liquidation_ledger: Ledger | None = None
    marked_equity: float | None = None
    forced_liquidation_equity: float | None = None
    # security_id -> aggregated shares and marked value. Reported ALONGSIDE the
    # per-slot rows because two positions taken over by the same acquirer are
    # one exposure and two holdings, and a report showing only one of those two
    # views is misleading in whichever direction it omits.
    aggregate_by_security: dict = field(default_factory=dict)
    unresolved_terminals: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session": self.session,
            "cash": round(self.cash, 2),
            "marked_positions": sorted(self.marked_positions,
                                       key=lambda p: p["security_id"]),
            "unmarkable_positions": sorted(self.unmarkable_positions,
                                           key=lambda p: p["security_id"]),
            "liquidated_during_run": sorted(
                self.liquidated_during_run,
                key=lambda p: (p["session"], p["security_id"], p["event_type"])),
            "forced_liquidation": sorted(self.forced_liquidation,
                                         key=lambda p: p["security_id"]),
            "marked_equity": None if self.marked_equity is None
            else round(self.marked_equity, 2),
            "forced_liquidation_equity": None if self.forced_liquidation_equity is None
            else round(self.forced_liquidation_equity, 2),
            "unresolved_terminals": dict(sorted(self.unresolved_terminals.items())),
            "aggregate_by_security": {
                k: self.aggregate_by_security[k]
                for k in sorted(self.aggregate_by_security)},
        }


_LIQUIDATING_EVENTS = ("SELL", "CASH_MERGER", "WRITE_OFF", "CONVERSION")


def final_report(*, session: str, state: PortfolioState, marks: Mapping[str, Mark],
                 ledger: Ledger, cfg: WealthCoreConfig) -> FinalReport:
    """Value the book at the end of a run without trading it.

    `marked_equity` is None whenever ANY open position lacks a trustworthy
    current mark — the same fail-closed rule the running equity gate uses, for
    the same reason: a total that silently omits an unmarkable holding reads as
    a complete valuation.
    """
    rep = FinalReport(session=session, cash=float(state.cash),
                      mark_ledger=Ledger(), forced_liquidation_ledger=Ledger(),
                      unresolved_terminals=dict(state.unresolved_terminals))

    total, forced_total, any_unmarkable = float(state.cash), float(state.cash), False

    for slot_id in sorted(state.episodes):
        ep = state.episodes[slot_id]
        m = marks.get(ep.security_id)
        if m is not None and m.status is MarkStatus.CURRENT:
            value = ep.current_shares * float(m.raw_mark_close)
            rep.marked_positions.append({
                "security_id": ep.security_id, "ticker": ep.ticker,
                "slot_id": slot_id, "shares": ep.current_shares,
                "final_raw_close": float(m.raw_mark_close),
                "marked_value": round(value, 2),
                "sessions_held": ep.market_sessions_held})
            total += value

            # TERMINAL_LIQUIDATION goes in its OWN ledger. Posting it to the
            # run's ledger would make a hypothetical indistinguishable from a
            # trade in every downstream reconciliation.
            proceeds = value * (1.0 - cfg.transaction_cost_bps / 10_000.0)
            rep.forced_liquidation.append({
                "security_id": ep.security_id, "ticker": ep.ticker,
                "shares": ep.current_shares,
                "assumed_price": float(m.raw_mark_close),
                "gross": round(value, 2),
                "cost": round(value - proceeds, 2),
                "net_proceeds": round(proceeds, 2)})
            rep.forced_liquidation_ledger.post(
                session=session, event_type=EventType.TERMINAL_LIQUIDATION,
                cash_before=forced_total, cash_delta=proceeds,
                security_id=ep.security_id, ticker=ep.ticker,
                shares_delta=-ep.current_shares, price=float(m.raw_mark_close),
                fees=value - proceeds, reason="HYPOTHETICAL_FORCED_LIQUIDATION",
                detail={"hypothetical": True})
            forced_total += proceeds

            rep.mark_ledger.post(
                session=session, event_type=EventType.TERMINAL_MARK,
                cash_before=state.cash, cash_delta=0.0,
                security_id=ep.security_id, ticker=ep.ticker,
                shares_delta=0, price=float(m.raw_mark_close),
                reason="FINAL_SESSION_MARK",
                detail={"shares": ep.current_shares,
                        "marked_value": round(value, 2)})
        else:
            any_unmarkable = True
            rep.unmarkable_positions.append({
                "security_id": ep.security_id, "ticker": ep.ticker,
                "slot_id": slot_id, "shares": ep.current_shares,
                "mark_status": m.status.value if m else "ABSENT",
                "last_known_raw_close": (m.stale_raw_close if m else None),
                "blocking_reason": state.unresolved_terminals.get(
                    ep.security_id, "NO_CURRENT_MARK")})

    for p in rep.marked_positions:
        agg = rep.aggregate_by_security.setdefault(
            p["security_id"], {"shares": 0, "marked_value": 0.0, "lots": 0,
                               "slots": []})
        agg["shares"] += p["shares"]
        agg["marked_value"] = round(agg["marked_value"] + p["marked_value"], 2)
        agg["lots"] += 1
        agg["slots"].append(p["slot_id"])

    rep.marked_equity = None if any_unmarkable else total
    rep.forced_liquidation_equity = None if any_unmarkable else forced_total

    for e in ledger.events:
        if e.event_type.value in _LIQUIDATING_EVENTS:
            rep.liquidated_during_run.append({
                "session": e.session, "security_id": e.security_id,
                "ticker": e.ticker, "event_type": e.event_type.value,
                "shares_delta": e.shares_delta, "cash_delta": e.cash_delta,
                "price": e.price, "reason": e.reason})
    return rep


__all__ = ["FinalReport", "TerminalKind", "TerminalTerms", "TermsIncomplete",
           "apply_terminal", "final_report"]
