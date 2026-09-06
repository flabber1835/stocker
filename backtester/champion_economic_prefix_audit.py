#!/usr/bin/env python3
"""Read-only prefix evidence recovery and preregistered one-factor controls.

Run in a fresh interpreter whose cwd/PYTHONPATH identify the exact source tree.
No final performance report or certificate is produced by this program.
"""
from __future__ import annotations

import argparse
import ast
import copy
import dataclasses
from decimal import Decimal
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import types

CASES = ('candidate', 'certified', 'certified_capacity_off',
         'certified_dividend_1', 'certified_candidate_types')
EXPECTED_CORPUS = '5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993'
SOURCE = {'candidate': 'ba74e79490beb8950611b1d17f5d124833b3d91e',
          'certified': '27bb992087182c42c3c051e62bf837895f5d2ab7'}
RUNTIME = '887f479b15ad861313da666ad698034d3847121c'
PROFILE = 'strategy9-e3-research-champion-v1'
PROFILE_HASH = '1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26'
CAP_GUARDS = tuple(
    '                    if _research_capacity_guard(' + expr +
    ',_capacity_volumes.get(int(' + tid +
    '),()),security_id=str(sid[int(' + tid +
    ')]),session=ds,defer_excess=True) is None:\n                        continue\n'
    for expr, tid in [('s.qty', 's.tid'), ('s.pending_shares', 'tid')]
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_one(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f'Expected one seam: {old!r}; found {text.count(old)}')
    return text.replace(old, new, 1)


def clean(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean(x) for x in value]
    if hasattr(value, 'item'):
        return clean(value.item())
    return str(value)


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(clean(value), sort_keys=True, indent=2, allow_nan=False) + '\n')


def normalized_ast(text: str, *, strip_hooks=False) -> str:
    tree = ast.parse(text)
    class Normalize(ast.NodeTransformer):
        def visit_Assign(self, node):
            if any(isinstance(t, ast.Name) and t.id == 'OUT' for t in node.targets):
                node.value = ast.Constant('<OUTPUT_PATH>')
            return self.generic_visit(node)
        def visit_Expr(self, node):
            if (strip_hooks and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == '_economic_audit_hook'):
                return None
            return self.generic_visit(node)
    return ast.dump(Normalize().visit(tree), include_attributes=False)


def build_source(case: str, output: Path, candidate_root: Path) -> tuple[str, str, str]:
    if case == 'candidate':
        from backtester import research_champion_corrected_classification as target
        os.environ['BEST_EFFORT_SECURITY_TYPES'] = str(target.base.DEFAULT_LEDGER)
        os.environ['BEST_EFFORT_CLASSIFICATION_SCENARIO'] = 'reviewed_18'
        baseline = target.build_source(output)
    else:
        from backtester import run_research_champion_strict_pit_20y_v2 as target
        baseline = target.champion._champion_strict20_transform('fullpit', output)
    text, dimension = baseline, 'NONE_OBSERVATION_ONLY'
    if case == 'certified_capacity_off':
        for guard in CAP_GUARDS:
            text = replace_one(text, guard, '')
        dimension = 'EXECUTION_PARTICIPATION_CAP_ONLY'
    elif case == 'certified_dividend_1':
        text = replace_one(text, 'book.receivables.append((gday+15,q*rawdiv))',
                           'book.receivables.append((gday+1,q*rawdiv))')
        dimension = 'DIVIDEND_SETTLEMENT_LAG_ONLY'
    elif case == 'certified_candidate_types':
        import backtester
        backtester.__path__.append(str(candidate_root / 'backtester'))
        from backtester import research_champion_corrected_classification as classifier
        os.environ['BEST_EFFORT_SECURITY_TYPES'] = str(classifier.base.DEFAULT_LEDGER)
        os.environ['BEST_EFFORT_CLASSIFICATION_SCENARIO'] = 'reviewed_18'
        text = replace_one(text, 'from collections import defaultdict\n',
                           'from collections import defaultdict\nfrom backtester import research_champion_corrected_classification as _bestclass\n')
        anchor = 'actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()'
        text = replace_one(text, anchor, anchor + "\n    _BEST_TYPES=_bestclass.SecurityTypeEstimate(Path(os.environ['BEST_EFFORT_SECURITY_TYPES']),os.environ['BEST_EFFORT_CLASSIFICATION_SCENARIO'])")
        text = replace_one(text, '            elig=_sec_ok&_base_elig', '''            for _j in np.flatnonzero(_base_elig):
                _tid=int(tids[int(_j)]); _mr=_metadata(_tid,ds)
                if _mr is None or str(_mr.get('security_type','')).strip().lower()=='unknown':
                    _estimated=_BEST_TYPES.classify(str(sid[_tid]),ds)
                    _sec_ok[int(_j)]=_estimated=='common'
            elig=_sec_ok&_base_elig''')
        dimension = 'UNKNOWN_SECURITY_TYPE_CLASSIFICATION_ONLY'
    compile(text, '<economic-case>', 'exec')
    return baseline, text, dimension


def instrument(text: str) -> str:
    before = [
        ('            # Open: settle prior receivables, transform splits, then execute pending exits/buys.\n', 'before_actions'),
        ('            # Capture prior-close entitlement after split-domain conversion,\n', 'after_splits'),
        ('            for s in book.slots:\n                if not(s.reserved() and not s.held()): continue\n', 'after_sells'),
        ('            for _tid0,_sig_close,_raw_close,_reported_volume in zip(tids,c,cu,vol):\n', 'after_buys'),
        ('            for tid0 in tids:\n                if finite(clraw[int(tid0)]) and clraw[int(tid0)]>0: book.last_raw[int(tid0)]=float(clraw[int(tid0)])\n', 'after_dividends'),
    ]
    after = [
        ('            open_eq,_=book.equity(opraw)\n', 'before_fills'),
        ('            eq,unresolved=book.equity(clraw)\n', 'close_nav'),
        ("            pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d\n", 'session_end'),
    ]
    original = text
    for anchor, phase in before:
        text = replace_one(text, anchor, f"            _economic_audit_hook('{phase}',locals())\n" + anchor)
    for anchor, phase in after:
        text = replace_one(text, anchor, anchor + f"            _economic_audit_hook('{phase}',locals())\n")
    if normalized_ast(original) != normalized_ast(text, strip_hooks=True):
        raise AssertionError('Observer-stripped AST does not match economic source')
    compile(text, '<instrumented-economic-case>', 'exec')
    return text


class PrefixComplete(Exception):
    """Explicit successful diagnostic stop after the last observed session."""


class Observer:
    def __init__(self, output: Path, stop: str, case: str, lag: int):
        self.output, self.stop, self.case, self.lag = output, stop, case, lag
        self.handle = gzip.open(output / 'state-stages.jsonl.gz', 'wt', encoding='utf-8')
        self.previous = None
        self.checks = []
        self.fills = []
        self.rows = []
        self.sessions = 0
        self.last_session = None
        self.terminal_touches = set()

    def check(self, kind: str, session: str, actual, expected):
        error = abs(Decimal(str(actual)) - Decimal(str(expected)))
        record = {'kind': kind, 'session': session, 'actual': str(actual),
                  'expected': str(expected), 'absolute_error': str(error),
                  'status': 'PASS' if error <= Decimal('0.0001') else 'FAIL'}
        self.checks.append(record)
        if record['status'] != 'PASS':
            raise AssertionError(record)

    def __call__(self, phase: str, loc: dict):
        book, ids, ticks = loc['book'], loc['sid'], loc['tick']
        slots = []
        active = set()
        for index, slot in enumerate(book.slots):
            row = clean(dataclasses.asdict(slot))
            row['slot'] = index
            for key in ('tid', 'pending_tid'):
                tid = int(getattr(slot, key))
                row[key + '_security_id'] = str(ids[tid]) if tid >= 0 else None
                row[key + '_ticker'] = str(ticks[tid]) if tid >= 0 else None
                if tid >= 0:
                    active.add(tid)
            slots.append(row)
        # Prior positions may have just been sold; preserve their input marks.
        if self.previous and self.previous['session'] == loc['ds']:
            active.update(int(t) for t in self.previous['market'])
        market = {}
        for tid in sorted(active):
            market[str(tid)] = clean({
                'security_id': str(ids[tid]), 'ticker': str(ticks[tid]),
                'open': loc['opraw'][tid], 'close': loc['clraw'][tid],
                'signal_close': loc['clsig'][tid], 'volume': loc['volume'][tid],
                'dividend': loc['rawdividend'][tid], 'split': loc['canonicalsplit'][tid],
                'last_raw': book.last_raw.get(tid),
                'prior_capacity_volumes': list(loc['_capacity_volumes'].get(tid, ())),
            })
        record = clean({'session': loc['ds'], 'gday': loc['gday'], 'phase': phase,
                        'cash': book.cash, 'receivables': list(book.receivables),
                        'slots': slots, 'market': market,
                        'terminal_pending': copy.deepcopy(book.terminal_pending)})
        if phase in ('before_actions', 'session_end'):
            for key, value in [('eligible', loc['et']), ('durable', loc['durable']),
                               ('recent_leadership', loc['recsel'])]:
                record[key] = [str(ids[int(t)]) for t in value]
        if phase == 'session_end':
            record['controller_state'] = clean(copy.deepcopy(loc['ca'].__dict__))
            record['allocation'] = loc['eff']['A']
            record['strategy_nav'] = loc['navs']['A']
            self.sessions += 1
            self.last_session = loc['ds']
            if loc['rows'] and str(loc['rows'][-1]['date'].date()) == loc['ds']:
                self.rows.append(dict(loc['rows'][-1]))
        prior = self.previous
        if prior and prior['session'] == record['session']:
            if phase == 'after_splits':
                due = sum((Decimal(str(a)) for day, a in prior['receivables'] if day <= loc['gday']), Decimal(0))
                self.check('settlement_cash', loc['ds'], book.cash, Decimal(str(prior['cash'])) + due)
                self.check('settlement_claims', loc['ds'], sum(Decimal(str(a)) for _, a in book.receivables),
                           sum((Decimal(str(a)) for _, a in prior['receivables']), Decimal(0)) - due)
                for old, new in zip(prior['slots'], slots):
                    if old['tid'] >= 0 and old['qty'] > 1e-12:
                        ratio = record['market'][str(old['tid'])]['split']
                        self.check('split_shares', loc['ds'], new['qty'], Decimal(str(old['qty'])) * Decimal(str(ratio)))
            elif phase in ('after_sells', 'after_buys'):
                delta_cash = Decimal(0)
                for old, new in zip(prior['slots'], slots):
                    if phase == 'after_sells' and old['tid'] >= 0 and old['qty'] > 0 and new['tid'] < 0:
                        tid, quantity, side = old['tid'], old['qty'], 'SELL'
                        flow = Decimal(str(quantity)) * Decimal(str(market[str(tid)]['open'])) * Decimal('0.999')
                    elif phase == 'after_buys' and old['tid'] < 0 and new['tid'] >= 0 and new['qty'] > 0:
                        tid, quantity, side = new['tid'], new['qty'], 'BUY'
                        flow = -Decimal(str(quantity)) * Decimal(str(market[str(tid)]['open'])) * Decimal('1.001')
                    else:
                        continue
                    delta_cash += flow
                    self.fills.append({'session': loc['ds'], 'slot': old['slot'], 'side': side,
                                       'security_id': market[str(tid)]['security_id'],
                                       'ticker': market[str(tid)]['ticker'], 'quantity': quantity,
                                       'raw_open': market[str(tid)]['open'], 'cash_flow': str(flow)})
                self.check(phase + '_cash', loc['ds'], book.cash, Decimal(str(prior['cash'])) + delta_cash)
            elif phase == 'after_dividends':
                expected = [(int(day), Decimal(str(amount))) for day, amount in prior['receivables']]
                for tid, quantity in loc['prior_qty'].items():
                    dividend = float(loc['rawdividend'][int(tid)])
                    if quantity > 0 and dividend > 0:
                        expected.append((loc['gday'] + self.lag, Decimal(str(quantity)) * Decimal(str(dividend))))
                self.check('dividend_claim_amount', loc['ds'], sum(Decimal(str(a)) for _, a in book.receivables),
                           sum((amount for _, amount in expected), Decimal(0)))
                if [int(x[0]) for x in book.receivables] != [x[0] for x in expected]:
                    raise AssertionError('Dividend due-session mismatch')
                self.check('dividend_cash_unchanged', loc['ds'], book.cash, prior['cash'])
        if phase in ('before_fills', 'close_nav'):
            mark_key = 'open' if phase == 'before_fills' else 'close'
            reconstructed = Decimal(str(book.cash)) + sum((Decimal(str(x[1])) for x in book.receivables), Decimal(0))
            carry_ids = []
            for slot in slots:
                if slot['tid'] >= 0 and slot['qty'] > 1e-12:
                    price = market[str(slot['tid'])][mark_key]
                    if price is None or price <= 0:
                        price = market[str(slot['tid'])]['last_raw']
                        carry_ids.append(slot['tid_security_id'])
                    if price is None or price <= 0:
                        raise AssertionError('Independent NAV lacks an admissible mark')
                    reconstructed += Decimal(str(slot['qty'])) * Decimal(str(price))
            reported = loc['open_eq'] if phase == 'before_fills' else loc['eq']
            record['independent_nav'] = str(reconstructed)
            record['reported_nav'] = reported
            record['carried_mark_ids'] = carry_ids
            self.check('independent_' + mark_key + '_nav', loc['ds'], reported, reconstructed)
        if phase == 'before_fills':
            for tid in loc.get('term_tids', ()):
                if any(s['tid'] == int(tid) for s in slots):
                    self.terminal_touches.add((loc['ds'], str(ids[int(tid)])))
        self.handle.write(json.dumps(clean(record), sort_keys=True, allow_nan=False) + '\n')
        self.previous = record
        if phase == 'session_end' and loc['ds'] >= self.stop:
            raise PrefixComplete()

    def close(self):
        self.handle.close()
        write_json(self.output / 'accounting-checks.json', self.checks)
        write_json(self.output / 'fills.json', self.fills)
        write_json(self.output / 'observation-summary.json', {
            'sessions': self.sessions, 'last_session': self.last_session,
            'checks': len(self.checks), 'failed_checks': sum(x['status'] != 'PASS' for x in self.checks),
            'fills': len(self.fills), 'held_terminal_touches': sorted(self.terminal_touches),
            'terminal_settlement_independent_proof': 'NOT_ESTABLISHED_BY_THIS_PREFIX',
            'scope': 'BOUNDED_PREFIX_ONLY_NOT_A_CERTIFICATE',
        })
        import pandas as pd
        pd.DataFrame(self.rows).to_csv(self.output / 'observed-daily.csv', index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, choices=CASES)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--stop', default='2006-08-02', choices=['2006-08-02'])
    parser.add_argument('--assemble-only', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    engine_output = output / 'engine'
    engine_output.mkdir(exist_ok=True)
    baseline, economic, dimension = build_source(args.case, engine_output, args.candidate_root.resolve())
    observed = instrument(economic)
    for name, content in [('baseline-generated.py', baseline), ('economic-generated.py', economic), ('observed-generated.py', observed)]:
        (output / name).write_text(content)
    baseline_kind = 'candidate' if args.case == 'candidate' else 'certified'
    identity = {
        'schema': 'champion.economic-prefix-audit/1', 'case': args.case,
        'baseline_source_sha': SOURCE[baseline_kind], 'runtime_sha': RUNTIME,
        'profile': PROFILE, 'profile_sha256': PROFILE_HASH, 'corpus_hash': EXPECTED_CORPUS,
        'changed_dimension': dimension, 'initial_shadow_cash': 100000000,
        'warmup_start': '2006-01-03', 'measurement_start': '2006-07-31', 'stop_after': args.stop,
        'baseline_generated_sha256': sha(baseline.encode()),
        'economic_generated_sha256': sha(economic.encode()),
        'instrumented_generated_sha256': sha(observed.encode()),
        'baseline_normalized_ast_sha256': sha(normalized_ast(baseline).encode()),
        'economic_normalized_ast_sha256': sha(normalized_ast(economic).encode()),
        'observer_stripped_ast_matches': True, 'audit_source_sha': os.environ.get('GITHUB_SHA'),
        'status': 'ASSEMBLED', 'certification_status': 'NOT_CERTIFIED_DIAGNOSTIC',
    }
    write_json(output / 'identity.json', identity)
    if args.assemble_only:
        return 0
    actual_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if actual_sha != SOURCE[baseline_kind]:
        raise RuntimeError(f'Wrong source checkout: {actual_sha}')
    manifest = json.loads((Path(os.environ['CANONICAL_PIT_DATASET']) / 'manifest.json').read_text())
    if manifest['dataset_hash'] != EXPECTED_CORPUS:
        raise RuntimeError('Wrong corpus')
    lag = 1 if args.case in ('candidate', 'certified_dividend_1') else 15
    observer = Observer(output, args.stop, args.case, lag)
    module = types.ModuleType('economic_target')
    sys.modules[module.__name__] = module
    module.__dict__['_economic_audit_hook'] = observer
    try:
        exec(compile(observed, str(output / 'observed-generated.py'), 'exec'), module.__dict__)
        module.run()
        raise RuntimeError('Prefix boundary was not reached')
    except PrefixComplete:
        identity['status'] = 'PASS_BOUNDED_OBSERVATION'
    except Exception as exc:
        identity['status'] = 'FAIL'
        identity['failure'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        observer.close()
        write_json(output / 'identity.json', identity)
        write_json(output / 'SHA256.json', {p.name: sha(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file() and p.name != 'SHA256.json'})
    print(json.dumps(identity, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
