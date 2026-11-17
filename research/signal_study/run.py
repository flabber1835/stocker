"""Study observable signals on the retained fractional Core history."""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from research.exposure_oracle import accounting as A, inputs
from research.structured_search import data, protocol
from . import audit, features, opportunities, probes, report
from .guard import CoreGuard


def jsonl(path, records):
    with path.open('w', encoding='utf8') as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False)+'\n')


def profiles(rows, recovered, x, names, actual, changed):
    result = []
    for t in changed:
        eligible = [i for i in range(63, len(actual)) if actual[i]==actual[t]]
        values = {}
        for k, name in enumerate(names):
            v = x[t, k]; population = x[eligible, k]; population = population[np.isfinite(population)]
            values[name] = dict(value=float(v) if np.isfinite(v) else None,
                retrospective_percentile=float(np.mean(population<=v)) if np.isfinite(v) and len(population) else None,
                comparison_n=len(population))
        result.append(dict(t=t, session=rows[t]['session'], actual=float(actual[t]),
                           features=values, recovered=recovered[t]))
    return result


def retained_checks(rows, recovered, x, names):
    comparisons = Counter(); errors = Counter()
    for i, record in enumerate(recovered):
        if i<63: continue
        v = record['values']
        for name, recorded in (('leadership_r20','recorded_recent_r20'), ('leadership_r40','recorded_recent_r40')):
            if recorded in v:
                error = abs(float(x[i,names.index(name)])-v[recorded])
                if error>1e-10: raise ValueError('recovered leadership disagrees with exact saved observation')
                comparisons[name] += 1; errors[name] = max(errors[name], error)
        for h in (5,10,20,40):
            key = 'recorded_shadow_r'+str(h)
            if key in v:
                error = abs(float(rows[i]['core']['nav'])/float(rows[i-h]['core']['nav'])-1-v[key])
                if error>1e-10: raise ValueError('retained Core returns disagree with saved observations')
                comparisons[key] += 1; errors[key] = max(errors[key], error)
        if 'recorded_stops20' in v:
            error = abs(x[i,names.index('recorded_stops20')]-v['recorded_stops20'])
            if error>1e-10: raise ValueError('recovered stop window differs from exact observation')
            comparisons['stops20'] += 1
    return dict(comparisons=dict(comparisons), max_errors=dict(errors))


def run(snapshot: Path, observations: Path, anchor: Path, output: Path):
    paths = [p.resolve() for p in (snapshot, observations, anchor)]
    output = output.resolve()
    if any(output==p or output in p.parents or p in output.parents for p in paths):
        raise ValueError('output must be separate from research inputs')
    output.mkdir(parents=True, exist_ok=False)
    binding, rows = inputs.load(snapshot)
    root = Path(__file__).resolve().parents[2]
    accountant_sources = inputs.verify_accountant_sources(binding, root)
    days, initial, actual = A.tape(rows)
    saved = json.loads((anchor/'paths.json').read_text())
    saved_summary = json.loads((anchor/'summary.json').read_text())
    manifest = json.loads((snapshot/'manifest.json').read_text())
    if saved_summary['source_daily']!=manifest['daily'] or saved_summary['source_binding']!=manifest['binding']:
        raise ValueError('hindsight anchor uses a different Core tape')
    if saved['actual']['exposure']!=[float(a) for a in actual]:
        raise ValueError('anchor baseline differs from retained Sentinel decisions')
    target = [A.D(str(a)) for a in saved['target']['exposure']]
    anatomy = opportunities.anatomy(rows, days, initial, actual, target)
    for which in ('actual','target'):
        for key in ('cagr','maxdd','multiple'):
            if abs(float(anatomy[which][key])-float(saved[which][key]))>1e-10:
                raise ValueError('anchor metrics do not replay')
    inputs.write_json(output/'anatomy.json', anatomy)
    recovered, coverage = features.load_observations(observations, snapshot, rows)
    x, names, tiers = features.build(rows, recovered)
    observed = retained_checks(rows, recovered, x, names)
    dates = [r['session'] for r in rows]
    matrix = data.matrices(days)
    labels = opportunities.local_labels(matrix, data.action_indices(actual), int(data.action_indices([initial])[0]))
    print('INPUTS_AND_LABELS_VALIDATED', flush=True)
    dependencies = ('research/exposure_oracle/accounting.py', 'research/exposure_oracle/inputs.py',
        'research/exposure_oracle/neural_data.py', 'research/exposure_oracle/target_analysis.py',
        'research/exposure_oracle/analysis.py', 'research/structured_search/data.py',
        'research/structured_search/protocol.py')
    files = [*sorted((root/'research/signal_study').glob('*.py')), *(root/p for p in dependencies)]
    sources = {str(p.relative_to(root)):inputs.sha(p.read_bytes()) for p in files}
    spec = dict(schema='sentinel-signal-study/1', source_manifest=manifest, sources=sources,
        accountant_sources=accountant_sources, anchor_paths_sha256=inputs.sha((anchor/'paths.json').read_bytes()),
        observations_sha256=coverage['observations_sha256'], design_sha256=inputs.sha((root/'docs/sentinel-signal-study.md').read_bytes()),
        feature_names=names, tiers=tiers, horizons=[1,5,20], positive_relative_gain=.01,
        model_settings=dict(logistic_C=1, tree_depth=2, tree_min_leaf=25, min_train=200, min_each_class=20,
                            threshold='training score 90th percentile, ties included'),
        folds=protocol.folds(dates))
    inputs.write_json(output/'protocol.json', spec)
    jsonl(output/'features.jsonl', [dict(session=d, values={name:float(v) if np.isfinite(v) else None for name,v in zip(names,row)})
                                   for d,row in zip(dates,x)])
    jsonl(output/'labels.jsonl', labels)
    inputs.write_json(output/'oracle-profiles.json', profiles(rows, recovered, x, names, actual, anatomy['changed_decisions']))
    result = probes.run(x, names, tiers, labels, dates, set(anatomy['changed_decisions']))
    jsonl(output/'predictions.jsonl', result['predictions'])
    inputs.write_json(output/'models.json', result['models'])
    inputs.write_json(output/'unavailable.json', result['unavailable'])
    checked = dict(status='PASS', retained_observations=observed,
        labels=audit.labels(rows, actual, labels, anatomy['changed_decisions'], result['folds']),
        models=audit.models(result, x, names, dates, labels))
    inputs.write_json(output/'audit.json', checked)
    distributions = []
    for h in (1,5,20):
        for task in ('exit','entry','partial'):
            records = [r for r in labels if r['horizon']==h and r['task']==task]
            distributions.append(dict(horizon=h, task=task, n=len(records),
                positive=sum(r['positive'] is True for r in records),
                best_actions=dict(Counter(str(r['best_action']) for r in records)),
                best_beats_baseline=sum(r['best_beats_baseline'] for r in records)))
    summary = dict(schema=spec['schema'], start=dates[0], end=dates[-1], closes=len(rows),
        protocol_sha256=inputs.sha((output/'protocol.json').read_bytes()), anatomy={k:v for k,v in anatomy.items() if k not in ('episodes','changed_flags')},
        coverage=coverage, complete_feature_dates={k:int(np.isfinite(x[:,v]).all(axis=1).sum()) for k,v in tiers.items()},
        opportunity_distributions=distributions, probes=result['summary'], audit=checked,
        caveat='Fixed chronological diagnostic probes on repeatedly researched history. Local gains overlap; no new strategy CAGR or independent certification.')
    inputs.write_json(output/'summary.json', summary)
    report.write(output, summary, anatomy)
    return summary


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot','observations','anchor','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    with CoreGuard() as guard:
        result = run(**vars(args))
    inputs.write_json(args.output/'core-preservation.json', guard.receipt())
    print(json.dumps(dict(status='COMPLETE', audit=result['audit'], complete_feature_dates=result['complete_feature_dates']), indent=2), flush=True)
