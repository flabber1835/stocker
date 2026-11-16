"""Bounded historical transport into unchanged production compilers and kernel."""
from collections import deque
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from typing import NamedTuple
from unittest.mock import patch

from sentinel.core.cash_distributions import Inputs as CashInputs
from sentinel.core.history import CurrentWindowProof, FormationWindowProof
from sentinel.core.session import PublishedSession
from sentinel.core.window_material import compile_rows, protected
from sentinel.feed.calendar import previous_sessions
from sentinel.feed.rolling_contract import CanonicalBar, digest
from stock_strategy_shared.wealth_core.feed import VendorBar


class Row(NamedTuple):
    security_id: str
    session: str
    ticker: str
    close_signal: float | None
    close_unadjusted: float
    open_unadjusted: float | None
    volume: float | None
    split_ratio: float
    dividend_per_share: float
    tradeable: bool

    def canonical(self):
        return CanonicalBar(**{k:v for k,v in self._asdict().items() if k != 'tradeable'})

    def vendor(self):
        return VendorBar(self.session, self.security_id, self.ticker,
            self.close_unadjusted, self.open_unadjusted, self.volume,
            split_ratio=self.split_ratio, dividend_per_share=self.dividend_per_share,
            tradeable=self.tradeable, signal_close=self.close_signal)


class Buffer:
    def __init__(self, source_identity):
        self.axis, self.spy = deque(), deque()
        self.rows, self.aliases, self.metadata, self.sectors = {}, {}, {}, {}
        self.current = None
        self.source_identity = source_identity

    def append(self, packet):
        if self.axis and previous_sessions(packet.day, 2)[0] != self.axis[-1]:
            raise ValueError('nonadjacent input session')
        self.axis.append(packet.day)
        self.spy.append(float(packet.spy))
        if len(self.axis) > 300:
            old = self.axis.popleft()
            self.spy.popleft()
            del self.aliases[old]
        lower = self.axis[0]
        for sid in list(self.rows):
            ring = self.rows[sid]
            while ring and ring[0].session < lower:
                ring.popleft()
            if not ring:
                del self.rows[sid]
                self.metadata.pop(sid, None)
                self.sectors.pop(sid, None)
        aliases = {}
        seen = set()
        for bar in packet.bars:
            if bar.session != packet.day or bar.security_id in seen or bar.ticker in aliases:
                raise ValueError('input identity or session changed')
            seen.add(bar.security_id)
            aliases[bar.ticker] = bar.security_id
            # Validate once at ingestion. Compact immutable transport avoids
            # retaining millions of Pydantic bookkeeping sets, not validation.
            canonical = CanonicalBar(security_id=bar.security_id, session=date.fromisoformat(packet.day),
                ticker=bar.ticker, close_signal=bar.signal_close, close_unadjusted=bar.raw_close,
                open_unadjusted=bar.raw_open, volume=bar.volume, split_ratio=bar.split_ratio,
                dividend_per_share=bar.dividend_per_share)
            row = Row(canonical.security_id, packet.day, canonical.ticker,
                canonical.close_signal, canonical.close_unadjusted, canonical.open_unadjusted,
                canonical.volume, canonical.split_ratio, canonical.dividend_per_share, bar.tradeable)
            self.rows.setdefault(bar.security_id, deque()).append(row)
        self.aliases[packet.day] = aliases
        self.metadata.update(packet.meta)
        self.sectors.update(packet.sectors)
        self.current = packet

    def prepare(self, prior, version, *, formation=False):
        axis = list(self.axis)
        if axis != previous_sessions(axis[-1], 300):
            raise ValueError('exact current 300-session axis required')
        live = protected(prior)
        snapshot = digest(dict(source=self.source_identity, session=axis[-1]))
        def stream():
            for sid in sorted(self.rows):
                for row in self.rows[sid]:
                    # The production material model retains typed owned history.
                    yield row.canonical() if sid in live else row
        material = compile_rows(prior=prior,
            manifest=SimpleNamespace(snapshot_id=snapshot, window=SimpleNamespace(sessions=axis)),
            metadata=self.metadata, resolve_identity=lambda ticker, day:self.aliases[day].get(ticker),
            publication_version=version, session=axis[-1], rows=stream())
        anchors = {}
        for sid in live:
            anchor = prior.feed.get('series', {}).get(sid, {}).get('signal_basis_anchor')
            matches = [r for r in self.rows.get(sid, ()) if anchor and r.session == anchor[0]]
            if len(matches) != 1:
                raise ValueError('owned signal basis anchor missing: '+sid)
            anchors[sid] = matches[0].vendor()
        proof = None
        if prior.last_processed_session:
            proof_type = FormationWindowProof if formation else CurrentWindowProof
            proof = proof_type(prior_version=prior.data_version, publication_version=version,
                prior_session=prior.last_processed_session, session=axis[-1],
                prior_state_sha256=prior.state_hash, snapshot_sha256=snapshot,
                features_sha256=material.sha256,
                protected_economics_sha256=digest(dict(immutable_research_tape=self.source_identity))).model_dump(by_alias=True)
        packet = self.current
        cash = None if formation else CashInputs(prior_state_sha256=prior.state_hash,
            publication_version=version, session=packet.day, observations=[]).model_dump(mode='json', by_alias=True)
        return PublishedSession(session=packet.day, data_version=version, bars=packet.bars,
            meta=dict(self.metadata), sectors=dict(self.sectors), spy_closeadj=tuple(self.spy)[-254:],
            spy_sessions=tuple(axis[-254:]), spy_expected_sessions=tuple(axis[-254:]),
            terminal_events=packet.terminal, spinoff_distributions=packet.spins,
            signal_basis_anchors=anchors, history_proof=proof,
            window_features=material.model_dump(mode='json', by_alias=True), cash_distributions=cash)


class WarmupBars(Mapping):
    def __init__(self, buffer):
        self.buffer, self.axis = buffer, tuple(buffer.axis)

    def __iter__(self):
        return iter(self.axis)

    def __len__(self):
        return len(self.axis)

    def __getitem__(self, day):
        if day not in self.axis:
            raise KeyError(day)
        return tuple(row.vendor() for sid in sorted(self.buffer.rows)
                     for row in self.buffer.rows[sid] if row.session == day)


@contextmanager
def observe_core():
    """Capture existing audit results, without changing a production argument."""
    from stock_strategy_shared.wealth_core import live
    original, evidence = live.run_with_hashes, {}
    def observe(*args, **kwargs):
        result = original(*args, **kwargs)
        run, _ = result
        evidence.clear()
        evidence.update(counters=dict(run.settlement_counters), terminal_results=list(run.terminal_results),
                        fills=list(run.sessions[0].fills), cancelled=list(run.sessions[0].cancelled))
        return result
    with patch.object(live, 'run_with_hashes', observe):
        yield evidence
