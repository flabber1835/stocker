"""Independent raw-ledger and bounded exhaustive audit of target-search evidence."""
import argparse
from datetime import date
from decimal import Decimal as D
import json
import math
from pathlib import Path

import numpy as np

from . import inputs

GRID=(D(0),D('.55'),D(1))


def factor(previous, row, old, new):
    p,e=previous['economics'],row['economics']
    if e['initial_deployment']:
        if new!=D(e['held_allocation']):
            return D(0)
        return D(e['net_factor'])
    close=D(e['parent_core_close_equity']); opened=D(e['parent_core_open_equity'])
    before=D(p['parent_core_close_equity'])
    bil_close=D(e['bil_close_adjusted']); bil_open=D(e['bil_open_adjusted'])
    bil_before=D(e['bil_previous_close_adjusted_current_publication'])
    if old==new:
        gross=new*close/before+(1-new)*bil_close/bil_before
    else:
        overnight=old*opened/before+(1-old)*bil_open/bil_before
        intraday=new*close/opened+(1-new)*bil_close/bil_open
        gross=overnight*intraday
    return gross*(1-D('.001')*abs(new-old))


def metrics(values, dates):
    multiple=values[-1]/values[0]
    years=(date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days/365.2425
    high=values[0]; depth=D(0)
    for value in values:
        high=max(high,value); depth=max(depth,1-value/high)
    return dict(cagr=math.expm1(math.log(float(multiple))/years),
                multiple=float(multiple),maxdd=float(depth))


def assert_metrics(expected, actual):
    for key in ('cagr','multiple','maxdd'):
        if not math.isclose(float(expected[key]),float(actual[key]),rel_tol=1e-10,abs_tol=1e-10):
            raise ValueError('independent metric mismatch: '+key)


def enumerate_bound(factors, actual, initial, budget, lower, upper, cap, limit=100000):
    """Multiplicative budget bounds and exhaustive survivors; no search imports."""
    n=len(actual)
    prefix=np.zeros((n+1,budget+1,3)); suffix=np.zeros_like(prefix)
    prefix[0,0,initial]=1.; suffix[n,0,:]=1.
    for t in range(n):
        for old in range(3):
            for new in range(3):
                change=int(new!=actual[t])
                prefix[t+1,change:,new]=np.maximum(prefix[t+1,change:,new],
                    prefix[t,:budget+1-change,old]*factors[t,old,new])
    for t in range(n-1,-1,-1):
        for old in range(3):
            for new in range(3):
                change=int(new!=actual[t])
                suffix[t,change:,old]=np.maximum(suffix[t,change:,old],
                    suffix[t+1,:budget+1-change,new]*factors[t,old,new])
    if budget and max(prefix[n,:budget].ravel())>=lower*(1-1e-10):
        raise ValueError('audit cannot prove claimed minimum changed decisions')
    # Labels retain every feasible prefix, even if another has greater wealth.
    labels=[(initial,1.,1.,0,0,0)]
    peak_labels=1; retained_edges=0
    for t in range(n):
        allowed=np.zeros((3,3),dtype=bool)
        for old in range(3):
            for new in range(3):
                change=int(new!=actual[t])
                if change>budget: continue
                k=np.arange(budget-change+1)
                bound=(prefix[t,k,old]*factors[t,old,new]*suffix[t+1,budget-change-k,new]).max()
                allowed[old,new]=bound>=lower*(1-1e-9)
        retained_edges+=int(allowed.sum())
        following=[]
        for old,wealth,peak,k,distance,switches in labels:
            for new in range(3):
                kk=k+int(new!=actual[t])
                if not allowed[old,new] or kk>budget: continue
                w=wealth*factors[t,old,new]; p=max(peak,w)
                if 1-w/p>cap+1e-10: continue
                following.append((new,w,p,kk,
                    distance+int(100*abs(GRID[new]-GRID[actual[t]])),switches+int(new!=old)))
        if len(following)>limit:
            raise ValueError('exhaustive audit resource limit reached; no beam fallback')
        labels=following; peak_labels=max(peak_labels,len(labels))
    valid=[x for x in labels if x[3]==budget and lower*(1-1e-10)<=x[1]<=upper*(1+1e-10)]
    if not valid:
        raise ValueError('audit found no admissible complete path')
    objective=min((x[3],x[4],x[5]) for x in valid)
    return dict(minimum_objective=list(objective),feasible_complete_paths=len(valid),
        retained_edges=retained_edges,peak_enumeration_labels=peak_labels,
        previous_budget_maximum_multiple=float(prefix[n,budget-1].max()) if budget else None,
        budget_maximum_multiple=float(prefix[n,budget].max()))


def run(snapshot: Path, root: Path):
    summary=json.loads((root/'summary.json').read_text())
    _,rows=inputs.load(snapshot,summary['start'],summary['end'])
    paths=json.loads((root/'paths.json').read_text())
    months=json.loads((root/'monthly.json').read_text())
    dates=[r['session'] for r in rows]; sessions={s:i for i,s in enumerate(dates)}
    held=rows[0]['economics']['held_allocation']
    initial=D(held) if held is not None else D(rows[1]['economics']['held_allocation'])
    navs={}; validated=0
    for name in ('actual','target'):
        if len(paths[name]['nav'])!=len(rows) or len(paths[name]['exposure'])!=len(rows)-1:
            raise ValueError('audit requires complete daily paths')
        nav=[D(1)]; old=initial
        for previous,row,exposure,saved in zip(rows,rows[1:],paths[name]['exposure'],paths[name]['nav'][1:]):
            new=D(str(exposure))
            if new not in GRID: raise ValueError('audit exposure outside selected grid')
            nav.append(nav[-1]*factor(previous,row,old,new))
            if abs(nav[-1]-D(saved))>D('1e-20'):
                raise ValueError('independent Decimal NAV mismatch')
            if name=='actual':
                recorded=D(row['strategy']['nav'])/D(rows[0]['strategy']['nav'])
                if abs(nav[-1]-recorded)>D('1e-20'):
                    raise ValueError('actual NAV mismatch')
            old=new; validated+=1
        navs[name]=nav
    navs['spy']=[D(r['spy']['nav'])/D(rows[0]['spy']['nav']) for r in rows]
    for name,nav in navs.items():
        assert_metrics(summary['metrics'][name],metrics(nav,dates))
    for month in months:
        i=sessions[month['session']]
        for name,nav in navs.items():
            assert_metrics(month['series'][name],metrics(nav[:i+1],dates[:i+1]))
    years=(date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days/365.2425
    lower=(1+summary['settings']['lower_cagr'])**years
    upper=(1+summary['settings']['upper_cagr'])**years
    actual=[GRID.index(D(r['economics']['held_allocation'])) for r in rows[1:]]
    factors=np.array([[[float(factor(p,r,a,b)) for b in GRID] for a in GRID]
                      for p,r in zip(rows,rows[1:])])
    selected=summary['target_metrics']
    bound=enumerate_bound(factors,actual,GRID.index(initial),selected['changed_days'],
        lower,upper,summary['drawdown_limit'])
    if bound['minimum_objective']!=[selected[k] for k in ('changed_days','deviation_points','switches')]:
        raise ValueError('exhaustive objective differs from reported optimum')
    result=dict(status='PASS',decimal_return_rows=validated,monthly_rows=len(months),
        monthly_series=3,exhaustive=bound,
        files={p.name:inputs.sha(p.read_bytes()) for p in root.iterdir()
               if p.suffix=='.json' and p.name!='audit.json'},
        audit_source_sha256=inputs.sha(Path(__file__).read_bytes()))
    inputs.write_json(root/'audit.json',result)
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--result',type=Path,required=True)
    args=p.parse_args()
    run(args.snapshot,args.result)
