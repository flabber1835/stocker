"""Predeclared parameter probes on one independent production Core stream."""
import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import platform

from sentinel.core.kernel import advance_session
from sentinel.core.session import SessionState
from research.impedance.account import Account, BILL, dec
from research.impedance.pipeline import CASES, LENGTH, make_origin
from research.impedance.pipeline_diagnostics import measure
from research.impedance.parameters import PRESETS, ProbeController, assert_baseline, production_constants

CUTS = (0, 4, 8, 19, 31, 41, 69, 119)


def run_case(case, origin):
    config, identity, state, original_market, formation = origin
    market = copy.deepcopy(original_market)
    state = SessionState.from_dict(state.to_dict())
    probes = {name: ProbeController(name) for name in PRESETS}
    for row in formation:
        for name, probe in probes.items():
            result = probe.step(row)
            if name == 'current':
                assert_baseline(row, result, probe)
    accounts = {name: Account() for name in PRESETS}
    initial_marks = {s: dec(p) for s, p in market.prices.items()} | {BILL: dec(100)}
    for name, account in accounts.items():
        account.rebalance(state, initial_marks, probes[name].target)
    initial = {name: dict(controller=probes[name].snapshot(), account=a.snapshot())
               for name, a in accounts.items()}
    held = {ep['security_id'] for ep in state.wealth_core['episodes'].values()}
    labels = formation[-1]['labels']
    records = []
    for day in range(LENGTH):
        published = market.advance(case, day, held)
        previous = state
        state = advance_session(previous, published, controller_config=config, strategy_identity=identity)
        open_marks = {b.security_id: dec(b.raw_open) for b in published.bars} | {BILL: dec(100)}
        close_marks = {b.security_id: dec(b.raw_close) for b in published.bars} | {BILL: dec(100)}
        row = measure(state, published, labels)
        labels = row['labels']
        row.update(day=day, variants={})
        for name, probe in probes.items():
            prior_target = probe.target
            before = probe.snapshot()
            result = probe.step(row)
            if name == 'current':
                assert_baseline(row, result, probe)
            if day in CUTS:
                restored = ProbeController(name)
                restored.restore(json.loads(json.dumps(before)))
                assert restored.step(row) == result
                assert restored.snapshot() == probe.snapshot()
            account = accounts[name]
            before_account = account.snapshot()
            account.split(published.bars)
            execution = account.rebalance(state, open_marks, prior_target)
            if day in CUTS:
                restored_account = Account.restore(json.loads(json.dumps(before_account)))
                restored_account.split(published.bars)
                assert restored_account.rebalance(state, open_marks, prior_target) == execution
                assert restored_account.snapshot() == account.snapshot()
            row['variants'][name] = dict(decision=result, controller=probe.snapshot(),
                account=account.snapshot(), execution=execution, nav=float(account.nav(close_marks)))
        records.append(row)
        if day % 40 == 0:
            print(f'{case}: {day+1}/{LENGTH}', flush=True)
    summary = {}
    for name, account in accounts.items():
        peak, drawdown, prior = 100000., 0., initial[name]['controller']['target']
        changes, changed_days = [], []
        for row in records:
            variant = row['variants'][name]
            peak = max(peak, variant['nav'])
            drawdown = min(drawdown, variant['nav']/peak-1)
            target = variant['decision']['target']
            if target != prior:
                changes.append(dict(day=row['day'], session=row['session'], before=prior, after=target))
            if target != row['variants']['current']['decision']['target']:
                changed_days.append(row['day'])
            prior = target
        summary[name] = dict(ending_nav=records[-1]['variants'][name]['nav'], max_drawdown=drawdown,
            fees=float(account.fees), turnover=float(account.turnover), changes=changes,
            different_target_days=changed_days,
            days_below_full=sum(r['variants'][name]['decision']['target'] < 1 for r in records))
    for name, result in summary.items():
        result['terminal_difference_dollars'] = result['ending_nav']-summary['current']['ending_nav']
        result['drawdown_difference_pp'] = 100*(result['max_drawdown']-summary['current']['max_drawdown'])
    return dict(initial=initial, summary=summary, records=records, restart_cuts=CUTS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()
    original_constants = production_constants()
    origin = make_origin()
    print('Production formation complete; starting five fixed profiles.', flush=True)
    cases = {case: run_case(case, origin) for case in CASES}
    reference_bytes = args.reference.read_bytes()
    reference = json.loads(reference_bytes)
    for case in CASES:
        for key in ('ending_nav', 'max_drawdown', 'fees', 'turnover'):
            assert cases[case]['summary']['current'][key] == reference[case]['current'][key], (case, key)
    for a, b in zip(cases['healthy']['records'], cases['healthy_split']['records']):
        assert a['observation'] == b['observation']
        for name in PRESETS:
            assert a['variants'][name]['decision'] == b['variants'][name]['decision']
    assert production_constants() == original_constants
    sources = ['research/impedance/parameters.py', 'research/impedance/compare_parameters.py',
               'research/impedance/account.py', 'research/impedance/pipeline.py',
               'research/impedance/pipeline_diagnostics.py', 'sentinel/controller/champion_frozen.py',
               'sentinel/core/kernel.py']
    report = dict(schema='sentinel.parameter-probes/1', python=platform.python_version(),
        production_identity=origin[1], production_origin_hash=origin[2].state_hash,
        presets=PRESETS, research_identities={n: ProbeController(n).identity for n in PRESETS},
        source_sha256={p: hashlib.sha256(Path(p).read_text(encoding='utf-8').encode()).hexdigest() for p in sources},
        reference_sha256=hashlib.sha256(reference_bytes).hexdigest(),
        formation=origin[4], cases=cases,
        checks=dict(production_parity_closes=80+7*120, controller_restart_pairs=7*5*len(CUTS),
                    account_restart_pairs=7*5*len(CUTS), reference_economics_exact=True,
                    production_constants_unchanged=True, split_decisions_equal=True))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'results.json.gz').write_bytes(gzip.compress(json.dumps(report, indent=2, allow_nan=False).encode(), mtime=0))
    summary = {case: data['summary'] for case, data in cases.items()}
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
