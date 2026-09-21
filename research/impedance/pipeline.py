"""Synthetic prices through production warmup, Core and complete controller."""
from __future__ import annotations

import argparse
from dataclasses import replace
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
from types import SimpleNamespace

import numpy as np

from sentinel.controller.machine import Controller
from sentinel.core.kernel import advance_session
from sentinel.core.production import warm_session_state
from sentinel.core.session import PublishedSession, SessionState
from sentinel.feed.calendar import calendar_version, sessions_in_range
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar

from .pipeline_diagnostics import measure, probe_tuple
from .study import entry_probes

WARMUP, FORMATION, LENGTH, UNIVERSE = 252, 80, 120, 60
CASES = ('healthy', 'synchronized_shock', 'staggered_damage', 'gradual_decline',
         'temporary_correction', 'leadership_rotation', 'healthy_split')


def ordinary(t, i):
    return .0008 + .00001*(i % 7) + .0015*math.sin(.19*t) + .002*math.sin(.11*t + .6*i)


def market_ordinary(t):
    return .0004 + .0025*math.sin(.37*t) + .001*math.sin(.13*t)


def factors(case, day, sid, initially_held):
    equity = market = 1.
    if case == 'synchronized_shock' and day == 0:
        equity, market = .82, .92
    elif case == 'staggered_damage':
        group = set(sorted(initially_held)[:len(initially_held)*4//5])
        if day < 15 and sid in group:
            equity = .988
        if day == 15:
            equity, market = (.92 if sid in group else .82), .92
    elif case == 'gradual_decline' and day < 80:
        equity, market = .996, .998
    elif case == 'temporary_correction':
        if day == 0:
            equity, market = .86, .92
        elif day == 8:
            equity, market = 1/.86, 1/.92
    elif case == 'leadership_rotation':
        if day < 60:
            equity = .992 if sid in initially_held else 1.004
        elif sid in initially_held:
            equity = 1.004
    return equity, market


class Market:
    def __init__(self):
        self.sessions = sessions_in_range('2020-01-01', '2022-12-31')[:WARMUP+FORMATION+LENGTH]
        self.meta = {f'S{i:02d}': SecurityMeta(f'S{i:02d}', f'S{i:02d}', 'Domestic Common Stock',
                    f'S{i:02d}', first_session=self.sessions[0]) for i in range(UNIVERSE)}
        self.prices = {sid: 100.+i for i, sid in enumerate(self.meta)}
        self.spy = [100.]
        self.index = -1

    def advance(self, case='healthy', day=-1, initially_held=()):
        self.index += 1
        t = self.index
        session = self.sessions[t]
        bars = []
        split_sid = min(initially_held) if initially_held else None
        market_factor = factors(case, day, '', initially_held)[1]
        if case == 'staggered_damage' and day == 15:
            market_factor = .92
        self.spy.append(self.spy[-1]*(1+market_ordinary(t))*market_factor)
        for i, sid in enumerate(self.meta):
            equity_factor, _ = factors(case, day, sid, initially_held)
            gross = (1+ordinary(t, i))*equity_factor
            before = self.prices[sid]
            self.prices[sid] = before*gross
            split = case == 'healthy_split' and sid == split_sid and day >= 20
            units = 2 if split else 1
            bars.append(VendorBar(session, sid, sid, self.prices[sid]/units,
                before*math.sqrt(gross)/units, 1e6*units,
                split_ratio=2. if split and day == 20 else 1., signal_close=self.prices[sid]))
        start = max(0, t-40)
        dates = self.sessions[start:t+1]
        return PublishedSession(session=session, data_version=1, bars=bars, meta=self.meta,
            sectors={sid:'SYNTHETIC' for sid in self.meta},
            spy_sessions=dates, spy_expected_sessions=dates, spy_closeadj=self.spy[start+1:t+2])


def make_origin():
    config, identity = production_strategy()
    market = Market()
    warm = [market.advance() for _ in range(WARMUP)]
    window = SimpleNamespace(sessions=[p.session for p in warm],
        bars_by_session={p.session:p.bars for p in warm}, meta=market.meta,
        median5_spy_closes={p.session:market.spy[i+1] for i,p in enumerate(warm)},
        median5_terminals={})
    state = SessionState.fresh(starting_cash=100000., controller=Controller(config), strategy_identity=identity)
    state = warm_session_state(state, window, publication_version=1, prospective_concordance_witness=True)
    assert not state.wealth_core['episodes'] and not state.pending
    records = []
    labels = None
    for _ in range(FORMATION):
        p = market.advance()
        state = advance_session(state, p, controller_config=config, strategy_identity=identity)
        row = measure(state, p, labels)
        labels = row['labels']
        records.append(row)
    assert len(state.wealth_core['episodes']) == 20, 'Scenario must begin with production-formed twenty-slot ownership'
    return config, identity, state, market, records


def run_case(case, config, identity, origin, original_market, formation):
    import copy
    market = copy.deepcopy(original_market)
    state = SessionState.from_dict(json.loads(json.dumps(origin.to_dict())))
    held = {ep['security_id'] for ep in state.wealth_core['episodes'].values()}
    records, checks = [], []
    previous_labels = formation[-1]['labels']
    for day in range(LENGTH):
        p = market.advance(case, day, held)
        prior = state
        state = advance_session(prior, p, controller_config=config, strategy_identity=identity)
        if day in (0, 8, 20, 40, 60, 80, 119):
            restored = SessionState.from_dict(json.loads(json.dumps(prior.to_dict())))
            restored_next = advance_session(restored, p, controller_config=config, strategy_identity=identity)
            assert state.state_hash == restored_next.state_hash
            shuffled = advance_session(prior, replace(p, bars=tuple(reversed(p.bars))),
                                       controller_config=config, strategy_identity=identity)
            assert state.state_hash == shuffled.state_hash
            checks.append(day)
        before_diagnostic = state.state_hash if day in checks else None
        row = measure(state, p, previous_labels)
        if before_diagnostic is not None:
            assert before_diagnostic == state.state_hash
        row['day'] = day
        records.append(row)
        previous_labels = row['labels']
        if day % 40 == 0:
            print(f'{case}: {day+1}/{LENGTH} sessions', flush=True)
    probes = entry_probes([probe_tuple(r) for r in formation+records])[len(formation):]
    for row, eligibility in zip(records, probes):
        row['alternative_entry_eligibility'] = eligibility
    def first(predicate):
        return next((r['day'] for r in records if predicate(r)), None)
    return {'checks':checks, 'summary':{
        'first_native_defense':first(lambda r:r['native_multiplier']==0.),
        'first_controlled_below_full':first(lambda r:r['core_multiplier']<1.),
        'days_below_full':sum(r['core_multiplier']<1. for r in records),
        'first_eligibility':{key:first(lambda r,k=key:r['alternative_entry_eligibility'][k]) for key in probes[0]},
        'max_core_drawdown':min(r['observation']['shadow_drawdown'] for r in records),
        'minimum_held':min(r['held'] for r in records),
        'maximum_cash_fraction':max(r['cash']/r['nav'] for r in records),
        'weak_core_releases':[r['day'] for r in records if 'FULL_RISK_CERTIFIED' in r['recovery_reason'] and r['observation']['shadow_r20']<=0],
        'ending_nav':records[-1]['nav']}, 'records':records}


def assert_split_neutral(healthy, split):
    assert len(healthy['records']) == len(split['records']) == LENGTH
    events = [e for row in split['records'] for e in row['events'] if e['event_type'] == 'SPLIT']
    assert len(events) == 1, 'The neutral control must actually execute its owned split'
    for a,b in zip(healthy['records'],split['records']):
        for key in ('nav','cash','stock_value','core_multiplier','native_multiplier','held',
                    'damaged_stock_fraction','implied_stock_target_at_close_marks'):
            assert math.isclose(a[key],b[key],rel_tol=1e-11,abs_tol=1e-8), (a['day'],key,a[key],b[key])
        assert a['labels'] == b['labels']
        assert a['observation'] == b['observation']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    config, identity, origin, market, formation = make_origin()
    print('Production warmup/formation completed; 20 positions, no manually seeded holdings.',flush=True)
    cases = {case:run_case(case,config,identity,origin,market,formation) for case in CASES}
    assert_split_neutral(cases['healthy'],cases['healthy_split'])
    root = Path(__file__).resolve().parents[2]
    files = ['research/impedance/pipeline.py','research/impedance/pipeline_diagnostics.py',
             'research/impedance/study.py','sentinel/core/kernel.py','sentinel/core/production.py',
             'sentinel/controller/champion_frozen.py','sentinel/controller/median5_breadth.py',
             'sentinel/controller/median5.py','sentinel/controller/champion.py',
             'shared/stock_strategy_shared/wealth_core/engine.py',
             'shared/stock_strategy_shared/wealth_core/adapter.py',
             'shared/stock_strategy_shared/wealth_core/median5.py',
             'shared/stock_strategy_shared/wealth_core/v5.py']
    report = {'schema':'sentinel.synthetic-pipeline-impedance/1',
        'scope':'Canonical in-memory market/book/controller investigation; not deployed ingestion or broker execution.',
        'runtime':{'python':platform.python_version(),'numpy':np.__version__,'calendar':calendar_version()},
        'strategy_identity':identity,'origin_state_hash':origin.state_hash,
        'dimensions':{'warmup':WARMUP,'formation':FORMATION,'per_case':LENGTH,'universe':UNIVERSE},
        'source_sha256':{p:hashlib.sha256((root/p).read_text(encoding='utf-8').encode()).hexdigest() for p in files},
        'formation':formation,'cases':cases,'split_neutral':True}
    raw = json.dumps(report,indent=2,allow_nan=False).encode()
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'pipeline-results.json.gz').write_bytes(gzip.compress(raw,mtime=0))
    summary = {case:data['summary'] for case,data in cases.items()}
    (args.output/'pipeline-summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
