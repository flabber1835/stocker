"""Stateless current-window feature formulas; ownership stays in the canonical book."""
from __future__ import annotations

import math

from .eligibility import is_common_equity
from .engine import SecurityBar
from .signals import (
    annualized_formation_volatility, durable_score, medium_term_momentum, recent_return)


def positive(value):
    return value is not None and math.isfinite(value) and value > 0


def feature(series, meta, *, index, session):
    closes = series.signal_window(127)
    contiguous = (len(series.session_indices) >= 127
                  and series.session_indices[-127:] == list(range(index-126, index+1)))
    valid = contiguous and all(positive(c) for c in closes)
    mom = medium_term_momentum(closes) if valid else None
    recent = recent_return(closes) if valid else None
    vol = annualized_formation_volatility(closes) if valid else None
    score = durable_score(mom, vol)
    dollars = [c*v if positive(c) and v is not None and math.isfinite(v) and v >= 0 else None
               for c, v in zip(series.raw_closes[-20:], series.volumes[-20:])]
    raw = series.raw_closes[-1]
    facts = valid and positive(raw) and len(dollars)==20 and all(d is not None for d in dollars)
    eligible = bool(facts and is_common_equity(meta.category)
        and meta.first_session is not None and meta.first_session <= session
        and (meta.last_session is None or meta.last_session >= session)
        and raw >= 1 and sum(dollars)/20 >= 20_000_000 and dollars[-1] >= 5_000_000
        and score is not None and recent is not None)
    return SecurityBar(series.security_id, series.ticker, f'SID:{series.security_id}',
        closes, raw, eligible,
        '' if eligible else 'SNAPSHOT_INELIGIBLE' if facts else 'SNAPSHOT_INPUT_UNAVAILABLE',
        (mom, recent, vol, score) if eligible else None)
