"""Warm up Wealth Core and produce today's target book.

```text
corpus window  ->  Feed.warmup(history)   trailing series, NO trading
                        |
                        v
                   run_sessions([today])  the OPENING: every free slot at once
                        |
                        v
                   target book            what Sentinel should hold at 100%
```

**Why the split matters.** `Feed.warmup` builds the trailing series without
trading. Running the strategy across the whole window instead would manufacture a
year of episodes — peaks, ages, review clocks and cooldowns from trades that
never happened — and those are precisely the path-dependent state
`docs/sentinel-deployment.md` §8 says warm-up must never reconstruct. A fresh
book has no history, and pretending otherwise sets every trailing stop against a
peak the account never saw.

**A cold start opens the whole book at once, by design.** `run_sessions` leaves
`initialized` unset until the first position actually FILLS, and `decide` reads
it to choose between filling every free slot (the opening) and one admission per
session (steady state). That distinction exists because setting it too early once
turned an opening into a drip-feed — 4 entries in 130 sessions instead of a book.

**Exposure is pinned to 1.00.** This is item E of the deployment doc: prove the
engine, the feed, the persistence and the execution before the controller is
allowed to vary anything. Sentinel deciding how much to hold comes after.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import Operation, WealthCoreConfig
from stock_strategy_shared.wealth_core.feed import Feed
from stock_strategy_shared.wealth_core.run import run_sessions

from sentinel.core.loader import CorpusWindow, load_window

#: Sentinel's exposure during item E. Not a parameter yet, and deliberately
#: named rather than inlined so the day it becomes one is a visible change.
PINNED_EXPOSURE = 1.0


@dataclass
class TargetBook:
    """What Sentinel intends to hold, priced for the NEXT open.

    Read this as an ORDER LIST, not a portfolio. Wealth Core decides after the
    close and queues for the next open (adapter step 8), so a bootstrap's first
    decision session produces PENDING ORDERS and zero filled episodes. Reading
    filled positions instead reports an empty book and looks like the engine
    declined to trade — it did not; it has not been to market yet.

    That shape is also exactly what the execution projection needs: shares to buy
    at tomorrow's open, which is where item I picks this up.
    """

    session: str
    positions: dict[str, float] = field(default_factory=dict)   # security -> weight
    shares: dict[str, float] = field(default_factory=dict)      # security -> shares
    tickers: dict[str, str] = field(default_factory=dict)       # security -> ticker
    held: dict[str, float] = field(default_factory=dict)        # already-filled
    cash_weight: float = 0.0
    exposure: float = PINNED_EXPOSURE
    warmup_sessions: int = 0
    caveats: list[str] = field(default_factory=list)

    @property
    def n_positions(self) -> int:
        return len(self.positions)

    def to_dict(self) -> dict:
        return {
            "session": self.session,
            "exposure": self.exposure,
            "n_positions": self.n_positions,
            "cash_weight": round(self.cash_weight, 6),
            "warmup_sessions": self.warmup_sessions,
            "positions": {
                self.tickers.get(s, s): round(w, 6)
                for s, w in sorted(self.positions.items(),
                                   key=lambda kv: -kv[1])
            },
            "shares": {self.tickers.get(s, s): v
                       for s, v in sorted(self.shares.items())},
            "already_held": {self.tickers.get(s, s): round(v, 6)
                             for s, v in sorted(self.held.items())},
            "caveats": self.caveats,
        }


def bootstrap(conn, *, start: str, end: str, starting_cash: float,
              cfg: WealthCoreConfig | None = None,
              eligibility_cfg: EligibilityConfig | None = None,
              window: Optional[CorpusWindow] = None) -> TargetBook:
    """Warm the feed over [start, end), then decide on `end`."""
    cfg = cfg or WealthCoreConfig()
    elig = eligibility_cfg or EligibilityConfig()
    w = window or load_window(conn, start=start, end=end)
    if not w.sessions:
        raise RuntimeError(
            f"no sessions in the corpus between {start} and {end}. Wealth Core "
            f"cannot plan from nothing, and an empty window reads downstream as "
            f"a market with no eligible securities rather than as a missing "
            f"load. Run `feed-seed`, then `check-data`.")

    warmup, decide_on = w.split_warmup(1)
    feed = Feed(w.meta, elig)
    if warmup:
        feed.warmup(warmup, w.bars_by_session)

    result = run_sessions(
        sessions=decide_on,
        bars_by_session=w.bars_by_session,
        meta=w.meta,
        starting_cash=starting_cash,
        cfg=cfg,
        eligibility_cfg=elig,
        feed=feed,
        # terminal_events deliberately absent — see loader.load_terminal_events.
        # The caveat below is what stops that being silent.
    )

    book = _book_from_result(result, decide_on[-1], w, len(warmup))
    book.caveats.append(
        "TERMINAL EVENTS NOT APPLIED: corporate actions are stored but not yet "
        "mapped, so this book may admit or retain a security that has been "
        "acquired or delisted. Not fatal for a first paper book; it must be "
        "closed before the book is left unattended.")
    return book


def _book_from_result(result, session: str, w: CorpusWindow,
                      n_warmup: int) -> TargetBook:
    """The target book = positions HELD plus entries COMMITTED for the next open.

    A cold start has no holdings at all. `run_sessions` decides at the close and
    QUEUES for the next open (step 8 of the fixed daily ordering), so a single
    decision session produces pending orders and zero fills — reading only
    `state.episodes` reports an empty book and hides the entire opening.

    Both are included because in steady state both exist, and the question
    execution has to answer is "what should the account hold once this session's
    orders fill?" — not "what did it hold before they were placed".

    Weights are of TOTAL equity including cash. Normalising cash away would
    report a fully-invested portfolio that does not exist: Wealth Core's 25 slots
    at 4% legitimately leave cash when fewer than 25 admissions clear.
    """
    state = getattr(result, "state", None)
    book = TargetBook(session=session, warmup_sessions=n_warmup)
    if state is None:
        return book

    marks: dict[str, float] = {}
    for b in w.bars_by_session.get(session, ()):
        book.tickers[b.security_id] = b.ticker
        if b.raw_close:
            marks[b.security_id] = float(b.raw_close)

    notional: dict[str, float] = {}

    for ep in getattr(state, "episodes", {}).values():
        sec = getattr(ep, "security_id", None)
        # `current_shares`, not `initial_shares`: a split or a partial settlement
        # changes the count, and sizing off the entry number would report a
        # weight the book has not carried since.
        shares = float(getattr(ep, "current_shares", 0.0) or 0.0)
        px = marks.get(sec)
        if sec and shares and px:
            notional[sec] = notional.get(sec, 0.0) + shares * px

    # `unfilled_at_end` is a list of SERIALISED PendingOrders (to_dict), not
    # objects — it is the restart payload, and reading it as objects is the kind
    # of shape mistake that only surfaces when a queue is non-empty.
    committed = 0.0
    for po in getattr(result, "unfilled_at_end", ()) or ():
        if po.get("operation") != Operation.OPEN_SLOT_POSITION.value:
            continue
        sec = po.get("security_id")
        px = marks.get(sec)
        shares = float(po.get("shares") or 0.0)
        if sec and shares and px:
            value = shares * px
            notional[sec] = notional.get(sec, 0.0) + value
            committed += value
            book.tickers.setdefault(sec, po.get("ticker") or sec)

    cash = float(getattr(state, "cash", 0.0) or 0.0)
    # Equity is unchanged by a pending order — the cash is still in the account
    # until the fill. Counting the committed notional on top of full cash would
    # inflate the denominator and understate every weight.
    equity = cash + sum(notional.values()) - committed
    if equity > 0:
        book.positions = {s: v / equity for s, v in notional.items()}
        book.cash_weight = max(0.0, (cash - committed) / equity)
    return book
