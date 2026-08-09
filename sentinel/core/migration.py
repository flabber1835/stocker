"""The migration delta — legacy broker book versus Wealth Core's target. PURE.

Stocker's delta engine is retired and is not what this is. That one managed a
running book with rank buffers and an orphan timer; this one answers a
once-in-a-platform question:

```text
what does the account hold now   ->  legacy Stocker positions
what should it hold              ->  Wealth Core's target at exposure 1.00
what changes                     ->  this
```

## Overlap is REPORTED and NOT retained, deliberately

Where the legacy book and the target want the same security, the tempting move is
to keep the shares and skip a round trip. It is rejected, and the reason is not
transaction cost:

**Wealth Core is a stateful-ownership book.** Every position is an EPISODE with an
entry price, a peak, an age, a review clock and a cooldown. An inherited Stocker
position has none of that. Adopting it means inventing the state — and inventing
`peak = today's close` makes the 30% trailing stop looser than it should be,
while inventing `opened_on = today` fires the 119-session review at the wrong
time. Both are risk controls failing silently toward less protection, which is
the specific failure mode this project keeps finding.

On a paper account at 10 bps the saving is noise. Episode state you can trust is
worth more than a round trip that costs nothing real.

So the overlap is COMPUTED AND SHOWN — an operator should see exactly what is
being sold and rebought, and what it costs — but the plan sells it. If that
trade-off is ever revisited, it needs an explicit adoption policy for every
fabricated episode field, written down before it is coded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional


@dataclass(frozen=True)
class Leg:
    """One security's side of the migration."""

    ticker: str
    security_id: Optional[str] = None
    shares: Optional[float] = None
    notional: Optional[float] = None
    weight: Optional[float] = None


@dataclass
class MigrationPlan:
    session: str
    exits: list[Leg] = field(default_factory=list)
    entries: list[Leg] = field(default_factory=list)
    #: In BOTH books. Sold and rebought anyway — see the module docstring.
    overlap: list[Leg] = field(default_factory=list)
    account_equity: float = 0.0
    target_exposure: float = 1.0
    caveats: list[str] = field(default_factory=list)

    @property
    def churn_notional(self) -> float:
        """What the clean rebuy costs in turnover: the overlap, sold and bought.

        Surfaced as its own number so the decision not to retain overlap is
        priced rather than assumed. If this is ever large enough to matter, that
        is the signal to revisit it — with an adoption policy, not by dropping
        the sells.
        """
        return sum(l.notional or 0.0 for l in self.overlap)

    def to_dict(self) -> dict:
        return {
            "session": self.session,
            "target_exposure": self.target_exposure,
            "account_equity": round(self.account_equity, 2),
            "exits": [_leg(l) for l in self.exits],
            "entries": [_leg(l) for l in self.entries],
            "overlap": {
                "tickers": [l.ticker for l in self.overlap],
                "notional": round(self.churn_notional, 2),
                "policy": "SOLD AND REBOUGHT — episode state cannot be adopted",
            },
            "caveats": self.caveats,
        }


def _leg(l: Leg) -> dict:
    out = {"ticker": l.ticker}
    if l.shares is not None:
        out["shares"] = round(l.shares, 4)
    if l.notional is not None:
        out["notional"] = round(l.notional, 2)
    if l.weight is not None:
        out["weight"] = round(l.weight, 6)
    return out


def plan_migration(*, session: str, broker_positions: Mapping[str, float],
                   target_weights: Mapping[str, float],
                   marks: Mapping[str, float],
                   account_equity: float,
                   target_exposure: float = 1.0,
                   security_ids: Mapping[str, str] | None = None,
                   ) -> MigrationPlan:
    """Compare the two books. Keys are TICKERS on both sides.

    `broker_positions` maps ticker -> shares held at the broker.
    `target_weights` maps ticker -> fraction of equity Wealth Core wants.

    Tickers, not security ids, because the broker only knows symbols — and the
    comparison has to happen in the vocabulary both sides actually share. The
    security id is carried through for the audit where it is known.
    """
    plan = MigrationPlan(session=session, account_equity=account_equity,
                         target_exposure=target_exposure)
    ids = security_ids or {}

    held = {t: q for t, q in broker_positions.items() if q}
    wanted = {t: w for t, w in target_weights.items() if w}

    for ticker in sorted(held):
        px = marks.get(ticker)
        plan.exits.append(Leg(
            ticker=ticker, security_id=ids.get(ticker),
            shares=float(held[ticker]),
            notional=None if px is None else float(held[ticker]) * px))

    for ticker in sorted(wanted):
        weight = float(wanted[ticker])
        # Exposure scales the whole basket, never the membership. Sentinel
        # decides HOW MUCH of Wealth Core's book is held, never WHAT is in it —
        # so a 0.55 exposure buys every name at 0.55x, it does not buy 55% of
        # the names.
        notional = account_equity * weight * target_exposure
        px = marks.get(ticker)
        plan.entries.append(Leg(
            ticker=ticker, security_id=ids.get(ticker), weight=weight,
            notional=notional,
            shares=None if not px else notional / px))

    for ticker in sorted(set(held) & set(wanted)):
        px = marks.get(ticker)
        plan.overlap.append(Leg(
            ticker=ticker, security_id=ids.get(ticker),
            shares=float(held[ticker]),
            notional=None if px is None else float(held[ticker]) * px))

    missing = sorted({t for t in set(held) | set(wanted) if t not in marks})
    if missing:
        # Named rather than silently sized at zero. A leg with no price cannot be
        # converted to shares, and a plan that quietly omits it reports a
        # migration that does not cover the account.
        plan.caveats.append(
            f"NO MARK for {len(missing)} ticker(s): {', '.join(missing[:10])}"
            f"{' ...' if len(missing) > 10 else ''}. Their share counts are "
            f"unknown; execution must resolve a price or refuse the leg rather "
            f"than size it at zero.")

    if plan.overlap:
        plan.caveats.append(
            f"{len(plan.overlap)} security(s) appear in BOTH books "
            f"(~{plan.churn_notional:,.0f} notional). They are sold and "
            f"rebought: an inherited position carries no episode — no entry "
            f"price, no peak, no age — and fabricating those makes the trailing "
            f"stop and the review clock wrong in the direction of less "
            f"protection.")

    return plan
