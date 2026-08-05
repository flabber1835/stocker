"""Wealth Core v1 — the SHARED session adapter. PURE.

The backtester, the wind tunnel and the live book all drive the strategy through
`step_session`. They differ only in where `DailyBar`s come from and what they do
with the resulting ledger — the ordering, the pending-order queue, the corporate
actions and the equity gate are identical by construction, which is the only way
the cross-engine parity requirement can be met rather than asserted.

DAILY EVENT ORDERING (spec §11), fixed here and nowhere else:

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
    apply_entry,
    apply_exit,
    decide,
)
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.marks import Mark, MarkStatus
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


@dataclass
class SessionResult:
    session: str
    decision: Decision | None
    fills: list[dict] = field(default_factory=list)
    resolved_equity: float | None = None
    estimated_equity: float = 0.0
    blocked: bool = False


def build_marks(bars: Sequence[DailyBar], held: set[str],
                last_known: dict[str, float]) -> dict[str, Mark]:
    """Turn today's bars into per-holding mark STATUS (spec, 2026-08-03 rule).

    A held security with no bar, or an unresolved terminal action, becomes STALE
    or UNRESOLVED_TERMINAL — never absent, because absence reads as zero to
    anything summing a dict.
    """
    by_sec = {b.security_id: b for b in bars}
    marks: dict[str, Mark] = {}
    for sec in sorted(set(by_sec) | held):
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
                    ledger: Ledger, session: str) -> None:
    """Step 2. Accrue as receivables, then settle. Two events, never one."""
    for b in sorted(bars, key=lambda x: x.security_id):
        if b.dividend_per_share <= 0:
            continue
        for ep in state.episodes.values():
            if ep.security_id == b.security_id:
                ledger.accrue_dividend(session=session, security_id=b.security_id,
                                       ticker=ep.ticker, shares=ep.current_shares,
                                       per_share=b.dividend_per_share,
                                       cash=state.cash)
    state.cash, _ = ledger.settle_receivables(session=session, cash=state.cash)


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
        state.ticker_cooldowns[ep.ticker] = 0


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
        state.ticker_cooldowns[ep.ticker] = 0


def step_session(*, session: str, state: PortfolioState, bars: Sequence[DailyBar],
                 pending: list[PendingOrder], ledger: Ledger,
                 last_known: dict[str, float], cfg: WealthCoreConfig,
                 strategy_id: str, strategy_version: int,
                 signal_windows: Mapping[str, Sequence[float]] | None = None
                 ) -> SessionResult:
    """One market session, in the fixed order documented at module level."""
    by_sec = {b.security_id: b for b in bars}

    apply_splits(state, bars, ledger, session)
    apply_dividends(state, bars, ledger, session)

    # ── 4. execute orders decided BEFORE this session ────────────────────────
    fills: list[dict] = []
    still_pending: list[PendingOrder] = []
    entered_this_session: list[int] = []
    for po in pending:
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
            before = state.cash
            apply_entry(state, op=Op(Operation.OPEN_SLOT_POSITION, None,
                                     po.slot_id, po.security_id, po.ticker,
                                     po.shares),
                        session=session, signal_session=po.signal_session,
                        raw_open=px,
                        split_adjusted_price=b.signal_close_split_adj_div_unadj or px,
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
    marks = build_marks(bars, held, last_known)
    # The trailing SIGNAL window is supplied by the adapter, never derived from
    # `last_known` — that dict holds RAW mark closes, a different price domain,
    # and reusing it here is exactly the cross-domain error prices.py exists to
    # prevent. A caller that supplies none gets no signals rather than wrong ones.
    windows = signal_windows or {}
    sec_bars = [SecurityBar(b.security_id, b.ticker, b.issuer_id,
                            list(windows.get(b.security_id, ())),
                            eligible=b.can_execute)
                for b in bars]
    ev = state.equity_view(marks)
    d = decide(session=session, state=state, bars=sec_bars, marks=marks, cfg=cfg,
               strategy_id=strategy_id, strategy_version=strategy_version)

    # ── 8. queue for the NEXT open ───────────────────────────────────────────
    for op in d.operations:
        if op.operation in (Operation.OPEN_SLOT_POSITION, Operation.CLOSE_POSITION):
            pending.append(PendingOrder(
                operation=op.operation, security_id=op.security_id,
                ticker=op.ticker, slot_id=op.slot_id, shares=op.shares or 0,
                signal_session=session, reason=op.reason.value))

    return SessionResult(session=session, decision=d, fills=fills,
                         resolved_equity=ev.resolved_equity,
                         estimated_equity=ev.estimated_equity_including_stale_marks,
                         blocked=not ev.is_resolved)
