"""Research policies composed with the canonical Wealth Core book and signals."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from stock_strategy_shared.wealth_core.eligibility import is_common_equity
from stock_strategy_shared.wealth_core.feed import to_daily_bar
from stock_strategy_shared.wealth_core.signals import (
    annualized_formation_volatility, durable_score, medium_term_momentum,
    recent_return)
from stock_strategy_shared.wealth_core.state import PortfolioState

WINDOW = 300
VARIANTS = ('baseline', 'snapshot', 'rolling300', 'account300')


def positive(value):
    return value is not None and math.isfinite(value) and value > 0


class Correction(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', allow_inf_nan=False)
    security_id: str = Field(min_length=1)
    session: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    signal_close: float = Field(gt=0)
    raw_close: float = Field(gt=0)
    volume: float = Field(ge=0)


def apply_corrections(feed, rows):
    """Replace window facts atomically; never apply economic events again.

    This seam accepts same-basis corrections only. Basis transformations are
    explicit via rebase(), not guessed from a revised last-close anchor.
    """
    planned, seen = [], set()
    lower = feed._session_index - WINDOW + 1
    for item in rows:
        row = item if isinstance(item, Correction) else Correction.model_validate(item)
        key = (row.security_id, row.session)
        if key in seen:
            raise ValueError('duplicate correction')
        seen.add(key)
        series = feed.series.get(row.security_id)
        if series is None or row.session not in series.sessions:
            raise ValueError('correction outside retained snapshot')
        pos = series.sessions.index(row.session)
        if not lower <= series.session_indices[pos] <= feed._session_index:
            raise ValueError('correction outside 300-session window')
        planned.append((series, pos, row))
    for series, pos, row in planned:
        series.signal_closes[pos] = row.signal_close
        series.raw_closes[pos] = row.raw_close
        series.volumes[pos] = row.volume


def snapshot_bars(feed, bars):
    """Recompute from current facts; no historical floating-point accumulator."""
    result = []
    for bar in bars:
        series = feed.series[bar.security_id]
        closes = series.signal_window(127)
        meta = feed.meta.get(bar.security_id)
        contiguous = (len(series.session_indices) >= 127
                      and series.session_indices[-127:] == list(range(feed._session_index-126, feed._session_index+1)))
        valid = contiguous and all(positive(c) for c in closes)
        mom = medium_term_momentum(closes) if valid else None
        recent = recent_return(closes) if valid else None
        vol = annualized_formation_volatility(closes) if valid else None
        score = durable_score(mom, vol)
        dollar = [c*v if positive(c) and v is not None and math.isfinite(v) and v >= 0 else None
                  for c, v in zip(series.raw_closes[-20:], series.volumes[-20:])]
        eligible = bool(valid and meta is not None and is_common_equity(meta.category)
                        and meta.first_session is not None and meta.first_session <= series.sessions[-1]
                        and (meta.last_session is None or meta.last_session >= series.sessions[-1])
                        and positive(bar.raw_close) and bar.raw_close >= 1
                        and len(dollar) == 20 and all(d is not None for d in dollar)
                        and sum(dollar)/20 >= 20_000_000 and dollar[-1] >= 5_000_000
                        and score is not None and recent is not None)
        facts_available = (valid and positive(bar.raw_close) and meta is not None
                           and len(dollar)==20 and all(d is not None for d in dollar))
        result.append(replace(bar, closes=closes, eligible=eligible,
                              eligibility_reason=('' if eligible else 'SNAPSHOT_INELIGIBLE'
                                                  if facts_available else 'SNAPSHOT_INPUT_UNAVAILABLE'),
                              certified_signals=(mom, recent, vol, score) if eligible else None))
    return result


def trim(feed):
    lower = feed._session_index - WINDOW + 1
    for series in feed.series.values():
        first = next((i for i, ix in enumerate(series.session_indices) if ix >= lower), len(series.session_indices))
        for name in ('sessions', 'session_indices', 'signal_closes', 'raw_closes', 'volumes'):
            setattr(series, name, getattr(series, name)[first:])
    feed._seen_sessions = {s:i for s,i in feed._seen_sessions.items() if i >= lower}


class RollingState(PortfolioState):
    """Only changes the stop reference; all ownership/accounting is inherited."""
    def initialize_research(self, history=None):
        self.owned_closes = history or {}
        return self

    def age_one_session(self, signal_closes, **kwargs):
        # Actions occur before age_one_session. Translate retained observations
        # by the same reference multiplier the canonical action applied to peak.
        for slot, episode in self.episodes.items():
            key = str(slot)
            prior = self.owned_closes.get(key)
            if prior is not None and prior['entry_date'] != episode.entry_date:
                prior = None
            if prior is None:
                prior = dict(entry_date=episode.entry_date, observations=[], peak=None)
            old_peak, new_peak = prior['peak'], episode.episode_peak_split_adjusted_close
            factor = new_peak/old_peak if positive(old_peak) and positive(new_peak) else 1.
            lower = self.session_index - WINDOW + 1
            rows = [[i, c*factor] for i,c in prior['observations'] if i >= lower]
            current = signal_closes.get(episode.security_id)
            if positive(current):
                rows.append([self.session_index, current])
            peak = max((c for _,c in rows), default=None)
            episode.episode_peak_split_adjusted_close = peak
            self.owned_closes[key] = dict(entry_date=episode.entry_date, observations=rows, peak=peak)
        super().age_one_session(signal_closes, **kwargs)

    def remember_entries(self, day):
        # Newly filled episodes bypass age_one_session by canonical design.
        for slot, episode in self.episodes.items():
            if episode.entry_date == day:
                peak = episode.episode_peak_split_adjusted_close
                self.owned_closes[str(slot)] = dict(entry_date=day,
                    observations=[[self.session_index-1, peak]] if positive(peak) else [], peak=peak)
        self.owned_closes = {k:v for k,v in self.owned_closes.items() if int(k) in self.episodes}


def rebase(feed, state, security_id, factor):
    if not positive(factor):
        raise ValueError('signal rebase must be finite and positive')
    series = feed.series[security_id]
    series.signal_closes = [c*factor if c is not None else None for c in series.signal_closes]
    series.signal_basis_multiplier *= factor
    series.split_factor *= factor
    if series.signal_basis_anchor:
        series.signal_basis_anchor[2] *= factor
    for episode in state.episodes.values():
        if episode.security_id == security_id:
            episode.entry_split_adjusted_price *= factor
            if episode.episode_peak_split_adjusted_close is not None:
                episode.episode_peak_split_adjusted_close *= factor
    # RollingState translates its own observations at the next canonical age.
