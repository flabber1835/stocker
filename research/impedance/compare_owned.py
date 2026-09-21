"""Frozen synthetic markets through two complete production controller profiles."""
import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import platform

import numpy as np

from sentinel.core.kernel import advance_session
from sentinel.core.session import SessionState
from sentinel.strategy import owned_impairment_strategy, production_strategy
from research.impedance.account import Account, BILL, dec
from research.impedance.pipeline import CASES, LENGTH, make_origin
from research.impedance.pipeline_diagnostics import measure

CUTS = (0, 4, 8, 19, 31, 41, 69, 119)


def compare_case(case, origins):
    market = copy.deepcopy(origins['current'][3])
    states = {name:SessionState.from_dict(origin[2].to_dict()) for name,origin in origins.items()}
    accounts = {name:Account() for name in origins}
    initial_marks = {s:dec(p) for s,p in market.prices.items()} | {BILL:dec(100)}
    for name in origins:
        accounts[name].rebalance(states[name], initial_marks, states[name].last_decision['target_core_exposure'])
    initial_accounts = {n:a.snapshot() for n,a in accounts.items()}
    held = {ep['security_id'] for ep in states['current'].wealth_core['episodes'].values()}
    records = {name:[] for name in origins}
    labels = {name:origin[4][-1]['labels'] for name,origin in origins.items()}
    for day in range(LENGTH):
        p = market.advance(case, day, held)
        open_marks = {b.security_id:dec(b.raw_open) for b in p.bars} | {BILL:dec(100)}
        close_marks = {b.security_id:dec(b.raw_close) for b in p.bars} | {BILL:dec(100)}
        for name,(config,identity,*_) in origins.items():
            previous = states[name]
            target = previous.last_decision['target_core_exposure']
            state = advance_session(previous, p, controller_config=config, strategy_identity=identity)
            if day in CUTS:
                again = advance_session(SessionState.from_dict(json.loads(json.dumps(previous.to_dict()))),
                                        p,controller_config=config,strategy_identity=identity)
                assert state.state_hash == again.state_hash
                accounts[name] = Account.restore(json.loads(json.dumps(accounts[name].snapshot())))
            account = accounts[name]
            account.split(p.bars)
            execution = account.rebalance(state, open_marks, target)
            before = state.state_hash if day in CUTS else None
            row = measure(state, p, labels[name])
            if before:
                assert before == state.state_hash
            labels[name] = row['labels']
            row.update(day=day, execution=execution, account_nav=float(account.nav(close_marks)),
                       account=account.snapshot(), owned_state=state.owned_impairment,
                       owned_evidence=state.last_decision.get('owned_impairment'))
            records[name].append(row)
            states[name] = state
        assert states['current'].wealth_core == states['owned'].wealth_core, ('Core ownership drift',case,day)
        assert states['current'].ledger == states['owned'].ledger, ('Core ledger drift',case,day)
        assert states['current'].last_evidence['observation'] == states['owned'].last_evidence['observation']
        if day % 40 == 0:
            print(f'{case}: {day+1}/{LENGTH}',flush=True)
    summary = {}
    for name,rows in records.items():
        peak, drawdown = 100000., 0.
        for row in rows:
            peak = max(peak,row['account_nav']);drawdown=min(drawdown,row['account_nav']/peak-1)
        summary[name] = dict(ending_nav=rows[-1]['account_nav'],return_fraction=rows[-1]['account_nav']/100000-1,
            max_drawdown=drawdown,fees=float(accounts[name].fees),turnover=float(accounts[name].turnover),
            first_reduction=next((r['day'] for r in rows if r['core_multiplier']<1),None),
            days_below_full=sum(r['core_multiplier']<1 for r in rows),
            owned_entries=[r['day'] for r in rows if r['owned_evidence'] and r['owned_evidence']['reason']=='OWNED_IMPAIRMENT_ENTER'],
            owned_releases=[r['day'] for r in rows if r['owned_evidence'] and r['owned_evidence']['reason']=='OWNED_RECOVERED'])
    summary['terminal_difference_dollars'] = summary['owned']['ending_nav']-summary['current']['ending_nav']
    summary['drawdown_difference_pp'] = 100*(summary['owned']['max_drawdown']-summary['current']['max_drawdown'])
    return dict(summary=summary,initial_accounts=initial_accounts,records=records,restart_cuts=CUTS)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    origins={'current':make_origin(production_strategy),'owned':make_origin(owned_impairment_strategy)}
    assert origins['current'][2].wealth_core==origins['owned'][2].wealth_core
    cases={case:compare_case(case,origins) for case in CASES}
    for profile in origins:
        for left,right in zip(cases['healthy']['records'][profile],cases['healthy_split']['records'][profile]):
            assert left['observation']==right['observation']
            assert left['core_multiplier']==right['core_multiplier']
    files = ['sentinel/controller/owned_impairment.py','sentinel/core/kernel.py','sentinel/core/session.py',
             'research/impedance/compare_owned.py','research/impedance/account.py','research/impedance/pipeline.py']
    report=dict(schema='sentinel-owned-impairment-synthetic/1',
        runtime=dict(python=platform.python_version(),numpy=np.__version__),
        identities={n:o[1] for n,o in origins.items()},
        source_sha256={p:hashlib.sha256(Path(p).read_text(encoding='utf-8').encode()).hexdigest() for p in files},
        scenario_source='PR431/0070f410; unchanged stimulus functions',cases=cases,
        assumptions=dict(account_start=100000,core_formation_start=100000,cost_bps=10,bill_yield=0,
                         timing='prior close scalar; next open projection and fills; current close marks'))
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'comparison.json.gz').write_bytes(gzip.compress(json.dumps(report,indent=2,allow_nan=False).encode(),mtime=0))
    summary={n:c['summary'] for n,c in cases.items()}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
