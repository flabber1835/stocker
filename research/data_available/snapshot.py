"""Build research features from one supplied current window, without a prior feed."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from stock_strategy_shared.wealth_core.feed import Feed
from stock_strategy_shared.wealth_core.median5 import fresh
from .policy import WINDOW, snapshot_bars


def from_window(sessions, rows, metadata):
    """All supplied bars are facts in this snapshot, not historical commands.

    Missing instrument rows are allowed. Session-axis holes must be resolved by
    the acquisition adapter before this seam: the axis names market sessions.
    A caller can replace yesterday's window with a corrected one without a
    historical equality comparison or touching any portfolio/account state.
    """
    axis=list(sessions)
    if len(axis)!=WINDOW or any(a>=b for a,b in zip(axis,axis[1:])):
        raise ValueError('snapshot requires exactly 300 ordered market sessions')
    for d in axis:
        date.fromisoformat(d)
    dates=set(axis)
    by_date=defaultdict(list)
    seen=set()
    for row in rows:
        key=(row.session,row.security_id)
        if row.session not in dates or key in seen:
            raise ValueError('snapshot row outside axis or duplicate identity')
        seen.add(key)
        by_date[row.session].append(row)
    feed=Feed(metadata)
    feed.median5_state=fresh()
    for d in axis:
        norm=feed.advance(d,by_date[d])
    # Window-only calculation discards accumulated historical numerical residue.
    return snapshot_bars(feed,norm.security_bars),feed
