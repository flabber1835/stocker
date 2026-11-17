"""Close-dated features; unavailable historical observations stay unavailable."""
import json
from pathlib import Path

import numpy as np

from research.exposure_oracle import inputs
from research.structured_search import data

MEMORY = ('base_dur', 'base_fast_age', 'fast_age', 'slow_age', 'ordinary_age',
          'fast_h', 'slow_h', 'ordinary_h', 'base_fast_h', 'fast_armed',
          'binary_armed', 'base_fast_armed', 'ordinary', 'base_fast')
ANATOMY = ('core_gap_today', 'core_intraday_today', 'core_gap_mean5',
           'core_intraday_mean5', 'core_downside20', 'core_up_fraction5',
           'core_negative_gap_fraction20', 'core_rebound20', 'core_peak_dd',
           'core_peak_dd_change5', 'core_momentum_acceleration',
           'core_vol_acceleration', 'spy_vol_acceleration',
           'core_spy_correlation20', 'relative_momentum5', 'recorded_stops20')
LEADERSHIP = ('leadership_r5', 'leadership_r20', 'leadership_r40',
              'leadership_minus_core20', 'leadership_minus_spy20',
              'leadership_acceleration', 'leadership_dd20', 'leadership_vol20')
DAMAGE = ('damaged_breadth', 'damaged_breadth_change1')


def load_observations(folder: Path, snapshot: Path, rows):
    summary = json.loads((folder/'summary.json').read_text())
    manifest = json.loads((snapshot/'manifest.json').read_text())
    blob = (folder/'observations.jsonl').read_bytes()
    if summary['source_manifest'] != manifest or inputs.sha(blob) != summary['observations_sha256']:
        raise ValueError('recovered observations are bound to different input bytes')
    records = [json.loads(line) for line in blob.splitlines()]
    if [r['session'] for r in records] != [r['session'] for r in rows]:
        raise ValueError('recovered observation dates differ from Core tape')
    for record in records:
        for key, value in record['values'].items():
            if not np.isfinite(float(value)):
                raise ValueError('nonfinite recovered value')
            if record['origins'][key]['preserved_through'] < record['session']:
                raise ValueError('preservation checkpoint predates its observation')
    return records, summary


def build(rows, records):
    if [r['session'] for r in rows] != [r['session'] for r in records]:
        raise ValueError('features require exact dated observations')
    n = len(rows)
    names = [*data.FEATURES, *ANATOMY, *('native_'+k for k in MEMORY), *LEADERSHIP, *DAMAGE]
    base = data.features(rows)
    x = np.full((n, len(names)), np.nan)
    x[:, :len(data.FEATURES)] = base
    levels = {a: np.array([float(r[a]['nav']) for r in rows]) for a in ('core', 'spy')}
    logs = {a: np.log(v) for a, v in levels.items()}
    ret = {a: np.r_[np.nan, np.diff(v)] for a, v in logs.items()}
    peak_dd = levels['core']/np.maximum.accumulate(levels['core'])-1
    gap = np.full(n, np.nan); intra = np.full(n, np.nan)
    for i in range(1, n):
        e, p = rows[i]['economics'], rows[i-1]['economics']
        gap[i] = np.log(float(e['parent_core_open_equity'])/float(p['parent_core_close_equity']))
        intra[i] = np.log(float(e['parent_core_close_equity'])/float(e['parent_core_open_equity']))
    witness = np.array([r['values'].get('leadership_nav', np.nan) for r in records])
    damage = np.array([r['values'].get('recorded_damaged_breadth', np.nan) for r in records])
    stops = np.array([r['values'].get('recorded_stops_today', np.nan) for r in records])
    for i in range(data.WARMUP, n):
        c5 = ret['core'][i-4:i+1]; c20 = ret['core'][i-19:i+1]
        s20 = ret['spy'][i-19:i+1]
        corr = float(np.corrcoef(c20, s20)[0, 1]) if np.std(c20)*np.std(s20)>0 else 0.
        def acceleration(a):
            v = ret[a]
            return np.std(v[i-4:i+1])/max(np.std(v[i-19:i+1]), 1e-12)-1
        v = [gap[i], intra[i], np.mean(gap[i-4:i+1]), np.mean(intra[i-4:i+1]),
             np.sqrt(np.mean(np.minimum(c20, 0)**2)), np.mean(c5>0),
             np.mean(gap[i-19:i+1]<0), levels['core'][i]/min(levels['core'][i-19:i+1])-1,
             peak_dd[i], peak_dd[i]-peak_dd[i-5],
             np.sum(c5)-np.sum(c20)/4, acceleration('core'), acceleration('spy'), corr,
             np.sum(c5)-np.sum(ret['spy'][i-4:i+1]), np.sum(stops[i-19:i+1])]
        state = rows[i]['decision']['evidence']['native_snapshot']['state']
        v.extend(float(state[k]) if state[k] is not None else np.nan for k in MEMORY)
        w = witness[i-40:i+1]
        if np.isfinite(w).all() and np.all(w>0):
            r5, r20, r40 = (w[-1]/w[-1-k]-1 for k in (5, 20, 40))
            v.extend([r5, r20, r40, r20-(levels['core'][i]/levels['core'][i-20]-1),
                      r20-(levels['spy'][i]/levels['spy'][i-20]-1),
                      r5-r20/4, w[-1]/max(w[-20:])-1, np.std(np.diff(np.log(w[-21:])))])
        else:
            v.extend([np.nan]*len(LEADERSHIP))
        v.extend([damage[i], damage[i]-damage[i-1]])
        x[i, len(data.FEATURES):] = v
    end_base = len(data.FEATURES)
    end_anatomy = end_base+len(ANATOMY)+len(MEMORY)
    end_lead = end_anatomy+len(LEADERSHIP)
    tiers = dict(existing=list(range(end_base)), anatomy=list(range(end_anatomy)),
                 leadership=list(range(end_lead)), breadth=list(range(len(names))))
    return x, names, tiers
