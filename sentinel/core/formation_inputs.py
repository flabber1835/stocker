"""Current-information startup inputs from one admitted Sharadar generation."""
from sentinel.core.loader import CorpusWindow
from sentinel.core.rolling_inputs import SnapshotReferences, _mapped_bars, fresh_anchors
from sentinel.core.session import DefensiveBar, PublishedSession
from sentinel.feed import rolling_store
from sentinel.feed.rolling_contract import FormationWindow, digest


class FormationInputs:
    def __init__(self, conn, binding, publication):
        self.conn, self.binding, self.publication = conn, binding, publication
        self.refs = SnapshotReferences(conn, candidate_id=binding['candidate_id'], snapshot_id=binding['snapshot_id'])
        if not isinstance(self.refs.manifest.window, FormationWindow):
            raise ValueError('FORMATION_STARTUP_WINDOW_REQUIRED')
        rolling_store.verify_content(conn, binding['candidate_id'])
        self.axis = [str(s) for s in self.refs.manifest.window.sessions]
        self.benchmarks = tuple(rolling_store.read_benchmarks(conn, binding['candidate_id']))
        if [str(b.session) for b in self.benchmarks] != self.axis:
            raise ValueError('FORMATION_BENCHMARK_COVERAGE_CHANGED')
        self.terminals = self.refs.terminals(start=self.axis[0], end=self.axis[-1]).events

    def plan(self, *, capital, strategy):
        from sentinel.core.formation import FormationPlan
        from sentinel.formed_origin import POLICY
        return FormationPlan(end=self.axis[-2], capital=str(capital), strategy=strategy,
            source_sha256=digest(dict(snapshot=self.binding, publication=self.publication.to_dict())),
            metadata_policy=POLICY)

    def bars(self, start, end, meta):
        return _mapped_bars(self.conn, self.binding['candidate_id'], self.refs, meta, start, end)

    def warmup(self):
        axis = self.axis[:252]
        meta, _ = self.refs.current_metadata(session=axis[-1])
        grouped = {}
        for bar in self.bars(axis[0], axis[-1], meta):
            grouped.setdefault(bar.session, []).append(bar)
        if sorted(grouped) != axis:
            raise ValueError('FORMATION_PRICE_COVERAGE_CHANGED')
        window = CorpusWindow(axis, grouped, meta)
        window.median5_spy_closes = {str(b.session): b.spy_total_return for b in self.benchmarks[:252]}
        window.median5_terminals = {}
        for event in self.terminals:
            if event.session in axis:
                window.median5_terminals.setdefault(event.session, set()).add(event.security_id)
        return window

    def session(self, day, state):
        index = self.axis.index(day)
        if index < 252:
            raise ValueError('FORMATION_SESSION_BEFORE_FEATURE_WARMUP')
        meta, sectors = self.refs.current_metadata(session=day)
        bars = tuple(self.bars(day, day, meta))
        if not bars:
            raise ValueError('FORMATION_EMPTY_SESSION')
        benchmarks = self.benchmarks[max(0, index - 253):index + 1]
        def defensive(b):
            return DefensiveBar(str(b.session), 'SENTINEL:BIL', 'BIL', b.bil_open_signal,
                                b.bil_close_signal, b.bil_close_adjusted, b.bil_close_unadjusted)
        spy_axis = tuple(str(b.session) for b in benchmarks)
        return PublishedSession(session=day, data_version=self.publication.version, bars=bars,
            meta=meta, sectors=sectors, spy_closeadj=tuple(b.spy_total_return for b in benchmarks),
            spy_sessions=spy_axis, spy_expected_sessions=spy_axis,
            defensive_bar=defensive(benchmarks[-1]), defensive_previous_bar=defensive(benchmarks[-2]),
            terminal_events=tuple(e for e in self.terminals if e.session == day),
            spinoff_distributions=self.refs.distributions(session=day),
            feed_anchors=fresh_anchors(bars, meta, state.feed['series']),
            history_proof=self.publication.evidence['strategy_history'])
