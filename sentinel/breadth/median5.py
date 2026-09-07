"""Causal residual-correlation breadth for the certified Median-5 profile."""
from __future__ import annotations

import numpy as np

from stock_strategy_shared.wealth_core.median5 import at
from sentinel.breadth.classifier import (
    Holding, HoldingLabel, SessionBreadth, is_green, is_red)


def _finite(value):
    return value is not None and np.isfinite(value)


def _residuals(series, index, market):
    keys, asset, spy = [], [], []
    for day in range(max(1, index-252), index):
        left, right = at(series, day-1), at(series, day)
        mv = market.get(day)
        if (not _finite(left) or left <= 0 or not _finite(right) or right <= 0
                or not _finite(mv)):
            continue
        keys.append(day)
        asset.append(float(np.float32(right))/float(np.float32(left))-1.)
        spy.append(float(mv))
    if len(keys) < 120:
        return {}
    a, m = np.asarray(asset, float), np.asarray(spy, float)
    da, dm = a-float(a.mean()), m-float(m.mean())
    denominator = float(np.dot(dm, dm))
    if not np.isfinite(denominator) or denominator <= 0:
        return {}
    beta = float(np.dot(da, dm)/denominator)
    return {day: float(x-beta*y) for day, x, y in zip(keys, a, m)}


def _correlation(left, right):
    common = sorted(set(left) & set(right))
    if len(common) < 120:
        return None
    a, b = np.asarray([left[k] for k in common]), np.asarray([right[k] for k in common])
    da, db = a-float(a.mean()), b-float(b.mean())
    denominator = float(np.sqrt(np.dot(da, da)*np.dot(db, db)))
    if not np.isfinite(denominator) or denominator <= 0:
        return None
    result = float(np.dot(da, db)/denominator)
    return result if np.isfinite(result) else None


def breadth(state, feed, spy_history, meta):
    market = {int(row[0]): row[2] for row in spy_history}
    index = feed._session_index
    held, identities, residuals = [], [], []
    for slot in sorted(state.episodes):
        ep = state.episodes[slot]
        series = feed.series.get(ep.security_id)
        close, peak = at(series, index), ep.episode_peak_split_adjusted_close
        own = close/peak-1 if _finite(close) and _finite(peak) and peak > 0 else None
        def ret(lag):
            previous = at(series, index-lag)
            return float(np.float64(close)/np.float32(previous)-1) if _finite(close) and _finite(previous) and previous > 0 else None
        held.append(Holding(ep.ticker, None, own, ret(21), ret(63), ep.market_sessions_held))
        item = meta.get(ep.security_id)
        identities.append((item.ticker if item else ep.ticker,
                           item.first_session or "" if item else "", ep.security_id))
        residuals.append(_residuals(series, index, market))
    greens, reds = [is_green(h) for h in held], [is_red(h) for h in held]
    labels = []
    for i, h in enumerate(held):
        scores = []
        for j, other in enumerate(residuals):
            if i == j:
                continue
            c = _correlation(residuals[i], other)
            if c is not None and c >= 0.145:
                scores.append((c, identities[j], j))
        scores.sort(key=lambda row: (-row[0], row[1]))
        neighbors = [i] + [row[2] for row in scores[:3]]
        stress = sum(reds[j] for j in neighbors)/len(neighbors)
        individual = (_finite(h.own_dd) and h.own_dd <= -0.10) or (_finite(h.r21) and h.r21 <= -0.03)
        amber = bool(individual or (stress >= 0.5 and not greens[i]))
        labels.append(HoldingLabel(h.ticker, None, greens[i], reds[i], amber, stress))
    n, ng, na = len(held), sum(greens), sum(h.amber for h in labels)
    return SessionBreadth(na/n if n else 0., ng/n if n else 0., n, ng, na,
                          sum(reds), tuple(labels)), held
