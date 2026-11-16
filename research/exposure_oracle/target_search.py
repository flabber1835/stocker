"""Minimum changed-decision budgets and an exact sparse transition MILP."""
from dataclasses import dataclass
import math
import warnings

import numpy as np

GRID = np.array([0.,.55,1.])
PRUNE_MARGIN = 1e-9


@dataclass
class Budgets:
    growth: np.ndarray
    parents: np.ndarray
    actual: np.ndarray
    initial: int

    def path(self, budget: int) -> list[int]:
        current = int(self.growth[-1,budget].argmax())
        if not np.isfinite(self.growth[-1,budget,current]):
            raise ValueError('unreachable change budget')
        result=[]
        for t in range(len(self.actual)-1,-1,-1):
            previous=int(self.parents[t,budget,current])
            if previous > 2:
                raise ValueError('invalid budget predecessor')
            result.append(current)
            budget-=int(current != self.actual[t])
            current=previous
        if budget or current != self.initial:
            raise ValueError('budget path did not reach its initial state')
        return result[::-1]


def validate(matrices, initial, actual, maximum):
    m=np.asarray(matrices,dtype=float)
    raw=np.asarray(actual)
    if not np.isin(raw,[0,1,2]).all():
        raise ValueError('actual actions must be exact grid indices')
    a=raw.astype(int)
    if (m.shape != (len(a),3,3) or not len(a) or initial not in range(3) or
            not np.isin(a,[0,1,2]).all() or not 0 <= maximum <= len(a) or
            np.isnan(m).any() or np.isposinf(m).any()):
        raise ValueError('invalid three-state budget problem')
    return m,a


def forward(matrices, initial: int, actual, maximum: int) -> Budgets:
    m,a=validate(matrices,initial,actual,maximum)
    values=np.full((len(a)+1,maximum+1,3),-np.inf)
    parents=np.full((len(a),maximum+1,3),255,dtype=np.uint8)
    values[0,0,initial]=0.
    for t,matrix in enumerate(m):
        for b in range(3):
            change=int(b != a[t])
            scores=values[t,:maximum+1-change]+matrix[:,b]
            prior=scores.argmax(axis=1)
            values[t+1,change:,b]=scores[np.arange(len(prior)),prior]
            parents[t,change:,b]=prior
    return Budgets(values,parents,a,initial)


def backward(matrices, actual, maximum: int) -> np.ndarray:
    m,a=validate(matrices,0,actual,maximum)
    values=np.full((len(a)+1,maximum+1,3),-np.inf)
    values[-1,0,:]=0.
    for t in range(len(a)-1,-1,-1):
        for b in range(3):
            change=int(b != a[t])
            for old in range(3):
                values[t,change:,old]=np.maximum(values[t,change:,old],
                    m[t,old,b]+values[t+1,:maximum+1-change,b])
    return values


def prune(matrices, budgets: Budgets, budget: int, lower: float) -> np.ndarray:
    if budget >= budgets.growth.shape[1] or not math.isfinite(lower):
        raise ValueError('invalid pruning budget or target')
    remaining=backward(matrices,budgets.actual,budget)
    allowed=np.zeros(np.shape(matrices),dtype=bool)
    for t,matrix in enumerate(matrices):
        for old in range(3):
            for new in range(3):
                change=int(new != budgets.actual[t])
                if change > budget or not np.isfinite(matrix[old,new]):
                    continue
                k=np.arange(budget-change+1)
                bound=(budgets.growth[t,k,old]+matrix[old,new]+remaining[t+1,budget-change-k,new]).max()
                allowed[t,old,new]=bool(bound >= lower-PRUNE_MARGIN)
    if not allowed.any(axis=(1,2)).all():
        raise ValueError('no target-reaching path under this budget')
    return allowed


def path_metrics(matrices, initial: int, actual, path: list[int]) -> dict:
    if len(path) != len(actual) or any(x not in range(3) for x in path):
        raise ValueError('incomplete three-state path')
    old=initial
    wealth=peak=depth=0.
    changed=deviation=switches=0
    for t,new in enumerate(path):
        wealth+=float(matrices[t,old,new])
        peak=max(peak,wealth)
        depth=max(depth,peak-wealth)
        changed+=int(new != actual[t])
        deviation+=int(round(100*abs(GRID[new]-GRID[actual[t]])))
        switches+=int(new != old)
        old=new
    return dict(log_wealth=wealth,log_drawdown=depth,changed_days=changed,
                deviation_points=deviation,switches=switches)


def admissible(metrics: dict, lower: float, upper: float, cap: float) -> bool:
    return (math.isfinite(metrics['log_wealth']) and
        lower-1e-10 <= metrics['log_wealth'] <= upper+1e-10 and
        metrics['log_drawdown'] <= -math.log1p(-cap)+1e-10)


def milp_path(matrices, initial: int, actual, budget: int, lower: float, upper: float,
              cap: float, allowed: np.ndarray, *, objective='deviation', deviation=None,
              incumbent=None, time_limit=120.) -> dict:
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import csc_array
    m,a=validate(matrices,initial,actual,budget)
    if not (0 <= cap < 1 and math.isfinite(lower) and math.isfinite(upper) and lower <= upper
            and np.shape(allowed)==m.shape and objective in ('deviation','switches')):
        raise ValueError('invalid constrained target problem')
    edges=np.argwhere(allowed & np.isfinite(m))
    count=len(edges); n=len(a)
    by_day=[[] for _ in range(n)]
    changes=np.zeros(count); distances=np.zeros(count); switches=np.zeros(count)
    for j,(t,old,new) in enumerate(edges):
        by_day[t].append(j)
        changes[j]=new != a[t]
        distances[j]=round(100*abs(GRID[new]-GRID[a[t]]))
        switches[j]=old != new
    if any(not ids for ids in by_day):
        raise ValueError('pruning removed every transition from a session')
    wr=lambda t:count+t
    pk=lambda t:count+n+t
    ri,ci,coeff,low,high=[],[],[],[],[]
    def row(terms,lo,hi):
        r=len(low)
        for col,value in terms:
            if value:
                ri.append(r); ci.append(int(col)); coeff.append(float(value))
        low.append(float(lo)); high.append(float(hi))
    drawdown=-math.log1p(-cap)
    for t in range(n):
        ids=by_day[t]
        for state in range(3):
            terms=[(j,1) for j in ids if edges[j,1]==state]
            if t:
                terms.extend((j,-1) for j in by_day[t-1] if edges[j,2]==state)
            rhs=int(t==0 and state==initial)
            row(terms,rhs,rhs)
        row([(wr(t),1),*([(wr(t-1),-1)] if t else []),
             *[(j,-m[tuple(edges[j])]) for j in ids]],0,0)
        row([(pk(t),1),*([(pk(t-1),-1)] if t else [])],0,np.inf)
        row([(pk(t),1),(wr(t),-1)],0,np.inf)
        row([(wr(t),1),(pk(t),-1)],-drawdown,np.inf)
    row(enumerate(changes),budget,budget)
    row([(wr(n-1),1)],lower,upper)
    if deviation is not None:
        row(enumerate(distances),deviation,deviation)
    if incumbent is not None:
        candidate=path_metrics(m,initial,a,incumbent)
        if candidate['changed_days'] != budget or not admissible(candidate,lower,upper,cap):
            raise ValueError('invalid incumbent bound')
        if objective=='deviation':
            row(enumerate(distances),-np.inf,candidate['deviation_points'])
        elif candidate['deviation_points']==deviation:
            row(enumerate(switches),-np.inf,candidate['switches'])
    c=np.zeros(count+2*n)
    c[:count]=distances if objective=='deviation' else switches
    ceiling=max(1.,float(sum(max(0.,np.max(matrix[np.isfinite(matrix)])) for matrix in m)))
    bounds=Bounds(np.r_[np.zeros(count),np.full(n,-drawdown),np.zeros(n)],
                  np.r_[np.ones(count),np.full(2*n,ceiling)])
    matrix=csc_array((coeff,(np.asarray(ri,dtype=np.int32),np.asarray(ci,dtype=np.int32))),
                     shape=(len(low),len(c)))
    options=dict(time_limit=time_limit,mip_rel_gap=0.,presolve=True,
        threads=1,parallel=False,random_seed=17,mip_feasibility_tolerance=1e-10)
    # SciPy forwards these documented HiGHS controls after warning about its own
    # smaller public option list. They bound resource use and numerical tolerance.
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore',message='Unrecognized options detected.*',category=RuntimeWarning)
        result=milp(c,integrality=np.r_[np.ones(count),np.zeros(2*n)],bounds=bounds,
                    constraints=LinearConstraint(matrix,low,high),options=options)
    def number(key):
        value=getattr(result,key,None)
        return float(value) if value is not None and np.isfinite(value) else None
    record=dict(status=int(result.status),message=result.message,objective=objective,
        objective_value=number('fun'),dual_bound=number('mip_dual_bound'),gap=number('mip_gap'),
        nodes=number('mip_node_count'),retained_edges=count,original_edges=n*9,
        budget=budget,path=None)
    if result.x is not None:
        path=[]; old=initial
        for t,ids in enumerate(by_day):
            selected=[j for j in ids if result.x[j] > .5]
            if len(selected)!=1 or edges[selected[0],1]!=old:
                raise ValueError('solver returned a disconnected/fractional path')
            old=int(edges[selected[0],2]); path.append(old)
        metrics=path_metrics(m,initial,a,path)
        if (metrics['changed_days'] != budget or not admissible(metrics,lower,upper,cap) or
                (deviation is not None and metrics['deviation_points'] != deviation)):
            raise ValueError('solver path failed independent target/constraint replay')
        record.update(path=path,metrics=metrics)
    return record
