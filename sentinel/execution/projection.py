"""Turning a shadow target and a scalar into a concrete basket of shares.

```text
Wealth Core shadow      WHAT to hold, as weights.  Never touched here
Sentinel controller     HOW MUCH of it, as a scalar in [0, 1]
        |
        v
this module             desired quantity per security, in whole shares
```

Sentinel scales exposure; it never changes membership. That is architecture
invariant #9, and it is why this module reads the shadow's weights and multiplies
them by one number rather than re-selecting anything.

## What belongs here and what does not

Integer shares, affordability, missing prints, the defensive sleeve and the cash
residual all live HERE — never inside Wealth Core. The shadow is a certified
state machine whose outputs must not depend on whether a broker could fill
something; the moment execution reality leaks into it, the immutable shadow stops
being immutable and restart equivalence stops holding.

## Rounding is not a detail

With 25 names at 4%, exact weights are unreachable in whole shares, so a residual
always exists. Two rules keep it honest:

  * round DOWN, always. Rounding to nearest can overshoot the exposure the
    controller asked for, and overshooting a defensive target is the direction
    that costs money in the state where money is being lost;
  * the residual is EXECUTION residual, not a Sentinel decision. It is reported,
    not silently swept into the next thing.

## No mark, no target

A security with no usable price cannot be sized, and guessing one produces a
confident wrong quantity. It is excluded and NAMED. This mirrors the wind
tunnel's "no print, no fill" rule, which exists because the alternative executed
trades against securities that had no market.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from typing import Mapping, Optional


class ProjectionRefused(ValueError):
    """The projection cannot be computed from these inputs."""


@dataclass(frozen=True)
class Projection:
    """A concrete basket, plus everything that did not fit into one."""

    target_exposure: Decimal
    nav: Decimal
    quantities: Mapping[str, Decimal] = field(default_factory=dict)
    notional: Mapping[str, Decimal] = field(default_factory=dict)
    unpriced: tuple = ()
    defensive_security: Optional[str] = None
    defensive_quantity: Decimal = Decimal(0)
    cash_residual: Decimal = Decimal(0)

    @property
    def invested_notional(self) -> Decimal:
        return sum(self.notional.values(), Decimal(0))

    @property
    def realised_exposure(self) -> Decimal:
        """What this basket actually achieves, which is NOT the target.

        Reported separately on purpose. Conflating the two is how a book that
        rounded down to 96% gets recorded as having been asked for 96%, after
        which nobody can tell an execution shortfall from a decision.
        """
        if self.nav == 0:
            return Decimal(0)
        return self.invested_notional / self.nav

    def to_dict(self) -> dict:
        return {
            "target_exposure": str(self.target_exposure),
            "realised_exposure": str(self.realised_exposure),
            "nav": str(self.nav),
            "quantities": {k: str(v) for k, v in sorted(self.quantities.items())},
            "unpriced": list(self.unpriced),
            "defensive": {"security_id": self.defensive_security,
                          "quantity": str(self.defensive_quantity)},
            "cash_residual": str(self.cash_residual),
        }


def project(*, shadow_weights: Mapping[str, Decimal], exposure: Decimal,
            nav: Decimal, marks: Mapping[str, Decimal],
            defensive_security: Optional[str] = None,
            lot: Decimal = Decimal(1)) -> Projection:
    """`shadow target x exposure -> whole shares`.

    `shadow_weights` are fractions of the CORE book summing to at most 1; they
    are the shadow's, and this function does not reweight them. Renormalising
    after dropping an unpriced name would silently redistribute its weight — the
    same defect as `composite_scores` renormalising over a factor that is missing
    from the whole corpus, and it would make the realised exposure look correct
    while the book was concentrated somewhere nobody chose.
    """
    if not isinstance(exposure, Decimal) or not isinstance(nav, Decimal):
        raise TypeError("exposure and nav must be Decimal")

    # FINITENESS FIRST, and before any comparison. `Decimal("NaN") < 0` does
    # not return False — it raises InvalidOperation — and `Decimal("Infinity")`
    # compares perfectly happily, sails through a range check and produces an
    # infinite target notional. Neither is caught by an `isinstance` test, so a
    # bounds check written without this is a bounds check with two holes.
    for label, value in (("exposure", exposure), ("nav", nav), ("lot", lot)):
        if not isinstance(value, Decimal):
            raise TypeError(f"{label} must be Decimal")
        if not value.is_finite():
            raise ProjectionRefused(f"{label} is not finite: {value}")

    if exposure < 0 or exposure > 1:
        raise ProjectionRefused(
            f"exposure must be in [0, 1], got {exposure}. Sentinel scales how "
            f"much of the shadow is held; it does not lever it.")
    if nav < 0:
        raise ProjectionRefused(f"nav must be non-negative, got {nav}")
    if lot <= 0:
        raise ProjectionRefused(f"lot must be positive, got {lot}")

    # ── THE UNLEVERED ENVELOPE, ENFORCED RATHER THAN DOCUMENTED ──────────────
    #
    # This function's own docstring said the weights "sum to at most 1" and
    # nothing checked it. Three 40% weights at exposure 1.0 produced ~120% of
    # NAV in equities and every downstream gate passed: `_assert_executable`
    # sees only the exposure scalar and the sign of each quantity, and it has
    # no NAV and no marks, so it cannot re-derive aggregate notional even in
    # principle. This is the last place the arithmetic is available, which
    # makes it the place the envelope has to hold.
    #
    # A NEGATIVE weight was worse than unchecked — it was silently ABSORBED.
    # It produced a non-positive quantity, hit the `qty <= 0: continue` below,
    # and vanished. A short leg arriving from a malformed shadow should stop
    # the appliance, not be quietly dropped on the way to the broker.
    #
    # "Wealth Core always produces sane weights" is not a protection at a
    # broker boundary. It is an assumption about another component, and this is
    # the membrane.
    total = Decimal(0)
    for security_id, weight in sorted(shadow_weights.items()):
        if not isinstance(weight, Decimal):
            raise TypeError(f"weight for {security_id} must be Decimal")
        if not weight.is_finite():
            raise ProjectionRefused(
                f"weight for {security_id} is not finite: {weight}")
        if weight < 0:
            raise ProjectionRefused(
                f"weight for {security_id} is negative ({weight}). The book is "
                f"LONG ONLY; a short leg is a malformed shadow, not a position "
                f"to floor away.")
        if weight > 1:
            raise ProjectionRefused(
                f"weight for {security_id} is {weight}, above 1. A single name "
                f"cannot exceed the whole core book.")
        total += weight
    # STRICTLY. No tolerance, deliberately: 25 slots at 4% is exactly 1 in
    # Decimal, so a legitimate shadow never needs slack, and a gate with an
    # epsilon is a gate whose real limit is the epsilon. If a producer ever
    # does need rounding room, it belongs where the weights are MADE — not at
    # the boundary that exists to disbelieve them.
    if total > 1:
        raise ProjectionRefused(
            f"shadow weights sum to {total}, above 1. At exposure {exposure} "
            f"that is {total * exposure:f} of NAV in equities — leverage. The "
            f"envelope is long-only and unlevered.")

    quantities: dict = {}
    notional: dict = {}
    unpriced: list = []

    for security_id, weight in sorted(shadow_weights.items()):
        price = marks.get(security_id)
        # A NON-FINITE mark is unpriced, not a price. `Decimal("Infinity")`
        # passes `> 0` and yields a zero quantity; NaN raises on comparison.
        # Both are corrupt evidence about what a share is worth, and the
        # existing machinery for that is to NAME the security, never guess.
        if price is not None and (not isinstance(price, Decimal)
                                  or not price.is_finite()):
            unpriced.append(security_id)
            continue
        if price is None or price <= 0:
            # NOT renormalised away, and not guessed at. The name is named.
            unpriced.append(security_id)
            continue
        target_notional = nav * exposure * weight
        raw = target_notional / price
        # FLOOR, in whole lots. Rounding to nearest can overshoot the exposure
        # the controller asked for, and overshoot is the wrong direction in
        # exactly the state where the controller is cutting.
        qty = (raw / lot).to_integral_value(rounding=ROUND_DOWN) * lot
        if qty <= 0:
            continue
        quantities[security_id] = qty
        notional[security_id] = qty * price

    invested = sum(notional.values(), Decimal(0))
    residual = nav - invested

    defensive_qty = Decimal(0)
    if defensive_security is not None:
        # The sleeve absorbs what the core did not take — INCLUDING the part
        # deliberately not invested because exposure < 1. That is the whole
        # mechanism: Sentinel moves money between the core and T-bills, so a
        # 0.55 exposure is not "45% idle cash", it is "45% in the sleeve".
        price = marks.get(defensive_security)
        if price is not None and price > 0 and residual > 0:
            defensive_qty = (residual / price).to_integral_value(
                rounding=ROUND_DOWN)
            residual -= defensive_qty * price
        elif residual > 0:
            unpriced.append(defensive_security)

    return Projection(
        target_exposure=exposure, nav=nav, quantities=quantities,
        notional=notional, unpriced=tuple(sorted(set(unpriced))),
        defensive_security=defensive_security,
        defensive_quantity=defensive_qty, cash_residual=residual)


def desired_basket(projection: Projection) -> dict:
    """Everything the executor should drive toward, core plus sleeve.

    One mapping rather than two, because the executor's arithmetic is per
    security and a sleeve that lived outside it would be the one holding nothing
    reconciles against.
    """
    basket = dict(projection.quantities)
    if projection.defensive_security is not None:
        basket[projection.defensive_security] = projection.defensive_quantity
    return basket
