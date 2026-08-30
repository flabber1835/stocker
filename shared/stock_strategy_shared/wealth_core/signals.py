"""Wealth Core v1 — signal mathematics. PURE: no DB, no clock, no I/O.

Every formula here is transcribed from the written specification, with the
section it came from named at the point of use. Where the spec forces a choice
it does not make, the choice is a PARAMETER with a documented default, never an
inlined constant — see `UNRESOLVED` at the bottom of this module and
docs/wealth-core-v1.md.

PRICE DOMAIN (spec §2). Everything in this file consumes SPLIT-ADJUSTED,
DIVIDEND-UNADJUSTED closes. Passing a dividend-adjusted total-return series here
is a specification violation, not a rounding difference: it would change the
signal, the ranking and the trailing stop simultaneously. The caller owns that
contract; this module cannot detect the difference and does not try.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

# ── Session offsets (spec §3, §5) ────────────────────────────────────────────
# The signal reads close[t-21] and close[t-126]; the formation segment is the
# daily path from t-126 through t-21 INCLUSIVE. Named rather than literal so the
# tests and the config speak the same vocabulary as the spec.
SKIP_RECENT_SESSIONS = 21
LONG_LOOKBACK_SESSIONS = 126
TRADING_SESSIONS_PER_YEAR = 252

# Closes needed to evaluate a candidate at session t: indices t-126 … t
# inclusive. Spec §1 requires "exact continuous history covering 126 market
# sessions"; 126 SPANS require 127 observations, and an off-by-one here silently
# admits securities one session short of the stated history.
REQUIRED_CLOSES = LONG_LOOKBACK_SESSIONS + 1


def _finite(x) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


def medium_term_momentum(
        closes: Sequence[float | None]) -> float | None:
    """Spec §3:  close[t-21] / close[t-126] - 1

    `closes` is the trailing window ending at t, oldest first, so index -1 is
    close[t]. Returns None when the window is short or either endpoint is
    unusable — never a sentinel number, because a sentinel would rank.
    """
    if closes is None or len(closes) < REQUIRED_CLOSES:
        return None
    near = closes[-(SKIP_RECENT_SESSIONS + 1)]
    far = closes[-(LONG_LOOKBACK_SESSIONS + 1)]
    if not (_finite(near) and _finite(far)):
        return None
    near, far = float(near), float(far)
    if far <= 0 or near <= 0:
        return None
    return near / far - 1.0


def recent_return(closes: Sequence[float | None]) -> float | None:
    """Spec §4:  close[t] / close[t-21] - 1

    The freshness gate is `>= 0` and ZERO QUALIFIES (spec §4, explicit). That
    boundary is a mandatory acceptance test, so the comparison lives in
    `passes_freshness` rather than being written inline at each call site.
    """
    if closes is None or len(closes) < SKIP_RECENT_SESSIONS + 1:
        return None
    last = closes[-1]
    prior = closes[-(SKIP_RECENT_SESSIONS + 1)]
    if not (_finite(last) and _finite(prior)):
        return None
    last, prior = float(last), float(prior)
    if prior <= 0 or last <= 0:
        return None
    return last / prior - 1.0


def passes_freshness(recent: float | None) -> bool:
    """Spec §4: require recent_return >= 0. Zero qualifies."""
    return recent is not None and recent >= 0.0


# ── Volatility profiles (SPECIFICATION CONFLICT, resolved 2026-08-05) ───────
# The written §5 spec says "sample standard deviation of one-session SIMPLE
# returns". The RECOVERED CERTIFIED SOURCE uses LOG returns. Both are here, both
# named, and the certified configuration selects the certified one.
#
# They are NOT interchangeable and the difference is not cosmetic: log returns
# compress large moves, so a volatile name scores a lower denominator and a
# HIGHER durable score than it would on simple returns. That reorders the
# ranking and therefore changes which securities are bought.
#
# Editing the formula in place would have made every historical result
# unattributable — the same config hash would refer to two different strategies
# depending on when it ran. The profile name is in the config hash instead, so a
# result can always be traced to the rule that produced it.
SIMPLE_RETURNS_V1 = "simple_returns_v1"
"""The written §5 spec: (P_t / P_{t-1}) - 1. Retained, selectable, superseded
for certified parity."""

LOG_RETURNS_CERTIFIED_V1 = "log_returns_certified_v1"
"""The recovered certified source: ln(P_t / P_{t-1}). AUTHORITATIVE for
"certified Wealth Core"."""

VOLATILITY_PROFILES: tuple[str, ...] = (SIMPLE_RETURNS_V1,
                                        LOG_RETURNS_CERTIFIED_V1)

DEFAULT_VOLATILITY_PROFILE = LOG_RETURNS_CERTIFIED_V1
"""Certified reproduction is the point of this engine, so the certified rule is
the default. A deployment wanting the old written-spec behaviour must ask for it
by name — the traceable direction, since silence should mean the authoritative
source rather than a superseded one."""


def annualized_formation_volatility(
        closes: Sequence[float | None],
        profile: str = DEFAULT_VOLATILITY_PROFILE) -> float | None:
    """Annualised sample stdev of one-session returns over the formation
    segment (t-126 … t-21), x sqrt(252).

    SAMPLE standard deviation means ddof=1. The formation segment spans 106
    closes and therefore 105 returns.

    `profile` selects SIMPLE or LOG returns — see the block above; they are two
    different strategies, not two spellings of one.

    Returns None for zero, non-finite, or insufficient observations (spec §5:
    "Reject zero, nonfinite, or insufficient volatility observations") — a zero
    denominator would otherwise send `durable_score` to infinity and hand the
    top of the ranking to whichever security had a frozen price.
    """
    if profile not in VOLATILITY_PROFILES:
        raise ValueError(
            f"unknown volatility profile {profile!r}; known: "
            f"{list(VOLATILITY_PROFILES)}. Refused rather than defaulted — "
            f"defaulting would score a run under a formula the caller did not "
            f"choose, which is the whole reason these are named.")
    if closes is None or len(closes) < REQUIRED_CLOSES:
        return None
    # Inclusive segment: index t-126 through t-21.
    seg = closes[-(LONG_LOOKBACK_SESSIONS + 1):len(closes) - SKIP_RECENT_SESSIONS]
    if len(seg) < 3:
        return None
    use_log = profile == LOG_RETURNS_CERTIFIED_V1
    rets: list[float] = []
    for prev, cur in zip(seg, seg[1:]):
        if not (_finite(prev) and _finite(cur)):
            return None            # a gap inside formation invalidates the window
        prev, cur = float(prev), float(cur)
        if prev <= 0 or (use_log and cur <= 0):
            return None
        rets.append(math.log(cur / prev) if use_log else cur / prev - 1.0)
    n = len(rets)
    if n < 2:
        return None
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)      # ddof=1
    if not math.isfinite(var) or var <= 0:
        return None
    vol = math.sqrt(var) * math.sqrt(TRADING_SESSIONS_PER_YEAR)
    return vol if math.isfinite(vol) and vol > 0 else None


def durable_score(momentum: float | None, vol: float | None) -> float | None:
    """Spec §5:  log1p(medium_term_momentum) / annualized_formation_volatility

    This is the FINAL candidate ordering. Raw momentum decides membership in the
    leadership decile (spec §3) and is explicitly NOT the sort key — a
    distinction with a mandatory acceptance test, because the two orderings
    genuinely differ whenever a lower-momentum name is calmer.

    log1p is undefined at or below -100%; such a candidate is rejected rather
    than clamped.
    """
    if momentum is None or vol is None:
        return None
    if not (_finite(momentum) and _finite(vol)) or vol <= 0:
        return None
    if momentum <= -1.0:
        return None
    score = math.log1p(float(momentum)) / float(vol)
    return score if math.isfinite(score) else None


# ── Top-decile membership (spec §3) ─────────────────────────────────────────

# LOCKED 2026-08-03: ceil(eligible_count x 0.10), floored at one candidate
# whenever the eligible universe is non-empty. Named rather than inlined so the
# adapters, the config hash and the tests all refer to the same value.
DEFAULT_TOP_FRACTION = 0.10
DEFAULT_TOP_DECILE_ROUNDING = "ceil"
# CERTIFIED SOURCE (2026-08-03 correction): the frozen implementation used
# max(25, ceil(N x 0.10)), NOT ceil with a minimum of one. Identical for large
# universes; materially different for small ones and for early history, which is
# exactly where a reproduction would first diverge.
DEFAULT_MIN_TOP_DECILE = 1
MINIMUM_LEADERSHIP_POPULATION = 25


def leadership_count(n_eligible: int, top_fraction: float = DEFAULT_TOP_FRACTION,
                     rounding: str = DEFAULT_TOP_DECILE_ROUNDING,
                     minimum_leadership_population: int = MINIMUM_LEADERSHIP_POPULATION
                     ) -> int:
    """CERTIFIED: max(minimum_leadership_population, ceil(N x top_fraction)),
    capped at N.

    The floor of 25 matters only when the eligible universe is small — but that
    is precisely early history, where a reproduction diverges first and where a
    "minimum of one" would have the strategy picking from a single name while
    the certified path considered everything available.
    """
    return top_decile_cutoff(n_eligible, top_fraction, rounding,
                             minimum=minimum_leadership_population)


def top_decile_cutoff(n_eligible: int, top_fraction: float = DEFAULT_TOP_FRACTION,
                      rounding: str = DEFAULT_TOP_DECILE_ROUNDING,
                      minimum: int = DEFAULT_MIN_TOP_DECILE) -> int:
    """How many of the ranked cross-section are retained as "the highest 10%".

    UNRESOLVED IN THE SPEC. The assignment says "retain the highest 10%" without
    stating the rounding rule or the tie policy at the boundary, and the two
    plausible readings differ by one name on most days. `ceil` is the default
    because it is inclusive at the boundary — with 25 slots, admitting one extra
    candidate is a far smaller error than excluding a genuine leader — but it is
    a CONFIGURED choice, reported as unresolved, not a silent constant.

    Ties at the cutoff are resolved by the deterministic sort in
    `rank_candidates` (spec §5: security_id then ticker), NOT by expanding the
    set. That too is a recorded decision.
    """
    if n_eligible <= 0:
        return 0                       # empty universe admits nobody
    raw = n_eligible * float(top_fraction)
    if rounding == "ceil":
        k = math.ceil(raw)
    elif rounding == "floor":
        k = math.floor(raw)
    elif rounding == "round":
        k = int(raw + 0.5)
    else:
        raise ValueError(f"unknown top-decile rounding rule: {rounding!r}")
    # The minimum is what stops a thin universe from admitting nobody at all
    # under `floor`. It never expands the set beyond the deterministic count —
    # ties at the boundary are still resolved by the sort, not by inclusion.
    return max(0, min(max(int(k), int(minimum)), n_eligible))


# ── Deterministic candidate ordering (spec §5) ──────────────────────────────

@dataclass(frozen=True)
class DurableScore:
    """One candidate's full signal record. Every field the audit trail needs is
    carried, including the values that caused a REJECTION — a candidate that
    fails is as much a decision as one that passes."""
    security_id: str
    ticker: str
    momentum: float | None
    recent: float | None
    volatility: float | None
    score: float | None
    in_top_decile: bool = False
    reason: str = ""

    @property
    def qualified(self) -> bool:
        return self.in_top_decile and self.score is not None and \
            passes_freshness(self.recent)


def rank_candidates(rows: Iterable[DurableScore]) -> list[DurableScore]:
    """Descending durable score, with security_id then ticker as stable tie
    breakers (spec §5).

    INPUT ORDER MUST NOT MATTER. The tie breakers are not decoration: without
    them a database returning rows in a different order would produce a
    different portfolio from identical data, which breaks both determinism and
    the cross-engine parity contract. A mandatory acceptance test shuffles the
    input and asserts the output is unchanged.
    """
    from stock_strategy_shared.wealth_core.ordering import sort_for_admission
    # Imported lazily: ordering.py is deliberately dependency-free and importing
    # it at module scope here would close a cycle through engine.py.
    return sort_for_admission([r for r in rows if r.qualified])


# ── Details the specification does not settle ───────────────────────────────
# Surfaced as data so docs and tests can enumerate them, rather than living only
# in prose that drifts. Each is a real fork where a choice had to be made.
UNRESOLVED: dict[str, str] = {
    "top_decile_rounding":
        "LOCKED 2026-08-03: ceil(n x 0.10), minimum 1 while the eligible "
        "universe is non-empty. The ORIGINAL CERTIFICATION ARTIFACT IS STILL "
        "REQUIRED to confirm this matches the historical prototype — this does "
        "not block implementation, but it blocks any claim of exact historical "
        "reproduction.",
    "top_decile_tie_policy":
        "boundary ties are broken by the deterministic sort rather than by "
        "expanding the retained set. The spec states tie breakers for ORDERING "
        "(§5) but not for MEMBERSHIP (§3).",
    "required_history_observations":
        "spec §1 says 'exact continuous history covering 126 market sessions'. "
        "Implemented as 127 CLOSES (t-126 … t inclusive), since 126 spans need "
        "127 observations.",
}
