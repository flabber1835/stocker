#!/usr/bin/env python3
"""Replay the frozen capacity-corrected Champion with seven factual type fixes.

The generated economic program changes only the unknown-type classifier import.
A separate fixed read-only observer records the new path using copied string IDs.
The program remains a diagnostic while the broader factual review is open.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import backtester
# Exact audit modules coexist with the frozen certified package.
_audit_package = str(Path(__file__).resolve().parent)
if _audit_package not in backtester.__path__:
    backtester.__path__.insert(0, _audit_package)
from backtester.champion_security_truth_audit_v2 import FACTS_SHA256, DEFAULT_FACTS, digest, write_json, write_csv, read_csv, unique, coverage, COUNTS

OLD_IMPORT = 'from backtester import research_champion_corrected_classification as _bestclass'
NEW_IMPORT = 'from backtester import champion_security_truth_overlay_v2 as _bestclass'
OBSERVER_ANCHOR = '            if date in _quarter_last and date < START:\n'
OBSERVER = "            _bestclass.observe(ds,tuple(str(sid[int(x)]) for x in durable),tuple(str(sid[int(s.tid)]) for s in book.slots if s.held()),tuple(str(sid[int(s.pending_tid)]) for s in book.slots if s.reserved()),tuple(str(sid[int(x)]) for x in recsel),tuple(str(sid[int(x)]) for x in et))\n"


def install(source: str) -> str:
    if source.count(OLD_IMPORT) != 1 or source.count(OBSERVER_ANCHOR) != 1:
        raise ValueError('unknown-type classifier or observer seam is not unique')
    result = source.replace(OLD_IMPORT, NEW_IMPORT, 1).replace(OBSERVER_ANCHOR, OBSERVER + OBSERVER_ANCHOR, 1)
    restored = result.replace(NEW_IMPORT, OLD_IMPORT, 1).replace(OBSERVER, '', 1)
    if restored != source:
        raise ValueError('economic source changed beyond the declared classifier/observer seams')
    compile(result, '<champion-factual-type-control-v2>', 'exec')
    return result


def metrics(frame, column: str) -> dict:
    import numpy as np
    nav = frame[column].astype(float)
    if len(nav) < 2 or not np.isfinite(nav).all() or (nav <= 0).any():
        raise ValueError('invalid NAV path')
    elapsed = (frame['date'].iloc[-1] - frame['date'].iloc[0]).days / 365.2425
    multiple = float(nav.iloc[-1] / nav.iloc[0])
    returns = nav.pct_change().dropna()
    volatility = float(returns.std(ddof=1))
    return dict(start=str(frame['date'].iloc[0].date()), end=str(frame['date'].iloc[-1].date()), sessions=len(frame),
                cagr_actual_elapsed=multiple ** (1 / elapsed) - 1, ending_multiple=multiple,
                max_drawdown=float((nav / nav.cummax() - 1).min()),
                sharpe_daily_252=float(returns.mean() / volatility * np.sqrt(252)) if volatility > 0 else None)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate-root', required=True, type=Path)
    p.add_argument('--original-queue', required=True, type=Path)
    p.add_argument('--baseline-directory', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    from backtester import champion_full_classification_control as control
    from backtester.champion_economic_prefix_audit import SOURCE, EXPECTED_CORPUS, PROFILE, PROFILE_HASH, RUNTIME, normalized_ast
    if digest(DEFAULT_FACTS.read_bytes()) != FACTS_SHA256:
        raise ValueError('factual batch hash mismatch')
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    candidate = subprocess.check_output(['git', '-C', str(args.candidate_root), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != SOURCE['certified'] or candidate != SOURCE['candidate']:
        raise ValueError('certified/candidate source pin mismatch')
    manifest = json.loads((Path(os.environ['CANONICAL_PIT_DATASET']) / 'manifest.json').read_text())
    if manifest.get('dataset_hash') != EXPECTED_CORPUS:
        raise ValueError('canonical corpus identity mismatch')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    engine = output / 'engine'
    engine.mkdir()
    baseline, capacity_off, previous = control.build_source(engine, args.candidate_root)
    from backtester import run_research_champion_strict_pit_20y_v2 as frozen_program
    from backtester import research_champion_corrected_classification as frozen_classifier
    if Path(frozen_program.__file__).resolve().parents[1] != Path.cwd().resolve():
        raise RuntimeError('economic program imported from a non-certified source tree')
    if Path(frozen_classifier.__file__).resolve().parents[1] != args.candidate_root.resolve():
        raise RuntimeError('prior classifier imported from a non-candidate source tree')
    revised = install(previous)
    for name, text in [('baseline-generated.py', baseline), ('capacity-off-generated.py', capacity_off),
                       ('previous-classification-generated.py', previous), ('factual-type-control-generated.py', revised)]:
        (output / name).write_text(text)
    restored = revised.replace(NEW_IMPORT, OLD_IMPORT, 1).replace(OBSERVER, '', 1)
    if normalized_ast(restored) != normalized_ast(previous):
        raise RuntimeError('economic AST preservation proof failed')
    identity = dict(schema='champion.factual-type-control/2', status='RUNNING_DIAGNOSTIC_NOT_CERTIFIED',
                    certification_status='NOT_CERTIFIED_FACTUAL_AUDIT_OPEN', audit_source_sha=os.environ['AUDIT_SOURCE_SHA'],
                    baseline_source_sha=actual, candidate_classifier_source_sha=candidate, runtime_sha=RUNTIME,
                    profile=PROFILE, profile_sha256=PROFILE_HASH, corpus_hash=EXPECTED_CORPUS, initial_shadow_cash=100000000,
                    warmup_start='2006-01-03', measurement_start='2006-07-31', end_session='2026-07-31',
                    capacity_guards_removed=2, changed_dimension='SEVEN_FACTUAL_UNKNOWN_SECURITY_TYPE_CORRECTIONS',
                    factual_batch_sha256=FACTS_SHA256, classification_scenario='reviewed_18_plus_PDS_EQM_plus_factual_batch_v2',
                    normalized_economic_ast_preserved_after_declared_seam_restoration=True,
                    observer_inputs='COPIED_TUPLES_OF_SECURITY_ID_STRINGS_ONLY',
                    prior_generated_sha256=digest(previous.encode()), revised_generated_sha256=digest(revised.encode()),
                    known_limitation='The broader factual type and identity audit remains open; later legal authority is permitted by the factual-truth contract.')
    write_json(output / 'identity.json', identity)
    module = types.ModuleType('champion_factual_type_control_v2')
    sys.modules[module.__name__] = module
    try:
        exec(compile(revised, str(output / 'factual-type-control-generated.py'), 'exec'), module.__dict__)
        module.run()
        from backtester import champion_security_truth_overlay_v2 as overlay
        if len(overlay.ACTIVE_ESTIMATES) != 1 or len(overlay.PATH_SESSIONS) < 5032:
            raise RuntimeError('fresh path observer coverage incomplete')
        estimate = overlay.ACTIVE_ESTIMATES[0]
        work = {sid: dict(security_id=sid, **{key: int(overlay.PATH_COUNTS.get(sid, {}).get(key, 0)) for key in COUNTS}) for sid in estimate.rows}
        original = unique(read_csv(args.original_queue), 'security_id')
        fresh = coverage(estimate.rows, original, work, estimate.factual_cases)
        for row in fresh:
            row['path_evidence_run'] = os.environ.get('GITHUB_RUN_ID', 'LOCAL')
            row['path_is_pre_correction'] = 'false'
        write_csv(output / 'fresh-path-type-coverage.csv', fresh, list(fresh[0]))
        write_csv(output / 'fresh-path-open-review-queue.csv', [r for r in fresh if r['status'] == 'OPEN_REVIEW'], list(fresh[0]))
        write_json(output / 'classifier-observations.json', estimate.summary())
        import pandas as pd
        frame = pd.read_csv(engine / 'daily.csv', parse_dates=['date'])
        if len(frame) != 5032 or str(frame['date'].iloc[0].date()) != '2006-07-31' or str(frame['date'].iloc[-1].date()) != '2026-07-31' or not frame['date'].is_monotonic_increasing or frame['date'].duplicated().any():
            raise RuntimeError('measurement horizon mismatch')
        reference_identity = json.loads((args.baseline_directory / 'controlled/identity.json').read_text())
        for key in ['baseline_source_sha', 'candidate_classifier_source_sha', 'runtime_sha', 'profile_sha256', 'corpus_hash', 'initial_shadow_cash']:
            if reference_identity.get(key) != identity.get(key):
                raise RuntimeError(f'classification-only comparison control mismatch: {key}')
        prior = pd.read_csv(args.baseline_directory / 'controlled/engine/daily.csv', parse_dates=['date'])
        if not prior['date'].equals(frame['date']):
            raise RuntimeError('classification-only comparison dates differ')
        first_differences = {}
        for key in ['A_nav', 'research_ranking_sha256', 'research_selected_positions_sha256', 'research_eligible_universe']:
            changed = frame[key].astype(str) != prior[key].astype(str)
            first_differences[key] = str(frame.loc[changed, 'date'].iloc[0].date()) if changed.any() else None
        result = dict(status='DIAGNOSTIC_NOT_CERTIFIED', strategy=metrics(frame, 'A_nav'), spy=metrics(frame, 'spy_nav'),
                      previous_classification=metrics(prior, 'A_nav'), first_differences=first_differences,
                      factual_batch_sha256=FACTS_SHA256, changed_dimension=identity['changed_dimension'],
                      corrected_tickers=sorted(c['ticker'] for c in estimate.factual_cases.values()),
                      fresh_observer_first_session=overlay.PATH_SESSIONS[0], fresh_observer_last_session=overlay.PATH_SESSIONS[-1],
                      fresh_observer_sessions=len(overlay.PATH_SESSIONS),
                      fresh_held_or_pending_type_cases=sum(r['priority'] == 'P0_HELD_OR_PENDING' for r in fresh),
                      fresh_held_or_pending_open_cases=sum(r['priority'] == 'P0_HELD_OR_PENDING' and r['status'] == 'OPEN_REVIEW' for r in fresh),
                      trailing_years={})
        result['cagr_change_percentage_points'] = 100 * (result['strategy']['cagr_actual_elapsed'] - result['previous_classification']['cagr_actual_elapsed'])
        for years in (5, 10, 15, 20):
            start = frame['date'].iloc[-1] - pd.DateOffset(years=years)
            part = frame[frame['date'] >= start]
            result['trailing_years'][str(years)] = {'strategy': metrics(part, 'A_nav'), 'spy': metrics(part, 'spy_nav')}
        write_json(output / 'RESULT.json', result)
        identity['status'] = 'PASS_FULL_HORIZON_DIAGNOSTIC_NOT_CERTIFIED'
        print('[FACTUAL_TYPE_RESULT] ' + json.dumps(result, sort_keys=True), flush=True)
    except Exception as exc:
        identity.update(status='FAIL', failure=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        write_json(output / 'identity.json', identity)
        write_json(output / 'SHA256.json', {str(f.relative_to(output)): digest(f.read_bytes()) for f in sorted(output.rglob('*')) if f.is_file() and f.name != 'SHA256.json'})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
