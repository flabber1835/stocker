"""Current-information startup inputs from one admitted market-data generation."""
from sentinel.core.loader import CorpusWindow
from sentinel.core.rolling_inputs import SnapshotReferences, _mapped_bars, fresh_anchors
from sentinel.core.session import DefensiveBar, PublishedSession
from sentinel.feed import rolling_store
from sentinel.feed.rolling_contract import FormationWindow, CurrentFormationWindow, digest


def _benchmark_fields(benchmarks):
    """Single SPY/BIL transport shared by both formation input policies."""
    def defensive(b):
        return DefensiveBar(str(b.session), 'SENTINEL:BIL', 'BIL', b.bil_open_signal,
                            b.bil_close_signal, b.bil_close_adjusted, b.bil_close_unadjusted)
    axis = tuple(str(b.session) for b in benchmarks)
    return dict(spy_closeadj=tuple(b.spy_total_return for b in benchmarks),
        spy_sessions=axis, spy_expected_sessions=axis,
        defensive_bar=defensive(benchmarks[-1]), defensive_previous_bar=defensive(benchmarks[-2]))


class FormationInputs:
    def __init__(self, conn, binding, publication):
        self.conn, self.binding, self.publication = conn, binding, publication
        self.refs = SnapshotReferences(conn, candidate_id=binding['candidate_id'], snapshot_id=binding['snapshot_id'])
        if not isinstance(self.refs.manifest.window, FormationWindow):
            raise ValueError('FORMATION_STARTUP_WINDOW_REQUIRED')
        rolling_store.verify_content(conn, binding['candidate_id'])
        self.axis = [str(s) for s in self.refs.manifest.window.sessions]
        self.current_window = isinstance(self.refs.manifest.window, CurrentFormationWindow)
        if self.current_window and not self.refs.current_window:
            raise ValueError('CURRENT_WINDOW_PUBLICATION_REQUIRED')
        from sentinel.core.formation_features import FormationFeatures
        self.features = FormationFeatures(conn, refs=self.refs, publication=publication) if self.current_window else None
        self.warmup_sessions = 299 if self.current_window else 252
        self.benchmarks = tuple(rolling_store.read_benchmarks(conn, binding['candidate_id']))
        if [str(b.session) for b in self.benchmarks] != self.axis:
            raise ValueError('FORMATION_BENCHMARK_COVERAGE_CHANGED')
        self.terminals = self.refs.terminals(start=self.axis[0], end=self.axis[-1]).events

    def plan(self, *, capital, strategy):
        from sentinel.core.formation import FormationPlan
        from sentinel.formed_origin import POLICY
        from sentinel.core import window_policy
        if self.current_window != window_policy.formed(strategy):
            raise ValueError('FORMATION_SOURCE_POLICY_CHANGED')
        return FormationPlan(end=self.axis[-2], capital=str(capital), strategy=strategy,
            warmup_sessions=self.warmup_sessions,
            source_sha256=digest(dict(snapshot=self.binding, publication=self.publication.to_dict())),
            metadata_policy=POLICY)

    def bars(self, start, end, meta):
        return _mapped_bars(self.conn, self.binding['candidate_id'], self.refs, meta, start, end)

    def warmup(self):
        axis = self.axis[:self.warmup_sessions]
        meta, _ = self.refs.current_metadata(session=axis[-1])
        grouped = {}
        for bar in self.bars(axis[0], axis[-1], meta):
            grouped.setdefault(bar.session, []).append(bar)
        if sorted(grouped) != axis:
            raise ValueError('FORMATION_PRICE_COVERAGE_CHANGED')
        window = CorpusWindow(axis, grouped, meta)
        window.median5_spy_closes = {str(b.session): b.spy_total_return for b in self.benchmarks[:self.warmup_sessions]}
        window.median5_terminals = {}
        for event in self.terminals:
            if event.session in axis:
                window.median5_terminals.setdefault(event.session, set()).add(event.security_id)
        return window

    def session(self, day, state):
        index = self.axis.index(day)
        if index < self.warmup_sessions:
            raise ValueError('FORMATION_SESSION_BEFORE_FEATURE_WARMUP')
        if self.current_window:
            return self._window_session(day, state)
        meta, sectors = self.refs.current_metadata(session=day)
        bars = tuple(self.bars(day, day, meta))
        if not bars:
            raise ValueError('FORMATION_EMPTY_SESSION')
        benchmarks = self.benchmarks[max(0, index - 253):index + 1]
        return PublishedSession(session=day, data_version=self.publication.version, bars=bars,
            meta=meta, sectors=sectors, **_benchmark_fields(benchmarks),
            terminal_events=tuple(e for e in self.terminals if e.session == day),
            spinoff_distributions=self.refs.distributions(session=day),
            feed_anchors=fresh_anchors(bars, meta, state.feed['series']),
            history_proof=self.publication.evidence['strategy_history'])

    def _window_session(self, day, state):
        from sentinel.feed import calendar
        from sentinel.core import window_features
        from sentinel.core.history import FormationWindowProof
        from sentinel.core.rolling_reader import RollingPriceReader
        reader = RollingPriceReader(self.conn, candidate_id=self.refs.candidate_id,
                                    snapshot_id=self.refs.manifest.snapshot_id)
        anchors = {}
        lower = calendar.previous_sessions(day, 300)[0]
        for sid in window_features.protected(state):
            anchor = state.feed.get('series', {}).get(sid, {}).get('signal_basis_anchor')
            if not anchor or not lower <= anchor[0] < day:
                raise ValueError('FORMATION_LIVE_ANCHOR_MISSING: ' + sid)
            anchors[sid] = anchor[0]
        prices = reader.prices(session=day, spy_sessions=254, anchor_sessions=anchors)
        features = self.features.load(prior=state, session=day)
        meta, sectors = self.refs.current_metadata(session=day)
        proof = None
        if state.last_processed_session:
            proof = FormationWindowProof(prior_version=state.data_version,
                publication_version=self.publication.version, prior_session=state.last_processed_session,
                session=day, prior_state_sha256=state.state_hash,
                snapshot_sha256=self.refs.manifest.snapshot_id, features_sha256=features.sha256,
                protected_economics_sha256=digest({'immutable_snapshot': self.refs.manifest.snapshot_id}))
            proof = proof.model_dump(by_alias=True)
        return PublishedSession(session=day, data_version=self.publication.version, bars=prices.bars,
            meta=meta, sectors=sectors, **_benchmark_fields(prices.benchmarks),
            terminal_events=tuple(e for e in self.terminals if e.session == day),
            spinoff_distributions=self.refs.distributions(session=day),
            signal_basis_anchors=prices.signal_basis_anchors,
            window_features=features.model_dump(mode='json', by_alias=True), history_proof=proof)
