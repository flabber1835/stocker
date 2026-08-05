"""Mark status and the resolved/estimated equity split. PURE.

THE FORK THIS SETTLES. When an open holding has no trustworthy current raw
close, two obvious treatments are both wrong and both silent:

    value it at ZERO        invents an immediate total loss, and — because every
                            admission is 4% of equity — permanently shrinks every
                            position opened afterwards
    carry the LAST PRICE    presents a stale number as current and overstates the
                            sizing base for as long as the situation persists

Neither raises. Both produce a complete backtest of a different strategy.

So the condition is REPRESENTED rather than resolved by guessing. The holding
and its share count stay in the ledger, its last known close is preserved as
explicitly stale, and the strategy stops admitting new positions until the
ambiguity is settled — because the one thing you cannot do with an unknown
equity is size 4% of it.

This is a canonical implementation convention adopted 2026-08-03. It may differ
from the unavailable certified prototype; see UNRESOLVED_REPRODUCTION below.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class MarkStatus(str, Enum):
    CURRENT = "CURRENT"
    """A trustworthy current raw unadjusted close."""

    STALE = "STALE"
    """No close this session. The last known price is informational only."""

    UNRESOLVED_TERMINAL = "UNRESOLVED_TERMINAL"
    """A terminal action (merger, delisting, conversion) whose outcome is not
    yet known. Fail closed: not tradeable, not markable, not written off."""

    CONFIRMED_WORTHLESS = "CONFIRMED_WORTHLESS"
    """A processed write-off. This is RESOLVED — zero is now a fact rather than
    an assumption, and equity is trustworthy again."""


@dataclass(frozen=True)
class Mark:
    """One holding's valuation state for one session."""
    security_id: str
    status: MarkStatus
    raw_mark_close: float | None = None        # only meaningful when CURRENT
    stale_raw_close: float | None = None       # last known, informational

    def __post_init__(self) -> None:
        if self.status is MarkStatus.CURRENT and not _positive(self.raw_mark_close):
            raise ValueError(
                "MarkStatus.CURRENT requires a positive raw_mark_close — a "
                "'current' mark with no price is the stale case wearing the "
                "wrong label, which is precisely what this type exists to stop")

    @property
    def resolves_equity(self) -> bool:
        """Whether this holding's contribution to equity is TRUSTWORTHY.

        CONFIRMED_WORTHLESS resolves: a processed write-off makes zero a fact.
        STALE and UNRESOLVED_TERMINAL do not — and the difference between
        'worth nothing' and 'worth we-don't-know' is the whole point.
        """
        return self.status in (MarkStatus.CURRENT, MarkStatus.CONFIRMED_WORTHLESS)

    @property
    def value_per_share(self) -> float:
        """Trustworthy per-share value. Zero for a confirmed write-off, zero for
        anything unresolved (whose value belongs in the ESTIMATE, not here)."""
        if self.status is MarkStatus.CURRENT:
            return float(self.raw_mark_close)
        return 0.0

    @property
    def estimated_value_per_share(self) -> float:
        """Best-effort per-share value INCLUDING stale information. Explicitly
        not equity — reported alongside so a human can see the gap."""
        if self.status is MarkStatus.CURRENT:
            return float(self.raw_mark_close)
        if self.status is MarkStatus.CONFIRMED_WORTHLESS:
            return 0.0
        return float(self.stale_raw_close) if _positive(self.stale_raw_close) else 0.0


def _positive(x) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0


@dataclass(frozen=True)
class EquityView:
    """Two clearly named numbers, and only one of them is trustworthy.

    `resolved_equity` is None — not zero, not an approximation — when any open
    holding is unresolved. A caller that wants a number regardless has to reach
    for the estimate explicitly and, in doing so, acknowledge what it is.
    """
    resolved_equity: float | None
    estimated_equity_including_stale_marks: float
    cash: float
    unresolved_security_ids: tuple[str, ...] = ()

    @property
    def is_resolved(self) -> bool:
        return self.resolved_equity is not None

    @property
    def sizing_base(self) -> float | None:
        """The ONLY value an admission may size against. Neither number may be
        used while an owned asset's value is unresolved, so this is None
        exactly when admissions are blocked."""
        return self.resolved_equity


def build_equity_view(cash: float, shares_by_security: Mapping[str, int],
                      marks: Mapping[str, Mark]) -> EquityView:
    """Split portfolio value into the trustworthy part and the estimate.

    A holding with NO mark at all is treated as UNRESOLVED rather than absent.
    Silently skipping it is the zero-treatment failure by another route: the
    position vanishes from equity while remaining in the book.
    """
    resolved = float(cash)
    estimated = float(cash)
    unresolved: list[str] = []

    for sec in sorted(shares_by_security):
        qty = shares_by_security[sec]
        m = marks.get(sec)
        if m is None:
            m = Mark(sec, MarkStatus.STALE)          # no mark == unresolved
        if m.resolves_equity:
            resolved += qty * m.value_per_share
        else:
            unresolved.append(sec)
        estimated += qty * m.estimated_value_per_share

    return EquityView(
        resolved_equity=None if unresolved else resolved,
        estimated_equity_including_stale_marks=estimated,
        cash=float(cash),
        unresolved_security_ids=tuple(unresolved))


UNRESOLVED_REPRODUCTION: dict[str, str] = {
    "unmarkable_holding_treatment":
        "ADOPTED 2026-08-03: an unmarkable or terminally-unresolved holding is "
        "preserved at its share count, its last price kept as explicitly stale, "
        "and NEW ADMISSIONS ARE BLOCKED until resolution. The certified "
        "prototype's behaviour here is unknown — it may have zeroed the holding "
        "or carried the last price, either of which changes every subsequent "
        "admission size. A reproduction difference, not a correctness one.",
}
