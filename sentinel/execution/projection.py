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
    if exposure < 0 or exposure > 1:
        raise ProjectionRefused(
            f"exposure must be in [0, 1], got {exposure}. Sentinel scales how "
            f"much of the shadow is held; it does not lever it.")
    if nav < 0:
        raise ProjectionRefused(f"nav must be non-negative, got {nav}")

    quantities: dict = {}
    notional: dict = {}
    unpriced: list = []

    for security_id, weight in sorted(shadow_weights.items()):
        if not isinstance(weight, Decimal):
            raise TypeError(f"weight for {security_id} must be Decimal")
        price = marks.get(security_id)
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
