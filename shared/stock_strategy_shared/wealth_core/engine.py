"""Wealth Core v1 — the state machine. PURE: no DB, no clock, no I/O.

ONE implementation of every state transition. The live book, the wind tunnel and
the backtester call `decide()`; they differ only in where the market data comes
from and how the resulting operations are executed. That is what makes the
cross-engine parity test a real test rather than three parallel reimplementations
agreeing by luck.

WHAT THIS IS NOT (spec §12). No daily rank exits, no repeated reviews, no winner
trimming, no drift rebalancing, no normalised target generation, no portfolio-
wide stop, no scale-ins, no sector caps. A holding that is up 300% and ranked
900th is HELD; the only ways out are the one-time review, the episode stop, and
a corporate action.

EXECUTION MODEL (spec §11). `decide()` runs on information available AFTER
session t closes and returns operations to be executed at the NEXT positive-
volume raw open. Nothing here fills anything — the adapter does, and it is the
adapter that enforces "positive volume on the execution session". Keeping the
decision and the fill apart is what stops same-close information leaking into a
signal that depends on that close.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

from stock_strategy_shared.wealth_core.signals import (
    DurableScore,
    leadership_count,
    annualized_formation_volatility,
    durable_score,
    medium_term_momentum,
    passes_freshness,
    rank_candidates,
    recent_return,
    top_decile_cutoff,
)
from stock_strategy_shared.wealth_core.marks import Mark
from stock_strategy_shared.wealth_core.ordering import (
    CANONICAL_PROFILE,
    ISSUER_CONFLICT_ADMISSION_TIE_BREAK,
    KNOWN_PROFILES,
    sort_for_leadership,
)
from stock_strategy_shared.wealth_core.state import (
    DEFAULT_ENTRY_WEIGHT,
    HoldingEpisode,
    PortfolioState,
)


class Operation(str, Enum):
    """The vocabulary the delta engine translates into orders. Deliberately
    small: anything not expressible here is a behaviour Wealth Core does not
    have."""
    HOLD_UNCHANGED = "HOLD_UNCHANGED"
    OPEN_SLOT_POSITION = "OPEN_SLOT_POSITION"
    CLOSE_POSITION = "CLOSE_POSITION"
    KEEP_SLOT_IN_COOLDOWN = "KEEP_SLOT_IN_COOLDOWN"
    RELEASE_SLOT = "RELEASE_SLOT"
    BLOCK_NEW_ADMISSIONS_UNRESOLVED_EQUITY = "BLOCK_NEW_ADMISSIONS_UNRESOLVED_EQUITY"


class Reason(str, Enum):
    """Machine-readable reason codes (spec §18 of the original brief). Every
    operation carries one; free prose is never the only audit trail."""
    ENTRY_DURABLE_RANK = "ENTRY_DURABLE_RANK"
    EXIT_REVIEW_WEAKNESS = "EXIT_REVIEW_WEAKNESS"
    EXIT_TRAILING_STOP = "EXIT_TRAILING_STOP"
    HOLD_NOT_REVIEW_ELIGIBLE = "HOLD_NOT_REVIEW_ELIGIBLE"
    HOLD_REVIEW_PASSED = "HOLD_REVIEW_PASSED"
    HOLD_REVIEW_ALREADY_COMPLETED = "HOLD_REVIEW_ALREADY_COMPLETED"
    SLOT_IN_COOLDOWN = "SLOT_IN_COOLDOWN"
    SLOT_RELEASED = "SLOT_RELEASED"
    REJECT_TICKER_COOLDOWN = "REJECT_TICKER_COOLDOWN"
    ISSUER_CONFLICT = "ISSUER_CONFLICT"
    REJECT_ALREADY_HELD = "REJECT_ALREADY_HELD"
    REJECT_INSUFFICIENT_CASH = "REJECT_INSUFFICIENT_CASH"
    REJECT_ADMISSION_LIMIT = "REJECT_ADMISSION_LIMIT"
    REJECT_NO_READY_SLOT = "REJECT_NO_READY_SLOT"
    REJECT_UNRESOLVED_EQUITY = "REJECT_UNRESOLVED_EQUITY"


@dataclass(frozen=True)
class Op:
    operation: Operation
    reason: Reason
    slot_id: int | None = None
    security_id: str | None = None
    ticker: str | None = None
    shares: int | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class Decision:
    """One session's complete decision snapshot — serialisable and hashable so
    a replay can prove it reproduced the run rather than merely resembling it."""
    strategy_id: str
    strategy_version: int
    session: str
    session_index: int
    input_state_hash: str
    config_hash: str
    operations: list[Op] = field(default_factory=list)
    candidates: list[DurableScore] = field(default_factory=list)
    eligible_universe_count: int = 0
    ranked_candidate_count: int = 0
    # Why a ranked candidate was NOT admitted. Recorded rather than dropped:
    # ISSUER_CONFLICT in particular is the ONLY place related securities are
    # separated (the certified path does not deduplicate before the cutoff), so
    # it has to be visible or the reason a name was passed over is unrecoverable.
    admission_rejections: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "session": self.session,
            "session_index": self.session_index,
            "input_state_hash": self.input_state_hash,
            "config_hash": self.config_hash,
            "eligible_universe_count": self.eligible_universe_count,
            "ranked_candidate_count": self.ranked_candidate_count,
            "operations": [
                {"operation": o.operation.value, "reason": o.reason.value,
                 "slot_id": o.slot_id, "security_id": o.security_id,
                 "ticker": o.ticker, "shares": o.shares,
                 "detail": {k: o.detail[k] for k in sorted(o.detail)}}
                for o in self.operations],
            # SORTED, not in arrival order. The candidate audit list is part of
            # the decision hash, so serialising it in the order the rows
            # happened to arrive made the hash depend on the caller's query
            # ordering — identical data, different hash, and the cross-engine
            # parity test would fail for a reason that has nothing to do with
            # the strategy. (Caught by the input-shuffle acceptance test.)
            "candidates": [
                {"security_id": c.security_id, "ticker": c.ticker,
                 "momentum": c.momentum, "recent": c.recent,
                 "volatility": c.volatility, "score": c.score,
                 "in_top_decile": c.in_top_decile, "reason": c.reason}
                for c in sorted(self.candidates,
                                key=lambda c: (c.security_id, c.ticker))],
            "admission_rejections": sorted(
                self.admission_rejections,
                key=lambda r: (r.get("security_id") or "", r.get("reason") or "")),
            "warnings": sorted(self.warnings),
        }

    def decision_hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class WealthCoreConfig:
    """Immutable during a run (original brief §11). Every constant that could
    change behaviour lives here rather than scattered through the code."""
    entry_weight: float = DEFAULT_ENTRY_WEIGHT
    n_slots: int = 25
    top_fraction: float = 0.10
    top_decile_rounding: str = "ceil"
    transaction_cost_bps: float = 10.0
    max_admissions_per_session: int = 1
    minimum_leadership_population: int = 25
    # The ORDERING PROFILE, in the config hash. A run scored under one profile
    # can never be mistaken for a run scored under another — which is what makes
    # a future compatibility profile a deliberate, visible change rather than a
    # silent re-interpretation of every historical result.
    ordering_profile: str = CANONICAL_PROFILE

    def __post_init__(self) -> None:
        if self.ordering_profile not in KNOWN_PROFILES:
            raise ValueError(
                f"unknown ordering_profile {self.ordering_profile!r}; known: "
                f"{list(KNOWN_PROFILES)}. Refused rather than defaulted — "
                f"silently falling back to canonical would score a run under "
                f"rules the caller explicitly did not ask for.")

    def config_hash(self) -> str:
        blob = json.dumps({
            "entry_weight": self.entry_weight, "n_slots": self.n_slots,
            "top_fraction": self.top_fraction,
            "top_decile_rounding": self.top_decile_rounding,
            "transaction_cost_bps": self.transaction_cost_bps,
            "max_admissions_per_session": self.max_admissions_per_session,
            "minimum_leadership_population": self.minimum_leadership_population,
            "ordering_profile": self.ordering_profile,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class SecurityBar:
    """One security's view at session t, already truncated by the adapter.

    `closes` is the split-adjusted, dividend-unadjusted trailing window ending
    at t (oldest first). The adapter owns the truncation; passing a window that
    extends past t is a look-ahead the engine cannot detect.
    """
    security_id: str
    ticker: str
    issuer_id: str
    closes: Sequence[float]
    raw_close: float | None = None
    eligible: bool = True
    eligibility_reason: str = ""


def score_universe(bars: Sequence[SecurityBar],
                   cfg: WealthCoreConfig) -> list[DurableScore]:
    """Signals + decile membership for the whole cross-section (spec §3-§5).

    The decile is computed over ELIGIBLE securities only. Including ineligible
    or unusable names would move the cutoff and admit a security that is not
    actually in the top 10% of anything the strategy can trade — an explicit
    acceptance test.
    """
    scored: list[DurableScore] = []
    for b in bars:
        if not b.eligible:
            scored.append(DurableScore(b.security_id, b.ticker, None, None, None,
                                       None, False, b.eligibility_reason or "INELIGIBLE"))
            continue
        mom = medium_term_momentum(b.closes)
        rec = recent_return(b.closes)
        vol = annualized_formation_volatility(b.closes)
        scored.append(DurableScore(b.security_id, b.ticker, mom, rec, vol,
                                   durable_score(mom, vol), False, ""))

    ranked_pool = [s for s in scored if s.momentum is not None]
    # The NAMED rule, not an inline sort: a tie at the cutoff swaps one holding
    # for another and then compounds for years through the slot and cooldown
    # machinery, without producing an error or a visible discontinuity anywhere.
    ranked_pool = sort_for_leadership(ranked_pool)
    # CERTIFIED: max(minimum_leadership_population, ceil(N x 0.10)).
    k = leadership_count(len(ranked_pool), cfg.top_fraction, cfg.top_decile_rounding,
                         cfg.minimum_leadership_population)
    top = {s.security_id for s in ranked_pool[:k]}

    out = []
    for s in scored:
        if s.security_id in top:
            reason = "" if passes_freshness(s.recent) else "REJECT_RECENT_MOMENTUM"
            out.append(DurableScore(s.security_id, s.ticker, s.momentum, s.recent,
                                    s.volatility, s.score, True, reason))
        else:
            out.append(DurableScore(s.security_id, s.ticker, s.momentum, s.recent,
                                    s.volatility, s.score, False,
                                    s.reason or "REJECT_BELOW_PERCENTILE"))
    return out


def still_qualifies(row: DurableScore | None) -> bool:
    """Spec §8, second limb: "the security no longer passes the full entry
    qualification: not in the raw-momentum top decile OR recent 21-session
    return < 0". Absent from the scored universe counts as NOT qualifying."""
    if row is None:
        return False
    return row.in_top_decile and passes_freshness(row.recent)


def whole_shares(equity: float, price: float, cash: float,
                 cfg: WealthCoreConfig) -> int:
    """Spec §6: 4% of CURRENT portfolio equity, whole shares, actual available
    cash, 10bps cost on the traded side, no leverage.

    The cost is included in the affordability test rather than applied after —
    sizing to exactly `cash` and then paying commission would overdraw by the
    commission on every single admission.
    """
    if price is None or price <= 0 or equity <= 0 or cash <= 0:
        return 0
    target = equity * cfg.entry_weight
    per_share = price * (1.0 + cfg.transaction_cost_bps / 10_000.0)
    shares = int(min(target, cash) // per_share)
    return max(0, shares)


def affordable_shares(cash: float, price: float | None,
                      cfg: WealthCoreConfig) -> int:
    """Whole shares `cash` can actually pay for AT THIS PRICE, cost included.

    Separate from `whole_shares` because they answer different questions at
    different times. `whole_shares` sizes the POSITION against 4% of equity when
    the decision is made, on session t's close. This one is applied when the
    order FILLS, at session t+1's open — and the open can gap above the close
    the size was computed from, which overdraws by the gap. Observed in the
    golden run before this existed: a fully-invested book finished on NEGATIVE
    cash, which is leverage the strategy does not have.
    """
    if price is None or price <= 0 or cash <= 0:
        return 0
    per_share = price * (1.0 + cfg.transaction_cost_bps / 10_000.0)
    return max(0, int(cash // per_share))


def decide(*, session: str, state: PortfolioState, bars: Sequence[SecurityBar],
           marks: Mapping[str, "Mark"], cfg: WealthCoreConfig,
           strategy_id: str, strategy_version: int) -> Decision:
    """One session's decisions, on information available after session t closes.

    The caller has ALREADY aged the state for this session (see
    PortfolioState.age_one_session), so ages and peaks here are as of t's close.
    Splitting those apart keeps this function free of any notion of ordering
    between "what happened" and "what we decided about it".
    """
    d = Decision(strategy_id=strategy_id, strategy_version=strategy_version,
                 session=session, session_index=state.session_index,
                 input_state_hash=state.state_hash(),
                 config_hash=cfg.config_hash())

    scored = score_universe(bars, cfg)
    by_sec = {s.security_id: s for s in scored}
    d.candidates = scored
    d.eligible_universe_count = sum(1 for b in bars if b.eligible)
    closes = {b.security_id: (b.closes[-1] if b.closes else None) for b in bars}

    # ── 1. exits: trailing stop, then the one-time review ────────────────────
    # Stop first: a position can hit its stop on the same session it reaches
    # review age, and the stop is unconditional while the review is not.
    exiting: set[int] = set()
    for slot_id in sorted(state.episodes):
        ep = state.episodes[slot_id]
        if ep.exit_pending:
            continue
        px = closes.get(ep.security_id)

        if ep.stop_triggered(px):
            ep.exit_pending, ep.exit_reason = True, Reason.EXIT_TRAILING_STOP.value
            exiting.add(slot_id)
            d.operations.append(Op(Operation.CLOSE_POSITION, Reason.EXIT_TRAILING_STOP,
                                   slot_id, ep.security_id, ep.ticker, ep.current_shares,
                                   {"close": px,
                                    "episode_peak": ep.episode_peak_split_adjusted_close,
                                    "age": ep.market_sessions_held}))
            continue

        if ep.review_due:
            underwater = ep.is_underwater(px)
            qualified = still_qualifies(by_sec.get(ep.security_id))
            if underwater and not qualified:
                ep.exit_pending, ep.exit_reason = True, Reason.EXIT_REVIEW_WEAKNESS.value
                exiting.add(slot_id)
                d.operations.append(Op(Operation.CLOSE_POSITION,
                                       Reason.EXIT_REVIEW_WEAKNESS, slot_id,
                                       ep.security_id, ep.ticker, ep.current_shares,
                                       {"close": px,
                                        "entry": ep.entry_split_adjusted_price,
                                        "underwater": True, "qualified": False}))
            else:
                # PERMANENTLY completed. Passing review once means never being
                # rank-reviewed again — the winners the strategy depends on
                # would otherwise be sold the first time they slipped a decile.
                ep.review_completed = True
                d.operations.append(Op(Operation.HOLD_UNCHANGED,
                                       Reason.HOLD_REVIEW_PASSED, slot_id,
                                       ep.security_id, ep.ticker, ep.current_shares,
                                       {"underwater": underwater,
                                        "qualified": qualified}))
            continue

        d.operations.append(Op(
            Operation.HOLD_UNCHANGED,
            Reason.HOLD_REVIEW_ALREADY_COMPLETED if ep.review_completed
            else Reason.HOLD_NOT_REVIEW_ELIGIBLE,
            slot_id, ep.security_id, ep.ticker, ep.current_shares,
            {"age": ep.market_sessions_held}))

    # ── 2. slots in cooldown keep their cash ─────────────────────────────────
    # Spec §10: the slot stays cash, and that cash is NOT redistributed to
    # surviving holdings. Recording it as an operation makes the idle capital
    # visible in the audit trail instead of looking like an accounting gap.
    for slot_id in sorted(state.slots):
        s = state.slots[slot_id]
        if s.in_cooldown:
            d.operations.append(Op(Operation.KEEP_SLOT_IN_COOLDOWN,
                                   Reason.SLOT_IN_COOLDOWN, slot_id,
                                   detail={"elapsed": s.cooldown_sessions_elapsed}))

    # ── 3. admissions ────────────────────────────────────────────────────────
    ready = [i for i in state.ready_slots() if i not in exiting]
    # Spec §6: initial construction may fill every available slot together;
    # after that, at most one admission per session.
    budget = len(ready) if not state.initialized else cfg.max_admissions_per_session
    if not ready:
        d.operations.append(Op(Operation.RELEASE_SLOT, Reason.REJECT_NO_READY_SLOT))
        d.ranked_candidate_count = 0
        return d

    held_secs = state.held_security_ids()
    held_issuers = state.held_issuer_ids()

    def reject(cand, reason: Reason, **extra):
        d.admission_rejections.append(
            {"security_id": cand.security_id, "ticker": cand.ticker,
             "reason": reason.value, **extra})
    # Slots emptying at the same open are NOT reusable this session: their cash
    # is not available until the sale executes, and the spec forbids implicitly
    # replacing a position using same-open information.
    # A security is unavailable if it is exiting at the same open OR if an
    # earlier session already queued an entry for it that has not filled. The
    # second term is what stops one untradeable name accumulating an entry order
    # per session, each against its own slot.
    pending_secs = ({state.episodes[i].security_id for i in exiting}
                    | state.reserved_security_ids())
    pending_issuers = ({state.episodes[i].issuer_id for i in exiting}
                       | state.reserved_issuer_ids())

    ranked = rank_candidates(scored)
    d.ranked_candidate_count = len(ranked)

    # THE EQUITY GATE. Exits, holds and cooldowns above all ran regardless —
    # a position whose value is unknown must still be able to leave, and a
    # cooldown must still tick. But an ADMISSION is 4% of equity, and 4% of an
    # unknown is not a number. Blocking is the only treatment that does not
    # silently invent one.
    ev = state.equity_view(marks)
    if not ev.is_resolved:
        d.operations.append(Op(
            Operation.BLOCK_NEW_ADMISSIONS_UNRESOLVED_EQUITY,
            Reason.REJECT_UNRESOLVED_EQUITY,
            detail={"unresolved": list(ev.unresolved_security_ids),
                    "estimated_equity_including_stale_marks":
                        ev.estimated_equity_including_stale_marks}))
        d.warnings.append(
            f"admissions blocked: {len(ev.unresolved_security_ids)} holding(s) "
            f"without a trustworthy current mark")
        return d

    equity = ev.resolved_equity
    admitted = 0

    for cand in ranked:
        if admitted >= budget or not ready:
            break
        if cand.security_id in held_secs or cand.security_id in pending_secs:
            reject(cand, Reason.REJECT_ALREADY_HELD)
            continue
        bar = next((b for b in bars if b.security_id == cand.security_id), None)
        issuer = bar.issuer_id if bar else cand.security_id
        if issuer in held_issuers or issuer in pending_issuers:
            # The ONLY issuer separation in the certified path. Related
            # securities were never removed from the leadership population —
            # they compete on merit and lose here, once, at admission.
            # The comparison tuple is PERSISTED, not left to be re-derived: the
            # reason this security lost has to be recoverable from the record
            # months later, and a reader who re-derives it from the code of the
            # day gets that day's answer rather than the one that applied.
            reject(cand, Reason.ISSUER_CONFLICT, issuer_group_key=issuer,
                   tie_break=ISSUER_CONFLICT_ADMISSION_TIE_BREAK
                   .comparison_tuple(cand))
            continue
        if state.ticker_in_cooldown(cand.ticker):
            reject(cand, Reason.REJECT_TICKER_COOLDOWN)
            continue
        m = marks.get(cand.security_id)
        px = m.raw_mark_close if (m and m.status.name == "CURRENT") else None
        shares = whole_shares(equity, px, state.cash, cfg)
        if shares <= 0:
            reject(cand, Reason.REJECT_INSUFFICIENT_CASH, price=px)
            continue
        slot_id = ready.pop(0)
        # RESERVE now, not at fill. The order may not fill for many sessions and
        # the slot must be unavailable for every one of them; because the
        # reservation lives in PortfolioState it also survives a restart, which
        # a queue-side guard alone would not.
        state.reserve_slot(slot_id, cand.security_id, cand.ticker, issuer)
        d.operations.append(Op(Operation.OPEN_SLOT_POSITION, Reason.ENTRY_DURABLE_RANK,
                               slot_id, cand.security_id, cand.ticker, shares,
                               {"durable_score": cand.score, "momentum": cand.momentum,
                                "recent": cand.recent, "volatility": cand.volatility,
                                "target_weight": cfg.entry_weight,
                                "equity_at_decision": equity}))
        held_secs.add(cand.security_id)
        held_issuers.add(issuer)
        admitted += 1

    if admitted == 0 and ready:
        d.operations.append(Op(Operation.RELEASE_SLOT, Reason.SLOT_RELEASED,
                               detail={"ready_slots": len(ready),
                                       "ranked_candidates": len(ranked)}))
    return d


def apply_entry(state: PortfolioState, *, op: Op, session: str, signal_session: str,
                raw_open: float, split_adjusted_price: float,
                issuer_id: str, cfg: WealthCoreConfig) -> None:
    """Execute an admission at the next open (spec §11). Called by the adapter
    once a fill is known — the engine never invents a price."""
    cost = op.shares * raw_open * (1.0 + cfg.transaction_cost_bps / 10_000.0)
    state.cash -= cost
    state.slots[op.slot_id].occupied_by = op.security_id
    state.slots[op.slot_id].release_reservation()   # the claim became a holding
    state.episodes[op.slot_id] = HoldingEpisode(
        security_id=op.security_id, ticker=op.ticker, issuer_id=issuer_id,
        slot_id=op.slot_id, signal_date=signal_session, entry_date=session,
        entry_raw_open=float(raw_open),
        entry_split_adjusted_price=float(split_adjusted_price),
        initial_shares=int(op.shares), current_shares=int(op.shares),
        source_lots=[{"kind": "ADMISSION", "session": session,
                      "security_id": op.security_id, "ticker": op.ticker,
                      "shares": int(op.shares), "raw_open": float(raw_open)}],
        # Peak deliberately UNSET here. The caller initialises it from the entry
        # session's close via observe_entry_close(); seeding it from the entry
        # open would arm the stop against a price that is not a close.
        episode_peak_split_adjusted_close=None)


def apply_exit(state: PortfolioState, *, slot_id: int, raw_open: float,
               cfg: WealthCoreConfig) -> None:
    """Execute a scheduled exit and start BOTH cooldowns (spec §10).

    Ticker and slot cool down independently and both start here; starting only
    one would let the same name re-enter through a different slot, or the slot
    take a different name immediately.
    """
    ep = state.episodes.pop(slot_id)
    state.cash += ep.current_shares * raw_open * (1.0 - cfg.transaction_cost_bps / 10_000.0)
    state.slots[slot_id].start_cooldown()
    state.ticker_cooldowns[ep.ticker] = 0
