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
    build_marks,
    step_session,
)
from stock_strategy_shared.wealth_core.eligibility import (
    EligibilityConfig,
    TerminalState,
)
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.feed import (
    DecisionMetadataTimeline,
    Feed,
    SecurityMeta,
    VendorBar,
    validate_session_stream,
)
from stock_strategy_shared.wealth_core.hashes import quantize as _quantize
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState
from stock_strategy_shared.wealth_core.terminal import (
    FinalReport,
    TerminalKind,
    TerminalTerms,
    final_report,
)

STRATEGY_ID = "stocker_wealth_core_v1"
STRATEGY_VERSION = 1


def TerminalEvent(*, session: str, security_id: str, kind: str,
                  cash_per_share: float = 0.0, **kw) -> TerminalTerms:
    """Back-compatible constructor for the two original kinds.

    Kept because it reads well at a call site and because the golden scenario
    and several tests were written against it; it is a thin factory over
    `TerminalTerms`, which is the real type. New kinds (CONVERSION,
    CASH_PLUS_STOCK) are only expressible through TerminalTerms directly — a
    kwargs-shaped shim for a nine-field deal would be worse than the type.
    """
    return TerminalTerms(session=session, security_id=security_id,
                         kind=TerminalKind(kind),
                         cash_per_share=cash_per_share, **kw)


@dataclass
class RunResult:
    sessions: list[SessionResult] = field(default_factory=list)
    state: PortfolioState | None = None
    ledger: Ledger | None = None
    unfilled_at_end: list[dict] = field(default_factory=list)
    blocked_sessions: list[str] = field(default_factory=list)
    terminal_results: list[dict] = field(default_factory=list)
    final: FinalReport | None = None
    # How every terminal event was resolved — see settlement.SETTLEMENT_COUNTERS.
    # DELIBERATELY ABSENT FROM `to_dict()`, so it never reaches a parity hash:
    # it is a REPORT, and the settlement events it counts are already hashed via
    # the ledger, so a counter that disagreed with the run would show up there.
    # Hashing it would also add a second thing to re-pin for no extra evidence.
    #
    # It exists because nothing else answers "did the waterfall settle, or did
    # the book quietly block?" — a blocked book still completes and still
    # reports a plausible CAGR, so the counters are the only place that failure
    # is visible.
    settlement_counters: dict = field(default_factory=dict)
    # The equity/fills series, ALWAYS retained. Three scalars and a short fills
    # list per session, against a SessionResult carrying a Decision with one
    # candidate row per eligible security — so this costs almost nothing and is
    # what `measure_run_result` needs. Retaining it is what makes dropping the
    # heavy objects safe.
    session_facts: list = field(default_factory=list)

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
            # `hash_payload`, not `to_dict`: audit-only keys are persisted for
            # restart but must not be pinned into the certified artefact. The
            # terminal audit reaches this dict through `terminal_results`, where
            # it is per-episode and legible, rather than as raw state.
            "final_state": self.state.hash_payload() if self.state else None,
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
            # Money the book is OWED but has not received. Reported as its own
            # number rather than folded into cash or equity, for the same reason
            # the final report keeps marked / liquidated / forced apart: an
            # accrued dividend that has not settled by the last session is real
            # and is NOT spendable, and a single total cannot say both. Omitting
            # it entirely would understate the run by however much was in flight
            # when it stopped.
            "outstanding_receivables": _round(
                self.ledger.receivable_total() if self.ledger else 0.0),
            "terminal_results": sorted(
                self.terminal_results,
                key=lambda r: (r.get("session") or "",
                               r.get("security_id") or "", r.get("kind") or "")),
            "final": self.final.to_dict() if self.final else None,
        }

    def result_hash(self) -> str:
        blob = json.dumps(_quantize(self.to_dict()), sort_keys=True,
                          separators=(",", ":"), default=_json_default)
        return hashlib.sha256(blob.encode()).hexdigest()

    def session_row(self, s) -> dict:
        """One `sessions` entry, in the shape `to_dict` gives it.

        Extracted so the materialised and streaming paths build the row from
        ONE definition. Two copies of this dict would be a silent parity
        divergence waiting to happen — the streamed hash would stay internally
        consistent while describing a different structure.
        """
        return {"session": s.session,
                "resolved_equity": _round(s.resolved_equity),
                "estimated_equity": _round(s.estimated_equity),
                "blocked": s.blocked,
                "fills": sorted(s.fills, key=lambda f: (f["security_id"],
                                                        f["operation"])),
                "decision": s.decision.to_dict() if s.decision else None}

    def result_hash_spliced(self, spool) -> str:
        """`result_hash`, with the sessions array replayed from a SPOOL.

        Byte-identical to `result_hash()` by construction: the object is
        serialised once with a placeholder in the sessions slot, split there,
        and the spool's canonical array bytes fed between the two halves.

        THE PLACEHOLDER IS STRUCTURALLY UNCOLLIDABLE. A fresh uuid4 per call, so
        no data the engine did not invent can contain it, wrapped in NUL bytes
        which cannot appear unescaped in JSON output. Its serialised form is
        asserted to occur EXACTLY ONCE before anything is split on it — a
        placeholder appearing twice would splice the array into the wrong place
        and yield a plausible, permanently wrong certification hash.
        """
        import uuid
        from stock_strategy_shared.wealth_core.hashes import CanonicalArraySpool
        if not isinstance(spool, CanonicalArraySpool):
            raise TypeError("spool must be a CanonicalArraySpool")

        placeholder = f"\x00WC-SESSIONS-{uuid.uuid4().hex}\x00"
        skeleton = dict(self.to_dict())
        skeleton["sessions"] = placeholder
        blob = json.dumps(_quantize(skeleton), sort_keys=True,
                          separators=(",", ":"), default=_json_default)
        marker = json.dumps(placeholder)
        n = blob.count(marker)
        if n != 1:
            raise RuntimeError(
                f"sessions placeholder occurred {n} times, expected exactly 1; "
                f"refusing to splice — a mis-placed splice produces a plausible "
                f"and permanently wrong certification hash")
        pre, post = blob.split(marker)

        h = hashlib.sha256()
        h.update(pre.encode())
        spool.replay_into(h)
        h.update(post.encode())
        return h.hexdigest()


def _round(x):
    """Round money to the cent BEFORE hashing.

    Two engines can accumulate the same cash flows in a different association
    order and land 1e-12 apart — a difference that is not a strategy difference
    but would fail the parity test forever, training everyone to ignore it.
    """
    return None if x is None else round(float(x), 2)


def _json_default(o):
    """Still the encoder's last resort — for genuinely unserialisable types.

    It no longer carries the float rounding, because it was never reached for
    one. Anything arriving here is a type the run result should not contain,
    and raising names it instead of silently stringifying it.
    """
    raise TypeError(f"{type(o).__name__} is not serialisable in a run result")


def run_sessions(*, sessions: Sequence[str],
                 bars_by_session: Mapping[str, Sequence[VendorBar]],
                 meta: Mapping[str, SecurityMeta],
                 metadata_timeline: DecisionMetadataTimeline | None = None,
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
                 hash_mode: str = "materialized",
                 hash_accumulator=None,
                 on_session: Callable[[SessionResult], None] | None = None,
                 ) -> RunResult:
    """Drive the strategy across `sessions`, in order.

    RESUMABLE by construction: pass back the state, pending queue, ledger,
    last-known marks and feed from a previous call and the run continues as if
    it had never stopped. That is not a convenience — the live book restarts,
    and a strategy whose position ages and episode peaks cannot survive a
    restart is a different strategy after every deploy.
    """
    # Validate the complete driver stream before constructing or mutating any
    # canonical state. A repeated session is not an idempotent retry here: it
    # would reapply corporate actions, dividends and rolling observations.
    validate_session_stream(sessions, context="run")

    seen_terminal_events: set[tuple[str, str]] = set()
    for ev in terminal_events:
        key = (ev.session, ev.security_id)
        if key in seen_terminal_events:
            raise ValueError(
                f"duplicate terminal event for {ev.security_id!r} on "
                f"{ev.session!r}; one economic action would be applied twice")
        seen_terminal_events.add(key)

    cfg = cfg or WealthCoreConfig()
    state = state if state is not None else PortfolioState.fresh(
        starting_cash, cfg.n_slots if hasattr(cfg, "n_slots") else 25)
    # `initialized` is NOT set here. It means "the book has been constructed",
    # and `decide` reads it to choose between filling every free slot at once
    # (the opening) and one admission per session (steady state). Setting it
    # before the first decision made the opening drip-feed: 4 entries in 130
    # sessions instead of a book. It is now set by apply_entry, when the first
    # position actually FILLS — a resumed run carries it in from storage.
    pending = pending if pending is not None else []
    ledger = ledger if ledger is not None else Ledger()
    last_known = last_known if last_known is not None else {}
    feed = feed if feed is not None else Feed(
        meta, eligibility_cfg, metadata_timeline)

    events_by_session: dict[str, list[TerminalEvent]] = {}
    for ev in terminal_events:
        events_by_session.setdefault(ev.session, []).append(ev)
    # A terminal action dated INSIDE this run's window but not on one of its
    # sessions never fires — a weekend date or a typo silently leaves the
    # position outstanding for the rest of the backtest. Events dated OUTSIDE
    # the window are legitimate: a resumed run is handed the whole deal
    # calendar and only the part it covers is due yet.
    if sessions:
        lo, hi = sessions[0], sessions[-1]
        stranded = sorted(d for d in set(events_by_session) - set(sessions)
                          if lo <= d <= hi)
        if stranded:
            raise ValueError(
                f"terminal event(s) dated {stranded} fall inside this run's "
                f"window but on no trading session, so they would never fire "
                f"and the position would stay outstanding. Refused rather than "
                f"dropped.")

    from stock_strategy_shared.wealth_core.settlement import empty_counters
    # ZEROED, not empty: a missing key reads as "not measured", and the whole
    # point of these counters is to distinguish "no proxy settlements happened"
    # from "nobody looked".
    out = RunResult(state=state, ledger=ledger,
                    settlement_counters=empty_counters())
    if hash_mode not in ("materialized", "streaming"):
        raise ValueError(
            f"hash_mode must be 'materialized' or 'streaming', got "
            f"{hash_mode!r}. Refused rather than defaulted — a certification "
            f"run that silently fell back to materialized would OOM hours in.")
    last_norm = None

    for session in sessions:
        # Resolved terminal actions land BEFORE the session steps, so a security
        # acquired for cash pays into the balance that this session's admissions
        # size against — and a write-off resolves the equity block in the same
        # session rather than one late.
        norm = feed.advance(session, bars_by_session.get(session, ()),
                            (terminal_states or {}).get(session))
        last_norm = norm
        res = step_session(session=session, state=state, bars=norm.bars,
                           pending=pending, ledger=ledger, last_known=last_known,
                           cfg=cfg, strategy_id=STRATEGY_ID,
                           strategy_version=STRATEGY_VERSION,
                           security_bars=norm.security_bars,
                           # Applied INSIDE the session, at their documented
                           # position after splits/dividends and before fills.
                           terminal_terms=events_by_session.get(session, []),
                           settlement_counters=out.settlement_counters)
        # FOLD FIRST, then decide whether to keep. The accumulator has already
        # consumed everything the parity hashes need by the time the object is
        # dropped, which is what makes retention a storage decision rather than
        # a behavioural one.
        if hash_accumulator is not None:
            hash_accumulator.add(res, out.session_row(res))
        from stock_strategy_shared.wealth_core.performance import SessionFacts
        out.session_facts.append(SessionFacts(
            session=res.session, resolved_equity=res.resolved_equity,
            fills=tuple(res.fills or ()), blocked=bool(res.blocked)))
        if hash_mode == "materialized":
            out.sessions.append(res)
        out.terminal_results.extend(res.terminal_results)
        if res.blocked:
            out.blocked_sessions.append(session)
        if on_session is not None:
            on_session(res)

    # Orders still queued at the end are REPORTED, not dropped. An exit that
    # never found a tradeable open is a position the run is still holding for a
    # reason, and a summary that omits it reads as a clean finish.
    out.unfilled_at_end = []
    for p in pending:
        row = {"security_id": p.security_id, "ticker": p.ticker,
               "operation": p.operation.value, "shares": p.shares,
               "signal_session": p.signal_session,
               "sessions_waiting": p.sessions_waiting}
        if p.transformations:
            row["transformations"] = list(p.transformations)
        out.unfilled_at_end.append(row)

    # FINAL-SESSION ACCOUNTING. Marks come from the last session's bars, so the
    # book is valued at its final VALID close rather than at whatever was last
    # seen — a security that stopped printing in week two is reported unmarkable,
    # not carried forward as though it were current.
    if sessions and last_norm is not None:
        # Marks from the LAST SESSION'S OWN BARS, not from `last_known`. A
        # security that stopped printing in week two must be reported
        # unmarkable; `last_known` would hand back its final print and the
        # report would value a position that has had no market for years.
        # `dict(last_known)` because build_marks MUTATES what it is given, and
        # the final report must not change the run's marking state.
        # `terminal_pending_sessions` passed HERE too. Ordinary session marking
        # supplies it and this call did not, so a holding in an active C1 grace
        # was marked by a DIFFERENT rule at the run boundary than on every
        # session before it — the same divergence `final_report` had, one layer
        # down. Two places deciding what a carried holding is worth is one place
        # too many.
        final_marks = build_marks(last_norm.bars, state.held_security_ids(),
                                  dict(last_known), state.unresolved_terminals,
                                  state.terminal_pending_sessions)
        out.final = final_report(session=sessions[-1], state=state,
                                 marks=final_marks, ledger=ledger, cfg=cfg)
    return out


def run_with_hashes(**kw):
    """`run_sessions` plus the seven parity hashes, in one call.

    `hash_mode="streaming"` folds each session into the hashes as it completes
    and never retains it, which is what makes a three-year certification fit in
    memory. The digests are byte-identical to the materialised path — proven on
    the golden fixture, not assumed.

    Every engine goes through THIS rather than calling run_sessions and hashing
    itself. The point of the parity contract is that no engine gets to decide
    what it hashes or how it rounds — an engine that computed its own hashes
    could satisfy the contract while doing something different, which is the
    failure mode the contract exists to detect.
    """
    from stock_strategy_shared.wealth_core.hashes import (
        SessionHashAccumulator, parity_hashes)
    if kw.get("hash_mode", "materialized") != "streaming":
        result = run_sessions(**kw)
        return result, parity_hashes(
            result, list(kw["sessions"]), kw["bars_by_session"],
            metadata_timeline=kw.get("metadata_timeline"))
    acc = SessionHashAccumulator()
    try:
        result = run_sessions(**dict(kw, hash_accumulator=acc))
        return result, acc.finalize(
            result, list(kw["sessions"]), kw["bars_by_session"],
            metadata_timeline=kw.get("metadata_timeline"))
    finally:
        acc.dispose()


__all__ = ["RunResult", "TerminalEvent", "run_sessions", "run_with_hashes",
           "STRATEGY_ID", "STRATEGY_VERSION"]
