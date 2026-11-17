"""The reproducible candidate grammar and chronological selection contract."""
import json
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

SEED = 1729
PER_FAMILY = 144
FAMILIES = ('state', 'trend', 'predictive', 'combination')


class Candidate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    id: str
    family: Literal['state', 'trend', 'predictive', 'combination']
    params: dict[str, int | float | str]


def menu(seed=SEED, count=PER_FAMILY):
    if count < 3 or count % 3:
        raise ValueError('family budget must be a positive multiple of three')
    rng = np.random.default_rng(seed)
    def draw(options):
        return {key: values[int(rng.integers(len(values)))] for key, values in options.items()}
    def sample(family, options, size, prefix='', fixed=None):
        seen, result = set(), []
        while len(result) < size:
            p = {**(fixed or {}), **draw(options)}
            key = json.dumps(p, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            result.append(Candidate(id=f'{family}{prefix}-{len(result):03d}', family=family, params=p))
        return result
    state = sample('state', dict(entry=[1,2,3,5,8], release=[1,3,5,8,13],
        expiry=[0,5,10,21,42,84], recovery=[1,3,5,8], timeout=[0,5,10,21,42]), count)
    trend = sample('trend', dict(asset=['core','spy','blend'], momentum=[5,20,63],
        drawdown=[20,63], severe_momentum=[-.10,-.05,-.02], severe_dd=[-.08,-.12,-.18],
        warning_momentum=[-.02,0.,.02], warning_vol=[.012,.018,.025],
        severe_vol=[.03,.04,.06], down=[1,2,3], up=[1,3,5,8], hold=[1,3,5,10]), count)
    predictive = []
    for model in ('ridge','tree','neural'):
        opts = dict(features=['price','health','all'], horizon=[5,10,21], risk=[0.,.1,.3],
                    low=[-.05,-.02,0.], high=[.02,.05,.1], down=[1,2,3], up=[1,3,5], hold=[1,3,5])
        if model == 'ridge': opts.update(alpha=[1.,10.,100.])
        elif model == 'tree': opts.update(depth=[2,3,5], leaf=[25,50,100])
        else: opts.update(width=[8,16], alpha=[.001,.01,.1], rate=[.003,.01])
        predictive.extend(sample('predictive', opts, count//3, '-'+model, dict(model=model)))
    combo = sample('combination', dict(state=list(range(count)), trend=list(range(count)),
                   predictive=list(range(count)), vote=['minimum','median','mean']), count)
    return [*state,*trend,*predictive,*combo]


def folds(dates):
    result = []
    for start in (2013,2015,2017,2019,2021):
        left = max(i for i,d in enumerate(dates) if d < f'{start}-01-01')
        right = max(i for i,d in enumerate(dates) if d <= f'{start+1}-12-31')
        val_left = max(i for i,d in enumerate(dates) if d < f'{start-3}-01-01')
        if not 63 < val_left < left < right:
            raise ValueError('history does not cover declared chronological folds')
        result.append(dict(id=str(start), fit_end=val_left, val_left=val_left,
            val_right=left, left=left, right=right, fit_through=dates[val_left],
            validation_first=dates[val_left+1], validation_end=dates[left],
            test_first=dates[left+1], test_end=dates[right]))
    if result[-1]['right'] != len(dates)-1:
        raise ValueError('protocol ends in 2022; a new extension requires a declared protocol')
    return result


def choose(records, baseline, family=None):
    eligible = [baseline, *(r for r in records if (family is None or r['family']==family)
        and r['metrics']['maxdd'] <= baseline['metrics']['maxdd']+1e-10)]
    return min(eligible, key=lambda r:(-r['metrics']['cagr'], r['metrics']['turnover'],
                                     r['metrics']['switches'], r['id']))


def nearest(candidate, candidates, count=5):
    same = [c for c in candidates if c.family==candidate.family and c.id!=candidate.id
            and c.params.get('model')==candidate.params.get('model')]
    def distance(other):
        total = 0.
        for k,v in candidate.params.items():
            w = other.params[k]
            if isinstance(v, str): total += v != w
            else:
                options = [float(c.params[k]) for c in [candidate,*same]]
                span = max(options)-min(options)
                total += abs(float(v)-float(w))/span if span else 0
        return total, other.id
    return [c.id for c in sorted(same,key=distance)[:count]]
