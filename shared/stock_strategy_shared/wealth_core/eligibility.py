"""Wealth Core v1 — the ENTRY-UNIVERSE eligibility engine. PURE.

TRADEABILITY AND ELIGIBILITY ARE DIFFERENT QUESTIONS, and conflating them was a
real defect in the first adapter:

    is_eligible_candidate   may this security enter the LEADERSHIP POPULATION on
                            this SIGNAL date? (spec §1)
    can_execute             may an already-scheduled order FILL at this open?
                            (positive volume, tradeable, no unresolved action)

They are evaluated at different times, on different sessions, for different
purposes. A security can be perfectly eligible on the signal date and untradeable
at the next open — the entry simply does not fill, and the order waits. The
reverse must NEVER hold: tradeability cannot make an ineligible security
eligible, which is a permanent invariant test.

Using `can_execute` as eligibility made the decile population "everything
tradeable" rather than the investable universe — wider than specified, admitting
ETFs, preferreds, sub-$1 stocks and illiquid names the strategy must never see.

HISTORY COUNTING. `min_history_sessions = 126` counts sessions of continuous
history PRIOR TO the signal session. With the signal session itself that is 127
closes, which is exactly what `medium_term_momentum` needs to read close[t-126].
So "126 sessions qualify, 125 fail" and "127 observations" describe the same
rule; they are not in tension.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence

from stock_strategy_shared.wealth_core.signals import (
    REQUIRED_CLOSES,
    annualized_formation_volatility,
)


class SecurityClass(str, Enum):
    """Spec §1: common stock or common ADR only."""
    COMMON = "COMMON"
    ADR_COMMON = "ADR_COMMON"
    PREFERRED = "PREFERRED"
    ETF = "ETF"
    FUND = "FUND"
    WARRANT = "WARRANT"
    UNIT = "UNIT"
    OTHER = "OTHER"


ADMISSIBLE_CLASSES = frozenset({SecurityClass.COMMON, SecurityClass.ADR_COMMON})


class EligibilityReason(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_COMMON_EQUITY = "NOT_COMMON_EQUITY"
    NOT_LISTED_ON_SESSION = "NOT_LISTED_ON_SESSION"
    PRICE_BELOW_MINIMUM = "PRICE_BELOW_MINIMUM"
    ADV20_BELOW_MINIMUM = "ADV20_BELOW_MINIMUM"
    SIGNAL_DOLLAR_VOLUME_BELOW_MINIMUM = "SIGNAL_DOLLAR_VOLUME_BELOW_MINIMUM"
    INSUFFICIENT_126_SESSION_HISTORY = "INSUFFICIENT_126_SESSION_HISTORY"
    INVALID_FORMATION_VOLATILITY = "INVALID_FORMATION_VOLATILITY"
    DUPLICATE_ISSUER = "DUPLICATE_ISSUER"
    UNRESOLVED_TERMINAL_ACTION = "UNRESOLVED_TERMINAL_ACTION"


@dataclass(frozen=True)
class EligibilityConfig:
    """Spec §1 thresholds. "At least" means `>=` throughout, so a security
    sitting exactly on a threshold QUALIFIES — pinned by boundary tests, because
    `>` and `>=` differ by a real security on a real day."""
    min_unadjusted_price: float = 1.0
    min_adv20_dollars: float = 20_000_000.0
    min_signal_dollar_volume: float = 5_000_000.0
    min_history_sessions: int = 126        # PRIOR to the signal session


@dataclass(frozen=True)
class EligibilityInput:
    """One security's signal-day facts.

    `listed_on_session` carries point-in-time existence: a security that had not
    yet IPO'd, or had already delisted, was not in the universe that day. A
    delisted security REMAINS historically eligible for the sessions on which it
    existed — that is what stops survivorship bias.
    """
    security_id: str
    ticker: str
    issuer_id: str
    security_class: SecurityClass
    listed_on_session: bool
    unadjusted_signal_price: float | None
    adv20_dollars: float | None
    signal_dollar_volume: float | None
    signal_closes_split_adj_div_unadj: Sequence[float]
    unresolved_terminal_action: bool = False
    is_primary_listing: bool = True


@dataclass(frozen=True)
class EligibilityResult:
    security_id: str
    ticker: str
    issuer_id: str
    eligible: bool
    reason: EligibilityReason
    detail: dict = field(default_factory=dict)


def evaluate(inp: EligibilityInput, cfg: EligibilityConfig) -> EligibilityResult:
    """All §1 entry-universe requirements except issuer dedup (which needs the
    whole cross-section and runs afterwards).

    Order is deliberate: cheap structural facts first, the volatility computation
    last. It also produces the most USEFUL reason — a security failing on both
    price and history is better reported as sub-$1 than as short-history.
    """
    def no(reason, **d):
        return EligibilityResult(inp.security_id, inp.ticker, inp.issuer_id,
                                 False, reason, d)

    if inp.unresolved_terminal_action:
        # FAIL CLOSED and FIRST: a security whose terminal outcome is unknown
        # must not be admitted whatever else is true of it.
        return no(EligibilityReason.UNRESOLVED_TERMINAL_ACTION)
    if not inp.listed_on_session:
        return no(EligibilityReason.NOT_LISTED_ON_SESSION)
    if inp.security_class not in ADMISSIBLE_CLASSES:
        return no(EligibilityReason.NOT_COMMON_EQUITY,
                  security_class=inp.security_class.value)
    if inp.unadjusted_signal_price is None or \
            inp.unadjusted_signal_price < cfg.min_unadjusted_price:
        return no(EligibilityReason.PRICE_BELOW_MINIMUM,
                  price=inp.unadjusted_signal_price)
    if inp.adv20_dollars is None or inp.adv20_dollars < cfg.min_adv20_dollars:
        return no(EligibilityReason.ADV20_BELOW_MINIMUM, adv20=inp.adv20_dollars)
    if inp.signal_dollar_volume is None or \
            inp.signal_dollar_volume < cfg.min_signal_dollar_volume:
        return no(EligibilityReason.SIGNAL_DOLLAR_VOLUME_BELOW_MINIMUM,
                  signal_dollar_volume=inp.signal_dollar_volume)

    closes = list(inp.signal_closes_split_adj_div_unadj or ())
    # CONTINUITY, not just length: a window with a hole in it has 127 slots and
    # less than 127 sessions of history. None inside the window is a gap.
    if len(closes) < REQUIRED_CLOSES or any(
            c is None or not _positive(c) for c in closes[-REQUIRED_CLOSES:]):
        return no(EligibilityReason.INSUFFICIENT_126_SESSION_HISTORY,
                  observations=len(closes), required=REQUIRED_CLOSES)

    if annualized_formation_volatility(closes) is None:
        return no(EligibilityReason.INVALID_FORMATION_VOLATILITY)

    return EligibilityResult(inp.security_id, inp.ticker, inp.issuer_id, True,
                             EligibilityReason.ELIGIBLE, {})


def _positive(x) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return f == f and f > 0 and f != float("inf")


# ── issuer deduplication (spec §1: one position per economic issuer) ────────

def _dedup_key(inp: EligibilityInput):
    """The deterministic preference order, exposed so the audit trail can show
    WHY one listing beat another:

        1. primary common share
        2. otherwise primary ADR
        3. higher ADV20
        4. permanent security id
        5. ticker

    Sorting ascending, so every term is negated where "bigger wins".
    """
    cls_rank = {SecurityClass.COMMON: 0, SecurityClass.ADR_COMMON: 1}.get(
        inp.security_class, 9)
    return (0 if inp.is_primary_listing else 1,
            cls_rank,
            -(inp.adv20_dollars or 0.0),
            inp.security_id,
            inp.ticker)


def deduplicate_issuers(inputs: Iterable[EligibilityInput],
                        results: dict[str, EligibilityResult]
                        ) -> dict[str, EligibilityResult]:
    """Keep ONE security per economic issuer, among those already eligible.

    Runs AFTER the per-security filters and BEFORE the top decile, because the
    decile count is a fraction of the eligible population — deduplicating
    afterwards would compute the cutoff over a population that includes
    duplicates and admit a slightly wider set.
    """
    by_issuer: dict[str, list[EligibilityInput]] = {}
    for inp in inputs:
        r = results.get(inp.security_id)
        if r is not None and r.eligible:
            by_issuer.setdefault(inp.issuer_id, []).append(inp)

    out = dict(results)
    for issuer in sorted(by_issuer):
        contenders = sorted(by_issuer[issuer], key=_dedup_key)
        winner = contenders[0]
        for loser in contenders[1:]:
            out[loser.security_id] = EligibilityResult(
                loser.security_id, loser.ticker, loser.issuer_id, False,
                EligibilityReason.DUPLICATE_ISSUER,
                {"kept": winner.security_id, "kept_ticker": winner.ticker})
    return out


def eligible_universe(inputs: Sequence[EligibilityInput],
                      cfg: EligibilityConfig | None = None
                      ) -> dict[str, EligibilityResult]:
    """The full signal-day pipeline: per-security filters, then issuer dedup.

    Deterministic by construction — the inputs are sorted before evaluation, so
    the result cannot depend on the order a database returned rows in.
    """
    cfg = cfg or EligibilityConfig()
    ordered = sorted(inputs, key=lambda i: (i.security_id, i.ticker))
    results = {i.security_id: evaluate(i, cfg) for i in ordered}
    return deduplicate_issuers(ordered, results)


def eligible_ids(results: dict[str, EligibilityResult]) -> list[str]:
    """Canonically ordered — the audit hash is built from this, never from
    arrival order."""
    return sorted(sid for sid, r in results.items() if r.eligible)
