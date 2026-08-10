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

#: Decimal places a share quantity is held to after a corporate action.
#: Comfortably finer than any real entitlement and comfortably coarser than the
#: bits where float representation becomes noise, so a chained split lands on a
#: repeatable number instead of drifting.
SHARE_DP = 12

_Q = Decimal(1).scaleb(-SHARE_DP)


def split_shares(before, ratio) -> float:
    """Share count after a split. EXACT, never truncated.

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
        return float((Decimal(str(before)) * r).quantize(
            _Q, rounding=ROUND_HALF_EVEN))


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


__all__ = ["SHARE_DP", "as_json", "is_integral", "split_shares"]
