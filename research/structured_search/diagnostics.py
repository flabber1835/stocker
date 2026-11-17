"""Predeclared robustness, selection multiplicity and economic attribution."""
from pathlib import Path
import json

import numpy as np

from research.exposure_oracle import accounting as A, analysis, inputs
from . import data as D, protocol


def episodes(dates, candidate, baseline, old, delta, gross_delta):
    different = candidate!=baseline
    before = np.r_[False,different[:-1]]
    touched = different | before
    groups = []; start = None
    for i in range(len(touched)+1):
        if i<len(touched) and touched[i] and start is None: start=i
        if start is not None and (i==len(touched) or not touched[i]):
            groups.append(dict(first_return=dates[start+1],last_return=dates[i],sessions=i-start,
                changed_opens=int(different[start:i].sum()),left=start,right=i,
                net_log_gain=float(delta[start:i].sum()),gross_log_gain=float(gross_delta[start:i].sum()),
                cost_log_gain=float((delta[start:i]-gross_delta[start:i]).sum()),
                mean_exposure=float(D.GRID[candidate[start:i]].mean()),
                baseline_mean_exposure=float(D.GRID[baseline[start:i]].mean())))
            start=None
    if abs(sum(e['net_log_gain'] for e in groups)-float(delta.sum()))>1e-9:
        raise ValueError('difference episodes do not reconcile')
    return groups


def bootstrap_max(differences, observed, repetitions=500, block=20, seed=1729):
    """Circular block bootstrap max mean; exploratory, not a clean-holdout claim."""
    count,n = differences.shape
    if n<block*2 or not np.isfinite(differences).all(): raise ValueError('invalid bootstrap panel')
    rng = np.random.default_rng(seed)
    centered = differences-differences.mean(axis=1,keepdims=True)
    maxima = []
    for begin in range(0,repetitions,50):
        size = min(50,repetitions-begin)
        starts = rng.integers(0,n,(size,(n+block-1)//block))
        indices = ((starts[:,:,None]+np.arange(block))%n).reshape(size,-1)[:,:n]
        weights = np.stack([np.bincount(a,minlength=n) for a in indices]).T/n
        maxima.extend((centered@weights).max(axis=0).tolist())
    maxima = np.array(maxima)
    return dict(repetitions=repetitions,block_sessions=block,streams=count,
        corrected_p={k:float((1+np.sum(maxima>=v))/(repetitions+1)) for k,v in observed.items()},
        null_maximum_mean_log_quantiles=np.quantile(maxima,[.5,.9,.95,.99]).tolist(),
        caveat='This batch only; assumes block resampling is informative. Prior research searches are uncounted.')


def placebo(matrix, actions, old, dates, seed, repetitions=500):
    rng = np.random.default_rng(seed)
    shifts = rng.choice(np.arange(20,len(actions)-19),size=repetitions,replace=False)
    results = []
    actual = D.metrics(D.returns(matrix,actions,old),dates,actions,old)
    for shift in shifts:
        a = np.roll(actions,int(shift))
        m = D.metrics(D.returns(matrix,a,old),dates,a,old)
        results.append(dict(shift=int(shift),**m))
    return dict(actual=actual,repetitions=repetitions,
        cagr_percentile=float(np.mean([r['cagr']<actual['cagr'] for r in results])),
        cagr_quantiles=np.quantile([r['cagr'] for r in results],[.05,.5,.95]).tolist(),
        switch_range=[min(r['switches'] for r in results),max(r['switches'] for r in results)],
        turnover_range=[min(r['turnover'] for r in results),max(r['turnover'] for r in results)],
        caveat='Circular shifts preserve occupancy and interior durations; seam turnover is recomputed.',
        trials=results)


def assess(rows, days, initial, candidates, paths, selections, output: Path):
    dates = [r['session'] for r in rows]
    start = selections[0]['fold']['left']; stop = len(days)
    selected_dates = dates[start:]
    matrix = D.matrices(days); gross = D.matrices(days,0.)
    old = int(paths['baseline'][start-1])
    logs = {k:D.returns(matrix[start:],p[start:],old) for k,p in paths.items()}
    glogs = {k:D.returns(gross[start:],p[start:],old) for k,p in paths.items()}
    base = logs['baseline']
    names = ['selected',*protocol.FAMILIES]
    details = {}
    state_labels = [analysis.limiting_mechanism(rows[i]['decision'],float(D.GRID[paths['baseline'][i]]))
                    for i in range(start,stop)]
    for name in names:
        p = paths[name]; delta = logs[name]-base; gd = glogs[name]-glogs['baseline']
        ep = episodes(selected_dates,p[start:],paths['baseline'][start:],old,delta,gd)
        best = max([e['net_log_gain'] for e in ep]+[0.])
        block_gains = [float(delta[s['fold']['left']-start:s['fold']['right']-start].sum()) for s in selections]
        details[name] = dict(net_log_gain=float(delta.sum()),gross_log_gain=float(gd.sum()),
            cost_log_gain=float((delta-gd).sum()),changed_opens=int(np.sum(p[start:]!=paths['baseline'][start:])),
            episodes=ep,best_episode_log_gain=best,log_gain_without_best=float(delta.sum()-best),
            positive_blocks=sum(g>1e-12 for g in block_gains),block_log_gains=block_gains,
            timing_on_core_up_days=float(gd[np.array([float(d.core_full)>float(d.bil_full) for d in days[start:]])].sum()),
            timing_on_core_down_days=float(gd[np.array([float(d.core_full)<=float(d.bil_full) for d in days[start:]])].sum()),
            incumbent_states={label:dict(sessions=state_labels.count(label),
                log_gain=float(delta[np.array([s==label for s in state_labels])].sum()),
                candidate_mean_exposure=float(D.GRID[p[start:]][np.array([s==label for s in state_labels])].mean()))
                for label in sorted(set(state_labels))})
    stresses = {}
    for label,cost,delay in (('double_cost',.002,False),('one_session_late',.001,True)):
        mat = D.matrices(days,cost)
        stressed = {}
        for name,p in paths.items():
            a = np.r_[initial,p[:-1]] if delay else p
            for i,d in enumerate(days):
                if d.fixed is not None: a[i] = int(D.action_indices([float(d.fixed)])[0])
            stressed[name] = D.window(mat,a,initial,dates,start,stop)
        stresses[label] = stressed
    menu = protocol.menu(); by_id = {c.id:c for c in menu}
    neighbors = []
    for selection in selections:
        f = selection['fold']
        for name,chosen in selection['choices'].items():
            if chosen['id']=='baseline': continue
            ids = protocol.nearest(by_id[chosen['id']],menu)
            neighbors.append(dict(fold=f['id'],selector=name,chosen=chosen['id'],
                candidates=[dict(id=k,metrics=D.window(matrix,candidates[k],initial,dates,f['left'],f['right']))
                            for k in ids]))
    panel = np.stack([D.returns(matrix[start:],p[start:],old)-base for p in candidates.values()])
    panel = np.vstack((panel,np.stack([logs[n]-base for n in names])))
    multiplicity = bootstrap_max(panel,{n:float((logs[n]-base).mean()) for n in names})
    timing = {n:placebo(matrix[start:],paths[n][start:],old,selected_dates,protocol.SEED+i)
              for i,n in enumerate(names)}
    summary = json.loads((output/'summary.json').read_text())
    bm = summary['metrics']['baseline']
    gates = {}
    for name in names:
        m,d = summary['metrics'][name],details[name]
        checks = dict(higher_cagr=m['cagr']>bm['cagr']+1e-10,maxdd_within_baseline=m['maxdd']<=bm['maxdd']+1e-10,
            positive_in_three_blocks=d['positive_blocks']>=3,positive_without_best_episode=d['log_gain_without_best']>1e-10)
        for stress,values in stresses.items():
            checks[stress] = (values[name]['cagr']>values['baseline']['cagr']+1e-10
                              and values[name]['maxdd']<=values['baseline']['maxdd']+1e-10)
        gates[name] = dict(checks=checks,passes=all(checks.values()),
            target_25_to_30=.25<=m['cagr']<=.30,
            adjusted_bootstrap_p=multiplicity['corrected_p'][name],
            placebo_cagr_percentile=timing[name]['cagr_percentile'])
    inputs.write_json(output/'mechanics.json',details)
    inputs.write_json(output/'stress.json',stresses)
    inputs.write_json(output/'neighbors.json',neighbors)
    inputs.write_json(output/'multiplicity.json',multiplicity)
    inputs.write_json(output/'placebos.json',timing)
    inputs.write_json(output/'gates.json',gates)
    # Final public series use the existing Decimal accountant, independently
    # checked against the fast search engine before their monthly publication.
    public = {}
    for name,p in paths.items():
        path = A.replay(days[start:],A.D(str(D.GRID[old])),[A.D(str(D.GRID[a])) for a in p[start:]],dates[start])
        for metric in ('cagr','maxdd'):
            if abs(path[metric]-summary['metrics'][name][metric])>1e-10:
                raise ValueError('fast/Decimal finalist mismatch')
        public[name] = path
    nav = [A.D(r['spy']['nav'])/A.D(rows[start]['spy']['nav']) for r in rows[start:]]
    public['spy'] = dict(**A.performance(nav,selected_dates),nav=[str(x) for x in nav])
    inputs.write_json(output/'paths.json',public)
    inputs.write_json(output/'monthly.json',analysis.monthly(rows[start:],public))
    years = []
    for year in sorted({s[:4] for s in selected_dates[1:]}):
        pos = [i for i,s in enumerate(selected_dates) if i and s.startswith(year)]
        left,right = pos[0]-1,pos[-1]
        years.append(dict(year=year,baseline=selected_dates[left],end=selected_dates[right],
            series={n:float(A.D(p['nav'][right])/A.D(p['nav'][left])-1) for n,p in public.items()}))
    inputs.write_json(output/'yearly.json',years)
    summary.update(gates=gates,assessment='PROVISIONAL_IMPROVEMENT' if any(g['passes'] for g in gates.values())
                   else 'NO_CANDIDATE_PASSED_PREDECLARED_GATES')
    inputs.write_json(output/'summary.json',summary)
    return summary
