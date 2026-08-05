"""Wealth Core v1 — the price-domain contract, ENFORCED at the boundary.

Spec §2 keeps four price domains apart, and mixing any two is a silent
correctness failure rather than a crash:

    signal / trailing stop   split-adjusted, dividend-UNADJUSTED close
    execution                reconstructed actual RAW open
    portfolio marking        actual RAW unadjusted close
    dividends / splits       explicit ledger and share events

Supply a dividend-adjusted total-return series as the signal close and momentum
silently changes on every dividend payer. Supply an adjusted close as the mark
and every 4% admission is sized off the wrong equity. Neither raises; both
produce a plausible backtest that is not the strategy.

So the boundary refuses the ambiguous names outright. A field called `price`,
`close` or `adjusted_close` cannot express WHICH domain it belongs to, and a
contract that relies on the caller remembering is not a contract — it is a
comment. `DailyBar` names every domain explicitly and validates on construction.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

# Names that carry no domain information. Rejected at the boundary rather than
# tolerated, because every one of them reads as "obviously the right price" to
# whoever is wiring an adapter at the time.
BANNED_FIELD_NAMES = frozenset({
    "price", "close", "adjusted_close", "adj_close", "closeadj", "px",
    "last", "value", "prc",
})


class PriceDomainError(ValueError):
    """A Wealth Core adapter supplied a price whose domain is unstated or
    wrong. Its own type so an adapter test can assert the contract fired rather
    than matching on message text."""


def _positive(x: Any) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0


@dataclass(frozen=True)
class DailyBar:
    """One security on one session, with every price domain named.

    Nothing here is optional-by-accident: a field that is None means the adapter
    genuinely does not have that observation for this session, which the engine
    treats as "cannot act", never as zero.
    """
    security_id: str
    ticker: str
    issuer_id: str
    session: str

    # §2 domain 1 — signals and the trailing stop.
    signal_close_split_adj_div_unadj: float | None

    # §2 domain 2 — execution. The reconstructed ACTUAL raw open.
    raw_open: float | None

    # §2 domain 3 — portfolio marking. The actual RAW unadjusted close.
    raw_mark_close: float | None

    # §1 — "positive volume on the eventual execution session". Tradeability is
    # a fact about the session, not something the engine can infer from a price:
    # a halted name still prints a close.
    tradeable: bool = True

    # §2 domains 4/5 — explicit corporate-action events, never folded into a
    # price. 1.0 and 0.0 mean "no event", which is different from "unknown".
    split_ratio: float = 1.0
    dividend_per_share: float = 0.0

    # §1 — unresolved terminal actions FAIL CLOSED: the security is untradeable
    # and unmarkable rather than silently valued at its last print.
    unresolved_corporate_action: bool = False

    def __post_init__(self) -> None:
        for name in ("security_id", "ticker", "issuer_id", "session"):
            if not getattr(self, name):
                raise PriceDomainError(f"DailyBar.{name} is required")
        for name in ("signal_close_split_adj_div_unadj", "raw_open", "raw_mark_close"):
            v = getattr(self, name)
            if v is not None and not _positive(v):
                raise PriceDomainError(
                    f"DailyBar.{name}={v!r} is not a positive finite price. Use "
                    f"None for 'not observed' — zero or NaN would be treated as "
                    f"a real price by whatever reads it next.")
        if not _positive(self.split_ratio):
            raise PriceDomainError(
                f"split_ratio={self.split_ratio!r} must be positive (1.0 = no split)")
        if self.dividend_per_share < 0 or not math.isfinite(self.dividend_per_share):
            raise PriceDomainError(
                f"dividend_per_share={self.dividend_per_share!r} must be >= 0")
        if self.unresolved_corporate_action and self.tradeable:
            raise PriceDomainError(
                "an unresolved corporate action must FAIL CLOSED: the security "
                "cannot be tradeable while its action is unresolved (spec §2)")

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "DailyBar":
        """Build from an adapter row, REFUSING domain-ambiguous field names.

        This is the enforcement point. An adapter that hands over `close` gets
        an error naming the four domains, at wiring time, instead of a backtest
        that runs to completion measuring the wrong strategy.
        """
        offending = sorted(BANNED_FIELD_NAMES.intersection(row.keys()))
        if offending:
            raise PriceDomainError(
                f"ambiguous price field(s) {offending} at the Wealth Core "
                f"boundary. Name the domain explicitly: "
                f"signal_close_split_adj_div_unadj (signals + stop), raw_open "
                f"(execution), raw_mark_close (portfolio marking). See spec §2.")
        known = {f for f in cls.__dataclass_fields__}
        unknown = sorted(set(row) - known)
        if unknown:
            raise PriceDomainError(
                f"unknown field(s) {unknown} — the contract is closed so a "
                f"renamed column cannot silently arrive as a no-op")
        return cls(**{k: row[k] for k in row})

    # ── domain accessors, so callers never index a raw dict ──────────────────

    @property
    def can_execute(self) -> bool:
        """§1/§11: orders fill only at a positive-volume tradeable raw open."""
        return (self.tradeable and not self.unresolved_corporate_action
                and _positive(self.raw_open))

    @property
    def can_mark(self) -> bool:
        return not self.unresolved_corporate_action and _positive(self.raw_mark_close)


def signal_closes(bars_by_session: list[DailyBar]) -> list[float]:
    """The split-adjusted, dividend-unadjusted window the signals consume.

    A helper rather than a comprehension at each call site: this is the single
    place where a domain could be swapped by accident, and it being one line
    long is exactly why it is worth naming.
    """
    return [b.signal_close_split_adj_div_unadj for b in bars_by_session]


def marks_from(bars: list[DailyBar]) -> dict[str, float]:
    """{security_id: RAW mark close} for portfolio equity (§2 domain 3).

    Unmarkable securities are OMITTED rather than carried at a stale price —
    PortfolioState.equity treats a missing mark as contributing nothing, which
    is the honest reading of "we do not know what this is worth".
    """
    return {b.security_id: float(b.raw_mark_close) for b in bars if b.can_mark}
