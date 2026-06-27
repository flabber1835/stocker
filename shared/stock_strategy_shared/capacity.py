"""Canonical position-capacity rule — the SINGLE source of truth for "does this
book fit within max_positions", shared by the planner (delta engine
`_allocate_capacity`) and the risk gate (`MAX_POSITIONS`).

Why this exists
---------------
The planner decides entries at BUILD time (after close, from a broker snapshot);
the risk gate re-checks at EXECUTION time (the open) against live state + queued
orders. Historically the two computed capacity with the same arithmetic but
DIFFERENT inputs: the gate counts in-flight (queued, not-yet-filled) ENTRY orders
as already occupying a slot, while the planner saw only `live_positions`. So the
planner could admit an entry into a slot the gate considered taken → the gate
rejected it at the open ("Portfolio at capacity"), producing a confusing failed
order even though nothing else traded the account.

This module encodes the gate's projected-book rule as pure functions so the
planner can apply the EXACT same rule (and the same in-flight inputs), making
"the planner admits it" ⇔ "the gate approves it" true by construction. Residual
rejections then only come from genuine fill races DURING the open drain — which
is the gate's job and cannot be predicted at build time.

The projected post-cycle book (matching risk-service `_PROJECTED_POSITIONS_SQL`):

    projected = |held − exiting|  +  |entering − held|

  held     : distinct tickers currently held at the broker
  exiting  : held tickers leaving this cycle (confirmed exits + in-flight exit
             orders / exit intents) — they free their slot
  entering : NEW-ticker arrivals (this cycle's entries + in-flight entry orders),
             excluding anything already held (an already-held ticker is not a new
             slot)

A new entry for `candidate` is admissible iff adding it keeps projected ≤
max_positions.
"""
from __future__ import annotations

from typing import Iterable


def projected_book_count(
    held: set[str], exiting: set[str], entering: set[str]
) -> int:
    """Distinct positions the book will hold after this cycle settles.

    Mirrors the risk-service projected-positions SQL exactly:
    (held minus those being exited) plus (new entrants not already held)."""
    return len(held - exiting) + len(entering - held)


def fits_within_capacity(
    held: set[str],
    exiting: set[str],
    entering: set[str],
    candidate: str,
    max_positions: int,
) -> bool:
    """True if admitting `candidate` (a NEW-ticker entry) keeps the projected book
    within `max_positions`. An already-held candidate trivially fits (it occupies
    no new slot). max_positions ≤ 0 means "no cap"."""
    if max_positions <= 0:
        return True
    if candidate in held:
        return True
    return projected_book_count(held, exiting, entering | {candidate}) <= max_positions


def select_entries_within_capacity(
    held: set[str],
    exiting: set[str],
    ranked_entries: Iterable[str],
    max_positions: int,
    inflight_entries: set[str] | None = None,
) -> tuple[set[str], set[str]]:
    """Greedily admit new entries best-rank-first until the projected book reaches
    `max_positions`, exactly mirroring the gate's per-order sequential check.

    Parameters
    ----------
    held            : currently-held tickers (broker snapshot).
    exiting         : held tickers leaving this cycle (confirmed exits + in-flight
                      exit orders). They free their slots.
    ranked_entries  : candidate NEW-ticker entries, BEST RANK FIRST.
    max_positions   : the cap (≤ 0 → no cap, admit all).
    inflight_entries: NEW-ticker entry orders already queued at the broker (open,
                      not yet filled → not yet in `held`). They already claim a
                      slot in the gate's count, so they form the starting
                      occupancy. A ranked candidate already in this set is a
                      duplicate of a queued order → deferred (the executor's
                      per-ticker guard / the gate would reject it anyway).

    Returns (admitted, deferred) ticker sets. `admitted` are the entries that fit;
    `deferred` should be demoted to ``watch``.
    """
    inflight_entries = inflight_entries or set()
    admitted: set[str] = set()
    deferred: set[str] = set()
    # In-flight entries occupy slots from the start (the gate counts them).
    entering: set[str] = set(inflight_entries)
    for t in ranked_entries:
        if t in held:
            # not actually a new slot; leave it to the held/buy_add path
            continue
        if t in inflight_entries:
            # already queued — don't double-admit; defer the redundant entry
            deferred.add(t)
            continue
        if max_positions <= 0 or projected_book_count(held, exiting, entering | {t}) <= max_positions:
            admitted.add(t)
            entering.add(t)
        else:
            deferred.add(t)
    return admitted, deferred
