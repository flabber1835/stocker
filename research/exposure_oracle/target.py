"""Bounded hindsight target search; never changes the authenticated Core tape."""
import argparse
from datetime import date
from decimal import Decimal as D
import json
import math
from pathlib import Path
import time

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import accounting, analysis, inputs, target_search as search


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    start: str | None = None
    end: str | None = None
    lower_cagr: float = Field(default=.25, ge=0, le=1)
    upper_cagr: float = Field(default=.30, ge=0, le=1)
    maximum_changes: int = Field(default=128, ge=1, le=1024)
    solver_seconds: float = Field(default=120, ge=1, le=3600)

    @model_validator(mode='after')
    def ordered(self):
        if self.lower_cagr >= self.upper_cagr:
            raise ValueError('target band must be increasing')
        return self


def run(snapshot: Path, output: Path, settings: Settings) -> dict:
    snapshot,output=snapshot.resolve(),output.resolve()
    if snapshot==output or snapshot in output.parents or output in snapshot.parents:
        raise ValueError('output must be separate from input snapshot')
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    def status(label, **details):
        item=dict(status=label,elapsed_seconds=round(time.monotonic()-started,2),**details)
        inputs.write_json(output/'status.json',item)
        print(json.dumps(item),flush=True)
    status('AUTHENTICATING')
    binding,rows=inputs.load(snapshot,settings.start,settings.end)
    source_root=Path(__file__).resolve().parents[2]
    accountant_sources=inputs.verify_accountant_sources(binding,source_root)
    status('CHECKING_ACCOUNTING',sessions=len(rows),end=rows[-1]['session'])
    days,initial,actual_exposures=accounting.tape(rows)
    grid=accounting.make_grid(initial,actual_exposures)
    initial_index=grid.index(initial)
    actual_indices=[grid.index(x) for x in actual_exposures]
    matrices=np.stack([d.matrix(grid) for d in days])
    start,end=rows[0]['session'],rows[-1]['session']
    years=(date.fromisoformat(end)-date.fromisoformat(start)).days/365.2425
    lower,upper=(years*math.log1p(c) for c in (settings.lower_cagr,settings.upper_cagr))
    actual=accounting.replay(days,initial,actual_exposures,start)
    cap=actual['maxdd']
    maximum=min(settings.maximum_changes,len(days))
    status('CHANGE_BUDGET_BOUND',actual_cagr=actual['cagr'],drawdown_limit=cap,maximum=maximum)
    budgets=search.forward(matrices,initial_index,actual_indices,maximum)
    frontier=[]
    for k in range(maximum+1):
        value=float(budgets.growth[-1,k].max())
        frontier.append(dict(changed_days=k,maximum_log_wealth=value if math.isfinite(value) else None,
            maximum_cagr=math.expm1(value/years) if math.isfinite(value) else None,
            ignores_drawdown_and_upper_band=True))
    inputs.write_json(output/'budget-bounds.json',frontier)
    candidates=[k for k in range(maximum+1) if budgets.growth[-1,k].max() >= lower-search.PRUNE_MARGIN]
    if not candidates:
        status('BUDGET_LIMIT',maximum=maximum)
        raise ValueError('target requires a larger search budget; not globally infeasible')
    first=candidates[0]
    records=[]; excluded=[]; chosen=None; proof=False
    secondary_proven=tertiary_proven=False
    def save_candidate(path, label, primary):
        metrics=search.path_metrics(matrices,initial_index,actual_indices,path)
        replay=accounting.replay(days,initial,[grid[x] for x in path],start,cap)
        if (not search.admissible(metrics,lower,upper,cap) or
                not settings.lower_cagr-1e-10 <= replay['cagr'] <= settings.upper_cagr+1e-10 or
                abs(math.log(float(replay['multiple']))-metrics['log_wealth']) > 1e-10):
            raise ValueError('candidate failed independent Decimal target validation')
        inputs.write_json(output/'candidate.json',dict(label=label,path=path,metrics=metrics,
            performance=analysis.compact(replay),minimum_changed_days_proven=primary))
        return replay
    for k in range(first,maximum+1):
        candidate=budgets.path(k)
        metrics=search.path_metrics(matrices,initial_index,actual_indices,candidate)
        witness=candidate if search.admissible(metrics,lower,upper,cap) else None
        primary=k==first or excluded==list(range(first,k))
        if witness is not None:
            save_candidate(witness,'maximum-growth witness at change budget',primary)
        allowed=search.prune(matrices,budgets,k,lower)
        status('OPTIMIZING_DEVIATION',changed_days=k,lower_bound=first,
            witness_valid=witness is not None,retained_edges=int(allowed.sum()))
        result=search.milp_path(matrices,initial_index,actual_indices,k,lower,upper,cap,allowed,
            incumbent=witness,time_limit=settings.solver_seconds)
        records.append(result)
        inputs.write_json(output/'solver.json',records)
        if result['path'] is not None:
            witness=result['path']
        if witness is None:
            if result['status']==2:
                excluded.append(k)
                continue
            status('UNRESOLVED_BUDGET',changed_days=k,solver_status=result['status'])
            raise ValueError('solver did not resolve this budget; cannot label it infeasible')
        chosen=witness; proof=primary
        save_candidate(chosen,'minimum exposure deviation candidate',proof)
        secondary_proven=result['status']==0 and result['path'] is not None
        if secondary_proven:
            distance=search.path_metrics(matrices,initial_index,actual_indices,chosen)['deviation_points']
            status('OPTIMIZING_SWITCHES',changed_days=k,deviation_points=distance)
            tie=search.milp_path(matrices,initial_index,actual_indices,k,lower,upper,cap,allowed,
                objective='switches',deviation=distance,incumbent=chosen,time_limit=settings.solver_seconds)
            records.append(tie)
            inputs.write_json(output/'solver.json',records)
            if tie['path'] is not None:
                chosen=tie['path']
            tertiary_proven=tie['status']==0 and tie['path'] is not None
        break
    if chosen is None:
        raise ValueError('no feasible target in configured budget; not globally infeasible')
    target=save_candidate(chosen,'selected target path',proof)
    metrics=search.path_metrics(matrices,initial_index,actual_indices,chosen)
    spy_values=[D(r['spy']['nav'])/D(rows[0]['spy']['nav']) for r in rows]
    spy=dict(**accounting.performance(spy_values,[r['session'] for r in rows]),nav=[str(x) for x in spy_values])
    paths=dict(actual=actual,target=target,spy=spy)
    attribution=analysis.attribution(rows,actual,target)
    manifest=json.loads((snapshot/'manifest.json').read_text())
    summary=dict(schema='sentinel-target-cagr/1',start=start,end=end,sessions=len(rows),
        return_sessions=len(days),settings=settings.model_dump(),actions=[str(x) for x in grid],
        source_binding=manifest['binding'],source_daily=manifest['daily'],checkpoint=manifest['checkpoint'],
        accountant_sources=accountant_sources,
        harness={p.name:inputs.sha(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')},
        metrics={name:analysis.compact(p) for name,p in paths.items()},
        target_metrics=metrics,drawdown_limit=cap,
        optimization=dict(minimum_changed_days_lower_bound=first,
            minimum_changed_days_proven=proof,secondary_deviation_proven=secondary_proven,
            tertiary_switches_proven=tertiary_proven,
            excluded_budgets=excluded,numerical_bound_margin=search.PRUNE_MARGIN,
            milp_growth_inset=0.),
        validation=dict(canonical_accounting='PASS',decimal_replay='PASS',target_band='PASS',drawdown='PASS'),
        caveat='Hindsight feasibility, not a forecast; fixed fractional Core tape and modeled scalar execution.')
    inputs.write_json(output/'summary.json',summary)
    inputs.write_json(output/'paths.json',paths)
    inputs.write_json(output/'attribution.json',attribution)
    inputs.write_json(output/'monthly.json',analysis.monthly(rows,paths))
    status('COMPLETE',metrics=summary['metrics'],optimization=summary['optimization'],target_metrics=metrics)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--maximum-changes',type=int,default=128)
    parser.add_argument('--solver-seconds',type=float,default=120)
    args=parser.parse_args()
    run(args.snapshot,args.output,Settings(start=args.start,end=args.end,
        maximum_changes=args.maximum_changes,solver_seconds=args.solver_seconds))
