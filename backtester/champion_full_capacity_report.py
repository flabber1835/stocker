#!/usr/bin/env python3
"""Offline full-capacity attribution, preserving the original economic replay."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

METRICS_SOURCE_SHA256 = '570b44333db93b3ec6a6b1cfbc857cbbf6337a9448ee5507323933c028ecaff5'
SOURCE = '27bb992087182c42c3c051e62bf837895f5d2ab7'
AUDIT = '9924bfa5b36322a5bf78296f42544eaa175299d8'
CORPUS = '5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993'
WINDOWS = {'5': ('2021-07-30', 5.), '10': ('2016-07-29', 10.),
           '15': ('2011-07-29', 15.), '20': ('2006-07-31', 20.),
           'max': ('2006-07-31', None)}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def normalized(text: str) -> str:
    class Output(ast.NodeTransformer):
        def visit_Assign(self, node):
            if any(isinstance(t, ast.Name) and t.id == 'OUT' for t in node.targets):
                node.value = ast.Constant('<OUTPUT_PATH>')
            return self.generic_visit(node)
    return ast.dump(Output().visit(ast.parse(text)), include_attributes=False)


def metric_function(path: Path):
    assert sha(path) == METRICS_SOURCE_SHA256, 'Wrong reporting source'
    nodes = [n for n in ast.parse(path.read_text()).body
             if isinstance(n, ast.FunctionDef) and n.name == 'metric_block']
    assert len(nodes) == 1
    namespace = {'pd': pd, 'np': np, 'math': math}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['metric_block']


def metrics(daily: pd.DataFrame, fn, research_col: str) -> pd.DataFrame:
    result = []
    for window, (start, years) in WINDOWS.items():
        for variant, column in [('RESEARCH', research_col), ('SPY', 'spy_nav')]:
            result.append({'window_years': window, 'variant': variant,
                           **fn(daily, column, start, years)})
    return pd.DataFrame(result)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original', required=True, type=Path)
    p.add_argument('--metrics-source', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--control', type=Path)
    p.add_argument('--prefix', type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fn = metric_function(args.metrics_source)
    original = pd.read_csv(args.original / 'daily.csv.gz', parse_dates=['date'])
    original_metrics = pd.read_csv(args.original / 'metrics.csv', dtype={'window_years': str})
    reproduced = metrics(original, fn, 'research_nav')
    assert_frame_equal(original_metrics, reproduced, check_dtype=False, rtol=1e-11, atol=1e-12)
    proof = {'status': 'PASS', 'rows': len(reproduced), 'metrics_source_sha256': METRICS_SOURCE_SHA256,
             'original_daily_sha256': sha(args.original / 'daily.csv.gz'),
             'original_metrics_sha256': sha(args.original / 'metrics.csv')}
    write(args.output / 'original-metrics-reproduction.json', proof)
    if args.control is None:
        print('PASS: all ten original metric rows reproduced')
        return 0
    assert args.prefix is not None, 'Prefix evidence required'
    root = args.control
    identity = json.loads((root / 'identity.json').read_text())
    expected = {'status': 'PASS_FULL_HORIZON_DIAGNOSTIC_NOT_CERTIFIED',
                'baseline_source_sha': SOURCE, 'audit_source_sha': AUDIT,
                'runtime_sha': '887f479b15ad861313da666ad698034d3847121c',
                'profile': 'strategy9-e3-research-champion-v1',
                'profile_sha256': '1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26',
                'corpus_hash': CORPUS, 'initial_shadow_cash': 100000000,
                'changed_dimension': 'EXECUTION_PARTICIPATION_CAP_ONLY',
                'guard_occurrences_removed': 2, 'warmup_start': '2006-01-03',
                'measurement_start': '2006-07-31', 'end_session': '2026-07-31'}
    for key, value in expected.items():
        assert identity[key] == value, (key, identity.get(key))
    for name, digest in json.loads((root / 'SHA256.json').read_text()).items():
        assert sha(root / name) == digest, name
    baseline = (root / 'baseline-generated.py').read_text()
    control = (root / 'capacity-off-generated.py').read_text()
    assert normalized(baseline) == normalized((args.prefix / 'certified/economic-generated.py').read_text())
    assert normalized(control) == normalized((args.prefix / 'certified_capacity_off/economic-generated.py').read_text())
    assert sha(root / 'baseline-generated.py') == identity['baseline_generated_sha256']
    assert sha(root / 'capacity-off-generated.py') == identity['controlled_generated_sha256']
    daily = pd.read_csv(root / 'engine/daily.csv', parse_dates=['date'])
    assert len(daily) == len(original) == 5032
    assert daily.date.equals(original.date) and daily.date.is_unique
    for column in ['A_nav', 'control_nav', 'spy_nav', 'shadow_equity', 'open_equity']:
        assert np.isfinite(daily[column]).all() and (daily[column] > 0).all(), column
    np.testing.assert_allclose(daily.A_nav, daily.control_nav, rtol=0, atol=1e-12)
    np.testing.assert_allclose(daily.spy_nav, original.spy_nav, rtol=1e-12, atol=1e-12)
    np.testing.assert_array_equal(daily.research_ranking_sha256, original.research_ranking_sha256)
    np.testing.assert_array_equal(daily.eligible_count, original.eligible_count)
    prefix = pd.read_csv(args.prefix / 'certified_capacity_off/observed-daily.csv', parse_dates=['date'])
    columns = sorted(set(prefix.columns) & set(daily.columns))
    assert len(columns) == 30
    assert_frame_equal(prefix[columns], daily.loc[daily.date <= '2006-08-02', columns].reset_index(drop=True),
                       check_dtype=False, rtol=1e-12, atol=1e-7)
    calculated = metrics(daily, fn, 'A_nav')
    calculated.to_csv(args.output / 'controlled-metrics.csv', index=False)
    windows = {}
    for w in WINDOWS:
        a = reproduced[(reproduced.window_years == w) & (reproduced.variant == 'RESEARCH')].iloc[0]
        b = calculated[(calculated.window_years == w) & (calculated.variant == 'RESEARCH')].iloc[0]
        windows[w] = {name: {'original': float(a[name]), 'capacity_off': float(b[name]),
                            'difference': float(b[name] - a[name])}
                      for name in ['cagr', 'max_drawdown', 'sharpe', 'ending_multiple']}
        windows[w].update({'start': str(b['start']), 'end': str(b['end']), 'sessions': int(b['sessions'])})
    summary = json.loads((root / 'engine/summary.json').read_text())
    original_summary = json.loads((args.original / 'summary.json').read_text())
    result = {'schema': 'champion.full-capacity-attribution-offline/1',
              'status': 'PASS_CONDITIONAL_ONE_FACTOR_ATTRIBUTION_NOT_CERTIFIED',
              'controlled_run_id': 34044640055, 'original_run_id': 34014048220,
              'identity': identity, 'original_metrics_reproduction': proof,
              'full_source_asts_match_preregistered_prefix_cases': True,
              'prefix_columns_reproduced': 30, 'prefix_sessions_reproduced': 3,
              'full_universe_and_rankings_equal': True, 'full_spy_path_equal': True,
              'raw_summary_replay_mode_label': summary.get('replay_mode'),
              'mode_label_scope': 'MODE/PIT_MODE appear only in run labels, year-end logging and summary labels in the compared generated source; canonical data loading and economic branches are source-identical.',
              'windows': windows,
              'event_counts': {k: {'original': original_summary.get(k), 'capacity_off': summary.get(k)}
                               for k in ['buys', 'sells', 'dividend_events_held', 'split_events_applied']},
              'limitations': ['Conditional capacity effect with every other inherited economic rule fixed.',
                              'Known dividend/open-entitlement defect remains in both programs.',
                              'No complete candidate-versus-certificate CAGR decomposition.',
                              'No full-horizon independent fill/claim/PnL reconstruction.',
                              'Outcome E and economic-specification hold remain in force.']}
    write(args.output / 'FULL_CAPACITY_ATTRIBUTION.json', result)
    lines = ['# Full-horizon capacity-only attribution', '', '**Diagnostic only. Certification remains on HOLD / outcome E.**', '',
             'Original run 34014048220; controlled run 34044640055. Initial shadow cash remains $100M. Only the two executable-order participation guards change.', '',
             '| Window | Original CAGR | Capacity-off CAGR | Difference (percentage points) |', '|---|---:|---:|---:|']
    for w in ['20', '15', '10', '5', 'max']:
        c = windows[w]['cagr']; lines.append(f"| {w} | {c['original']:.4%} | {c['capacity_off']:.4%} | {100*c['difference']:+.4f} |")
    lines += ['', 'Numbered windows use the original report\'s fixed-year denominators. The max row uses actual elapsed calendar days divided by 365.2425.', '',
              'Both source ASTs match the already validated prefix cases. All 30 prefix columns reproduce, all 5,032 session dates align, and the full eligible universe, durable ranking hashes and SPY path match the original certificate.', '',
              'The raw runner emits daily.csv and summary.json. The original workflow comparison expects metrics.csv and a lowercase research role; the historical wrapper normally creates metrics.csv with uppercase RESEARCH. This offline analysis reuses the raw daily bytes and the exact historical metric function, first reproducing every original metric row.', '',
              f"Raw summary mode label: `{summary.get('replay_mode')}`. The generated MODE/PIT_MODE uses are reporting-only; exact canonical corpus and economic-source identities are verified separately.", '',
              'This result measures a conditional capacity effect. It does not approve the inherited economics or establish the return of the intended Champion. The full attribution, independent accounting and contract decisions remain open.', '']
    (args.output / 'FULL_CAPACITY_CONTROL.md').write_text('\n'.join(lines))
    write(args.output / 'SHA256.json', {p.name: sha(p) for p in sorted(args.output.iterdir())
                                      if p.is_file() and p.name != 'SHA256.json'})
    print(json.dumps({'status': result['status'], 'windows': windows}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
