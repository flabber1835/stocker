"""Causal observations and fast, checked scalar-overlay accounting."""
from datetime import date
import numpy as np

from research.exposure_oracle import accounting as A, neural_data

GRID = np.array([0., .55, 1.])
FEATURES = (*neural_data.FEATURES, 'sentinel_target', 'native_target', 'champion_target',
            'healthy_streak', 'impaired_streak', 'sentinel_state_age')
WARMUP = neural_data.LOOKBACK


def features(rows):
    base = neural_data.feature_matrix(rows)
    extras = np.zeros((len(rows),6))
    healthy = impaired = age = 0
    prior = None
    for i,row in enumerate(rows):
        d = row['decision']; owned = d['owned_impairment']
        healthy = healthy+1 if owned['healthy'] else 0
        impaired = impaired+1 if owned['impaired'] else 0
        target = float(A.allocation(d['target_core_exposure']))
        if target not in GRID: raise ValueError('recorded target outside action grid')
        age = age+1 if target==prior else 1
        extras[i] = [target, float(A.allocation(d['native_target_core_exposure'])),
            float(A.allocation(d['champion_target_core_exposure'])),
            min(healthy,63)/63, min(impaired,63)/63, min(age,252)/252]
        prior = target
    x = np.column_stack((base,extras))
    if not np.isfinite(x[WARMUP:]).all(): raise ValueError('nonfinite observations')
    return x


def columns(group):
    if group=='price': return list(range(32))
    if group=='health': return [*range(36),41,42]
    if group=='all': return list(range(len(FEATURES)))
    raise ValueError('unknown feature group')


def labels(days, horizon, cutoff):
    """Outcome ends by cutoff close; first owned return is next-open intraday."""
    if not 0 < horizon <= 21 or not WARMUP+horizon <= cutoff <= len(days):
        raise ValueError('invalid purged label boundary')
    indices = np.arange(WARMUP, cutoff-horizon+1)
    full = np.array([np.log(float(d.core_full/d.bil_full)) for d in days[:cutoff]])
    intra = np.array([np.log(float(d.core_day/d.bil_day)) for d in days[:cutoff]])
    y = np.zeros((len(indices),2))
    for j,i in enumerate(indices):
        path = np.cumsum(np.r_[intra[i],full[i+1:i+horizon]])
        y[j] = [path[-1]*252/horizon, max(0.,-float(path.min()))*252/horizon]
    if indices[-1]+horizon > cutoff or not np.isfinite(y).all():
        raise ValueError('future label crosses training boundary')
    return indices,y


def action_indices(values):
    a = np.asarray(values, dtype=float)
    if not np.isfinite(a).all() or not np.isin(a,GRID).all():
        raise ValueError('invalid long-only three-state action')
    return np.searchsorted(GRID,a)


def matrices(days, cost=.001):
    result = np.stack([d.matrix(tuple(A.D(str(x)) for x in GRID)) for d in days])
    if cost != .001:
        if not 0 <= cost < .1: raise ValueError('invalid transaction cost')
        turns = np.abs(GRID[:,None]-GRID[None,:])
        result += np.log1p(-cost*turns)-np.log1p(-.001*turns)
        for i,d in enumerate(days):
            if d.fixed is not None: result[i] = d.matrix(tuple(A.D(str(x)) for x in GRID))
    return result


def apply(decisions, days):
    """Decision close i supplies open i+1; no return is owned in advance."""
    result = action_indices(np.asarray(decisions)[:-1])
    if len(result)!=len(days): raise ValueError('incomplete decisions')
    for i,d in enumerate(days):
        if d.fixed is not None: result[i] = int(action_indices([float(d.fixed)])[0])
    return result


def returns(matrix, actions, initial):
    actions = np.asarray(actions,dtype=int)
    if np.any((actions<0)|(actions>2)) or len(actions)!=len(matrix):
        raise ValueError('invalid applied action indices')
    old = np.r_[initial,actions[:-1]]
    result = matrix[np.arange(len(matrix)),old,actions]
    if not np.isfinite(result).all(): raise ValueError('invalid economic transition')
    return result


def metrics(logs, dates, actions=None, initial=None):
    logs = np.asarray(logs)
    wealth = np.r_[0.,np.cumsum(logs)]
    elapsed = (date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days
    if elapsed<=0 or len(dates)!=len(logs)+1 or not np.isfinite(wealth).all():
        raise ValueError('invalid performance window')
    result = dict(cagr=float(np.expm1(wealth[-1]*365.2425/elapsed)),
                  multiple=float(np.exp(wealth[-1])),
                  maxdd=float(-np.expm1(np.min(wealth-np.maximum.accumulate(wealth)))))
    if actions is not None:
        delta = GRID[actions]-GRID[np.r_[initial,actions[:-1]]]
        result.update(turnover=float(np.abs(delta).sum()), switches=int(np.count_nonzero(delta)),
                      mean_exposure=float(GRID[actions].mean()))
    return result


def window(matrix, actions, initial, dates, left, right):
    old = int(actions[left-1]) if left else initial
    logs = returns(matrix[left:right],actions[left:right],old)
    return metrics(logs,dates[left:right+1],actions[left:right],old)
