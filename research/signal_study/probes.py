"""Fixed diagnostic classifiers, fit only to fully ended earlier outcomes."""
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier, export_text

from research.structured_search import protocol


def eligible(records, finite, left, right):
    train = [r for r in records if r['end']<=left and finite[r['t']]]
    test = [r for r in records if left<=r['t'] and r['end']<=right and finite[r['t']]]
    if any(r['t']>=left or r['end']>left for r in train):
        raise ValueError('training outcome crosses frozen boundary')
    if any(r['t']<left or r['end']>right for r in test):
        raise ValueError('test opportunity crosses its declared block')
    return train, test


def fit(x, y, kind, names):
    if len(x)<200 or min(np.bincount(y.astype(int), minlength=2))<20:
        return None
    scaler = StandardScaler().fit(x)
    scaled = scaler.transform(x)
    model = (LogisticRegression(C=1., max_iter=3000, random_state=1729) if kind=='logistic'
             else DecisionTreeClassifier(max_depth=2, min_samples_leaf=25, random_state=1729))
    with warnings.catch_warnings():
        warnings.simplefilter('error', ConvergenceWarning)
        model.fit(scaled, y)
    score = model.predict_proba(scaled)[:, 1]
    threshold = float(np.quantile(score, .9))
    exported = dict(kind=kind, features=names, mean=scaler.mean_.tolist(), scale=scaler.scale_.tolist(),
                    threshold=threshold, training_flag_rate=float(np.mean(score>=threshold)))
    if kind=='logistic':
        exported.update(coefficients=model.coef_[0].tolist(), intercept=float(model.intercept_[0]))
    else:
        tree = model.tree_
        exported.update(tree=dict(children_left=tree.children_left.tolist(), children_right=tree.children_right.tolist(),
            feature=tree.feature.tolist(), threshold=tree.threshold.tolist(), value=tree.value[:, 0, :].tolist()),
            rule=export_text(model, feature_names=names))
    return model, scaler, exported


def metrics(records):
    if not records: return dict(n=0)
    y = np.array([r['positive'] for r in records], dtype=bool)
    p = np.array([r['score'] for r in records]); flag = np.array([r['flag'] for r in records], dtype=bool)
    gains = np.array([r['gain'] for r in records]); n = int(flag.sum())
    return dict(n=len(records), positives=int(y.sum()), base_rate=float(y.mean()),
        auc=float(roc_auc_score(y,p)) if 0<y.sum()<len(y) else None,
        average_precision=float(average_precision_score(y,p)) if y.any() else None,
        flagged=n, true_positives=int((flag&y).sum()), false_alarms=int((flag&~y).sum()),
        precision=float(y[flag].mean()) if n else None,
        recall=float((flag&y).sum()/y.sum()) if y.any() else None,
        mean_flagged_gain=float(gains[flag].mean()) if n else None,
        median_flagged_gain=float(np.median(gains[flag])) if n else None,
        losing_flags=int((flag&(gains<0)).sum()),
        mean_all_gain=float(gains.mean()),
        oracle_eligible=sum(r['oracle_change'] for r in records),
        oracle_captured=sum(r['oracle_change'] and r['flag'] for r in records))


def run(x, names, tiers, labels, dates, oracle_changes):
    folds = protocol.folds(dates)
    predictions, models, unavailable = [], [], []
    for tier, columns in tiers.items():
        finite = np.isfinite(x[:, columns]).all(axis=1)
        views = [('augmented', columns)] if tier=='existing' else [('matched_existing', tiers['existing']), ('augmented', columns)]
        for horizon in (1, 5, 20):
            for task in ('exit', 'entry'):
                records = [r for r in labels if r['horizon']==horizon and r['task']==task]
                for fold in folds:
                    train, test = eligible(records, finite, fold['left'], fold['right'])
                    for view, selected in views:
                        for kind in ('logistic', 'tree'):
                            key = dict(tier=tier, view=view, horizon=horizon, task=task, fold=fold['id'], model=kind)
                            if not test:
                                unavailable.append(dict(**key, train=len(train), test=0, reason='no eligible test dates'))
                                continue
                            index = [r['t'] for r in train]
                            fitted = fit(x[np.ix_(index, selected)], np.array([r['positive'] for r in train]),
                                         kind, [names[c] for c in selected])
                            if fitted is None:
                                unavailable.append(dict(**key, train=len(train), test=len(test), reason='insufficient training class support'))
                                continue
                            model, scaler, export = fitted
                            export.update(key, train_indices=index, test_indices=[r['t'] for r in test],
                                training_cutoff=dates[fold['left']],
                                last_training_outcome=dates[max(r['end'] for r in train)])
                            models.append(export)
                            p = model.predict_proba(scaler.transform(x[np.ix_([r['t'] for r in test], selected)]))[:, 1]
                            for r, score in zip(test, p):
                                predictions.append(dict(**key, t=r['t'], session=dates[r['t']], end=dates[r['end']],
                                    positive=r['positive'], gain=r['gain'], score=float(score),
                                    threshold=export['threshold'], flag=bool(score>=export['threshold']),
                                    oracle_change=r['t'] in oracle_changes))
                    print(f"PROBE {tier} h={horizon} {task} block={fold['id']} train={len(train)} test={len(test)}", flush=True)
    groups = {}
    for row in predictions:
        key = (row['tier'], row['view'], row['horizon'], row['task'], row['model'])
        groups.setdefault(key, []).append(row)
    summary = []
    for key, values in groups.items():
        summary.append(dict(zip(('tier','view','horizon','task','model'), key),
            aggregate=metrics(values), blocks={f['id']:metrics([v for v in values if v['fold']==f['id']]) for f in folds}))
    return dict(summary=summary, unavailable=unavailable, models=models, predictions=predictions, folds=folds)
