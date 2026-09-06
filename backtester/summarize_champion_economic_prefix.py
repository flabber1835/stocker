#!/usr/bin/env python3
"""Offline attribution of already-observed exact Champion prefixes."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path

CASES = ('candidate', 'certified', 'certified_capacity_off', 'certified_dividend_1', 'certified_candidate_types')


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def rows(path: Path) -> list[dict]:
    with gzip.open(path, 'rt') as f:
        return [json.loads(line) for line in f]


def held(record: dict) -> list:
    return [(s['slot'], s['tid_security_id'], s['qty']) for s in record['slots'] if s['tid'] >= 0 and s['qty'] > 1e-12]


def orders(record: dict) -> list:
    result = []
    for s in record['slots']:
        if s['pending_tid'] >= 0:
            result.append((s['slot'], 'BUY', s['pending_tid_security_id'], s['pending_shares']))
        if s['pending_sell'] and s['tid'] >= 0:
            result.append((s['slot'], 'SELL', s['tid_security_id'], s['qty']))
    return result


def equal(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-7)
    return a == b


def detail(a, b) -> dict:
    if isinstance(a, list) and isinstance(b, list) and (len(a) > 30 or len(b) > 30):
        sa = {json.dumps(x, sort_keys=True) for x in a}
        sb = {json.dumps(x, sort_keys=True) for x in b}
        return {'left_count': len(a), 'right_count': len(b),
                'left_only': [json.loads(x) for x in sorted(sa - sb)],
                'right_only': [json.loads(x) for x in sorted(sb - sa)],
                'left_first_30': a[:30], 'right_first_30': b[:30]}
    return {'left': a, 'right': b}


def compare(left: list[dict], right: list[dict]) -> dict:
    keys = [(r['session'], r['phase']) for r in left]
    if keys != [(r['session'], r['phase']) for r in right]:
        raise AssertionError('Case session/phase grids differ')
    fields = {
        'eligible_universe': ('before_actions', lambda r: r['eligible']),
        'durable_ranking': ('before_actions', lambda r: r['durable']),
        'recent_leadership': ('before_actions', lambda r: r['recent_leadership']),
        'pending_orders': ('session_end', orders),
        'held_quantities': (None, held),
        'cash': (None, lambda r: r['cash']),
        'dividend_receivables': (None, lambda r: r['receivables']),
        'open_nav': ('before_fills', lambda r: r['reported_nav']),
        'close_nav': ('close_nav', lambda r: r['reported_nav']),
        'allocation': ('session_end', lambda r: r['allocation']),
        'normalized_strategy_nav': ('session_end', lambda r: r['strategy_nav']),
    }
    result = {}
    for name, (phase, get) in fields.items():
        changes = []
        for a, b in zip(left, right):
            if phase is not None and a['phase'] != phase:
                continue
            av, bv = get(a), get(b)
            if not equal(av, bv):
                changes.append((a, av, bv))
        result[name] = {'differing_observations': len(changes), 'first': None}
        if changes:
            a, av, bv = changes[0]
            result[name]['first'] = {'session': a['session'], 'phase': a['phase'], **detail(av, bv)}
    return result


def analyze_case(path: Path, records: list[dict]) -> dict:
    ident = json.loads((path / 'identity.json').read_text())
    observed = json.loads((path / 'observation-summary.json').read_text())
    if ident['status'] != 'PASS_BOUNDED_OBSERVATION' or observed['failed_checks'] != 0:
        raise AssertionError(f'Incomplete baseline evidence: {path}')
    phases = {(r['session'], r['phase']): r for r in records}
    complete_open = []
    over_cap = []
    for r in records:
        if r['phase'] != 'before_fills':
            continue
        s = phases[(r['session'], 'after_splits')]
        claims = []
        for slot in s['slots']:
            if slot['tid'] >= 0 and slot['qty'] > 1e-12:
                m = s['market'][str(slot['tid'])]
                div = m['dividend']
                if div is not None and div > 0:
                    amount = Decimal(str(slot['qty'])) * Decimal(str(div))
                    claims.append({'security_id': slot['tid_security_id'], 'ticker': slot['tid_ticker'],
                                   'quantity': slot['qty'], 'dividend_per_share': div, 'claim': str(amount)})
        if claims:
            missing = sum((Decimal(c['claim']) for c in claims), Decimal(0))
            complete_open.append({'session': r['session'], 'ex_date_claims': claims,
                                  'unposted_current_entitlement': str(missing),
                                  'recorded_open_nav': r['reported_nav'],
                                  'entitlement_complete_open_nav': str(Decimal(str(r['reported_nav'])) + missing),
                                  'scope': 'OPEN_ENTITLEMENT_COMPLETENESS; TOTAL_RECORDED_LEDGER_MAY_STILL_RECONCILE'})
        for slot in r['slots']:
            sid, tid, qty, side = None, None, None, None
            if slot['pending_tid'] >= 0 and slot['tid'] < 0:
                sid, tid, qty, side = slot['pending_tid_security_id'], slot['pending_tid'], slot['pending_shares'], 'BUY'
            elif slot['pending_sell'] and slot['tid'] >= 0:
                sid, tid, qty, side = slot['tid_security_id'], slot['tid'], slot['qty'], 'SELL'
            if tid is None:
                continue
            m = r['market'][str(tid)]
            history = m['prior_capacity_volumes'][-20:]
            if m['open'] is None or m['open'] <= 0 or m['volume'] is None or m['volume'] <= 0 or len(history) != 20:
                continue
            average = sum(history) / 20
            if qty / average > .1 + 1e-15:
                over_cap.append({'session': r['session'], 'slot': slot['slot'], 'side': side,
                                 'security_id': sid, 'ticker': m['ticker'], 'requested_shares': qty,
                                 'prior_20_mean_raw_compatible_volume': average, 'limit_shares': .1 * average,
                                 'participation': qty / average, 'raw_open': m['open']})
    last = next(r for r in reversed(records) if r['phase'] == 'session_end')
    dump(path / 'open-entitlement-completeness.json', complete_open)
    dump(path / 'over-capacity-order-observations.json', over_cap)
    checks = json.loads((path / 'accounting-checks.json').read_text())
    check_types = {}
    for c in checks:
        check_types[c['kind']] = check_types.get(c['kind'], 0) + 1
    return {'identity': ident, 'observation': observed, 'accounting_check_types': check_types,
            'held_count_at_prefix_end': len(held(last)), 'cash_at_prefix_end': last['cash'],
            'first_measured_daily': list(csv.DictReader((path / 'observed-daily.csv').open()))[0],
            'open_entitlement_missing_sessions': len(complete_open),
            'first_open_entitlement_gap': complete_open[0] if complete_open else None,
            'over_capacity_order_observations': len(over_cap),
            'first_over_capacity_order': over_cap[0] if over_cap else None,
            'ledger_arithmetic_status': 'PASS_RECORDED_STATE_ONLY',
            'entitlement_completeness_status': 'FAIL_OPEN_ENTITLEMENT' if complete_open else 'NOT_EXERCISED',
            'terminal_full_horizon_proof': 'NOT_ESTABLISHED'}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True, type=Path)
    args = p.parse_args()
    root = args.root
    reproduction = json.loads((root / 'baseline-reproduction.json').read_text())
    assert reproduction['candidate']['status'] == reproduction['certified']['status'] == 'PASS'
    records = {case: rows(root / case / 'state-stages.jsonl.gz') for case in CASES}
    cases = {case: analyze_case(root / case, records[case]) for case in CASES}
    pairs = [('candidate', 'certified'), ('certified', 'certified_capacity_off'),
             ('certified', 'certified_dividend_1'), ('certified', 'certified_candidate_types')]
    comparisons = {}
    for left, right in pairs:
        result = compare(records[left], records[right])
        left_fills = json.loads((root / left / 'fills.json').read_text())
        right_fills = json.loads((root / right / 'fills.json').read_text())
        sessions = sorted({r['session'] for r in left_fills + right_fills})
        result['first_different_fill_session'] = None
        for session in sessions:
            a = [r for r in left_fills if r['session'] == session]
            b = [r for r in right_fills if r['session'] == session]
            if a != b:
                result['first_different_fill_session'] = {'session': session, 'left': a, 'right': b}
                break
        comparisons[left + '__' + right] = result
    result = {'schema': 'champion.economic-prefix-attribution/1',
              'status': 'COMPLETED_BOUNDED_DIAGNOSTIC_CERTIFICATION_BLOCKED',
              'scope': '2006-01-03_THROUGH_2006-08-02_NOT_FULL_20Y_ATTRIBUTION',
              'baseline_reproduction': reproduction, 'cases': cases, 'comparisons': comparisons}
    dump(root / 'economic-attribution.json', result)
    fields = ['case', 'baseline_source_sha', 'audit_source_sha', 'runtime_sha', 'profile', 'corpus_hash',
              'initial_shadow_cash', 'changed_dimension', 'status', 'economic_generated_sha256',
              'sessions', 'checks', 'fills', 'held_count_at_prefix_end', 'cash_at_prefix_end',
              'open_entitlement_missing_sessions', 'over_capacity_order_observations']
    with (root / 'controlled-replays.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for case, data in cases.items():
            merged = {'case': case, **data['identity'], **data['observation'], **data}
            w.writerow({field: merged.get(field) for field in fields})
    dump(root / 'analysis-SHA256.json', {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'analysis-SHA256.json'})
    print(json.dumps({'status': result['status'], 'cases': len(cases)}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
