"""Independent Decimal economics and exported-model checks."""
from decimal import Decimal as D
import math

import numpy as np


def raw_growth(rows, t, actions, old):
    wealth = D(1)
    for j, new in enumerate(actions, start=t+1):
        e, p = rows[j]['economics'], rows[j-1]['economics']
        co, cc, cp = (D(str(v)) for v in (e['parent_core_open_equity'],
            e['parent_core_close_equity'], p['parent_core_close_equity']))
        bo, bc, bp = (D(str(e[k])) for k in ('bil_open_adjusted', 'bil_close_adjusted',
                                           'bil_previous_close_adjusted_current_publication'))
        new = D(str(new)); old = D(str(old))
        if new==old:
            gross = new*cc/cp+(1-new)*bc/bp
        else:
            gross = (old*co/cp+(1-old)*bo/bp)*(new*cc/co+(1-new)*bc/bo)
        wealth *= gross*(1-D('.001')*abs(new-old))
        old = new
    return wealth


def labels(rows, actual, records, changed, folds):
    selected = set(changed)
    selected.update(range(63, len(rows)-21, 97))
    for f in folds:
        selected.update(range(f['left']-22, f['left']+2))
    checks = 0; maximum = 0.
    for r in records:
        if r['t'] not in selected: continue
        t, h = r['t'], r['horizon']
        if r['end']!=t+h+1 or r['end']>=len(rows): raise ValueError('label endpoint changed')
        old = actual[t-1]
        base = raw_growth(rows, t, actual[t:t+h+1], old)
        for j, action in enumerate((D(0), D('.55'), D(1))):
            target = raw_growth(rows, t, [action]*h+[actual[t+h]], old)
            error = abs(float(target/base-1)-r['gains'][j])
            maximum = max(maximum, error)
            if error>2e-12: raise ValueError('local outcome differs from independent raw-ledger economics')
            checks += 1
    return dict(action_windows=checks, max_gain_error=maximum)


def scores(model, x):
    a = (x-np.array(model['mean']))/np.array(model['scale'])
    if model['kind']=='logistic':
        logit = a@np.array(model['coefficients'])+model['intercept']
        return np.exp(-np.logaddexp(0., -logit))
    tree = model['tree']; values = []
    for row in a:
        node = 0
        # sklearn's tree predictor converts input to float32.
        while tree['children_left'][node]!=tree['children_right'][node]:
            node = (tree['children_left'][node] if np.float32(row[tree['feature'][node]])<=tree['threshold'][node]
                    else tree['children_right'][node])
        v = tree['value'][node]
        values.append(v[1]/sum(v))
    return np.array(values)


def models(result, x, names, dates, records):
    lookup = {(r['t'], r['horizon'], r['task']):r for r in records}
    def key(r): return tuple(r[k] for k in ('tier','view','horizon','task','fold','model'))
    grouped = {}
    for r in result['predictions']: grouped.setdefault(key(r), []).append(r)
    checks = 0
    for m in result['models']:
        columns = [names.index(k) for k in m['features']]
        train = m['train_indices']; test = m['test_indices']
        cutoff = dates.index(m['training_cutoff'])
        if any(lookup[t, m['horizon'], m['task']]['end']>cutoff for t in train):
            raise ValueError('model was trained on future outcomes')
        if set(train)&set(test) or any(t<cutoff for t in test):
            raise ValueError('model train/test boundary violated')
        expected_mean = x[np.ix_(train, columns)].mean(axis=0)
        if not np.allclose(expected_mean, m['mean'], rtol=1e-12, atol=1e-12):
            raise ValueError('scaler uses observations outside declared training dates')
        trained = scores(m, x[np.ix_(train, columns)])
        if abs(float(np.quantile(trained, .9))-m['threshold'])>1e-10:
            raise ValueError('decision threshold differs from training quantile')
        predicted = scores(m, x[np.ix_(test, columns)])
        saved = grouped[key(m)]
        if [r['t'] for r in saved]!=test or not np.allclose(predicted, [r['score'] for r in saved], atol=1e-10, rtol=1e-10):
            raise ValueError('frozen model does not reproduce saved predictions')
        if any(r['flag']!=(r['score']>=m['threshold']) for r in saved):
            raise ValueError('flag uses a different threshold')
        checks += len(test)
    # The baseline and augmented probes must use exactly the same dates, including training dates.
    by_key = {key(m):m for m in result['models']}
    pairs = 0
    for m in result['models']:
        if m['view']!='matched_existing': continue
        other = dict(m, view='augmented'); pair = by_key[key(other)]
        if m['train_indices']!=pair['train_indices'] or m['test_indices']!=pair['test_indices']:
            raise ValueError('feature tiers are not matched on the same dates')
        pairs += 1
    return dict(reproduced_predictions=checks, frozen_models=len(result['models']), matched_model_pairs=pairs)
