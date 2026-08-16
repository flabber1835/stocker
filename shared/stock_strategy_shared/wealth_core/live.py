"""Wealth Core on the LIVE book — the stateful_ownership execution branch.

WHAT THIS BYPASSES, and why bypassing is correct rather than lazy:

    Alpha Vantage         the signal domain is split-adjusted/dividend-unadjusted
                          and the mark is as-traded. AV's adjusted_close is
                          AV-VINTAGE and re-bases whenever AV restates, which
                          would move every episode peak the trailing stop reads.
    the generic ranker    ranks the whole universe on a factor composite. Wealth
                          Core ranks the leadership set on raw momentum and
                          orders it on the durable score. Different question.
    the LLM vetter        Wealth Core has no discretionary exclusion. Adding one
                          would make the live book diverge from every backtest
                          by an amount nothing measures.
    the portfolio builder it produces a normalised TARGET. Wealth Core is not a
                          target strategy — see below.
    target-diff execution buy/add/trim/exit against a target is the wrong
                          vocabulary entirely.

THE LAST ONE IS THE LOAD-BEARING ONE. A target-difference engine re-derives the
book from a target each morning, so state that cannot be recomputed from a
target does not survive: position age, the one-time review flag, the episode
peak, the slot cooldown, the ticker cooldown, the slot reservation. Wealth Core
is defined by exactly those. Running it through the target-diff path would
produce a book that looked plausible every single day and was a different
strategy after the first restart.

So this path emits EXPLICIT WEALTH CORE OPERATIONS — open a slot, close a
position — and nothing else. The risk service and the executor still gate and
submit; what changes is that the intent vocabulary is the strategy's own.

DRY RUN IS THE DEFAULT AND IS ENFORCED BY TYPE. `submit=False` is not a flag
this module reads and hopes callers set: `plan_session` cannot submit anything
because it has no broker, no HTTP client and no credentials. Producing intents
and submitting them are separate functions in separate services, which is the
same boundary the rest of the system already enforces — only trade-executor
submits.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import Operation, WealthCoreConfig
from stock_strategy_shared.wealth_core.execution_model import (
    LEGACY_STAGES_BYPASSED,
)
from stock_strategy_shared.wealth_core.feed import (
    DecisionMetadataTimeline, Feed, SecurityMeta, VendorBar)
from stock_strategy_shared.wealth_core.hashes import parity_hashes
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.run import (
    STRATEGY_ID,
    STRATEGY_VERSION,
    run_with_hashes,
)
from stock_strategy_shared.wealth_core.state import PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalTerms

log = logging.getLogger(__name__)

EXECUTION_MODEL = "stateful_ownership"

# The legacy chain stages this branch does NOT require. THE SAME OBJECT as the
# execution model's, not a copy that agrees with it: both modules now live in
# this package, so the second list can be deleted rather than tested against.
# It was a literal while they sat in different services, and a test asserted
# they matched — which catches drift only after someone writes it.
BYPASSED_STAGES: tuple[str, ...] = LEGACY_STAGES_BYPASSED


@dataclass
class OrderIntent:
    """One explicit Wealth Core operation, ready for the risk gate.

    Deliberately NOT the generic delta-intent vocabulary. `buy_add` and
    `sell_trim` have no meaning here — Wealth Core never scales into or out of a
    position — and offering them would invite a future change that quietly makes
    the live book a different strategy from the backtest.
    """
    session: str
    operation: str                 # OPEN_SLOT_POSITION | CLOSE_POSITION
    security_id: str
    ticker: str
    slot_id: int
    shares: int
    reason: str
    signal_session: str
    limit_price: float | None = None
    strategy_id: str = STRATEGY_ID
    strategy_version: int = STRATEGY_VERSION

    def to_dict(self) -> dict:
        return {"session": self.session, "operation": self.operation,
                "security_id": self.security_id, "ticker": self.ticker,
                "slot_id": self.slot_id, "shares": self.shares,
                "reason": self.reason, "signal_session": self.signal_session,
                "strategy_id": self.strategy_id,
                "strategy_version": self.strategy_version}

    @property
    def side(self) -> str:
        return "sell" if self.operation == Operation.CLOSE_POSITION.value else "buy"


@dataclass
class LiveSessionPlan:
    session: str
    intents: list[OrderIntent] = field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None
    resolved_equity: float | None = None
    estimated_equity: float = 0.0
    hashes: dict = field(default_factory=dict)
    state_after: dict = field(default_factory=dict)
    pending_after: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"execution_model": EXECUTION_MODEL,
                "session": self.session,
                "intents": [i.to_dict() for i in self.intents],
                "blocked": self.blocked, "block_reason": self.block_reason,
                "resolved_equity": (None if self.resolved_equity is None
                                    else round(self.resolved_equity, 2)),
                "estimated_equity": round(self.estimated_equity, 2),
                "hashes": dict(self.hashes),
                "state_after": self.state_after,
                "pending_after": list(self.pending_after),
                "warnings": sorted(self.warnings)}


def plan_session(*, session: str,
                 bars: Sequence[VendorBar],
                 meta: Mapping[str, SecurityMeta],
                 metadata_timeline: DecisionMetadataTimeline | None = None,
                 state: PortfolioState,
                 pending: list[PendingOrder],
                 ledger: Ledger,
                 last_known: dict[str, float],
                 feed: Feed,
                 cfg: WealthCoreConfig | None = None,
                 eligibility_cfg: EligibilityConfig | None = None,
                 terminal_events: Sequence[TerminalTerms] = (),
                 ) -> LiveSessionPlan:
    """Advance the live book ONE session and return the resulting intents.

    This is `run_sessions` over a single-session window, not a separate code
    path. A live-specific stepper is precisely the drift the shared engine
    exists to prevent — and it would be invisible, because a one-session
    difference in ageing or peak ratcheting looks like nothing until it has
    compounded for a quarter.

    The caller owns loading `state`, `pending`, `ledger`, `last_known` and the
    warmed `feed` from storage; this function mutates them in place, exactly as
    a resumed backtest does, so live and replay share the resumption semantics
    the restart tests already cover.
    """
    result, hashes = run_with_hashes(
        sessions=[session], bars_by_session={session: list(bars)}, meta=meta,
        metadata_timeline=metadata_timeline,
        starting_cash=state.cash, cfg=cfg, eligibility_cfg=eligibility_cfg,
        terminal_events=[t for t in terminal_events if t.session == session],
        state=state, pending=pending, ledger=ledger, last_known=last_known,
        feed=feed)

    sr = result.sessions[0]
    plan = LiveSessionPlan(
        session=session, blocked=sr.blocked,
        resolved_equity=sr.resolved_equity,
        estimated_equity=sr.estimated_equity,
        hashes=hashes.to_dict(),
        state_after=state.to_dict(),
        pending_after=[p.to_dict() for p in pending])

    if sr.blocked:
        # The equity gate. Exits still flow — a position whose value is unknown
        # must always be able to LEAVE — but nothing new is admitted, because 4%
        # of an unknown is not a number.
        plan.block_reason = "UNRESOLVED_EQUITY"
        plan.warnings.append(
            "admissions blocked: at least one holding has no trustworthy "
            "current mark or has an unresolved terminal action")

    # The intents are the orders the engine QUEUED this session, which are the
    # ones that execute at the next open. Reading them off the pending queue
    # rather than off `decision.operations` is deliberate: the queue is what
    # actually survives to be filled, and it already excludes the holds,
    # cooldowns and releases that are decisions but not orders.
    for po in pending:
        if po.signal_session != session:
            continue
        plan.intents.append(OrderIntent(
            session=session, operation=po.operation.value,
            security_id=po.security_id, ticker=po.ticker, slot_id=po.slot_id,
            shares=po.shares, reason=po.reason,
            signal_session=po.signal_session))

    for c in sr.cancelled:
        plan.warnings.append(
            f"{c.get('reason')}: {c.get('security_id')} "
            f"wanted {c.get('wanted_shares')} shares")
    return plan


def dry_run(*, sessions: Sequence[str],
            bars_by_session: Mapping[str, Sequence[VendorBar]],
            meta: Mapping[str, SecurityMeta],
            starting_cash: float,
            cfg: WealthCoreConfig | None = None,
            eligibility_cfg: EligibilityConfig | None = None,
            terminal_events: Sequence[TerminalTerms] = (),
            ) -> tuple[Any, dict, list[dict]]:
    """Replay a whole stream through the LIVE path with nothing submitted.

    Used for the cross-engine parity check and for a real-data rehearsal before
    anything is ever sent to a broker. It returns the same seven hashes the
    backtester and the wind tunnel produce, so "the live path agrees" is checked
    rather than asserted.
    """
    result, hashes = run_with_hashes(
        sessions=list(sessions), bars_by_session=bars_by_session, meta=meta,
        starting_cash=starting_cash, cfg=cfg, eligibility_cfg=eligibility_cfg,
        terminal_events=terminal_events)

    intents: list[dict] = []
    for s in result.sessions:
        if not s.decision:
            continue
        for op in s.decision.operations:
            if op.operation in (Operation.OPEN_SLOT_POSITION,
                                Operation.CLOSE_POSITION):
                intents.append(OrderIntent(
                    session=s.session, operation=op.operation.value,
                    security_id=op.security_id, ticker=op.ticker,
                    slot_id=op.slot_id, shares=op.shares or 0,
                    reason=op.reason.value,
                    signal_session=s.session).to_dict())
    return result, hashes.to_dict(), intents


__all__ = ["BYPASSED_STAGES", "EXECUTION_MODEL", "LiveSessionPlan",
           "OrderIntent", "dry_run", "plan_session"]
