#!/usr/bin/env python3
"""Reproduce economic-integrity defects using extracted exact-source functions.

This probe executes synthetic fixtures, not a historical performance replay.
The supplied generated programs and runtime source remain unchanged.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def extract(text: str, names: set[str]) -> ast.Module:
    body = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in body} != names:
        raise AssertionError('Required exact-source functions are missing')
    return ast.Module(body=body, type_ignores=[])


def run(candidate: Path, certified: Path, classifier: Path, corrections: Path, adapter: Path) -> dict:
    outputs = {}
    function_hashes = set()
    date, prior = pd.Timestamp('2006-07-10'), pd.Timestamp('2006-07-07')
    cash = pd.DataFrame({'gap_factor': [1.0], 'intraday_factor': [1.0]}, index=[date])
    for label, path in [('candidate', candidate), ('certified', certified)]:
        source = path.read_text()
        tree = extract(source, {'bil_factors', 'apply_overlay'})
        cost_nodes = [n for n in ast.parse(source).body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'COST' for t in n.targets)]
        assert len(cost_nodes) == 1
        cost = ast.literal_eval(cost_nodes[0].value)
        assert cost == 0.001
        ns = {'pd': pd, 'np': np, 'COST': cost}
        exec(compile(tree, str(path), 'exec'), ns)
        ast_hash = digest(ast.dump(tree, include_attributes=False))
        function_hashes.add(ast_hash)
        assert source.index('prior_qty={s.tid:s.qty for s in book.slots if s.held()}') < source.index('open_eq,_=book.equity(opraw)') < source.index('book.receivables.append((gday+')
        rows = []
        for old, new in [(1., 0.), (0., 1.), (1., 1.), (.55, 1.)]:
            actual = ns['apply_overlay'](1., old, new, 100., 90., 100., cash, date, prior)[0]
            complete = ns['apply_overlay'](1., old, new, 100., 100., 100., cash, date, prior)[0]
            rows.append({'old_allocation': old, 'new_allocation': new,
                         'prior_nav': 100, 'raw_open_position_value': 90,
                         'ex_date_receivable': 10, 'recorded_open_nav': 90,
                         'entitlement_complete_open_nav': 100, 'close_nav': 100,
                         'actual_overlay_factor': actual,
                         'entitlement_complete_factor': complete,
                         'difference': actual - complete})
        assert abs(rows[0]['actual_overlay_factor'] - .8991) < 1e-12
        assert abs(rows[0]['entitlement_complete_factor'] - .999) < 1e-12
        assert abs(rows[1]['actual_overlay_factor'] - 1.11) < 1e-12
        assert abs(rows[1]['entitlement_complete_factor'] - .999) < 1e-12
        assert rows[2]['difference'] == 0
        outputs[label] = {'generated_source_sha256': digest(source),
                          'extracted_function_ast_sha256': ast_hash,
                          'dividend_posted_after_open_nav': True, 'rows': rows}
    assert len(function_hashes) == 1
    runtime_text = adapter.read_text()
    start = runtime_text.index('def step_session(')
    body = runtime_text[start:]
    assert body.index('apply_dividends(state, bars, ledger, session, cfg)') < body.index('resolved_open_equity, open_unresolved = _resolved_open_equity(')
    source = classifier.read_text()
    klass = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'SecurityTypeEstimate')
    method = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == '_historical_correction')
    ns = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(classifier), 'exec'), ns)
    grouped = {}
    for row in csv.DictReader(corrections.open()):
        grouped.setdefault(row['security_id'], []).append(row)
    session = '2006-07-05'
    row = ns['_historical_correction'](SimpleNamespace(corrections=grouped), '594891209465982980', session)
    assert row is not None and row['classification'] == 'non_common'
    assert row['evidence_available_from'] == '2010-06-01' and row['evidence_available_from'] > session
    return {'schema': 'champion.economic-source-probes/1',
            'status': 'DEFECTS_REPRODUCED',
            'scope': 'EXACT_EXTRACTED_FUNCTION_SYNTHETIC_FIXTURES_NOT_HISTORICAL_ATTRIBUTION',
            'dividend_open_boundary': outputs,
            'production_accrues_dividend_before_open_nav': True,
            'production_adapter_sha256': digest(runtime_text),
            'classification_availability': {'security_id': '594891209465982980', 'ticker': 'PDS',
                'requested_session': session, 'returned_correction': row,
                'future_authority_applied': True, 'classifier_sha256': digest(source),
                'correction_ledger_sha256': hashlib.sha256(corrections.read_bytes()).hexdigest()},
            'historical_dividend_CAGR_impact': 'NOT_MEASURED',
            'historical_classification_CAGR_impact': 'NOT_ISOLATED'}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'certified', 'classifier', 'corrections', 'adapter', 'output'):
        p.add_argument('--' + name, required=True, type=Path)
    args = p.parse_args()
    result = run(args.candidate, args.certified, args.classifier, args.corrections, args.adapter)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': result['status'], 'output': str(args.output)}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
