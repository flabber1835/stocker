"""Pure current-window material and its canonical feed installation."""
from __future__ import annotations
from array import array
from collections import deque
from typing import Literal
from pydantic import ConfigDict, Field
from stock_strategy_shared.wealth_core.engine import SecurityBar
from stock_strategy_shared.wealth_core.feed import FeedError, SecuritySeries
from stock_strategy_shared.wealth_core.window_signals import feature
from sentinel.feed import calendar
from sentinel.feed.rolling_contract import CanonicalBar, Contract, Digest, digest
from sentinel.core.input_domains import _vendor
from sentinel.core.session import _path_dependent_security_ids


class Signal(Contract):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)
    security_id: str
    ticker: str
    issuer_id: str
    closes: tuple[float | None, ...] = Field(max_length=127)
    raw_close: float | None
    eligible: bool
    eligibility_reason: str
    certified_signals: tuple[float, float, float, float] | None

    @classmethod
    def from_feature(cls, bar):
        return cls(security_id=bar.security_id, ticker=bar.ticker,
            issuer_id=bar.issuer_id, closes=tuple(bar.closes[-1:]),
            raw_close=bar.raw_close, eligible=bar.eligible,
            eligibility_reason=bar.eligibility_reason,
            certified_signals=bar.certified_signals)

    def bar(self, multiplier=1.):
        return SecurityBar(self.security_id, self.ticker, self.issuer_id,
            tuple(None if c is None else c*multiplier for c in self.closes),
            self.raw_close, self.eligible, self.eligibility_reason, self.certified_signals)



class WindowFeatures(Contract):
    schema_id: Literal['sentinel.current-window-features/1'] = Field(
        default='sentinel.current-window-features/1', alias='schema')
    snapshot_sha256: Digest
    prior_state_sha256: Digest
    publication_version: int = Field(gt=0)
    sessions: tuple[str, ...] = Field(min_length=300, max_length=300)
    signals: tuple[Signal, ...]
    histories: dict[str, tuple[CanonicalBar, ...]]

    @property
    def sha256(self):
        return digest(self.model_dump(mode='json', by_alias=True))



def protected(prior):
    ids = _path_dependent_security_ids(prior.wealth_core, prior.pending)
    ids.update((prior.median5 or {}).get('selected', ()))
    return ids


class _SignalTail:
    def __init__(self):
        self.indices = array('H')
        self.closes = array('d')
        self.liquidity = deque(maxlen=20)
        self.final_ticker = None


def compile_rows(*, prior, manifest, metadata, resolve_identity,
                 publication_version, session, rows):
    """Interpret a complete stream with ascending dates per security."""
    from sentinel.feed.rolling_contract import CurrentFormationWindow
    axis = calendar.previous_sessions(session, 300)
    available = list(map(str, manifest.window.sessions))
    if (axis != available and not (isinstance(manifest.window, CurrentFormationWindow)
                                   and set(axis).issubset(available))):
        raise ValueError('CURRENT_WINDOW_AXIS_REQUIRED')
    indices = {day:i for i, day in enumerate(axis)}
    latest_index = len(axis) - 1
    history_start = latest_index - 260
    live = protected(prior)
    signals, histories = [], {sid:[] for sid in live}
    tails = {}
    for row in rows:
        day, sid = str(row.session), row.security_id
        index = indices.get(day)
        if index is None or resolve_identity(row.ticker, day) != sid or sid not in metadata:
            raise ValueError('CURRENT_WINDOW_IDENTITY_OR_AXIS_CHANGED')
        if row.close_signal is None:
            raise FeedError('Median-5 requires a published signal-domain close')
        tail = tails.get(sid)
        if tail is None:
            tail = tails[sid] = _SignalTail()
        if tail.indices and index <= tail.indices[-1]:
            raise ValueError('CURRENT_WINDOW_PRICE_ORDER_CHANGED')
        tail.indices.append(index)
        tail.closes.append(row.close_signal)
        tail.liquidity.append((row.close_unadjusted, row.volume))
        if sid in live and history_start <= index < latest_index:
            histories[sid].append(row)
        if index == latest_index:
            tail.final_ticker = row.ticker
    for sid in sorted(tails):
        tail = tails[sid]
        if tail.final_ticker is None:
            continue
        raw_closes, volumes = map(list, zip(*tail.liquidity))
        series = SecuritySeries(sid, tail.final_ticker, f'SID:{sid}',
            session_indices=list(tail.indices[-127:]), signal_closes=list(tail.closes[-127:]),
            raw_closes=raw_closes, volumes=volumes)
        signals.append(Signal.from_feature(feature(
            series, metadata[sid], index=latest_index, session=session)))
    return WindowFeatures(snapshot_sha256=manifest.snapshot_id,
        prior_state_sha256=prior.state_hash, publication_version=publication_version,
        sessions=tuple(axis), signals=tuple(signals), histories=histories)


def install(feed, *, prior, published):
    """Refresh input state only; never reconstruct prior ownership or decisions."""
    from stock_strategy_shared.wealth_core.feed import FeedError
    material = WindowFeatures.model_validate(published.window_features)
    if (material.prior_state_sha256 != prior.state_hash
            or material.publication_version != published.data_version
            or material.sessions[-1] != published.session
            or list(material.sessions) != calendar.previous_sessions(published.session, 300)):
        raise FeedError('CURRENT_WINDOW_STATE_OR_SESSION_BINDING_CHANGED')
    if prior.last_processed_session:
        proof = published.history_proof or {}
        if (proof.get('features_sha256') != material.sha256
                or proof.get('snapshot_sha256') != material.snapshot_sha256):
            raise FeedError('CURRENT_WINDOW_FEATURE_PROOF_CHANGED')
    live = protected(prior)
    if set(material.histories) != live:
        raise FeedError('CURRENT_WINDOW_LIVE_DEPENDENCIES_CHANGED')
    index = feed._session_index + 1
    indices = {day:index-299+i for i, day in enumerate(material.sessions)}
    refreshed = {}
    for sid in sorted(live):
        previous = feed.series.get(sid)
        if previous is None:
            raise FeedError('CURRENT_WINDOW_OWNED_ANCHOR_MISSING: '+sid)
        previous.reconcile_signal_basis(published.signal_basis_anchors.get(sid))
        series = SecuritySeries(sid, previous.ticker, previous.issuer_id,
            signal_basis_multiplier=previous.signal_basis_multiplier)
        last = None
        for row in material.histories[sid]:
            day = str(row.session)
            if (row.security_id != sid or day not in indices or day >= published.session
                    or (last is not None and day <= last)):
                raise FeedError('CURRENT_WINDOW_LIVE_HISTORY_CHANGED')
            series.append(_vendor(row), indices[day], published_signal=True)
            last = day
        # A history gap never erases a retained economic anchor.
        if not series.sessions:
            series.split_factor = previous.split_factor
            series.signal_basis_anchor = previous.signal_basis_anchor
        refreshed[sid] = series
    feed.series = refreshed
    feed._seen_sessions = {day:ix for day, ix in indices.items() if day < published.session}
    feed._last_session = material.sessions[-2]
    bars = {bar.security_id:bar for bar in published.bars}
    if (len(bars) != len(published.bars) or len({s.security_id for s in material.signals}) != len(material.signals)
            or {s.security_id for s in material.signals} != set(bars)):
        raise FeedError('CURRENT_WINDOW_FEATURE_KEYS_CHANGED')
    signals = {}
    for signal in material.signals:
        bar = bars[signal.security_id]
        if (signal.ticker != bar.ticker or signal.raw_close != bar.raw_close
                or not signal.closes or signal.closes[-1] != bar.signal_close):
            raise FeedError('CURRENT_WINDOW_FEATURE_PRICE_CHANGED')
        multiplier = refreshed[signal.security_id].signal_basis_multiplier if signal.security_id in refreshed else 1.
        signals[signal.security_id] = signal.bar(multiplier)
        if signal.security_id not in refreshed:
            refreshed[signal.security_id] = SecuritySeries(
                signal.security_id, signal.ticker, signal.issuer_id)
    feed.snapshot_security_bars = signals
    return feed
