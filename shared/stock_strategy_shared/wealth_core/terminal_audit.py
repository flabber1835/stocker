"""Wealth Core v1 — the PER-EPISODE TERMINAL AUDIT record. PURE: no DB, no clock.

WHY THIS EXISTS. The 2021-2023 rehearsal carried $342,136.68 and settled
$342,419.72 — $283.04 apart — and nothing in the run could attribute the
difference to a security. The counters are aggregates: `tally_pending_entry`
sees `ep.current_shares` in the moment and keeps a running notional, and a carry
posts nothing to the ledger because it is a MARK, not a settlement. So the
difference existed in two totals and nowhere else.

THE TWO MECHANISMS THAT MAKE THE DIFFERENCE LEGITIMATE, both established
2026-08-09 and both required to read it:

    a later trustworthy PRINT during the grace updates `last_known`, so the
    settlement price is the security's last traded price rather than the mark
    the carry was authorised against

    a SPLIT during the grace changes the share count, because `apply_splits`
    matches on security_id and does not skip a carried holding

So the reconciliation is NOT `shares x (settlement_price - carry_price)` for any
single `shares`. It is:

    delta = (shares_at_settlement x settlement_price)
          - (shares_at_carry      x carry_price)

Recording one `shares` field per episode would have made the difference
unattributable in exactly the case where a split fired, and the defect would
have surfaced only after the golden hash had already moved — turning one
controlled re-pin into two. That is the whole reason this module exists before
the re-pin rather than after it.

WORKED EXAMPLE, from the falsifier in tests/wealth_core/test_adapter.py:

    carry       10 shares @ $90.00  =  $900.00
    2-for-1 split during the grace
    settlement  20 shares @ $46.00  =  $920.00
    delta       +$20.00

Economically one $20 price move; arithmetically reachable from neither share
count alone.

THE SPLIT MULTIPLIER IS RECORDED EXPLICITLY even though it is derivable from
the two share counts in simple cases. Derivable is not the same as legible, and
the cases where it is NOT cleanly derivable are precisely the ones worth
catching: `apply_splits` truncates with `int(before * ratio)`, so an odd share
count under a 3-for-2 loses the remainder and the implied ratio no longer equals
the stated one. An audit that forces the reader to infer the ratio would present
that as a price discrepancy.

NOTHING HERE IS A DECISION. Every field is an observation of something the
waterfall already did, which is what makes it safe to add to a certified
artefact: it changes no branch, no ordering and no number. It moves exactly one
hash — `final_result`, via `RunResult.to_dict()` — and that movement is the
deliberate re-pin.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

#: Every field of one terminal episode's audit, in the order a reader needs
#: them: WHAT terminated, what was CARRIED, what happened DURING the grace,
#: what was SETTLED, and only then the difference.
#:
#: Named as data rather than left implicit in a constructor so the acceptance
#: tests, the chain-level reconciliation and the docs enumerate ONE list. A
#: field discovered missing after the re-pin costs a second hash movement, so
#: the completeness of this tuple is itself load-bearing.
AUDIT_FIELDS: tuple[str, ...] = (
    # identity
    "security_id",
    "ticker",
    # the terminating event
    "event_session",
    "event_kind",
    "event_reference",
    # the carry (absent when the episode settled without ever being carried)
    "carried",
    "carry_session",
    "shares_at_carry",
    "carry_price",
    "carry_notional",
    "last_trustworthy_print_session",
    # what happened DURING the grace
    "grace_sessions",
    "grace_prints",
    "grace_split_multiplier",
    "grace_splits",
    # the settlement
    "settlement_session",
    "settlement_method",
    "settlement_kind",
    "episode_continues",
    "shares_at_settlement",
    "settlement_price",
    "settlement_notional",
    # non-cash consideration (CONVERSION / CASH_PLUS_STOCK). Absent as values,
    # never as keys — see `episode_audit`.
    "delivered_security_id",
    "delivered_ticker",
    "shares_delivered",
    "exchange_ratio",
    "cash_consideration",
    "cash_in_lieu",
    # the reconciliation
    "notional_delta",
)

#: What the holder actually RECEIVED. Typed rather than inferred from whether a
#: price happens to be present, because "no cash price" has two completely
#: different causes — paid in shares, or nothing settled at all — and a
#: reconciliation that cannot tell them apart is the one that silently fails to
#: close.
KIND_CASH = "cash"
"""Cash per share, from terms or from a proxy. The ordinary settlement."""

KIND_ZERO = "zero"
"""A stated worthlessness or a C2 orphan. Settles at exactly 0.0, which is a
DECISION and not the absence of one."""

KIND_NON_CASH = "non_cash"
"""Paid entirely in shares of another issuer. There is no settled cash notional
to difference against the carry, and inventing one by valuing the delivered
stock would reintroduce the invented-price objection this module exists to
avoid."""

KIND_MIXED = "mixed"
"""Cash per old share AND delivered shares. The cash leg reconciles; the share
leg does not, and both are reported rather than netted into a single figure that
would be neither."""

#: Kinds whose settlement is expressible as one cash number, and therefore the
#: only kinds that belong in the carried-vs-settled sum.
CASH_SETTLING_KINDS = frozenset({KIND_CASH, KIND_ZERO})

#: Money is rounded to the cent here and NOWHERE ELSE in this module, so the
#: reconciliation has exactly one rounding convention and `notional_delta` is
#: the difference of the two figures a reader can see — never a separately
#: rounded third quantity that fails to add up by a cent.
MONEY_DP = 2


def _money(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(float(x), MONEY_DP)


def _notional(shares: Optional[int], price: Optional[float]) -> Optional[float]:
    """None unless BOTH are known. A missing share count must not silently
    become a zero notional — that reads as "settled for nothing", which is a
    fact about a write-off rather than the absence of one."""
    if shares is None or price is None:
        return None
    return _money(int(shares) * float(price))


#: Settlement methods that can only ever pay CASH. A proxy settlement values the
#: position and credits proceeds; it cannot deliver shares of another issuer,
#: because nothing in the corpus states an exchange ratio. Only EXACT_TERMS
#: carries the terms that make a share delivery expressible at all.
_PROXY_METHODS = frozenset({
    "LAST_TRUSTWORTHY_MARK", "EXECUTABLE_PRINT", "PENDING_TERMS"})


def settlement_kind_for(event_kind: Optional[str],
                        settlement_price: Optional[float],
                        settlement_method: Optional[str] = None) -> str:
    """What the holder ACTUALLY RECEIVED — from the SETTLEMENT, not the notice.

    THE METHOD DOMINATES THE ANNOUNCED ACTION, and getting that backwards was a
    real defect (found in the 2021-2023 rehearsal, 2026-08-09). Every one of the
    eight terminal episodes settled via LAST_TRUSTWORTHY_MARK — a cash proxy —
    but five of them had been ANNOUNCED as conversions, so typing off
    `event_kind` filed them as `non_cash`. They were then bucketed out of the
    cash reconciliation, and `reconcile` reported `residual: 0.00` and
    `unreconciled_episodes: []` while covering only 3 of 8 episodes and
    $132,057 of $342,137.

    That is the exact failure `unreconciled_episodes` exists to prevent,
    arriving through the classifier instead of through a missing field: an
    episode is hardest to notice when it has been confidently put in the wrong
    place rather than left out.

    An ANNOUNCEMENT describes what was intended. Only the SETTLEMENT says what
    happened, and a documented conversion whose terms were never readable
    settles at a cash proxy exactly like any other unreadable termination.

    `settlement_method` defaults to None for callers that predate it; with no
    method the announced action is all there is, which is the old behaviour and
    is correct only when the terms were exact.
    """
    if settlement_method in _PROXY_METHODS:
        # A proxy pays cash — or nothing, which is still a cash outcome of zero.
        if settlement_price is not None and float(settlement_price) == 0.0:
            return KIND_ZERO
        return KIND_CASH
    if settlement_method == "ZERO_ORPHAN":
        return KIND_ZERO
    # EXACT_TERMS (or an unstated method): the action type is now authoritative,
    # because stated terms are the only thing that can deliver shares.
    if event_kind == "CONVERSION":
        return KIND_NON_CASH
    if event_kind == "CASH_PLUS_STOCK":
        return KIND_MIXED
    if event_kind == "WRITE_OFF":
        return KIND_ZERO
    if settlement_price is not None and float(settlement_price) == 0.0:
        return KIND_ZERO
    return KIND_CASH


def episode_audit(*, security_id: str, ticker: Optional[str],
                  event_session: Optional[str], event_kind: Optional[str],
                  event_reference: Optional[str] = None,
                  carry: Optional[Mapping[str, Any]] = None,
                  settlement_session: Optional[str] = None,
                  settlement_method: Optional[str] = None,
                  shares_at_settlement: Optional[int] = None,
                  settlement_price: Optional[float] = None,
                  grace_sessions: Optional[int] = None,
                  delivered_security_id: Optional[str] = None,
                  delivered_ticker: Optional[str] = None,
                  shares_delivered: Optional[int] = None,
                  exchange_ratio: Optional[float] = None,
                  cash_consideration: Optional[float] = None,
                  cash_in_lieu: Optional[float] = None,
                  episode_continues: bool = False) -> dict:
    """Compose one episode's audit from the carry provenance and the settlement.

    `carry` is the record the C1 grace stored on the portfolio state at ENTRY —
    None for an episode that settled without ever being carried (exact terms on
    the announcement, or a C2 orphan zero, which has no documented event at all).
    Such an episode has no carry notional and therefore no delta: `None`, not
    0.0, because "there was nothing to reconcile" and "it reconciled to zero"
    are different statements and only the second is a check that passed.

    The two notionals are computed HERE from contemporaneous shares and prices
    rather than accepted from the caller, so an independent recomputation and
    the persisted record cannot disagree — which is the property acceptance
    condition 4 turns on.
    """
    c = dict(carry or {})
    shares_at_carry = c.get("shares_at_carry")
    carry_price = c.get("carry_price")
    carry_notional = _notional(shares_at_carry, carry_price)
    settlement_notional = _notional(shares_at_settlement, settlement_price)
    kind = settlement_kind_for(event_kind, settlement_price, settlement_method)

    # A CASH delta only where the settlement IS cash. On a conversion the holder
    # received shares, so differencing "nothing" against the carry would report a
    # total loss of the carried value — the same fabricated write-off the
    # incomplete-terms block exists to prevent, arriving through the audit
    # instead of through the waterfall. The share leg is reported in its own
    # fields and bucketed separately by `reconcile`.
    delta = (None if carry_notional is None or settlement_notional is None
             or kind not in CASH_SETTLING_KINDS
             else _money(settlement_notional - carry_notional))

    return {
        "security_id": security_id,
        "ticker": ticker,
        "event_session": event_session,
        "event_kind": event_kind,
        "event_reference": event_reference,
        "carried": bool(carry),
        "carry_session": c.get("carry_session"),
        "shares_at_carry": shares_at_carry,
        "carry_price": carry_price,
        "carry_notional": carry_notional,
        "last_trustworthy_print_session": c.get("last_trustworthy_print_session"),
        "grace_sessions": grace_sessions,
        # Copied, not referenced: these lists live on the portfolio state and
        # the episode is released immediately after this record is built.
        "grace_prints": [dict(p) for p in (c.get("grace_prints") or [])],
        "grace_split_multiplier": c.get("grace_split_multiplier", 1.0),
        "grace_splits": [dict(s) for s in (c.get("grace_splits") or [])],
        "settlement_session": settlement_session,
        "settlement_method": settlement_method,
        "settlement_kind": kind,
        # A CONVERSION is not an exit: the episode keeps its slot, age, review
        # flag and rescaled peak because it is the same economic holding. An
        # audit that read as a settlement would say a position left the book
        # when it did not.
        "episode_continues": bool(episode_continues),
        "shares_at_settlement": shares_at_settlement,
        "settlement_price": settlement_price,
        "settlement_notional": settlement_notional,
        "delivered_security_id": delivered_security_id,
        "delivered_ticker": delivered_ticker,
        "shares_delivered": shares_delivered,
        "exchange_ratio": exchange_ratio,
        "cash_consideration": _money(cash_consideration),
        "cash_in_lieu": _money(cash_in_lieu),
        "notional_delta": delta,
    }


def with_non_cash_consideration(audit: Mapping[str, Any], *,
                                delivered_security_id: Optional[str],
                                delivered_ticker: Optional[str],
                                shares_delivered: Optional[int],
                                exchange_ratio: Optional[float],
                                cash_consideration: Optional[float],
                                cash_in_lieu: Optional[float],
                                episode_continues: bool) -> dict:
    """Attach what a CONVERSION actually delivered, AFTER it has been applied.

    A separate entry point rather than a caller-side dict merge, and that is not
    style. The delivered share count comes from a truncating entitlement split
    so it cannot be known before dispatch — but merging the raw result in would
    write money fields that never passed through `_money`, and this module's
    whole claim is that rounding happens in ONE place. Observed doing exactly
    that: a cash-in-lieu of 49.0000000000002 reaching `non_cash_cash_legs`,
    which is a reported total.
    """
    return {**audit,
            "delivered_security_id": delivered_security_id,
            "delivered_ticker": delivered_ticker,
            "shares_delivered": shares_delivered,
            "exchange_ratio": exchange_ratio,
            "cash_consideration": _money(cash_consideration),
            "cash_in_lieu": _money(cash_in_lieu),
            "episode_continues": bool(episode_continues)}


def new_carry_record(*, carry_session: str, shares_at_carry: int,
                     carry_price: float,
                     last_trustworthy_print_session: Optional[str]) -> dict:
    """The provenance stored on the portfolio state when a carry BEGINS.

    Written once, on entry, and never rewritten — a carry re-recorded at its
    current values every session would make `carry_price` mean "the price now",
    which is the settlement price, and the delta would be identically zero for
    every episode. That is a reconciliation that always passes and therefore
    checks nothing.

    The mutable parts are the two grace histories below, which only ever grow.
    """
    return {"carry_session": carry_session,
            "shares_at_carry": int(shares_at_carry),
            "carry_price": float(carry_price),
            "last_trustworthy_print_session": last_trustworthy_print_session,
            "grace_prints": [],
            "grace_split_multiplier": 1.0,
            "grace_splits": []}


def record_grace_print(carry: dict, *, session: str, price: float) -> dict:
    """A later trustworthy print DURING the grace. Mutates and returns `carry`.

    This is the first of the two mechanisms, made visible. Without it the audit
    would show a settlement price differing from the carry price with no record
    of where the new price came from, and the only available explanation would
    be an inference about `last_known`.
    """
    carry.setdefault("grace_prints", []).append(
        {"session": session, "price": float(price)})
    return carry


def record_grace_split(carry: dict, *, session: str, ratio: float,
                       shares_before: int, shares_after: int) -> dict:
    """A split DURING the grace. Mutates and returns `carry`.

    `shares_before`/`shares_after` are recorded alongside the stated ratio
    because `apply_splits` TRUNCATES (`int(before * ratio)`), so the realised
    ratio can differ from the declared one on an odd share count. Recording only
    the declared ratio would make that truncation look like a pricing error in
    the reconciliation.
    """
    carry.setdefault("grace_splits", []).append(
        {"session": session, "ratio": float(ratio),
         "shares_before": int(shares_before), "shares_after": int(shares_after)})
    carry["grace_split_multiplier"] = float(
        carry.get("grace_split_multiplier", 1.0)) * float(ratio)
    return carry


def reconcile(audits, *, carried_only: bool = True) -> dict:
    """Sum the per-episode deltas, and show the two totals they came from.

    Acceptance condition 4 (revised 2026-08-09): for every terminal episode,
    independently recompute `carry_notional` and `settlement_notional` from the
    persisted contemporaneous shares and prices, and prove that

        sum(settlement_notional - carry_notional) == the reported difference

    exactly, subject only to this module's rounding convention. Anything else
    stops the re-pin.

    `carried_only` restricts the sum to episodes that were actually carried,
    which is what the two rehearsal totals measure. An episode that settled
    without a carry contributes to the settled total and to no carried total, so
    including it would compare populations rather than prices — it is reported
    separately as `uncarried_settlements` instead of being folded in.
    """
    rows = [a for a in audits if a.get("carried")] if carried_only else list(audits)

    # TWO BUCKETS, and every carried episode belongs to exactly one. The cash
    # bucket is the one whose totals must balance; the non-cash bucket is
    # accounted in its own terms because it has no cash settlement to balance
    # against. An episode in NEITHER is the failure this function exists to
    # surface, and it is what `unreconciled_episodes` reports.
    cash = [a for a in rows if a.get("settlement_kind") in CASH_SETTLING_KINDS]
    non_cash = [a for a in rows
                if a.get("settlement_kind") in (KIND_NON_CASH, KIND_MIXED)]

    carried_total = _money(sum(a["carry_notional"] or 0.0 for a in cash))
    settled_total = _money(sum(a["settlement_notional"] or 0.0 for a in cash))
    # Summed from the per-episode deltas rather than differenced from the two
    # totals, because those are two different computations and the whole point
    # of the exercise is that they agree. `residual` below is the check.
    delta_total = _money(sum(a["notional_delta"] or 0.0 for a in cash))
    uncarried = [a for a in audits if not a.get("carried")]
    return {
        "episodes": len(rows),
        "cash_settled_episodes": len(cash),
        "carried_notional_total": carried_total,
        "settled_notional_total": settled_total,
        "notional_delta_total": delta_total,
        # Zero when the per-episode deltas explain the whole difference between
        # the two cash totals. Non-zero means at least one episode's audit is
        # internally inconsistent, and the re-pin must stop.
        "residual": _money((settled_total or 0.0) - (carried_total or 0.0)
                           - (delta_total or 0.0)),
        # NON-CASH, accounted in its own terms. The carried value is stated (it
        # is what the position was worth going in) alongside the cash legs that
        # DID settle and the share leg that did not. Deliberately not netted
        # into one figure, which would be neither.
        "non_cash_episodes": len(non_cash),
        "non_cash_carried_notional": _money(
            sum(a["carry_notional"] or 0.0 for a in non_cash)),
        "non_cash_cash_legs": _money(
            sum((a.get("cash_consideration") or 0.0)
                + (a.get("cash_in_lieu") or 0.0) for a in non_cash)),
        "non_cash_detail": [
            {"security_id": a["security_id"],
             "settlement_kind": a["settlement_kind"],
             "carry_notional": a["carry_notional"],
             "delivered_security_id": a.get("delivered_security_id"),
             "shares_delivered": a.get("shares_delivered"),
             "exchange_ratio": a.get("exchange_ratio"),
             "cash_consideration": a.get("cash_consideration"),
             "cash_in_lieu": a.get("cash_in_lieu"),
             "episode_continues": a.get("episode_continues")}
            for a in sorted(non_cash, key=lambda x: x["security_id"])],
        # THE COVERAGE FRACTION, reported unconditionally. `residual: 0.00` and
        # `unreconciled_episodes: []` were both true while the cash bucket held
        # 3 of 8 episodes and $132k of $342k — every green light on, and most of
        # the money outside the check. A reconciliation must state how much of
        # the population it actually reconciled, or "it balances" is a claim
        # about an unstated subset.
        "carried_notional_all_kinds": _money(
            sum(a["carry_notional"] or 0.0 for a in rows)),
        "cash_coverage_fraction": (
            round(len(cash) / len(rows), 4) if rows else None),
        "uncarried_settlements": len(uncarried),
        "episodes_with_a_price_move": sum(
            1 for a in rows if a.get("grace_prints")),
        "episodes_with_a_split": sum(1 for a in rows if a.get("grace_splits")),
        "unexplained_episodes": sorted(
            a["security_id"] for a in cash
            if (a.get("notional_delta") or 0.0) != 0.0
            and not a.get("grace_prints") and not a.get("grace_splits")),
        # A carried episode in NEITHER bucket: it settled for no cash and was
        # not paid in shares either, so nothing accounts for the value it was
        # carried at. THIS is the list that must be empty before the re-pin.
        # Summing such an episode's None as 0.0 would make the reconciliation
        # appear to close while its value went unaccounted — the precise failure
        # mode condition 4 exists to catch.
        "unreconciled_episodes": sorted(
            {a["security_id"] for a in rows} - {a["security_id"] for a in cash}
            - {a["security_id"] for a in non_cash}),
    }


__all__ = ["AUDIT_FIELDS", "CASH_SETTLING_KINDS", "KIND_CASH", "KIND_MIXED",
           "KIND_NON_CASH", "KIND_ZERO", "MONEY_DP", "episode_audit",
           "new_carry_record", "record_grace_print", "record_grace_split",
           "reconcile", "settlement_kind_for", "with_non_cash_consideration"]
