"""Wealth Core v1 — the SHARED session driver. PURE: no DB, no clock, no I/O.

`run_sessions` is the whole strategy, start to finish. The backtester, the wind
tunnel and the live book differ ONLY in how they obtain `VendorBar`s and what
they persist afterwards; every ordering decision, every corporate action, every
admission and every exit happens in here.

That is what makes the cross-engine parity requirement provable rather than
asserted. Two engines cannot disagree about the strategy because there is only
one implementation of it, and `RunResult.result_hash()` is the evidence: a
golden fixture pins the hash, and any engine that reproduces the same
`VendorBar` stream reproduces the same hash byte for byte or fails loudly.

WHAT THE HASH COVERS, and why it covers that much. Terminal state, cash, every
ledger event and every session's decision — including the decisions that did
NOTHING. A hash over trades alone would go on matching while the two engines
diverged on which candidates they considered, which is precisely the divergence
worth catching early: it shows up in the audit trail long before it shows up in
a fill.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from stock_strategy_shared.wealth_core.adapter import (
    PendingOrder,
    SessionResult,
    cash_merger,
    step_session,
    write_off,
)
from stock_strategy_shared.wealth_core.eligibility import (
    EligibilityConfig,
    TerminalState,
)
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState

STRATEGY_ID = "stocker_wealth_core_v1"
STRATEGY_VERSION = 1


@dataclass(frozen=True)
class TerminalEvent:
    """A resolved terminal action, applied on `session` BEFORE that session's
    orders execute.

    Deliberately an explicit input rather than something the driver infers from
    a price disappearing. "Stopped printing" and "was acquired for $54 cash" are
    different facts with different cash consequences, and inferring one from the
    other is how a delisting quietly becomes a full recovery.
    """
    session: str
    security_id: str
    kind: str                     # CASH_MERGER | WRITE_OFF
    cash_per_share: float = 0.0


@dataclass
class RunResult:
    sessions: list[SessionResult] = field(default_factory=list)
    state: PortfolioState | None = None
    ledger: Ledger | None = None
    unfilled_at_end: list[dict] = field(default_factory=list)
    blocked_sessions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Canonical, order-independent serialisation.

        `sort_keys=True` everywhere and every list explicitly ordered — the two
        engines will build these structures from different iteration orders and
        the hash has to be blind to that, or it fails for reasons that have
        nothing to do with the strategy.
        """
        return {
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "final_state": self.state.to_dict() if self.state else None,
            "final_state_hash": self.state.state_hash() if self.state else None,
            "ledger": [e.to_dict() for e in (self.ledger.events if self.ledger else [])],
            "ledger_hash": self.ledger.ledger_hash() if self.ledger else None,
            "sessions": [
                {"session": s.session,
                 "resolved_equity": _round(s.resolved_equity),
                 "estimated_equity": _round(s.estimated_equity),
                 "blocked": s.blocked,
                 "fills": sorted(s.fills, key=lambda f: (f["security_id"],
                                                         f["operation"])),
                 "decision": s.decision.to_dict() if s.decision else None}
                for s in self.sessions],
            "unfilled_at_end": sorted(
                self.unfilled_at_end,
                key=lambda o: (o["security_id"], o["operation"])),
            "blocked_sessions": list(self.blocked_sessions),
        }

    def result_hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          default=_json_default)
        return hashlib.sha256(blob.encode()).hexdigest()


def _round(x):
    """Round money to the cent BEFORE hashing.

    Two engines can accumulate the same cash flows in a different association
    order and land 1e-12 apart — a difference that is not a strategy difference
    but would fail the parity test forever, training everyone to ignore it.
    """
    return None if x is None else round(float(x), 2)


def _json_default(o):
    if isinstance(o, float):
        return round(o, 10)
    raise TypeError(f"{type(o).__name__} is not serialisable in a run result")


def run_sessions(*, sessions: Sequence[str],
                 bars_by_session: Mapping[str, Sequence[VendorBar]],
                 meta: Mapping[str, SecurityMeta],
                 starting_cash: float,
                 cfg: WealthCoreConfig | None = None,
                 eligibility_cfg: EligibilityConfig | None = None,
                 terminal_events: Sequence[TerminalEvent] = (),
                 terminal_states: Mapping[str, Mapping[str, TerminalState]] | None = None,
                 state: PortfolioState | None = None,
                 pending: list[PendingOrder] | None = None,
                 ledger: Ledger | None = None,
                 last_known: dict[str, float] | None = None,
                 feed: Feed | None = None,
                 on_session: Callable[[SessionResult], None] | None = None,
                 ) -> RunResult:
    """Drive the strategy across `sessions`, in order.

    RESUMABLE by construction: pass back the state, pending queue, ledger,
    last-known marks and feed from a previous call and the run continues as if
    it had never stopped. That is not a convenience — the live book restarts,
    and a strategy whose position ages and episode peaks cannot survive a
    restart is a different strategy after every deploy.
    """
    cfg = cfg or WealthCoreConfig()
    state = state if state is not None else PortfolioState.fresh(
        starting_cash, cfg.n_slots if hasattr(cfg, "n_slots") else 25)
    state.initialized = True
    pending = pending if pending is not None else []
    ledger = ledger if ledger is not None else Ledger()
    last_known = last_known if last_known is not None else {}
    feed = feed if feed is not None else Feed(meta, eligibility_cfg)

    events_by_session: dict[str, list[TerminalEvent]] = {}
    for ev in terminal_events:
        events_by_session.setdefault(ev.session, []).append(ev)

    out = RunResult(state=state, ledger=ledger)

    for session in sessions:
        # Resolved terminal actions land BEFORE the session steps, so a security
        # acquired for cash pays into the balance that this session's admissions
        # size against — and a write-off resolves the equity block in the same
        # session rather than one late.
        for ev in sorted(events_by_session.get(session, []),
                         key=lambda e: (e.security_id, e.kind)):
            if ev.kind == "CASH_MERGER":
                cash_merger(state, security_id=ev.security_id,
                            per_share=ev.cash_per_share, ledger=ledger,
                            session=session)
            elif ev.kind == "WRITE_OFF":
                write_off(state, security_id=ev.security_id, ledger=ledger,
                          session=session)
            else:
                raise ValueError(
                    f"unknown TerminalEvent.kind {ev.kind!r} — refused rather "
                    f"than ignored, because an unrecognised terminal action "
                    f"silently skipped leaves the holding unresolved forever")

        norm = feed.advance(session, bars_by_session.get(session, ()),
                            (terminal_states or {}).get(session))
        res = step_session(session=session, state=state, bars=norm.bars,
                           pending=pending, ledger=ledger, last_known=last_known,
                           cfg=cfg, strategy_id=STRATEGY_ID,
                           strategy_version=STRATEGY_VERSION,
                           security_bars=norm.security_bars)
        out.sessions.append(res)
        if res.blocked:
            out.blocked_sessions.append(session)
        if on_session is not None:
            on_session(res)

    # Orders still queued at the end are REPORTED, not dropped. An exit that
    # never found a tradeable open is a position the run is still holding for a
    # reason, and a summary that omits it reads as a clean finish.
    out.unfilled_at_end = [
        {"security_id": p.security_id, "ticker": p.ticker,
         "operation": p.operation.value, "shares": p.shares,
         "signal_session": p.signal_session, "sessions_waiting": p.sessions_waiting}
        for p in pending]
    return out


__all__ = ["RunResult", "TerminalEvent", "run_sessions", "STRATEGY_ID",
           "STRATEGY_VERSION"]
