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
from typing import Sequence

from stock_strategy_shared.wealth_core.signals import (
    DEFAULT_VOLATILITY_PROFILE,
    REQUIRED_CLOSES,
    annualized_formation_volatility,
)


class TerminalState(str, Enum):
    """LEDGER state derived from the ACTIONS stream — never from the static
    `isdelisted` flag.

    `isdelisted` says a security delisted; it never says an outcome is PENDING,
    and it can never establish a settlement or a write-off. Deriving terminal
    state from it would silently manufacture resolutions that nobody verified,
    which is the failure the fail-closed rule exists to prevent.
    """
    NORMAL = "NORMAL"
    TERMINAL_PENDING = "TERMINAL_PENDING"
    TERMINAL_RESOLVED = "TERMINAL_RESOLVED"


def is_common_equity(category: str | None) -> bool:
    """The CERTIFIED mapping, transcribed:

        category contains "Common Stock"
        AND NOT contains "Warrant"
        AND NOT contains "Preferred"

    Substring matching on the raw Sharadar category, deliberately — it admits
    both "Domestic Common Stock" and "ADR Common Stock" without this module
    having to enumerate every category string Sharadar has ever emitted, and a
    new one containing "Preferred" is excluded automatically rather than
    silently admitted as OTHER.
    """
    c = (category or "")
    return ("Common Stock" in c) and ("Warrant" not in c) and ("Preferred" not in c)


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
    MISSING_ISSUER_IDENTITY = "MISSING_ISSUER_IDENTITY"
    UNSUPPORTED_EXCHANGE = "UNSUPPORTED_EXCHANGE"


@dataclass(frozen=True)
class EligibilityConfig:
    """Spec §1 thresholds. "At least" means `>=` throughout, so a security
    sitting exactly on a threshold QUALIFIES — pinned by boundary tests, because
    `>` and `>=` differ by a real security on a real day."""
    min_unadjusted_price: float = 1.0
    min_adv20_dollars: float = 20_000_000.0
    min_signal_dollar_volume: float = 5_000_000.0
    min_history_sessions: int = 126        # PRIOR to the signal session
    # Must MATCH WealthCoreConfig.volatility_profile: eligibility rejects a
    # security whose formation volatility is unusable, and that verdict
    # depends on which formula computes it.
    volatility_profile: str = DEFAULT_VOLATILITY_PROFILE
    # Strict mode REFUSES a security whose issuer identity cannot be established
    # from relatedtickers or permaticker. The alternative — guessing from a name
    # or a ticker root — merges unrelated companies and splits related ones.
    strict_issuer_identity: bool = True


@dataclass(frozen=True)
class EligibilityInput:
    """One security's signal-day facts.

    `listed_on_session` carries point-in-time existence: a security that had not
    yet IPO'd, or had already delisted, was not in the universe that day. A
    delisted security REMAINS historically eligible for the sessions on which it
    existed — that is what stops survivorship bias.
    """
    security_id: str                    # permanent security identifier
    ticker: str
    category: str | None                # RAW Sharadar TICKERS.category, retained
    issuer_group_key: str | None
    issuer_key_source: str | None       # RELATEDTICKERS | PERMATICKER
    listed_on_session: bool
    unadjusted_signal_price: float | None
    adv20_dollars: float | None
    signal_dollar_volume: float | None
    signal_closes_split_adj_div_unadj: Sequence[float]
    # Whether those closes occupy CONSECUTIVE market sessions. A per-security
    # window counts OBSERVATIONS, so a security that missed a day still has 127
    # of them — spanning 128 sessions. The momentum endpoints are then read at
    # the wrong offsets and the security is admitted on history it does not
    # have. None = the caller could not determine it, treated as a gap.
    history_contiguous: bool | None = None
    terminal_state: TerminalState = TerminalState.NORMAL
    # OPTIONAL future metadata ONLY. Sharadar does not carry it and the certified
    # prototype did not use it, so nothing in certified mode may read it — proven
    # by a test rather than promised in a comment.
    is_primary_listing: bool | None = None
    exchange: str | None = None
    exchange_authoritative: bool = False


@dataclass(frozen=True)
class EligibilityResult:
    security_id: str
    ticker: str
    issuer_group_key: str | None
    eligible: bool
    reason: EligibilityReason
    detail: dict = field(default_factory=dict)


def evaluate(inp: EligibilityInput, cfg: EligibilityConfig) -> EligibilityResult:
    """All §1 entry-universe requirements EXCEPT issuer conflict.

    Issuer conflict is NOT decided here and NOT before the leadership cutoff —
    the certified implementation ranked the whole eligible population by raw
    momentum, took the leadership set, and only prevented a conflict at
    ADMISSION. Removing related securities earlier changes the population the
    cutoff is computed over, so it cannot reproduce the certified path.
    """
    def no(reason, **d):
        return EligibilityResult(inp.security_id, inp.ticker, inp.issuer_group_key,
                                 False, reason, d)

    if inp.terminal_state is TerminalState.TERMINAL_PENDING:
        # FAIL CLOSED and FIRST. Ledger state from the ACTIONS stream, never a
        # static delisting flag.
        return no(EligibilityReason.UNRESOLVED_TERMINAL_ACTION,
                  terminal_state=inp.terminal_state.value)
    if cfg.strict_issuer_identity and not inp.issuer_group_key:
        # STRICT MODE FAILS rather than inventing a group. A name- or
        # ticker-root-derived issuer would silently merge unrelated companies
        # and split related ones, and neither shows up in any aggregate.
        return no(EligibilityReason.MISSING_ISSUER_IDENTITY)
    if not inp.listed_on_session:
        return no(EligibilityReason.NOT_LISTED_ON_SESSION)
    if (inp.exchange_authoritative
            and (inp.exchange or "").upper() not in {
                "NYSE", "NASDAQ", "NYSEMKT", "NYSEARCA", "BATS", "AMEX"}):
        return no(EligibilityReason.UNSUPPORTED_EXCHANGE,
                  exchange=inp.exchange)
    if not is_common_equity(inp.category):
        return no(EligibilityReason.NOT_COMMON_EQUITY, category=inp.category)
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
    if len(closes) < REQUIRED_CLOSES or any(
            c is None or not _positive(c) for c in closes[-REQUIRED_CLOSES:]):
        return no(EligibilityReason.INSUFFICIENT_126_SESSION_HISTORY,
                  observations=len(closes), required=REQUIRED_CLOSES)

    if inp.history_contiguous is not True:
        # Fail closed on None as well as False: "unknown" and "gapped" are the
        # same risk here, and a feed that cannot say must not be believed.
        return no(EligibilityReason.INSUFFICIENT_126_SESSION_HISTORY,
                  gap="NON_CONTIGUOUS_SESSIONS",
                  contiguous=inp.history_contiguous)
    if annualized_formation_volatility(closes, cfg.volatility_profile) is None:
        return no(EligibilityReason.INVALID_FORMATION_VOLATILITY)

    return EligibilityResult(inp.security_id, inp.ticker, inp.issuer_group_key,
                             True, EligibilityReason.ELIGIBLE,
                             {"category": inp.category,
                              "issuer_key_source": inp.issuer_key_source})


def _positive(x) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return f == f and f > 0 and f != float("inf")


# ── issuer identity (spec correction, certified source) ─────────────────────

def build_issuer_group_key(ticker: str, related_tickers: Sequence[str] | None,
                           permaticker: str | None) -> tuple[str | None, str | None]:
    """The CERTIFIED construction, transcribed exactly:

        related = sorted unique set of {ticker} | set(relatedtickers)
        if len(related) > 1:  key = "|".join(related)
        else:                 key = "P:" + permaticker

    Returns (issuer_group_key, issuer_key_source). Sorting is what makes the key
    independent of the order Sharadar happened to list the related tickers in —
    without it the same issuer would produce different keys on different rows and
    the conflict check would silently stop working.

    Neither source available ⇒ (None, None), which strict mode turns into
    MISSING_ISSUER_IDENTITY rather than a guess.
    """
    related = sorted({t for t in ([ticker] + list(related_tickers or [])) if t})
    if len(related) > 1:
        return "|".join(related), "RELATEDTICKERS"
    if permaticker:
        return f"P:{permaticker}", "PERMATICKER"
    return None, None


def leadership_population(inputs: Sequence[EligibilityInput],
                          cfg: EligibilityConfig | None = None
                          ) -> dict[str, EligibilityResult]:
    """The signal-day eligible population — WITHOUT issuer deduplication.

    Related securities REMAIN here. The certified implementation ranked this
    whole population by raw momentum, took the leadership set from it, and only
    prevented an issuer conflict when admitting. Deduplicating earlier changes
    the population the cutoff is computed over and cannot reproduce it.

    Deterministic: inputs are sorted before evaluation, so the result cannot
    depend on the order a database returned rows in.
    """
    cfg = cfg or EligibilityConfig()
    ordered = sorted(inputs, key=lambda i: (i.security_id, i.ticker))
    return {i.security_id: evaluate(i, cfg) for i in ordered}


# Retained name for callers; the pipeline no longer deduplicates.
eligible_universe = leadership_population


def eligible_ids(results: dict[str, EligibilityResult]) -> list[str]:
    """Canonically ordered — the audit hash is built from this, never from
    arrival order."""
    return sorted(sid for sid, r in results.items() if r.eligible)


# ── liquidity, in the CERTIFIED price domain (2026-08-03 correction) ─────────
# RAW UNADJUSTED close x reported volume — NOT the split-adjusted signal close.
# Using the signal close would rescale every liquidity figure by the cumulative
# split factor, so a stock that split 4:1 would look a quarter as liquid as it
# is, and the error grows with age.

ADV_WINDOW_SESSIONS = 20


def signal_day_dollar_volume(raw_unadjusted_close: float | None,
                             reported_volume: float | None) -> float | None:
    if not _positive(raw_unadjusted_close) or reported_volume is None:
        return None
    try:
        vol = float(reported_volume)
    except (TypeError, ValueError):
        return None
    if vol < 0 or vol != vol:
        return None
    return float(raw_unadjusted_close) * vol


def adv20_dollars(raw_unadjusted_closes: Sequence[float],
                  reported_volumes: Sequence[float],
                  window: int = ADV_WINDOW_SESSIONS) -> float | None:
    """Arithmetic mean of raw close x volume over the `window` sessions ENDING
    AT t — the signal session INCLUDED.

    Any missing or unusable session inside the window fails CONTINUITY and
    returns None. Substituting a stale observation would quietly let a security
    that stopped trading keep its liquidity qualification.
    """
    n = len(raw_unadjusted_closes or ())
    if n < window or len(reported_volumes or ()) != n:
        return None
    closes = list(raw_unadjusted_closes)[-window:]
    vols = list(reported_volumes)[-window:]
    total = 0.0
    for c, v in zip(closes, vols):
        dv = signal_day_dollar_volume(c, v)
        if dv is None:
            return None
        total += dv
    return total / window
