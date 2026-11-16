"""Causal close features and independently bounded hindsight labels."""
from datetime import date
from decimal import Decimal as D
import math

import numpy as np

from . import accounting as A, search

LOOKBACK = 63
ACTIONS = (D(0),D('.55'),D(1))
PRICE_FEATURES = (*[f'lag_return_{k}' for k in range(1,6)],
    *[f'momentum_{k}' for k in (5,20,63)],
    *[f'volatility_{k}' for k in (5,20,63)],
    *[f'drawdown_{k}' for k in (20,63)],
    *[f'mean_deviation_{k}' for k in (20,63)])
FEATURES = tuple(f'{asset}_{name}' for asset in ('core','spy') for name in PRICE_FEATURES)+(
    'relative_momentum_20','relative_momentum_63','core_cash_fraction','core_positions_per_20',
    'core_healthy','core_impaired','native_fast_severe','native_slow_severe')


def feature_matrix(rows: list[dict]) -> np.ndarray:
    dates = [date.fromisoformat(r['session']) for r in rows]
    if any(a >= b for a,b in zip(dates,dates[1:])):
        raise ValueError('feature sessions must be strictly increasing')
    levels = {asset:np.array([float(A.number(r[asset]['nav'],positive=True)) for r in rows])
              for asset in ('core','spy')}
    if any(not np.isfinite(values).all() for values in levels.values()):
        raise ValueError('feature levels must be finite')
    logs = {asset:np.log(values) for asset,values in levels.items()}
    returns = {asset:np.diff(values) for asset,values in logs.items()}
    result = np.full((len(rows),len(FEATURES)),np.nan)
    for i in range(LOOKBACK,len(rows)):
        values = []
        for asset in ('core','spy'):
            p,r = levels[asset],returns[asset]
            values.extend(float(r[i-k]) for k in range(1,6))
            values.extend(float(logs[asset][i]-logs[asset][i-k]) for k in (5,20,63))
            values.extend(float(np.std(r[i-k:i],ddof=1)) for k in (5,20,63))
            values.extend(float(p[i]/max(p[i-k+1:i+1])-1) for k in (20,63))
            values.extend(float(np.log(p[i]/np.mean(p[i-k+1:i+1]))) for k in (20,63))
        values.extend(float((logs['core'][i]-logs['core'][i-k])-
                            (logs['spy'][i]-logs['spy'][i-k])) for k in (20,63))
        row = rows[i]
        held = row['held']
        if type(held) is not int or held < 0:
            raise ValueError('invalid canonical position count')
        values.extend((float(A.number(row['cash']))/levels['core'][i],held/20))
        owned,decision = row['decision']['owned_impairment'],row['decision']
        flags = (owned['healthy'],owned['impaired'],decision['fast_severe_active'],decision['slow_severe_active'])
        if any(type(x) is not bool for x in flags):
            raise ValueError('feature flags must be boolean')
        values.extend(float(x) for x in flags)
        if len(values) != len(FEATURES) or not np.isfinite(values).all():
            raise ValueError('invalid finite feature vector')
        result[i] = values
    return result


def partitions(rows: list[dict], train_end: str, validation_end: str) -> dict[str,tuple[int,int]]:
    dates = [r['session'] for r in rows]
    if train_end not in dates or validation_end not in dates:
        raise ValueError('split boundaries must be completed session closes')
    train,validation,last = dates.index(train_end),dates.index(validation_end),len(rows)-1
    if not LOOKBACK+20 <= train < validation < last or min(validation-train,last-validation) < 20:
        raise ValueError('chronological train/validation/test periods are too short or overlap')
    return dict(train=(0,train),validation=(train,validation),test=(validation,last))


def teacher(rows: list[dict], left: int, right: int) -> dict:
    if not 0 <= left < right < len(rows):
        raise ValueError('invalid bounded teacher period')
    selected = rows[left:right+1]
    days,initial,actual = A.tape(selected,canonical=False)
    A.make_grid(initial,actual)
    recorded = A.replay(days,initial,actual,selected[0]['session'])
    matrices = np.stack([d.matrix(ACTIONS) for d in days])
    solution = search.unconstrained(matrices,ACTIONS.index(initial),len(ACTIONS))
    ideal = A.replay(days,initial,[ACTIONS[i] for i in solution.path],selected[0]['session'])
    if ideal['maxdd'] > recorded['maxdd']+1e-13:
        solution = search.constrained(matrices,ACTIONS.index(initial),recorded['maxdd'])
        if solution is None:
            raise ValueError('recorded exposure must be a feasible teacher path')
        ideal = A.replay(days,initial,[ACTIONS[i] for i in solution.path],selected[0]['session'],recorded['maxdd'])
    if (ideal['maxdd'] > recorded['maxdd']+1e-10 or
            D(ideal['multiple']) < D(recorded['multiple'])*(1-D('1e-10')) or
            abs(math.log(float(ideal['multiple']))-solution.log_wealth) > 1e-10):
        raise ValueError('teacher failed independent growth/drawdown replay')
    return dict(left=left,right=right,start=selected[0]['session'],end=selected[-1]['session'],
                cap=recorded['maxdd'],labels=solution.path,path=ideal)


def supervised(rows: list[dict], features: np.ndarray, ideal: dict) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
    left,right = ideal['left'],ideal['right']
    if (ideal['start'] != rows[left]['session'] or ideal['end'] != rows[right]['session'] or
            len(ideal['labels']) != right-left):
        raise ValueError('teacher label horizon differs from its bounded period')
    indices = np.arange(max(LOOKBACK,left),right)
    labels = np.asarray(ideal['labels'],dtype=int)[indices-left]
    x = features[indices]
    if not len(indices) or not np.isfinite(x).all() or not np.isin(labels,[0,1,2]).all():
        raise ValueError('invalid supervised features or three-action labels')
    # Feature at close i predicts the action applied on return session i+1.
    if any(rows[i+1]['session'] > ideal['end'] for i in indices):
        raise ValueError('label outcome crosses its period boundary')
    return indices,x,labels


def counts(labels: np.ndarray) -> dict[str,int]:
    return {str(a):int(np.sum(labels == i)) for i,a in enumerate(ACTIONS)}
