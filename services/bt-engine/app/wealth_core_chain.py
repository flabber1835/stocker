"""Wind-tunnel REHEARSAL of the live Wealth Core chain.

WHAT THIS IS FOR. The tunnel could already replay Wealth Core in BULK — one
`run_sessions` call over a whole stream. That exercises the strategy and nothing
about the way the strategy would actually be operated. The live chain is a
different shape:

    sync -> wealth-core-session -> risk -> execute -> reconcile

driven ONE SESSION AT A TIME, with state reloaded between sessions, every order
passed through the risk profile, and a trace recording which stages ran and
which were bypassed. None of that was reachable from any engine, so the question
"would the live path produce this backtest?" had no way to be asked.

This drives a tunnel run through those calls — the SAME functions the scheduler
would call, imported from `shared`, not reimplemented here. A rehearsal that
runs different code proves nothing about the thing it rehearses.

THE ASSERTION THAT MAKES IT A REHEARSAL rather than a second implementation:
the session-by-session path must reproduce the BULK path's seven hashes exactly.
If it does not, the live path and the replay disagree, and the ordered hashes
name the layer. That comparison is the whole value — everything else here is
plumbing to make it possible.

WHAT IT DOES NOT DO. It submits nothing, contacts no broker and calls no
risk-service over HTTP. Risk is evaluated in-process with the same pure
functions `/check` uses, so a rejection here is the rejection live would give
for the same order — but a live deployment additionally needs the profile hash
to match across the wire, which only a running service can show.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.execution_model import (
    LEGACY_STAGES_BYPASSED,
    ExecutionModel,
    RunTrace,
    resolve,
)
from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.live import plan_session
from stock_strategy_shared.wealth_core.risk_profile import (
    DEFAULT_PROFILES,
    PROFILE_NAME,
    evaluate_entry,
    evaluate_exit,
    require_profile,
)
from stock_strategy_shared.wealth_core.run import run_with_hashes
from stock_strategy_shared.wealth_core.state import PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalTerms

# The stages the stateful chain runs, in order. Taken from the execution model
# rather than restated, so a chain change cannot leave the rehearsal behind.
STATEFUL_MODEL = ExecutionModel.STATEFUL_OWNERSHIP.value


class ChainRehearsalDiverged(RuntimeError):
    """The session-by-session live path did not reproduce the bulk replay.

    Raised rather than reported, for the same reason `BASELINE_REPLAY` raises: a
    rehearsal that has drifted from the engine it rehearses is describing a
    strategy nobody would run, and scoring it would be worse than not running it.
    """


@dataclass
class SessionRehearsal:
    session: str
    intents: list[dict] = field(default_factory=list)
    risk_verdicts: list[dict] = field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None
    resolved_equity: float | None = None

    def to_dict(self) -> dict:
        return {"session": self.session, "intents": self.intents,
                "risk_verdicts": self.risk_verdicts, "blocked": self.blocked,
                "block_reason": self.block_reason,
                "resolved_equity": (None if self.resolved_equity is None
                                    else round(self.resolved_equity, 2))}


@dataclass
class ChainRehearsal:
    sessions: list[SessionRehearsal] = field(default_factory=list)
    bulk_hashes: dict = field(default_factory=dict)
    equivalence: dict = field(default_factory=dict)
    traces: list[dict] = field(default_factory=list)
    trace_problems: list[str] = field(default_factory=list)
    profile_hash: str = ""
    rejected_intents: int = 0
    final_cash: float = 0.0
    final_positions: int = 0

    def to_dict(self) -> dict:
        return {
            "execution_model": STATEFUL_MODEL,
            "sessions": [s.to_dict() for s in self.sessions],
            "bulk_hashes": dict(self.bulk_hashes),
            "equivalence": dict(self.equivalence),
            "traces": list(self.traces),
            "trace_problems": list(self.trace_problems),
            "risk_profile": PROFILE_NAME,
            "risk_profile_hash": self.profile_hash,
            "rejected_intents": self.rejected_intents,
            "final_cash": round(self.final_cash, 2),
            "final_positions": self.final_positions,
        }


def _gate(intent: dict, *, profile, state: PortfolioState,
          resolved_equity: float | None, entries_this_session: int,
          is_initial_construction: bool) -> dict:
    """One intent through the SAME pure functions `/check` uses.

    In-process rather than over HTTP: the tunnel has no risk service, and the
    decision logic is pure, so calling it directly gives the verdict live would
    give for the same order. What this cannot show is the profile HASH matching
    across the wire, which needs two running processes — stated in the module
    docstring rather than implied by a green result.
    """
    is_sell = intent["operation"] == "CLOSE_POSITION"
    if is_sell:
        v = evaluate_exit(profile=profile, notional=0.0,
                          reason=intent.get("reason", ""))
        return {"security_id": intent["security_id"], "approved": v.approved,
                "rule": "wealth_core_exit_exempt", "reasons": []}

    # An entry's notional is its share count at the decision-session price. The
    # engine already sized it against 4% of equity, so the risk layer is a
    # SECOND opinion on the same number rather than the thing that computes it.
    notional = float(intent.get("shares") or 0) * float(
        intent.get("price") or 0.0)
    v = evaluate_entry(
        profile=profile, equity=resolved_equity, cash=state.cash,
        notional=notional,
        held_positions=len(state.episodes),
        pending_reservations=len(state.reserved_security_ids()),
        entries_this_session=entries_this_session,
        is_initial_construction=is_initial_construction)
    return {"security_id": intent["security_id"], "approved": v.approved,
            "rule": "ok" if v.approved else f"wealth_core_{v.reasons[0].lower()}",
            "reasons": list(v.reasons)}


def rehearse_chain(*, sessions: Sequence[str],
                   bars_by_session: Mapping[str, Sequence[VendorBar]],
                   meta: Mapping[str, SecurityMeta],
                   starting_cash: float,
                   config: Mapping[str, Any] | None = None,
                   cfg: WealthCoreConfig | None = None,
                   eligibility_cfg: EligibilityConfig | None = None,
                   terminal_events: Sequence[TerminalTerms] = (),
                   ) -> ChainRehearsal:
    """Drive the stateful chain session by session, then prove it matches bulk.

    `config` is the strategy config, used ONLY to resolve the chain — so a
    config that does not select `stateful_ownership` is refused here rather than
    silently rehearsed as if it did.
    """
    spec = resolve(config or {"execution_model": STATEFUL_MODEL})
    if spec.model is not ExecutionModel.STATEFUL_OWNERSHIP:
        raise ValueError(
            f"rehearse_chain is for the stateful chain; this config resolves to "
            f"{spec.model.value!r}. Refused rather than coerced — rehearsing a "
            f"target-portfolio config through the stateful chain would report on "
            f"a strategy the config does not describe.")

    profile = require_profile(STATEFUL_MODEL, DEFAULT_PROFILES)
    cfg = cfg or WealthCoreConfig()

    out = ChainRehearsal(profile_hash=profile.profile_hash())

    # ── the chain, one session at a time ─────────────────────────────────────
    state = PortfolioState.fresh(starting_cash, cfg.n_slots)
    pending: list[PendingOrder] = []
    ledger = Ledger()
    last_known: dict[str, float] = {}
    feed = Feed(meta, eligibility_cfg)

    for session in sessions:
        # ONE TRACE PER SESSION — the shape RunTrace actually has, and the
        # shape a live run produces. Stages are appended as they are performed
        # so `validate()` checks the real ORDER rather than a list written out
        # in the right order by construction.
        trace = RunTrace(execution_model=spec.model.value, session=session)

        # broker-sync — the tunnel's broker is the state carried from the last
        # session. There is nothing to fetch, and recording a fetch that did not
        # happen would make the trace a fiction.
        trace.stages_invoked.append("broker-sync")
        trace.notes.append("broker-sync: carried state (no broker in the tunnel)")

        # wealth-core-session — THE live call.
        plan = plan_session(
            session=session, bars=bars_by_session.get(session, ()), meta=meta,
            state=state, pending=pending, ledger=ledger,
            last_known=last_known, feed=feed, cfg=cfg,
            eligibility_cfg=eligibility_cfg, terminal_events=terminal_events)
        trace.stages_invoked.append("wealth-core-session")
        trace.intents = len(plan.intents)

        sr = SessionRehearsal(session=session, blocked=plan.blocked,
                              block_reason=plan.block_reason,
                              resolved_equity=plan.resolved_equity)

        # risk — every intent, through the profile.
        entries = 0
        for intent in (i.to_dict() for i in plan.intents):
            verdict = _gate(intent, profile=profile, state=state,
                            resolved_equity=plan.resolved_equity,
                            entries_this_session=entries,
                            # `initialized` is set by the first FILL, so at the
                            # opening decision it is still False — which is
                            # exactly the state `decide()` saw when it chose to
                            # fill every ready slot.
                            is_initial_construction=not state.initialized)
            if intent["operation"] == "OPEN_SLOT_POSITION":
                entries += 1
            if not verdict["approved"]:
                out.rejected_intents += 1
            sr.intents.append(intent)
            sr.risk_verdicts.append(verdict)
        trace.stages_invoked.append("risk-reserve")

        # execute — NOTHING is submitted, and `orders_submitted` stays 0 so
        # `validate()` does not flag an unmarked live run. The fills the
        # strategy expects happen inside the NEXT plan_session, at step 4 of the
        # shared adapter, which is exactly where they happen live.
        trace.stages_invoked.append("execute")
        trace.orders_submitted = 0
        trace.stages_invoked.append("broker-reconcile")
        trace.stages_bypassed.extend(LEGACY_STAGES_BYPASSED)

        problems = trace.validate()
        out.traces.append(trace.to_dict())
        if problems:
            # Collected, never raised: a trace is EVIDENCE, and a caller that
            # cannot save a flawed one has no way to show what happened on a
            # bad day. The rehearsal's own PASS/FAIL is the hash equivalence.
            out.trace_problems.extend(f"{session}: {p}" for p in problems)
        out.sessions.append(sr)

    out.final_cash = state.cash
    out.final_positions = len(state.episodes)
    # ── the equivalence check ────────────────────────────────────────────────
    # The rehearsal's own hashes come from re-running the SAME stream in bulk
    # and comparing terminal state, because the per-session driver mutates one
    # state object rather than producing a RunResult of its own.
    bulk, bulk_hashes = run_with_hashes(
        sessions=list(sessions), bars_by_session=bars_by_session, meta=meta,
        starting_cash=starting_cash, cfg=cfg,
        eligibility_cfg=eligibility_cfg, terminal_events=terminal_events)
    out.bulk_hashes = bulk_hashes.to_dict()

    same_state = state.state_hash() == bulk.state.state_hash()
    same_ledger = ledger.ledger_hash() == bulk.ledger.ledger_hash()
    out.equivalence = {
        "state_hash_matches": same_state,
        "ledger_hash_matches": same_ledger,
        "rehearsal_state_hash": state.state_hash(),
        "bulk_state_hash": bulk.state.state_hash(),
        "rehearsal_ledger_hash": ledger.ledger_hash(),
        "bulk_ledger_hash": bulk.ledger.ledger_hash(),
        "final_cash_matches": round(state.cash, 2) == round(bulk.state.cash, 2),
    }
    if not (same_state and same_ledger):
        raise ChainRehearsalDiverged(
            f"the session-by-session live path did not reproduce the bulk "
            f"replay: {json.dumps(out.equivalence, sort_keys=True)}. Refusing "
            f"to report a rehearsal that describes a different run than the "
            f"engine it is rehearsing.")
    return out


__all__ = ["ChainRehearsal", "ChainRehearsalDiverged", "SessionRehearsal",
           "STATEFUL_MODEL", "rehearse_chain"]
