"""Hindsight descriptions and bounded, next-open local opportunity outcomes."""
import math

import numpy as np

from research.exposure_oracle import accounting as A, target_analysis
from research.structured_search import data

HORIZONS = (1, 5, 20)


def local_labels(matrix, actions, initial, horizons=HORIZONS):
    """Decision t is applied on return t; outcome rejoin closes at t+h+1."""
    result = []
    n = len(actions)
    for h in horizons:
        if h<1: raise ValueError('positive holding horizon required')
        for t in range(data.WARMUP, n-h):
            old = int(actions[t-1]) if t else initial
            baseline = data.returns(matrix[t:t+h+1], actions[t:t+h+1], old).sum()
            gains = []
            for action in range(3):
                override = np.r_[np.full(h, action), actions[t+h]]
                value = data.returns(matrix[t:t+h+1], override, old).sum()
                gains.append(float(np.expm1(value-baseline)))
            task = 'exit' if actions[t]==2 else 'entry' if actions[t]==0 else 'partial'
            fixed_action = 0 if task=='exit' else 2 if task=='entry' else None
            result.append(dict(t=t, end=t+h+1, horizon=h, task=task,
                gain=gains[fixed_action] if fixed_action is not None else None,
                positive=gains[fixed_action]>=.01 if fixed_action is not None else None,
                gains=gains, best_action=float(data.GRID[int(np.argmax(gains))]),
                best_beats_baseline=max(gains)>0))
    return result


def decompose(day, old, new):
    net, gross, cost, _ = day.factors(old, new)
    if day.fixed is not None:
        return np.array([0., 0., math.log(float(gross)), math.log(float(cost))])
    gap = old*day.core_gap+(1-old)*day.bil_gap
    intraday = new*day.core_day+(1-new)*day.bil_day
    return np.array([math.log(float(gap)), math.log(float(intraday)),
                     math.log(float(gross/(gap*intraday))), math.log(float(cost))])


def anatomy(rows, days, initial, actual, target):
    if len(target)!=len(actual): raise ValueError('oracle path length changed')
    grid = A.make_grid(initial, actual)
    if any(a not in grid for a in target): raise ValueError('oracle action outside allowed states')
    baseline = A.replay(days, initial, actual, rows[0]['session'])
    oracle = A.replay(days, initial, target, rows[0]['session'])
    parts = []
    for i, day in enumerate(days):
        old_a = actual[i-1] if i else initial
        old_o = target[i-1] if i else initial
        parts.append(decompose(day, old_o, target[i])-decompose(day, old_a, actual[i]))
    parts = np.array(parts)
    total = parts.sum(axis=0)
    expected = math.log(float(A.D(oracle['multiple'])/A.D(baseline['multiple'])))
    if abs(sum(total)-expected)>1e-11:
        raise ValueError('oracle gap/intraday/cost attribution does not reconcile')
    changed = [i for i, (a, b) in enumerate(zip(actual, target)) if a!=b]
    groups = []
    for i in changed:
        if groups and i==groups[-1][-1]+1: groups[-1].append(i)
        else: groups.append([i])
    labels = ('overnight_log', 'intraday_log', 'allocation_residual_log', 'cost_log')
    episodes = []
    for g in groups:
        start, last = g[0], g[-1]
        end = min(last+1, len(days)-1)
        value = parts[start:end+1].sum(axis=0)
        episodes.append(dict(decision=rows[start]['session'], first_return=days[start].session,
            last_changed_return=days[last].session, through=days[end].session,
            decision_indices=g, changed_days=len(g), direction='exit' if target[start]<actual[start] else 'entry',
            **dict(zip(labels, map(float, value))), net_log=float(sum(value)),
            flags=target_analysis.signals(rows[start])))
    if abs(sum(e['net_log'] for e in episodes)-expected)>1e-11:
        raise ValueError('episode partition loses or overlaps oracle economics')
    return dict(actual={k:baseline[k] for k in ('cagr','maxdd','multiple','switches')},
        target={k:oracle[k] for k in ('cagr','maxdd','multiple','switches')},
        totals={**dict(zip(labels, map(float, total))), 'net_log':expected},
        changed_decisions=changed, episodes=episodes,
        changed_flags=[dict(t=i, session=rows[i]['session'], actual=float(actual[i]),
            target=float(target[i]), **target_analysis.signals(rows[i])) for i in changed],
        caveat='A minimal-change full-history target; not unique or usable as causal training labels.')
