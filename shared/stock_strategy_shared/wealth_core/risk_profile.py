"""Wealth Core execution-risk profile. PURE: no DB, no clock, no I/O.

WHY A SEPARATE PROFILE RATHER THAN THE EXISTING LIMITS. The risk service's
MAX_POSITIONS, MAX_POSITION_PCT and MAX_DAILY_TURNOVER_PCT were calibrated for a
target-portfolio strategy that rebalances toward normalised weights. Pointed at
Wealth Core they are not merely mis-tuned — several of them mean something the
strategy does not do, and one of them would fire in the one situation where
firing is worst:

    MAX_POSITION_PCT      a CONVERTED position legitimately exceeds its entry
                          weight, because a takeover is not a purchase. Under a
                          weight cap that reads as a breach demanding a trim —
                          a trade Wealth Core does not have and must not learn.
    MAX_DAILY_TURNOVER    a drawdown that trips several trailing stops at once
                          is the moment turnover is highest AND the moment exits
                          matter most. A cap that throttles them converts a risk
                          control into a risk.
    MAX_POSITIONS         counts held names. Wealth Core also has slots RESERVED
                          by queued-but-unfilled entries, which are already
                          committed capital; a count that ignores them
                          over-admits by exactly the number in flight.

So the limits are named here, in the strategy's own vocabulary, and a deploy that
selects Wealth Core without them FAILS TO START (`require_profile`). Inheriting
limits whose semantics are ambiguous is worse than having none, because the
ambiguity is invisible until the day it binds.

THE STRATEGY LIMIT AND THE EMERGENCY BRAKE ARE DIFFERENT THINGS. "One admission
per session" is how the strategy behaves, not a safety rail: it constrains ENTRIES
only, and it must never constrain an exit, a kill-switch liquidation or a
broker-side forced close. Every check below that could touch a sell is explicitly
inert for one, and there is a test per case — because the failure mode is a book
that cannot get out.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

PROFILE_NAME = "wealth_core_v1"


class TurnoverBehavior(str, Enum):
    EXITS_EXEMPT = "exits_exempt"
    """Exits are never counted against, or limited by, a turnover cap.

    The only supported value, and it is an enum rather than a boolean so the
    intent survives in config and in the audit row. A turnover cap exists to
    damp discretionary churn; Wealth Core has none — it never trims, never scales
    in, and never rebalances — so every sell it makes is a stop, a review exit or
    a corporate action, and throttling those has no upside to trade against."""


class FractionalSharePolicy(str, Enum):
    WHOLE_SHARES_ONLY = "whole_shares_only"
    """Sizes floor to whole shares; fractional entitlements from corporate
    actions settle in cash. Never round up — that delivers a share nobody
    issued."""


class PartialFillPolicy(str, Enum):
    ACCEPT_GAP_REDUCED = "accept_gap_reduced"
    """An entry sized on session t's close and filled at t+1's open may gap and
    become unaffordable at full size. The reduced quantity is a VALID entry, not
    a breach: the alternative is refusing the position entirely because the
    market moved between the decision and the fill, which would silently make
    the strategy skip exactly the names that ran."""


class RiskProfileUnavailable(RuntimeError):
    """Wealth Core was selected but no Wealth Core risk profile is configured.

    A startup failure by design. The legacy profile would load, every check
    would pass, and the limits enforced would be the wrong ones — with nothing
    in any log to say so.
    """


@dataclass(frozen=True)
class WealthCoreRiskProfile:
    name: str = PROFILE_NAME

    # ── structure ────────────────────────────────────────────────────────────
    maximum_positions: int = 25
    nominal_entry_weight: float = 0.04
    maximum_new_entries_per_session: int = 1

    # ── per-session notional ────────────────────────────────────────────────
    # Entries are bounded because an over-large entry is a sizing bug. Exits are
    # NOT: `None` here means unlimited and is the only correct value, since the
    # session on which the most capital needs to leave is a drawdown.
    maximum_total_entry_notional_per_session: float | None = None
    maximum_exit_notional_per_session: float | None = None

    # In-flight entries are committed capital. Counting them is what keeps the
    # risk view and the planner's slot view from disagreeing.
    maximum_pending_entry_reservations: int = 5

    # ── concentration, on AGGREGATED exposure ───────────────────────────────
    # Deliberately well above nominal_entry_weight: a position that ran, or two
    # holdings a takeover consolidated, legitimately exceeds its entry weight.
    # These are absurdity bounds, not rebalancing triggers.
    maximum_single_security_aggregate_exposure: float = 0.25
    maximum_same_issuer_exposure: float = 0.30

    # ── behaviour ───────────────────────────────────────────────────────────
    maximum_daily_turnover_behavior: TurnoverBehavior = TurnoverBehavior.EXITS_EXEMPT
    minimum_cash_buffer: float = 0.0
    fractional_share_policy: FractionalSharePolicy = \
        FractionalSharePolicy.WHOLE_SHARES_ONLY
    partial_fill_policy: PartialFillPolicy = PartialFillPolicy.ACCEPT_GAP_REDUCED

    def __post_init__(self) -> None:
        if self.maximum_exit_notional_per_session is not None:
            raise ValueError(
                "maximum_exit_notional_per_session must be None (unlimited). A "
                "cap on exits binds hardest during a drawdown — the session on "
                "which the most capital needs to leave — turning a risk control "
                "into a risk. If a broker-side limit genuinely exists, model it "
                "in the executor, not as a strategy risk limit.")
        if self.maximum_single_security_aggregate_exposure < self.nominal_entry_weight:
            raise ValueError(
                "maximum_single_security_aggregate_exposure below "
                "nominal_entry_weight would breach on the day of entry")
        if self.maximum_daily_turnover_behavior is not TurnoverBehavior.EXITS_EXEMPT:
            raise ValueError("only exits_exempt turnover behaviour is supported")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "maximum_positions": self.maximum_positions,
            "nominal_entry_weight": self.nominal_entry_weight,
            "maximum_new_entries_per_session": self.maximum_new_entries_per_session,
            "maximum_total_entry_notional_per_session":
                self.maximum_total_entry_notional_per_session,
            "maximum_exit_notional_per_session": self.maximum_exit_notional_per_session,
            "maximum_pending_entry_reservations":
                self.maximum_pending_entry_reservations,
            "maximum_single_security_aggregate_exposure":
                self.maximum_single_security_aggregate_exposure,
            "maximum_same_issuer_exposure": self.maximum_same_issuer_exposure,
            "maximum_daily_turnover_behavior":
                self.maximum_daily_turnover_behavior.value,
            "minimum_cash_buffer": self.minimum_cash_buffer,
            "fractional_share_policy": self.fractional_share_policy.value,
            "partial_fill_policy": self.partial_fill_policy.value,
        }


@dataclass(frozen=True)
class RiskVerdict:
    approved: bool
    reasons: tuple[str, ...] = ()
    detail: dict = field(default_factory=dict)


def require_profile(execution_model: str,
                    profiles: Mapping[str, WealthCoreRiskProfile] | None
                    ) -> WealthCoreRiskProfile:
    """Startup gate. Fails if Wealth Core is selected without its own profile."""
    if execution_model != "stateful_ownership":
        raise ValueError(
            f"require_profile is for stateful_ownership; got {execution_model!r}")
    profile = (profiles or {}).get(PROFILE_NAME)
    if profile is None:
        raise RiskProfileUnavailable(
            f"execution_model=stateful_ownership requires the {PROFILE_NAME!r} "
            f"risk profile; available: {sorted((profiles or {}))}. Refusing to "
            f"start on the target-portfolio profile — its MAX_POSITION_PCT would "
            f"read a converted position as a breach demanding a trim, and its "
            f"turnover cap would throttle trailing-stop exits during a drawdown. "
            f"Every check would pass while enforcing the wrong limits.")
    return profile


def evaluate_entry(*, profile: WealthCoreRiskProfile, equity: float | None,
                   cash: float, notional: float,
                   held_positions: int, pending_reservations: int,
                   entries_this_session: int,
                   entry_notional_this_session: float = 0.0,
                   aggregate_exposure_after: float = 0.0,
                   issuer_exposure_after: float = 0.0,
                   is_gap_reduced: bool = False) -> RiskVerdict:
    """Gate ONE admission. Entries only — never reached by a sell."""
    reasons: list[str] = []

    if equity is None:
        # The equity gate, restated at the risk layer. 4% of an unknown is not a
        # number, and an admission is the only operation that needs one.
        reasons.append("UNRESOLVED_EQUITY")
        return RiskVerdict(False, tuple(reasons))

    # Pending reservations count toward BOTH the slot view and this one. A risk
    # check that ignored them would approve entries the planner has already
    # committed capital to, and the two would disagree by exactly the number in
    # flight — the divergence class the shared capacity rule exists to close.
    projected = held_positions + pending_reservations
    if projected >= profile.maximum_positions:
        reasons.append("MAX_POSITIONS")
    if pending_reservations >= profile.maximum_pending_entry_reservations:
        reasons.append("MAX_PENDING_RESERVATIONS")
    if entries_this_session >= profile.maximum_new_entries_per_session:
        reasons.append("MAX_ENTRIES_PER_SESSION")

    cap = profile.maximum_total_entry_notional_per_session
    if cap is not None and entry_notional_this_session + notional > cap:
        reasons.append("MAX_ENTRY_NOTIONAL_PER_SESSION")

    if cash - notional < profile.minimum_cash_buffer:
        reasons.append("MIN_CASH_BUFFER")
    if notional > cash:
        reasons.append("INSUFFICIENT_CASH")

    if aggregate_exposure_after > profile.maximum_single_security_aggregate_exposure:
        reasons.append("MAX_SINGLE_SECURITY_EXPOSURE")
    if issuer_exposure_after > profile.maximum_same_issuer_exposure:
        reasons.append("MAX_ISSUER_EXPOSURE")

    # A gap-reduced entry is explicitly NOT a breach. It is smaller than the 4%
    # intent because the market moved between the decision and the fill;
    # rejecting it would make the strategy skip exactly the names that ran.
    detail = {"gap_reduced": is_gap_reduced,
              "weight": None if not equity else notional / equity}
    return RiskVerdict(not reasons, tuple(reasons), detail)


def evaluate_exit(*, profile: WealthCoreRiskProfile, notional: float,
                  exit_notional_this_session: float = 0.0,
                  reason: str = "") -> RiskVerdict:
    """Gate one exit. Approves unconditionally, and that is the design.

    Every sell Wealth Core makes is a trailing stop, a review exit or a corporate
    action — it never trims and never rebalances — so there is no discretionary
    churn for a turnover cap to damp, and the sessions with the most selling are
    the ones where blocking a sale is worst. A limit that can refuse an exit
    belongs in the executor as a broker constraint, not here as a strategy rule.
    """
    return RiskVerdict(True, (), {
        "reason": reason, "notional": notional,
        "exit_notional_this_session": exit_notional_this_session + notional,
        "turnover_behavior": profile.maximum_daily_turnover_behavior.value,
        "exempt_from_turnover_cap": True})


def aggregate_exposures(shares_by_security: Mapping[str, int],
                        issuer_by_security: Mapping[str, str],
                        prices: Mapping[str, float],
                        equity: float) -> tuple[dict, dict]:
    """Exposure per SECURITY and per ISSUER, from AGGREGATED share counts.

    Aggregation is load-bearing: two predecessor lots converted into one acquirer
    are ONE exposure, and reading them per-episode reports two 4% positions where
    the book holds one 8% position — the exact number a concentration limit
    exists to catch.
    """
    if equity <= 0:
        return {}, {}
    by_sec: dict[str, float] = {}
    by_issuer: dict[str, float] = {}
    for sec, qty in shares_by_security.items():
        px = prices.get(sec)
        if px is None or px <= 0:
            continue
        w = qty * float(px) / equity
        by_sec[sec] = by_sec.get(sec, 0.0) + w
        iss = issuer_by_security.get(sec, sec)
        by_issuer[iss] = by_issuer.get(iss, 0.0) + w
    return by_sec, by_issuer


DEFAULT_PROFILES: dict[str, WealthCoreRiskProfile] = {
    PROFILE_NAME: WealthCoreRiskProfile(),
}

__all__ = ["DEFAULT_PROFILES", "FractionalSharePolicy", "PROFILE_NAME",
           "PartialFillPolicy", "RiskProfileUnavailable", "RiskVerdict",
           "TurnoverBehavior", "WealthCoreRiskProfile", "aggregate_exposures",
           "evaluate_entry", "evaluate_exit", "require_profile"]
