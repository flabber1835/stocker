"""Position-episode bookkeeping for the trailing stop — PURE, no I/O.

An EPISODE is one unbroken period of holding a ticker. It gives the trailing stop
the two facts the schema could not otherwise answer: when the position opened (so
"highest close since entry" has an anchor) and what peak stopped it (so re-entry
stays blocked until the close exceeds that peak). Durable state lives in
`position_episodes` (migration 0048); this module decides what to write.

The one subtle rule is CLOSING. `live_positions` is a per-sync snapshot, so a
ticker's absence is not evidence of a sale — a degraded or partial sync produces
the same reading as a liquidation. Closing on first absence would mean a single bad
sync ends the episode, the ticker reappears next run, a NEW episode opens with a
RESET peak, and the stop silently loosens on that position. A risk control that
fails quietly toward "less protection" is the worst failure available here, so
absence must be confirmed across two consecutive runs before anything closes.

main.py owns the SQL; everything here is a pure function so the rules are testable
without a database.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence


@dataclass(frozen=True)
class EpisodeSync:
    """What the delta step should write to position_episodes this run."""
    to_open: set[str]           # held, no open episode → INSERT
    to_close: set[str]          # absence CONFIRMED across two runs → close
    to_mark_pending: set[str]   # absent for the FIRST time → stamp pending_close_since
    to_clear_pending: set[str]  # reappeared before confirmation → un-stamp


def plan_episode_sync(
    held: set[str],
    open_episodes: dict[str, date],
    pending_since: dict[str, Optional[date]],
    session: date,
    stop_pending: set[str] | None = None,
) -> EpisodeSync:
    """Reconcile the broker's held set against the open episodes.

    `held` is this run's live_positions snapshot; `open_episodes` maps ticker →
    opened_on for episodes with closed_on IS NULL; `pending_since` maps those same
    tickers to their pending_close_since (None when not pending).

    Confirmation is "seen absent on two different runs", not a day count: the delta
    step runs once per session, and counting runs rather than calendar days means a
    skipped or failed session never advances the timer. That matches how
    orphan_confirmation_days already behaves, and it fails in the safe direction —
    confirmation slows down, never speeds up.
    """
    to_open = {t for t in held if t not in open_episodes}
    to_close: set[str] = set()
    to_mark_pending: set[str] = set()
    to_clear_pending: set[str] = set()

    stop_pending = stop_pending or set()
    for ticker in open_episodes:
        if ticker in held:
            # A STOP-pending episode must NOT be cleared here. pending_close_since
            # carries two different meanings: "absent from one sync, probably a bad
            # snapshot" (clearable) and "the stop fired, the sell is queued for the
            # next open" (not clearable — the position is still held precisely
            # BECAUSE the sale has not happened yet). Clearing the second would
            # disarm the re-entry block and lose the recorded stop peak on the very
            # next sync, which is the failure mode the pending state was introduced
            # to prevent.
            if (pending_since.get(ticker) is not None
                    and ticker not in stop_pending):
                to_clear_pending.add(ticker)   # came back — it was a bad snapshot
            continue
        marked = pending_since.get(ticker)
        if marked is None:
            to_mark_pending.add(ticker)        # first absence: suspect, not proven
        elif session > marked:
            to_close.add(ticker)               # absent again on a later run: confirmed
    return EpisodeSync(to_open=to_open, to_close=to_close,
                       to_mark_pending=to_mark_pending,
                       to_clear_pending=to_clear_pending)


def sessions_after(calendar: Sequence[date], d: Optional[date]) -> Optional[int]:
    """How many trading sessions in `calendar` fall strictly after `d`.

    This is the staleness measure the stop uses. Counted in SESSIONS from a real
    market calendar rather than in calendar days, because a weekend or holiday must
    not make a perfectly fresh print look two days old and disarm the stop. Returns
    None when the date is unknown — the caller treats that as "cannot evaluate".
    """
    if d is None:
        return None
    return sum(1 for c in calendar if c > d)


def build_stop_states(
    rows: Sequence[dict],
    calendar: Sequence[date],
    stop_state_cls,
) -> dict:
    """Turn per-ticker price aggregates into StopStates the planner can judge.

    Each row is {ticker, peak_close, last_close, last_date, sessions_held}, already
    scoped to `date >= opened_on` by the query. A ticker is DROPPED (not defaulted)
    whenever any field is missing or unusable: absent from stop_states means the
    planner never considers it, which is the same "no fresh price ⇒ never force-sell"
    rule the delta engine's data-gap branch already applies. Defaulting instead
    would invent a peak, and an invented peak sells a real position.

    `stop_state_cls` is injected so this module does not import the engine — it is
    loaded by file path in bt-engine and normally in the pipeline, and a hard import
    here would couple the two load paths for no benefit.
    """
    states: dict = {}
    for row in rows:
        ticker = row.get("ticker")
        peak = row.get("peak_close")
        last = row.get("last_close")
        held = row.get("sessions_held")
        stale = sessions_after(calendar, row.get("last_date"))
        if not ticker or peak is None or last is None or held is None or stale is None:
            continue
        try:
            peak_f, last_f = float(peak), float(last)
        except (TypeError, ValueError):
            continue
        if not (peak_f > 0) or not (last_f > 0):   # NaN-safe
            continue
        states[ticker] = stop_state_cls(
            peak_close=peak_f, last_close=last_f,
            sessions_held=int(held), sessions_since_close=int(stale))
    return states


def blocked_reentries(
    stop_peaks: dict[str, float],
    last_closes: dict[str, float],
    held: set[str],
    reentry_blocked_fn,
    *,
    sessions_since_stop: dict[str, int] | None = None,
    policy: str = "peak",
    cooldown_sessions: int = 21,
) -> set[str]:
    """Tickers that stopped out and are still barred from being re-bought.

    Only names NOT currently held can be blocked — re-buying clears the block, and a
    position we already hold is governed by its own live episode. A ticker with no
    fresh close is NOT blocked under the PEAK policy: the block exists to prevent a
    re-buy, and without a price nothing can buy it anyway.

    Under the COOLDOWN policy the price is irrelevant — only elapsed sessions since
    the stop matter — so a name with no fresh print is still blocked while its timer
    runs. That asymmetry is deliberate: the peak rule needs a price to compare
    against and the cooldown does not, so requiring one would silently unblock a
    halted name early.
    """
    sessions_since_stop = sessions_since_stop or {}
    return {
        t for t, peak in stop_peaks.items()
        if t not in held and reentry_blocked_fn(
            last_closes.get(t), peak,
            sessions_since_stop=sessions_since_stop.get(t),
            policy=policy, cooldown_sessions=cooldown_sessions)
    }
