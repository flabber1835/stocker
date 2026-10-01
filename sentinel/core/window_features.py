"""Compact current-window inputs for the canonical transition, without a broker."""
from __future__ import annotations

from dataclasses import asdict
from itertools import groupby
from typing import Literal

from pydantic import ConfigDict, Field

from stock_strategy_shared.wealth_core.engine import SecurityBar
from stock_strategy_shared.wealth_core.feed import SecuritySeries
from stock_strategy_shared.wealth_core.window_signals import feature
from sentinel.feed import calendar, rolling_store, store
from sentinel.feed.rolling_contract import CanonicalBar, Contract, Digest, digest
from sentinel.core.rolling_reader import _vendor
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


def load(conn, *, prior, refs, publication, session=None):
    """One identity-ordered stream; retain 127 features plus live 260-row tails."""
    from sentinel.feed.rolling_contract import CurrentFormationWindow
    session = session or publication.window_end
    axis = calendar.previous_sessions(session, 300)
    available = list(map(str, refs.manifest.window.sessions))
    if (axis != available and not (isinstance(refs.manifest.window, CurrentFormationWindow)
                                   and set(axis).issubset(available))):
        raise ValueError('CURRENT_WINDOW_AXIS_REQUIRED')
    indices = {day:i for i, day in enumerate(axis)}
    live = protected(prior)
    signals, histories = [], {sid:[] for sid in live}
    meta, _ = refs.current_metadata(session=session)
    columns = rolling_store.BAR_COLUMNS
    query = (f"SELECT {','.join(columns)} FROM sentinel_snapshot_bars WHERE candidate_id=%s "
             'AND session BETWEEN %s AND %s '
             'ORDER BY security_id COLLATE "C",session')
    with store.streaming_cursor(conn, query, (refs.candidate_id, axis[0], axis[-1])) as cursor:
        rows = (CanonicalBar.model_validate(dict(zip(columns, row))) for row in cursor)
        for sid, group in groupby(rows, key=lambda row: row.security_id):
            series = None
            for row in group:
                day = str(row.session)
                if day not in indices or refs.resolver.resolve(row.ticker, day) != sid or sid not in meta:
                    raise ValueError('CURRENT_WINDOW_IDENTITY_OR_AXIS_CHANGED')
                if series is None:
                    series = SecuritySeries(sid, row.ticker, f'SID:{sid}')
                series.append(_vendor(row), indices[day], published_signal=True)
                if sid in live and axis[-261] <= day < axis[-1]:
                    histories[sid].append(row)
            if series is not None and series.sessions[-1] == axis[-1]:
                signals.append(Signal.model_validate(asdict(feature(
                    series, meta[sid], index=299, session=axis[-1]))))
    return WindowFeatures(snapshot_sha256=refs.manifest.snapshot_id,
        prior_state_sha256=prior.state_hash, publication_version=publication.version,
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
