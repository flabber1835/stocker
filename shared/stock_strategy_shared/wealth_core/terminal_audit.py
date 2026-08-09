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
    "shares_at_settlement",
    "settlement_price",
    "settlement_notional",
    # the reconciliation
    "notional_delta",
)

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


def episode_audit(*, security_id: str, ticker: Optional[str],
                  event_session: Optional[str], event_kind: Optional[str],
                  event_reference: Optional[str] = None,
                  carry: Optional[Mapping[str, Any]] = None,
                  settlement_session: Optional[str] = None,
                  settlement_method: Optional[str] = None,
                  shares_at_settlement: Optional[int] = None,
                  settlement_price: Optional[float] = None,
                  grace_sessions: Optional[int] = None) -> dict:
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

    delta = (None if carry_notional is None or settlement_notional is None
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
        "shares_at_settlement": shares_at_settlement,
        "settlement_price": settlement_price,
        "settlement_notional": settlement_notional,
        "notional_delta": delta,
    }


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
    carried_total = _money(sum(a["carry_notional"] or 0.0 for a in rows))
    settled_total = _money(sum(a["settlement_notional"] or 0.0 for a in rows))
    # Summed from the per-episode deltas rather than differenced from the two
    # totals, because those are two different computations and the whole point
    # of the exercise is that they agree. `residual` below is the check.
    delta_total = _money(sum(a["notional_delta"] or 0.0 for a in rows))
    uncarried = [a for a in audits if not a.get("carried")]
    return {
        "episodes": len(rows),
        "carried_notional_total": carried_total,
        "settled_notional_total": settled_total,
        "notional_delta_total": delta_total,
        # Zero when the per-episode deltas explain the whole difference between
        # the totals. Non-zero means at least one episode's audit is internally
        # inconsistent, and the re-pin must stop.
        "residual": _money((settled_total or 0.0) - (carried_total or 0.0)
                           - (delta_total or 0.0)),
        "uncarried_settlements": len(uncarried),
        "episodes_with_a_price_move": sum(
            1 for a in rows if a.get("grace_prints")),
        "episodes_with_a_split": sum(1 for a in rows if a.get("grace_splits")),
        "unexplained_episodes": sorted(
            a["security_id"] for a in rows
            if (a.get("notional_delta") or 0.0) != 0.0
            and not a.get("grace_prints") and not a.get("grace_splits")),
        # A carried episode with NO delta at all — a CONVERSION, whose
        # consideration is shares rather than cash, so there is no settled
        # notional to difference against the carry. It contributes to
        # `carried_notional_total` and to nothing else, so the totals above
        # legitimately fail to balance while this list is non-empty.
        #
        # Reported rather than folded in, because summing a None as 0.0 would
        # make the reconciliation appear to close while an episode's value went
        # unaccounted — the precise failure mode condition 4 exists to catch.
        "unreconciled_episodes": sorted(
            a["security_id"] for a in rows if a.get("notional_delta") is None),
    }


__all__ = ["AUDIT_FIELDS", "MONEY_DP", "episode_audit", "new_carry_record",
           "record_grace_print", "record_grace_split", "reconcile"]
