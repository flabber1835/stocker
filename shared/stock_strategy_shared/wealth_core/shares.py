"""Share quantities under corporate actions. PURE, and EXACT where it matters.

THE DEFECT THIS CLOSES (reproduced 2026-08-09). `apply_splits` computed

    ep.current_shares = int(before * b.split_ratio)

which TRUNCATES. Measured:

    15 shares  x 1.5     exact 22.5      engine 22      lost 0.5 sh = $33.33
    100 shares 1-for-7   exact 14.2857   engine 14      lost 0.2857 sh = $200.00

That last one is 2% of a $10,000 position, destroyed silently: no fractional
holding, no cash-in-lieu, no receivable, no ledger event. The position simply
became worth less and nothing recorded why.

A SPLIT IS A TRANSFORMATION, NOT A SALE. Nobody traded, so no value may leave
the book. The terminal-CONVERSION path already holds this standard — it refuses
to apply without a cash-in-lieu price rather than dropping the stub — and an
ordinary split had been held to a lower one.

WHY FRACTIONAL ENTITLEMENT RATHER THAN CASH-IN-LIEU (owner decision,
2026-08-09). Cash-in-lieu needs a per-share price at the action instant that the
vendor does not supply, and it is broker-specific treatment invented inside the
alpha engine. Fractional entitlement is exact, deterministic, and needs nothing
the corpus lacks. Integer-share constraints are a BROKER fact and belong in the
execution projection, not in canonical accounting:

    canonical Wealth Core   may hold fractional entitlement
    execution projection    obeys whatever the broker actually permits

ENTRY SIZING IS UNCHANGED and still whole shares. That is not the same question:
buying is a TRADE against a real order book, and `affordable_shares` sizing in
whole shares is a genuine execution constraint rather than an accounting
shortcut.

## Why the arithmetic is DECIMAL and the storage is float

The multiply is done in `Decimal` so a stated ratio is applied exactly. Chained
binary-float multiplication is what produces artefacts like `21.9999999997`,
which a later reader cannot distinguish from a genuine fraction — and on a
quantity that decides settlement notionals, that ambiguity is the whole problem.

The RESULT is stored as a float because every consumer multiplies it by a float
price — equity, marks, ledger cash flows, settlement notionals. Making the
quantity a `Decimal` would raise `TypeError` at each of those sites, and mixing
the two across the engine mid-certification buys precision the hash discards
anyway (`hashes.quantize` rounds to 10 dp) at the cost of a wide refactor of
code that is being certified.

So: exact where exactness is observable, float where it is not, and QUANTIZED at
a fixed share precision after every transformation so a chain of splits is
deterministic rather than accumulating drift.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from fractions import Fraction
import math

#: Decimal places a share quantity is held to after a corporate action.
#: Fixed storage precision. Exact relative and marked monetary error bounds
#: below refuse entitlements that cannot be represented safely at this scale.
SHARE_DP = 12

_Q = Decimal(1).scaleb(-SHARE_DP)


def split_shares(before, ratio, *, raw_price=None) -> float:
    """Share count after a split, or refusal outside supported precision.

    `Decimal(str(...))` on both operands: constructing a Decimal from a float
    would import the float's binary error before the multiply and defeat the
    purpose. A non-positive or absent ratio returns the count unchanged — a
    corporate action that says nothing must not silently zero a holding.
    """
    if ratio is None:
        return float(before)
    with localcontext() as ctx:
        ctx.prec = 34
        r = Decimal(str(ratio))
        if r <= 0:
            return float(before)
        exact = Fraction(str(before)) * Fraction(r)
        result = float((Decimal(str(before)) * r).quantize(
            _Q, rounding=ROUND_HALF_EVEN))
    error = abs(Fraction(str(result)) - exact)
    if exact > 0 and (result <= 0 or error > exact * Fraction("1e-12")):
        raise ValueError("split entitlement exceeds supported share precision")
    if (raw_price is not None and math.isfinite(float(raw_price))
            and raw_price > 0 and error * Fraction(str(raw_price)) > Fraction("1e-8")):
        raise ValueError("split entitlement exceeds supported monetary precision")
    return result


def affordable_whole_shares(cash: float, price: float,
                            cost_bps: float) -> int:
    """Whole shares purchasable with ``cash``, including traded-side cost.

    Floor exact decimal-spelled economics, independently of float operation
    order or ambient Decimal precision. Booking uses the same cost equation.
    """
    if (not all(math.isfinite(float(x)) for x in (cash, price, cost_bps))
            or cash <= 0 or price <= 0 or cost_bps < 0):
        return 0
    per_share = Fraction(str(price)) * (1 + Fraction(str(cost_bps)) / 10_000)
    return max(0, Fraction(str(cash)) // per_share)


def traded_cash(shares: float, price: float, cost_bps: float, *, buy: bool) -> float:
    """Round a traded-side cash amount once, after exact decimal arithmetic."""
    fee = Fraction(str(cost_bps)) / 10_000
    return float(Fraction(str(shares)) * Fraction(str(price))
                 * (1 + fee if buy else 1 - fee))


def is_integral(x) -> bool:
    return float(x) == int(float(x))


def as_json(x):
    """Canonical serialisation for a share quantity.

    INTEGRAL QUANTITIES SERIALISE AS `int`, and that is load-bearing rather than
    cosmetic: every share count in the certified golden fixture is a whole
    number, and emitting `20.0` where `20` stood would move `daily_state`,
    `order`, `ledger` and `final_state` for a book in which nothing economic
    changed. A representation change must not masquerade as a semantic one.

    Fractional quantities serialise as `float`, which the hash layer then rounds
    to 10 dp — finer than `SHARE_DP` leaves meaningful.
    """
    f = float(x)
    return int(f) if f == int(f) else f


__all__ = ["SHARE_DP", "affordable_whole_shares", "as_json", "is_integral",
           "split_shares", "traded_cash"]
