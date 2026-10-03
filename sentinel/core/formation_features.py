"""Bounded price work reuse within one immutable formation generation."""
from array import array
from dataclasses import asdict
from math import isnan

from stock_strategy_shared.wealth_core.feed import SecuritySeries
from stock_strategy_shared.wealth_core.window_signals import feature
from sentinel.core.window_features import Signal, WindowFeatures, protected
from sentinel.feed import calendar, rolling_store, store
from sentinel.feed.rolling_contract import CanonicalBar

_FIELDS = ('close_signal', 'close_unadjusted', 'open_unadjusted', 'volume',
           'split_ratio', 'dividend_per_share')


def _value(value):
    return None if isnan(value) else value


class _Ring:
    def __init__(self):
        self.indices = array('i')
        self.tickers = []
        self.values = {field: array('d') for field in _FIELDS}

    def append(self, row, index):
        if self.indices and index <= self.indices[-1]:
            raise ValueError('FORMATION_PRICE_ORDER_CHANGED')
        if row.close_signal is None:
            raise ValueError('FORMATION_PUBLISHED_SIGNAL_MISSING')
        self.indices.append(index)
        self.tickers.append(row.ticker)
        for field in _FIELDS:
            value = getattr(row, field)
            self.values[field].append(float('nan') if value is None else value)

    def expire(self, lower):
        count = 0
        while count < len(self.indices) and self.indices[count] < lower:
            count += 1
        if count:
            del self.indices[:count]
            del self.tickers[:count]
            for values in self.values.values():
                del values[:count]

    def history(self, sid, axis, first, last):
        return tuple(CanonicalBar(security_id=sid, session=axis[index],
            ticker=self.tickers[offset], **{field: _value(values[offset])
            for field, values in self.values.items()})
            for offset, index in enumerate(self.indices) if first <= index < last)


class FormationFeatures:
    """Packed rings contain at most 300 sessions, never a future price."""
    def __init__(self, conn, *, refs, publication):
        self.conn, self.refs, self.publication = conn, refs, publication
        self.candidate_id = refs.candidate_id
        self.snapshot_id = refs.manifest.snapshot_id
        self.version = publication.version
        self.axis = tuple(map(str, refs.manifest.window.sessions))
        self.indices = {day: index for index, day in enumerate(self.axis)}
        self.rings = {}
        self.last = None
        self.rows_read = 0

    def load(self, *, prior, session):
        if (self.refs.candidate_id != self.candidate_id
                or self.refs.manifest.snapshot_id != self.snapshot_id
                or self.publication.version != self.version):
            raise ValueError('FORMATION_FEATURE_SOURCE_CHANGED')
        days = calendar.previous_sessions(session, 300)
        if not set(days).issubset(self.indices):
            raise ValueError('CURRENT_WINDOW_AXIS_REQUIRED')
        lower, current = self.indices[days[0]], self.indices[session]
        meta, _ = self.refs.current_metadata(session=session)
        if self.last is None or current not in (self.last, self.last + 1):
            self.rings.clear()
            self.last = None
        start = days[0] if self.last is None else self.axis[self.last + 1] if current > self.last else None
        for ring in self.rings.values():
            ring.expire(lower)
        if start is not None:
            columns = rolling_store.BAR_COLUMNS
            query = (f"SELECT {','.join(columns)} FROM sentinel_snapshot_bars WHERE candidate_id=%s "
                     'AND session BETWEEN %s AND %s ORDER BY session,security_id COLLATE "C"')
            with store.streaming_cursor(self.conn, query, (self.candidate_id, start, session)) as cursor:
                previous = None
                for encoded in cursor:
                    row = CanonicalBar.model_validate(dict(zip(columns, encoded)))
                    day, sid = str(row.session), row.security_id
                    key = (day, sid)
                    if (day not in days or sid not in meta
                            or self.refs.resolver.resolve(row.ticker, day) != sid
                            or (previous is not None and key <= previous)):
                        raise ValueError('CURRENT_WINDOW_IDENTITY_OR_AXIS_CHANGED')
                    previous = key
                    self.rings.setdefault(sid, _Ring()).append(row, self.indices[day])
                    self.rows_read += 1
        self.last = current
        live = protected(prior)
        signals, histories = [], {sid: () for sid in live}
        for sid in sorted(self.rings):
            ring = self.rings[sid]
            if not ring.indices:
                continue
            if sid not in meta:
                raise ValueError('CURRENT_WINDOW_IDENTITY_OR_AXIS_CHANGED')
            if sid in live:
                histories[sid] = ring.history(sid, self.axis, current - 260, current)
            if ring.indices[-1] != current:
                continue
            # The canonical formula consumes 127 closes and 20 liquidity rows.
            # Relative indices reproduce the uncached 300-session series exactly.
            series = SecuritySeries(sid, ring.tickers[-1], f'SID:{sid}',
                session_indices=[index-lower for index in ring.indices[-127:]],
                signal_closes=list(ring.values['close_signal'][-127:]),
                raw_closes=list(ring.values['close_unadjusted'][-20:]),
                volumes=[_value(value) for value in ring.values['volume'][-20:]])
            signals.append(Signal.model_validate(asdict(feature(
                series, meta[sid], index=299, session=session))))
        return WindowFeatures(snapshot_sha256=self.snapshot_id,
            prior_state_sha256=prior.state_hash, publication_version=self.version,
            sessions=tuple(days), signals=tuple(signals), histories=histories)
