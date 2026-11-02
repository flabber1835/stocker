"""Fail-closed research sensor gateway and journal-bound range certificate."""
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path

from full_system_benchmark import need
from full_system_core import hosted
from system_campaign_uncertainty_gate import certified_recovery
from system_campaign_uncertainty_input import require_no_financial_position
from system_campaign_uncertainty_math import Interval, RollingWitnessBounds, growth

SID = '941065113449292610'
DAY = '2019-10-22'
SCHEMA = 'research.leadership-uncertainty-certificate/1'
WATCH_SCHEMA = 'research.leadership-uncertainty-certificate-commitment/1'
DISCRETE = ('version', 'episode', 'latched', 'full_streak', 'recent_positive_streak',
            'previous_native', 'previous_desired', 'effective_native', 'champion_audit')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def discrete(state):
    need(all(k in state for k in DISCRETE), 'UNCERTAINTY_CHAMPION_STATE_REQUIRED')
    return {k: deepcopy(state[k]) for k in DISCRETE}


def return_material(state, closes, terminal_values, event_bounds):
    rows, returns = [], []
    for sid in state['selected']:
        before = state['selected_closes'][sid]
        now = event_bounds if sid == SID and event_bounds is not None else Interval.point(
            terminal_values[sid] if sid in terminal_values else closes[sid])
        need(type(before) is float and before > 0, 'UNCERTAINTY_ACTUAL_PRIOR_WITNESS_MARK')
        returns.append(now.div(Interval.point(before)).sub(Interval.point(1.)))
        rows.append(dict(security_id=sid, prior=before, current=now.pair()))
    return rows, growth(returns)


class SensorCertificate:
    def __init__(self, out, codec, native, source_hashes, *, seed=(), event_source=None):
        self.out, self.codec, self.native = Path(out), codec, native
        self.source_hashes = source_hashes
        self.event_source = deepcopy(event_source)
        self.seed = list(seed)
        self.math = None
        self.pending = None
        self.event_bounds = None
        self.event_basis = None
        self.material = None
        self.bounds = None
        self.rows = 0
        self.chain = digest(SCHEMA)
        self.last_session = None

    def __enter__(self):
        hosted()
        from sentinel.controller import terminal_returns, median5, champion_config
        from research.pooled_vacancy_funding import runtime, journal, backtest
        for name, expected in self.source_hashes.items():
            need(hashlib.sha256((Path('/variant') / name).read_bytes()).hexdigest() == expected,
                 'UNCERTAINTY_ACTUAL_SOURCE_CLOSURE')
        self.terminal_module, self.witness_module, self.recovery_module = terminal_returns, median5, champion_config
        self.runtime, self.journal, self.backtest = runtime, journal, backtest
        self.original_values, self.original_witness = terminal_returns.values, median5.witness
        self.original_recover, self.original_advance = champion_config.recover, runtime.advance
        self.original_append, self.original_relevant = journal.Journal.append, backtest.relevant
        self.stream = (self.out / 'uncertainty-certificate.jsonl').open('xb')
        for row in self.seed:
            raw = encoded(row) + b'\n'
            self.stream.write(raw)
            self.chain = row['chain_sha256']
            self.rows += 1
            self.math = RollingWitnessBounds.restore(row['math'])
            self.last_session = row['session']
        self.stream.flush();os.fsync(self.stream.fileno())
        terminal_returns.values, median5.witness = self.values, self.witness
        champion_config.recover, runtime.advance = self.recover, self.advance
        # Install a function descriptor, not an already-bound SensorCertificate
        # method: Journal instances must still supply their own first argument.
        def append(owner, name, record):
            return self.append(owner, name, record)
        journal.Journal.append, backtest.relevant = append, self.relevant
        return self

    def relevant(self, state, packet):
        original = self.original_relevant(state, packet)
        if packet.day != DAY:
            return original
        # Storage only: retain the actual complete pre-event controller state
        # even though the affected sensor name is absent from the cash book.
        return {**(original or dict(terminal=[], spinoff=[])),
                'research_uncertainty_sensor': dict(security_id=SID, contract='ALL_VALUES_18_TO_20')}

    def values(self, *, prior, published):
        self.event_bounds = None
        if published.session != DAY or SID not in prior.median5['selected']:
            return self.original_values(prior=prior, published=published)
        need(self.codec.objects, 'UNCERTAINTY_COMMITTED_INPUT_REQUIRED')
        require_no_financial_position(prior)
        terms = [t for t in published.terminal_events if t.security_id == SID]
        need(len(terms) == 1 and asdict(terms[0]) == asdict(replace(self.native, session=DAY))
             and terms[0].cash_per_share is None and not terms[0].completeness(0)[0],
             'UNCERTAINTY_EXACT_UNRESOLVED_SOURCE_TERM')
        anchor = prior.feed['series'][SID]['signal_basis_anchor']
        need(anchor[0] == prior.last_processed_session, 'UNCERTAINTY_EXACT_PRIOR_PRICE_BASIS')
        raw, signal = map(lambda x: Fraction(str(x)), anchor[1:])
        bars = [b for b in published.bars if b.security_id == SID]
        need(len(bars) <= 1 and (not bars or bars[0].session == DAY), 'UNCERTAINTY_SOURCE_BAR_IDENTITY')
        split = Fraction(str(bars[0].split_ratio)) if bars else Fraction(1)
        need(self.event_source is not None and self.event_source['session'] == DAY
             and self.event_source['security_id'] == SID
             and bool(bars) == self.event_source['source_quote_present']
             and split == Fraction(self.event_source['split_ratio']),
             'UNCERTAINTY_EXACT_FROZEN_EVENT_SPLIT_AND_QUOTE_PRESENCE')
        need(raw > 0 and signal > 0 and split > 0, 'UNCERTAINTY_POSITIVE_SIGNAL_PRICE_BASIS')
        bounds = Interval(float(18 * split * signal / raw), float(20 * split * signal / raw))
        bounds.normal_positive()
        # Preserve all other canonical terminal guards. Do not mutate the
        # publication, invent a complete term, or alter a cash/account input.
        other = replace(published, terminal_events=tuple(t for t in published.terminal_events if t.security_id != SID))
        result = self.original_values(prior=prior, published=other)
        need(SID not in result, 'UNCERTAINTY_NO_DUPLICATE_SENSOR_CONSIDERATION')
        result[SID] = bounds.lo  # A proof representative, explicitly not a price.
        self.event_bounds = bounds
        self.event_basis = dict(prior_session=prior.last_processed_session, raw_anchor=str(anchor[1]),
            signal_anchor=str(anchor[2]), split=str(split), source_term_sha256=digest(asdict(terms[0])),
            source_event_sha256=digest(self.event_source),
            signal_consideration_interval=bounds.pair())
        return result

    def witness(self, state, **kwargs):
        if self.math is None and kwargs['session'] != DAY:
            return self.original_witness(state, **kwargs)
        if self.math is None:
            need(self.event_bounds is not None, 'UNCERTAINTY_ACTUAL_SELECTED_EVENT_REQUIRED')
            self.math = RollingWitnessBounds(state['witness_nav'])
        need(self.pending is None, 'UNCERTAINTY_PREVIOUS_PROOF_MUST_BE_COMMITTED')
        material, factor = return_material(state, kwargs['closes'], kwargs.get('terminal_values') or {}, self.event_bounds)
        result, observed = self.original_witness(state, **kwargs)
        self.math.advance(factor, result['witness_nav'][-1])
        self.bounds = {f'recent_r{n}': self.math.period(n) for n in (20, 40)}
        for name, bound in self.bounds.items():
            need((bound is None) == (observed[name] is None)
                 and (bound is None or bound.contains(observed[name])), 'UNCERTAINTY_ACTUAL_RETURN_ENCLOSURE')
        self.material = dict(rows=material, factor=factor.pair(), observed=observed,
                             representative_nav=result['witness_nav'][-1])
        return result, observed

    def recover(self, **kwargs):
        if self.math is None:
            return self.original_recover(**kwargs)
        try:
            (state, decision), checks = certified_recovery(self.original_recover, kwargs, self.bounds)
        except ValueError as exc:
            diagnostic = dict(session=kwargs['state']['last_session'], failure=str(exc),
                before=discrete(kwargs['state']), material=self.material,
                intervals={k: v.pair() if v is not None else None for k, v in self.bounds.items()},
                scalar_inputs={k: kwargs[k] for k in ('native', 'wc_drawdown', 'spy_r20', 'wc_r20', 'recent_r20', 'recent_r40')},
                financial_session_committed=False)
            with (self.out / 'uncertainty-refusal.json').open('xb') as stream:
                stream.write(encoded(diagnostic) + b'\n');stream.flush();os.fsync(stream.fileno())
            raise
        self.pending = dict(schema=SCHEMA, session=kwargs['state']['last_session'],
            material=self.material, math=self.math.snapshot(),
            intervals={k: v.pair() if v is not None else None for k, v in self.bounds.items()},
            comparisons=checks, before=discrete(kwargs['state']), after=discrete(state), decision=decision,
            scalar_inputs={k: kwargs[k] for k in ('native', 'wc_drawdown', 'spy_r20', 'wc_r20', 'recent_r20', 'recent_r40')},
            representative_is_not_a_valuation=True, owned_position=False, pending_order=False)
        if self.pending['session'] == DAY:
            self.pending['event_basis'] = deepcopy(self.event_basis)
        return state, decision

    def advance(self, run, published):
        result = self.original_advance(run, published)
        if self.math is not None:
            need(self.pending is not None and self.pending['session'] == published.session,
                 'UNCERTAINTY_ACTUAL_RECOVERY_CALL_REQUIRED')
            self.pending.update(input_sha256=run.input_sha256,
                prior_state_sha256=run.state.state_hash, next_state_sha256=result.state.state_hash)
        return result

    def append(self, journal, name, record):
        if name in ('formation', 'daily') and record['session'] >= DAY:
            need(self.pending is not None and record['session'] == self.pending['session']
                 and record['state_sha256'] == self.pending['next_state_sha256']
                 and record['input_sha256'] == self.pending['input_sha256'], 'UNCERTAINTY_PROOF_EXACT_FINANCIAL_ROW')
            need(self.last_session is None or self.last_session < record['session'], 'UNCERTAINTY_STRICT_CERTIFICATE_AXIS')
            self.chain = digest(dict(previous=self.chain, record=self.pending))
            row = {**self.pending, 'chain_sha256': self.chain}
            self.stream.write(encoded(row) + b'\n');self.stream.flush();os.fsync(self.stream.fileno())
            self.original_append(journal, 'watch', dict(schema=WATCH_SCHEMA, session=record['session'],
                input_sha256=record['input_sha256'], next_state_sha256=record['state_sha256'],
                certificate_chain_sha256=self.chain))
            self.rows += 1
            self.last_session = record['session']
            self.pending = None
        return self.original_append(journal, name, record)

    def __exit__(self, *args):
        self.terminal_module.values, self.witness_module.witness = self.original_values, self.original_witness
        self.recovery_module.recover, self.runtime.advance = self.original_recover, self.original_advance
        self.journal.Journal.append, self.backtest.relevant = self.original_append, self.original_relevant
        self.stream.close()
        summary = dict(schema='research.leadership-uncertainty-capture/1', rows=self.rows,
            last_session=self.last_session, chain_sha256=self.chain, uncommitted_proof=self.pending,
            financial_success_not_inferred=True, representative_is_not_a_valuation=True)
        (self.out / 'uncertainty-capture.json').write_bytes(encoded(summary) + b'\n')
