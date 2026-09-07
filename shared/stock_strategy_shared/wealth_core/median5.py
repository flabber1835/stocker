"""Certified Median-5 signals and ordering; the canonical book owns positions.

The mixed precision is economic state. See docs/median5-production.md.
"""
from __future__ import annotations

from bisect import bisect_left
import math
from statistics import median

PROFILE = "wealth-core-median5-v1"
HISTORY_SESSIONS = 260
REFERENCE_AST = "11c94a61c145261daac81047cf7b7bb1ea0c97b369476458d83fc29fbc10de95"


def config():
    from .engine import WealthCoreConfig
    return WealthCoreConfig(n_slots=20, entry_weight=0.05, economic_profile=PROFILE)


def fresh() -> dict:
    return {"version": 1, "last_index": -1, "sums": {},
            "rank_history": [], "formation_started": False}


def validate(value: dict) -> dict:
    if (set(value) != set(fresh()) or value["version"] != 1
            or type(value["last_index"]) is not int or value["last_index"] < -1
            or type(value["formation_started"]) is not bool):
        raise ValueError("invalid Median-5 feature state")
    if len(value["rank_history"]) > 5:
        raise ValueError("Median-5 rank history exceeds five sessions")
    for order in value["rank_history"]:
        if (not isinstance(order, list) or len(set(order)) != len(order)
                or any(not isinstance(sid, str) or not sid for sid in order)):
            raise ValueError("invalid Median-5 rank history")
    for sid, row in value["sums"].items():
        if (not isinstance(sid, str) or len(row) != 7
                or any(not math.isfinite(x) for x in row)
                or not 0 <= row[2] <= 126 or not 0 <= row[5] <= 21):
            raise ValueError("invalid Median-5 rolling accumulator")
    return value


def at(series, index, column="signal_closes"):
    if index < 0 or series is None:
        return None
    pos = bisect_left(series.session_indices, index)
    if pos == len(series.session_indices) or series.session_indices[pos] != index:
        return None
    return getattr(series, column)[pos]


def _number(value):
    return float(value) if value is not None else math.nan


def advance_signals(feed, ordered, effective, state):
    """Advance running sums once; return eligible, fully scored security bars.

    Expiring returns are reconstructed from retained ORIGINAL double closes
    and the preceding float32 close, then cast as the reference return ring.
    Only the running sums persist separately; no second price history exists.
    """
    import numpy as np
    from .eligibility import is_common_equity
    from .engine import SecurityBar
    idx = feed._session_index
    if state["last_index"] != idx - 1:
        raise ValueError("Median-5 feature sessions must advance exactly once")
    by_id = {b.security_id: b for b in ordered}
    ids = sorted(set(state["sums"]) | set(by_id))
    sums = np.asarray([state["sums"].get(sid, [0.] * 7) for sid in ids], float)
    if not ids:
        state["last_index"] = idx
        return []
    series = [feed.series.get(sid) for sid in ids]

    def values(lag, column="signal_closes"):
        return np.asarray([_number(at(s, idx-lag, column)) for s in series], float)

    current = values(0)
    previous = values(1).astype(np.float32).astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        lr = np.log(current / previous)
        valid = np.isfinite(lr) & (current > 0) & (previous > 0)
        for window, offset in ((126, 0), (21, 3)):
            old_close = values(window)
            old_previous = values(window+1).astype(np.float32).astype(float)
            expired = np.log(old_close / old_previous)
            old_valid = np.isfinite(expired) & (old_close > 0) & (old_previous > 0)
            old = np.where(old_valid, expired, 0).astype(np.float32)
            sums[:, offset] -= old
            sums[:, offset+1] -= old * old
            sums[:, offset+2] -= old_valid
            sums[valid, offset] += lr[valid]
            sums[valid, offset+1] += lr[valid] * lr[valid]
            sums[valid, offset+2] += 1

        lag21 = values(21).astype(np.float32)
        lag126 = values(126).astype(np.float32)
        # NumPy's float32 input loop is preserved even with a float64 output.
        mom = np.divide(lag21, lag126, out=np.full(len(ids), np.nan),
                        where=np.isfinite(lag21) & (lag126 > 0)) - 1
        recent = current / lag21 - 1
        fsum, fsq, count = sums[:, 0]-sums[:, 3], sums[:, 1]-sums[:, 4], sums[:, 2]-sums[:, 5]
        var = (fsq-fsum*fsum/np.maximum(count, 1))/np.maximum(count-1, 1)
        vol = np.sqrt(np.maximum(var, 0))*np.sqrt(252)
        scores = np.log1p(mom)/vol

    dv = np.nan_to_num(values(0, "raw_closes")*values(0, "volumes"),
                       nan=0., posinf=0., neginf=0.)
    old_dv = np.nan_to_num(values(20, "raw_closes")*values(20, "volumes"),
                           nan=0., posinf=0., neginf=0.).astype(np.float32)
    sums[:, 6] -= old_dv
    sums[:, 6] += dv
    state["sums"] = {sid: row.tolist() for sid, row in zip(ids, sums)}
    state["last_index"] = idx
    result = []
    for i, sid in enumerate(ids):
        bar, meta = by_id.get(sid), effective.get(sid)
        if bar is None or meta is None:
            continue
        eligible = bool(
            meta.first_session is not None and meta.first_session <= bar.session
            and is_common_equity(meta.category) and sums[i, 2] >= 126
            and bar.raw_close is not None and bar.raw_close >= 1
            and idx >= 19 and sums[i, 6]/20 >= 20_000_000
            and dv[i] >= 5_000_000 and np.isfinite(mom[i])
            and np.isfinite(recent[i]) and np.isfinite(scores[i]) and vol[i] > 0)
        result.append(SecurityBar(
            sid, bar.ticker, f"SID:{sid}", feed.series[sid].signal_window(),
            bar.raw_close, eligible, "" if eligible else "MEDIAN5_INELIGIBLE",
            tuple(float(x) for x in (mom[i], recent[i], vol[i], scores[i]))
            if eligible else None))
    return result


def rank(scored, state):
    """Advance history before freshness, reservations, or vacancy checks."""
    durable = sorted((s for s in scored if s.in_top_decile and s.score is not None),
                     key=lambda s: (-s.score, s.security_id, s.ticker))
    order = [s.security_id for s in durable]
    history = (state["rank_history"] + [order])[-5:]
    state["rank_history"] = history
    positions = [{sid: i for i, sid in enumerate(day)} for day in history]
    front = sorted(durable[:3], key=lambda s: (
        median([p.get(s.security_id, len(day)+1000)
                for p, day in zip(positions, history)]), order.index(s.security_id)))
    return [s for s in front + durable[3:] if s.recent is not None and s.recent >= 0]
