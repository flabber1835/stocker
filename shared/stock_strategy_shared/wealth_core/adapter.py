"""Wealth Core v1 — the SHARED session adapter. PURE.

The backtester, the wind tunnel and the live book all drive the strategy through
`step_session`. They differ only in where `DailyBar`s come from and what they do
with the resulting ledger — the ordering, the pending-order queue, the corporate
actions and the equity gate are identical by construction, which is the only way
the cross-engine parity requirement can be met rather than asserted.

DAILY EVENT ORDERING (spec §11), fixed here and nowhere else:

    0. ticker changes    re-label held positions, reservations and queued orders
                         BEFORE anything reads a symbol. Changes no number.
    1. splits            share counts change BEFORE anything reads them
    2. dividends         accrue as receivables, then settle to cash
    3. terminal actions  cash mergers, conversions, write-offs
    4. EXECUTE pending   orders decided at t-1, filled at THIS session's open
    5. age one session   holdings and both cooldowns advance at the close
    6. entry-close peak  newly-filled episodes take their first owned close
    7. decide()          on information available after this close
    8. queue             new operations become pending orders for the NEXT open

Step 4 before step 7 is what stops a same-open replacement: by the time
`decide()` runs, this session's fills have already happened and its decisions
cannot reach back to them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from stock_strategy_shared.wealth_core.engine import (
    Decision,
    Op,
    Operation,
    SecurityBar,
    WealthCoreConfig,
    affordable_shares,
    apply_entry,
    apply_exit,
    decide,
)
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.marks import Mark, MarkStatus, _positive
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import PortfolioState


@dataclass
class PendingOrder:
    """An order decided after session t, awaiting the next tradeable open.

    It PERSISTS across non-tradeable sessions (spec §11) rather than expiring:
    a halted security's exit is still wanted tomorrow, and silently dropping it
    would leave a stopped-out position in the book with no record of why.
    """
    operation: Operation
    security_id: str
    ticker: str
    slot_id: int
    shares: int
    signal_session: str
    reason: str
    sessions_waiting: int = 0

    def to_dict(self) -> dict:
        """Serialise for a restart. `sessions_waiting` is part of the state, not
        a statistic: an order that has waited eleven sessions and one queued
        yesterday are different facts, and resetting the counter across a
        restart hides a security that has become untradeable."""
        return {"operation": self.operation.value, "security_id": self.security_id,
                "ticker": self.ticker, "slot_id": self.slot_id,
                "shares": self.shares, "signal_session": self.signal_session,
                "reason": self.reason, "sessions_waiting": self.sessions_waiting}

    @classmethod
    def from_dict(cls, d: dict) -> "PendingOrder":
        return cls(operation=Operation(d["operation"]),
                   security_id=d["security_id"], ticker=d["ticker"],
                   slot_id=d["slot_id"], shares=d["shares"],
                   signal_session=d["signal_session"], reason=d["reason"],
                   sessions_waiting=d.get("sessions_waiting", 0))


@dataclass
class SessionResult:
    session: str
    decision: Decision | None
    fills: list[dict] = field(default_factory=list)
    resolved_equity: float | None = None
    estimated_equity: float = 0.0
    blocked: bool = False
    # Orders that reached a tradeable open but could not be paid for. Reported
    # rather than silently dropped: a cancelled entry leaves a slot empty for
    # reasons that have nothing to do with the strategy's opinion of the name.
    cancelled: list[dict] = field(default_factory=list)
    # What each terminal action dated on this session actually did — applied,
    # blocked on missing terms, or not held. RETURNED rather than kept local:
    # when the corporate-action ordering fix moved these from the caller into
    # `step_session`, the result rows stopped reaching `RunResult` and the run
    # hash silently stopped covering corporate-action outcomes entirely. The
    # ledger still recorded the events, so every aggregate looked right and only
    # the audit trail was gone — exactly the class of loss the hash exists to
    # catch. `session` is stamped here because the caller can no longer add it.
    terminal_results: list[dict] = field(default_factory=list)
    # Ticker changes applied this session. A relabelling moves no money, so it
    # posts no ledger event — but an exit silently submitted under a dead symbol
    # is exactly the kind of thing that must not be invisible.
    relabelled: list[dict] = field(default_factory=list)


def build_marks(bars: Sequence[DailyBar], held: set[str],
                last_known: dict[str, float],
                unresolved_terminals: Mapping[str, str] | None = None,
                pending_terms: Mapping[str, int] | None = None
                ) -> dict[str, Mark]:
    """Turn today's bars into per-holding mark STATUS (spec, 2026-08-03 rule).

    A held security with no bar, or an unresolved terminal action, becomes STALE
    or UNRESOLVED_TERMINAL — never absent, because absence reads as zero to
    anything summing a dict.

    `unresolved_terminals` OUTRANKS a printing price. A security whose deal
    terms are unknown may still trade — during a contested bid it usually does —
    and marking it CURRENT would let the book size admissions off a price that
    is about to be replaced by consideration nobody has stated.

    `pending_terms` (C1's grace period) does NOT outrank a printing price, and
    that asymmetry is deliberate. Both dicts describe a documented event with
    unreadable terms, but a blocked holding has no mark the waterfall was
    willing to trust while a carried one does — so a carried security that is
    still trading marks CURRENT on its own print, and only falls back to the
    carried value when it stops printing. Treating the two dicts alike would
    freeze admissions for a security that is visibly still trading, which is the
    exact outcome the grace period exists to avoid.
    """
    blocked = dict(unresolved_terminals or {})
    carried = dict(pending_terms or {})
    by_sec = {b.security_id: b for b in bars}
    marks: dict[str, Mark] = {}
    for sec in sorted(set(by_sec) | held):
        if sec in blocked:
            marks[sec] = Mark(sec, MarkStatus.UNRESOLVED_TERMINAL,
                              stale_raw_close=last_known.get(sec))
            continue
        if sec in carried:
            b = by_sec.get(sec)
            if b is not None and b.can_mark and not b.unresolved_corporate_action:
                marks[sec] = Mark(sec, MarkStatus.CURRENT,
                                  raw_mark_close=float(b.raw_mark_close))
                last_known[sec] = float(b.raw_mark_close)
            elif _positive(last_known.get(sec)):
                marks[sec] = Mark(sec, MarkStatus.PENDING_TERMS_CARRIED,
                                  stale_raw_close=last_known.get(sec),
                                  carried_raw_close=float(last_known[sec]))
            else:
                # Carrying was authorised against a mark that is no longer
                # available. Fail closed rather than carry nothing.
                marks[sec] = Mark(sec, MarkStatus.UNRESOLVED_TERMINAL,
                                  stale_raw_close=last_known.get(sec))
            continue
        b = by_sec.get(sec)
        if b is None:
            marks[sec] = Mark(sec, MarkStatus.STALE,
                              stale_raw_close=last_known.get(sec))
        elif b.unresolved_corporate_action:
            marks[sec] = Mark(sec, MarkStatus.UNRESOLVED_TERMINAL,
                              stale_raw_close=last_known.get(sec))
        elif b.can_mark:
            marks[sec] = Mark(sec, MarkStatus.CURRENT,
                              raw_mark_close=float(b.raw_mark_close))
            last_known[sec] = float(b.raw_mark_close)
        else:
            marks[sec] = Mark(sec, MarkStatus.STALE,
                              stale_raw_close=last_known.get(sec))
    return marks


def apply_ticker_changes(state: PortfolioState, bars: Sequence[DailyBar],
                         pending: Sequence["PendingOrder"] = ()) -> list[dict]:
    """Step 0. Re-label held positions, reservations and queued orders.

    A TICKER IS AN OBSERVATION LABEL; the permanent `security_id` owns every
    piece of economic state. So a rename must change the symbol and NOTHING
    else — no trade, no cost, no reset of the peak, the age, the review flag or
    either cooldown. That falls out of keying the state on security_id; what
    does NOT fall out is the label itself, which is frozen at entry on the
    episode and at decision time on a queued order.

    Left un-refreshed, an exit for a renamed holding is submitted under the OLD
    symbol — an order for something that no longer trades, which either rejects
    at the broker or, worse, fills against whatever now owns that ticker.

    Posts no ledger event, deliberately: the ledger's rule is that an event is
    the only way a NUMBER changes, and a relabelling changes none. It is
    reported on the session result instead, so the audit still shows it.
    """
    by_sec = {b.security_id: b.ticker for b in bars if b.ticker}
    changes: list[dict] = []

    for slot_id in sorted(state.episodes):
        ep = state.episodes[slot_id]
        new = by_sec.get(ep.security_id)
        if new and new != ep.ticker:
            changes.append({"security_id": ep.security_id, "from": ep.ticker,
                            "to": new, "where": "episode", "slot_id": slot_id})
            ep.ticker = new

    for slot_id in sorted(state.slots):
        s = state.slots[slot_id]
        if s.reserved_for:
            new = by_sec.get(s.reserved_for)
            if new and new != s.reserved_ticker:
                changes.append({"security_id": s.reserved_for,
                                "from": s.reserved_ticker, "to": new,
                                "where": "reservation", "slot_id": slot_id})
                s.reserved_ticker = new

    for po in pending:
        new = by_sec.get(po.security_id)
        if new and new != po.ticker:
            changes.append({"security_id": po.security_id, "from": po.ticker,
                            "to": new, "where": "pending_order",
                            "slot_id": po.slot_id})
            po.ticker = new

    return changes


def apply_splits(state: PortfolioState, bars: Sequence[DailyBar], ledger: Ledger,
                 session: str) -> None:
    """Step 1. Share counts change FIRST, so every later calculation — marks,
    equity, exit sizing — reads the post-split count."""
    for b in bars:
        if b.split_ratio == 1.0:
            continue
        for ep in state.episodes.values():
            if ep.security_id != b.security_id:
                continue
            before = ep.current_shares
            ep.current_shares = int(before * b.split_ratio)
            # The episode peak is a SPLIT-ADJUSTED price, so it needs no
            # rescaling — that is the entire reason the signal domain is
            # split-adjusted. Rescaling here would double-apply the split.
            ledger.post(session=session, event_type=EventType.SPLIT,
                        cash_before=state.cash, security_id=b.security_id,
                        ticker=ep.ticker,
                        shares_delta=ep.current_shares - before,
                        price=None, reason="SPLIT",
                        detail={"ratio": b.split_ratio, "before": before,
                                "after": ep.current_shares})


def apply_dividends(state: PortfolioState, bars: Sequence[DailyBar],
                    ledger: Ledger, session: str,
                    cfg: WealthCoreConfig | None = None) -> None:
    """Step 2. Accrue as receivables, then settle only what has come DUE.

    ORDER MATTERS AND IS FIXED: accrue today's, then settle+age. At a lag of 0
    that pays today's dividend today, which is exactly the pre-lag behaviour and
    is what makes `dividend_settlement_lag_sessions=0` an exact reproduction
    rather than an approximate one. At any lag > 0 today's accrual is not in the
    due set, so it survives the session — and `decide()`, which runs at step 7
    against `state.cash`, cannot spend it.

    ENTITLEMENT IS BY OWNERSHIP ON THE EX-DATE, and it is read here — before
    step 4 fills this session's orders. A position bought at THIS session's open
    is not entitled to a dividend whose ex-date is this session, and a position
    sold at this open still is. Reading the share count after the fills would
    get both backwards.
    """
    lag = cfg.dividend_settlement_lag_sessions if cfg is not None else 0
    for b in sorted(bars, key=lambda x: x.security_id):
        if b.dividend_per_share <= 0:
            continue
        for ep in state.episodes.values():
            if ep.security_id == b.security_id:
                ledger.accrue_dividend(session=session, security_id=b.security_id,
                                       ticker=ep.ticker, shares=ep.current_shares,
                                       per_share=b.dividend_per_share,
                                       cash=state.cash, due_in=lag)
    state.cash, _ = ledger.settle_due(session=session, cash=state.cash)


def write_off(state: PortfolioState, *, security_id: str, ledger: Ledger,
              session: str) -> None:
    """Confirmed worthlessness — and ONLY here does the value become zero.

    Until this event is posted the holding is UNRESOLVED, not worthless. That
    distinction is the whole 2026-08-03 rule: equity changes when a human
    confirms the outcome, not when a price stops arriving.
    """
    for slot_id, ep in list(state.episodes.items()):
        if ep.security_id != security_id:
            continue
        ledger.post(session=session, event_type=EventType.WRITE_OFF,
                    cash_before=state.cash, security_id=security_id,
                    ticker=ep.ticker, shares_delta=-ep.current_shares,
                    price=0.0, reason="CONFIRMED_WORTHLESS",
                    detail={"shares": ep.current_shares})
        state.episodes.pop(slot_id)
        state.slots[slot_id].start_cooldown()
        state.security_cooldowns[ep.security_id] = 0


def cash_merger(state: PortfolioState, *, security_id: str, per_share: float,
                ledger: Ledger, session: str) -> None:
    """Terminal cash acquisition: shares leave, actual proceeds arrive."""
    for slot_id, ep in list(state.episodes.items()):
        if ep.security_id != security_id:
            continue
        proceeds = ep.current_shares * float(per_share)
        ledger.post(session=session, event_type=EventType.CASH_MERGER,
                    cash_before=state.cash, cash_delta=proceeds,
                    security_id=security_id, ticker=ep.ticker,
                    shares_delta=-ep.current_shares, price=per_share,
                    reason="CASH_MERGER", detail={"shares": ep.current_shares})
        state.cash += proceeds
        state.episodes.pop(slot_id)
        state.slots[slot_id].start_cooldown()
        state.security_cooldowns[ep.security_id] = 0


def tradeability_only_bars(bars: Sequence[DailyBar],
                           windows: Mapping[str, Sequence[float]] | None
                           ) -> list[SecurityBar]:
    """SecurityBars whose `eligible` flag is TRADEABILITY, not §1 eligibility.

    Named this way because it is not the strategy: it admits sub-$1 securities,
    preferreds, ETFs and warrants — anything with a fillable open. It exists for
    engine-level tests that are about ordering rather than about the universe,
    and a caller has to say the word "tradeability" to get it, so the conflation
    the eligibility engine was extracted to end cannot reappear by default.
    """
    w = windows or {}
    return [SecurityBar(b.security_id, b.ticker, b.issuer_id,
                        list(w.get(b.security_id, ())), eligible=b.can_execute)
            for b in bars]


def step_session(*, session: str, state: PortfolioState, bars: Sequence[DailyBar],
                 pending: list[PendingOrder], ledger: Ledger,
                 last_known: dict[str, float], cfg: WealthCoreConfig,
                 strategy_id: str, strategy_version: int,
                 security_bars: Sequence[SecurityBar],
                 terminal_terms: Sequence = (),
                 settlement_counters: dict | None = None) -> SessionResult:
    """One market session, in the fixed order documented at module level.

    `security_bars` carries §1 eligibility and the trailing SIGNAL windows, both
    decided upstream by `feed.Feed`. It is REQUIRED and has no default: the
    previous signature derived eligibility from `can_execute`, which meant every
    caller that simply passed price bars silently ran a universe the strategy
    never specified. There is `tradeability_only_bars` for callers that really do
    want that, and it says so in its name.
    """
    by_sec = {b.security_id: b for b in bars}

    # ── 0. re-label ──────────────────────────────────────────────────────────
    # Before anything reads a ticker. Changes no number and no economic state.
    relabelled = apply_ticker_changes(state, bars, pending)

    apply_splits(state, bars, ledger, session)
    apply_dividends(state, bars, ledger, session, cfg)

    # ── 3. terminal actions, HERE and not before ─────────────────────────────
    # They used to be applied by the caller BEFORE this function ran, i.e. before
    # splits, before dividends and before pending fills — contradicting the
    # ordering documented at the top of this module. Two reproducible failures
    # followed: a pending exit plus a same-day cash merger raised KeyError,
    # because the merger had already removed the episode the exit then popped;
    # and a pending ENTRY plus a same-day merger BOUGHT a security that had
    # already terminated. Both are ordering artefacts, so the ordering is now in
    # one place — the same place that documents it.
    terminal_results: list[dict] = []
    for terms in sorted(terminal_terms,
                        key=lambda t: (t.security_id, t.kind.value)):
        from stock_strategy_shared.wealth_core.terminal import apply_terminal
        _b = by_sec.get(terms.security_id)
        terminal_results.append(
            {"session": session,
             **apply_terminal(
                 state, terms, ledger=ledger, session=session, cfg=cfg,
                 # Staleness carried in from PRIOR sessions — THIS session's
                 # marks have not been built yet, which is correct: "sessions
                 # since the last valid print" is a fact as of the event.
                 last_valid_mark=last_known.get(terms.security_id),
                 sessions_since_last_valid_print=(
                     state.sessions_since_valid_mark.get(terms.security_id, 0)),
                 # A real tradeable print on the terminal session outranks any
                 # proxy — an actual transaction rather than a valuation.
                 executable_price=(float(_b.raw_mark_close)
                                   if _b is not None and _b.can_execute
                                   and _b.raw_mark_close else None),
                 counters=settlement_counters)})
    terminated = {t.security_id for t in terminal_terms}

    # ── 4. execute orders decided BEFORE this session ────────────────────────
    fills: list[dict] = []
    res_cancelled: list[dict] = []
    still_pending: list[PendingOrder] = []
    entered_this_session: list[int] = []
    for po in pending:
        if po.security_id in terminated and po.slot_id not in state.episodes:
            # The security terminated this session and the slot is gone. An
            # ENTRY here would buy a security that no longer exists; an EXIT
            # would pop an episode the terminal action already removed
            # (KeyError). Dropping the order is the only coherent outcome, and
            # it is RECORDED so a vanished order is never silent.
            res_cancelled.append(
                {"session": session, "security_id": po.security_id,
                 "ticker": po.ticker, "slot_id": po.slot_id,
                 "wanted_shares": po.shares,
                 "reason": "TERMINATED_BEFORE_FILL"})
            continue
        b = by_sec.get(po.security_id)
        if b is None or not b.can_execute:
            po.sessions_waiting += 1        # persists; never silently dropped
            still_pending.append(po)
            continue
        px = float(b.raw_open)
        if po.operation is Operation.CLOSE_POSITION:
            before = state.cash
            apply_exit(state, slot_id=po.slot_id, raw_open=px, cfg=cfg)
            ledger.post(session=session, event_type=EventType.SELL,
                        cash_before=before, cash_delta=state.cash - before,
                        security_id=po.security_id, ticker=po.ticker,
                        shares_delta=-po.shares, price=px,
                        fees=po.shares * px * cfg.transaction_cost_bps / 10_000.0,
                        reason=po.reason)
        else:
            # NO LEVERAGE, checked at the fill and not only at the decision.
            # The size was computed from session t's close; this is t+1's open
            # and it can gap. Fill what the cash actually covers.
            fillable = min(po.shares, affordable_shares(state.cash, px, cfg))
            if fillable <= 0:
                state.slots[po.slot_id].release_reservation()
                res_cancelled.append(
                    {"session": session, "security_id": po.security_id,
                     "ticker": po.ticker, "slot_id": po.slot_id,
                     "wanted_shares": po.shares, "raw_open": px,
                     "cash": round(state.cash, 2), "reason": "UNAFFORDABLE_AT_OPEN"})
                continue
            if fillable < po.shares:
                res_cancelled.append(
                    {"session": session, "security_id": po.security_id,
                     "ticker": po.ticker, "slot_id": po.slot_id,
                     "wanted_shares": po.shares, "filled_shares": fillable,
                     "raw_open": px, "reason": "PARTIAL_AT_OPEN"})
                po.shares = fillable
            before = state.cash
            apply_entry(state, op=Op(Operation.OPEN_SLOT_POSITION, None,
                                     po.slot_id, po.security_id, po.ticker,
                                     po.shares),
                        session=session, signal_session=po.signal_session,
                        raw_open=px,
                        # The split-adjusted EXECUTION OPEN — the price the
                        # position was actually bought at, in the domain the
                        # review compares against. The fill session's signal
                        # close is a different number by a whole session's move.
                        split_adjusted_price=(
                            b.signal_open_split_adj_div_unadj
                            or b.signal_close_split_adj_div_unadj or px),
                        issuer_id=b.issuer_id, cfg=cfg)
            ledger.post(session=session, event_type=EventType.BUY,
                        cash_before=before, cash_delta=state.cash - before,
                        security_id=po.security_id, ticker=po.ticker,
                        shares_delta=po.shares, price=px,
                        fees=po.shares * px * cfg.transaction_cost_bps / 10_000.0,
                        reason=po.reason)
            entered_this_session.append(po.slot_id)
        fills.append({"session": session, "security_id": po.security_id,
                      "operation": po.operation.value, "shares": po.shares,
                      "raw_open": px, "waited": po.sessions_waiting})
    pending[:] = still_pending

    # ── 5. age, then 6. seed the entry-session peak ──────────────────────────
    signal_closes = {b.security_id: b.signal_close_split_adj_div_unadj for b in bars}
    aged = {sid: ep for sid, ep in state.episodes.items()
            if sid not in entered_this_session}
    saved, state.episodes = state.episodes, aged
    state.age_one_session(signal_closes)
    state.episodes = saved
    for slot_id in entered_this_session:
        # Age 0 at the entry close (locked convention), but this IS the first
        # owned close, so the peak initialises here and nowhere earlier.
        state.episodes[slot_id].observe_entry_close(
            signal_closes.get(state.episodes[slot_id].security_id))

    # ── 7. decide ────────────────────────────────────────────────────────────
    held = state.held_security_ids()
    marks = build_marks(bars, held, last_known, state.unresolved_terminals,
                        state.terminal_pending_sessions)

    # ── 7a. staleness, from THIS session's marks ─────────────────────────────
    # The input to both of the settlement waterfall's bounds. Counted on MARKET
    # sessions rather than calendar days, so a long weekend is never a data gap.
    # A security is REMOVED on a current mark rather than set to 0, so a healthy
    # book carries an empty dict and its state hash is unchanged.
    for sec in held:
        m = marks.get(sec)
        if m is not None and m.status is MarkStatus.CURRENT:
            state.sessions_since_valid_mark.pop(sec, None)
        else:
            state.sessions_since_valid_mark[sec] = (
                state.sessions_since_valid_mark.get(sec, 0) + 1)
    for sec in list(state.sessions_since_valid_mark):
        if sec not in held:          # no longer held: carries no staleness
            state.sessions_since_valid_mark.pop(sec, None)

    # ── 7b. age and expire C1 graces, THEN sweep C2 orphans ──────────────────
    # ORDER IS LOAD-BEARING. A still-pending DOCUMENTED holding must never be
    # visible to the orphan zero — that conflation writes off known acquisitions
    # at zero while the run reports clean completion. Both are separate passes
    # because neither has an event to hang off: a terminal record appears in
    # ACTIONS on ONE session and never again, so nothing else would ever advance
    # the grace counter and the carry would be infinite.
    from stock_strategy_shared.wealth_core.terminal import (
        sweep_orphans, sweep_pending_terms)
    swept = sweep_pending_terms(state, ledger=ledger, session=session,
                                last_known=last_known,
                                resolved_this_session=terminated,
                                counters=settlement_counters)
    swept += sweep_orphans(state, ledger=ledger, session=session,
                           terminated=terminated,
                           counters=settlement_counters)
    if swept:
        terminal_results.extend(swept)
        held = state.held_security_ids()
        marks = build_marks(bars, held, last_known,
                            state.unresolved_terminals,
                            state.terminal_pending_sessions)

    # The trailing SIGNAL window travels INSIDE security_bars, never derived
    # here from `last_known` — that dict holds RAW mark closes, a different
    # price domain, and reusing it would be exactly the cross-domain error
    # prices.py exists to prevent.
    ev = state.equity_view(marks)
    d = decide(session=session, state=state, bars=list(security_bars), marks=marks,
               cfg=cfg, strategy_id=strategy_id, strategy_version=strategy_version)

    # ── 8. queue for the NEXT open ───────────────────────────────────────────
    for op in d.operations:
        if op.operation in (Operation.OPEN_SLOT_POSITION, Operation.CLOSE_POSITION):
            pending.append(PendingOrder(
                operation=op.operation, security_id=op.security_id,
                ticker=op.ticker, slot_id=op.slot_id, shares=op.shares or 0,
                signal_session=session, reason=op.reason.value))

    d.warnings.extend(
        f"terminal {r.get('kind') or r.get('reason')} on {r.get('security_id')}"
        for r in terminal_results if not r.get("applied"))
    return SessionResult(session=session, decision=d, fills=fills,
                         resolved_equity=ev.resolved_equity,
                         estimated_equity=ev.estimated_equity_including_stale_marks,
                         blocked=not ev.is_resolved, cancelled=res_cancelled,
                         terminal_results=terminal_results,
                         relabelled=relabelled)
