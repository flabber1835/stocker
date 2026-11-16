"""python -m research.exposure_oracle.run --source-run RUN --output NEW_DIRECTORY."""
import argparse
from decimal import Decimal as D
import json
import math
from pathlib import Path
import time

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from . import accounting, analysis, inputs, report, search


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    start: str | None = None
    end: str | None = None
    cap_samples: int = Field(default=7, ge=3, le=30)
    max_labels: int = Field(default=5000000, ge=100)
    max_layer: int = Field(default=100000, ge=10)


def run(source: Path | None, snapshot: Path | None, output: Path, settings: Settings) -> dict:
    started = time.monotonic()
    def status(label, **details):
        value = dict(status=label, elapsed_seconds=round(time.monotonic()-started,2), **details)
        inputs.write_json(output/'status.json',value)
        print(json.dumps(value),flush=True)
    for protected in (source,snapshot):
        if protected is not None and (output.resolve() == protected.resolve()
                or protected.resolve() in output.resolve().parents
                or output.resolve() in protected.resolve().parents):
            raise ValueError('experiment output must be separate from source')
    output.mkdir(parents=True,exist_ok=False)
    status('AUTHENTICATING')
    if source is not None:
        snapshot = output/'snapshot'
        inputs.capture(source,snapshot)
    if snapshot is None:
        raise ValueError('source run or snapshot required')
    binding,rows = inputs.load(snapshot,settings.start,settings.end)
    source_root = Path(__file__).resolve().parents[2]
    accountant_sources = inputs.verify_accountant_sources(binding,source_root)
    status('CHECKING_CANONICAL_ACCOUNTING',through=rows[-1]['session'],sessions=len(rows))
    days,initial,actual_exposures = accounting.tape(rows)
    grid = accounting.make_grid(initial,actual_exposures)
    initial_index = grid.index(initial)
    matrices = np.stack([d.matrix(grid) for d in days])
    start = rows[0]['session']
    actual = accounting.replay(days,initial,actual_exposures,start)
    actual_cap = actual['maxdd']
    if not search.feasible(matrices,initial_index,actual_cap):
        raise ValueError('actual path must be feasible within its own drawdown')
    status('SEARCHING_UNCONSTRAINED',actual_cagr=actual['cagr'],actual_maxdd=actual_cap)
    upper = search.unconstrained(matrices,initial_index,len(grid))
    upper_path = accounting.replay(days,initial,[grid[i] for i in upper.path],start)
    if abs(math.log(float(upper_path['multiple']))-upper.log_wealth) > 1e-10:
        raise ValueError('unconstrained search and Decimal replay differ')
    floor_lower,floor_upper = search.minimum_cap(matrices,initial_index,upper_path['maxdd'])
    status('DRAWDOWN_FLOOR_FOUND',floor_lower=floor_lower,floor_upper=floor_upper,
           unconstrained_cagr=upper_path['cagr'],unconstrained_maxdd=upper_path['maxdd'])
    floor_safe = min(upper_path['maxdd'],floor_upper+1e-9)
    caps = sorted({actual_cap,upper_path['maxdd'],*map(float,np.linspace(floor_safe,upper_path['maxdd'],settings.cap_samples))})
    frontier,frontier_paths,selected = [],{},None
    for index,cap in enumerate(caps):
        if cap >= upper_path['maxdd']-1e-13:
            solution = upper
        else:
            solution = search.constrained(matrices,initial_index,cap,
                max_layer=settings.max_layer,max_labels=settings.max_labels)
        path_id = f'cap-{index:02d}'
        if solution is None:
            frontier.append(dict(path_id=path_id,cap=cap,status='INFEASIBLE'))
            continue
        path = accounting.replay(days,initial,[grid[i] for i in solution.path],start,cap)
        if abs(math.log(float(path['multiple']))-solution.log_wealth) > 1e-10:
            raise ValueError('constrained search and Decimal replay differ')
        if cap == actual_cap:
            selected = path
        frontier.append(dict(path_id=path_id,cap=cap,status='OPTIMAL',metrics=analysis.compact(path),
                             labels=solution.labels,max_layer=solution.max_layer,selected=cap == actual_cap))
        frontier_paths[path_id] = path
        status('CAP_COMPLETE',cap=cap,cagr=path['cagr'],maxdd=path['maxdd'],labels=solution.labels)
    feasible_points = [p for p in frontier if p['status'] == 'OPTIMAL']
    if any(b['metrics']['cagr'] < a['metrics']['cagr']-1e-10 for a,b in zip(feasible_points,feasible_points[1:])):
        raise ValueError('optimal CAGR decreased as the drawdown constraint relaxed')
    if selected is None or D(selected['multiple']) < D(actual['multiple'])*(1-D('1e-10')):
        raise ValueError('oracle cannot lose to feasible actual path')
    paths = dict(actual=actual,oracle=selected)
    for name,a in (('core',D(1)),('bil',D(0))):
        paths[name] = accounting.replay(days,initial,[d.fixed if d.fixed is not None else a for d in days],start)
    attribution = analysis.attribution(rows,actual,selected)
    months = analysis.monthly(rows,paths)
    pointer = json.loads((snapshot/'latest-checkpoint.json').read_text())
    manifest = json.loads((snapshot/'manifest.json').read_text())
    summary = dict(schema='fractional-exposure-oracle/1',start=start,end=rows[-1]['session'],
        sessions=len(rows),return_sessions=len(days),actions=[str(a) for a in grid],
        checkpoint=pointer,source_binding=manifest['binding'],source_daily=manifest['daily'],
        snapshot=str(snapshot),settings=settings.model_dump(),accountant_sources=accountant_sources,
        harness={p.name:inputs.sha(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')},
        actual_drawdown_cap=actual_cap,minimum_drawdown_bracket=[floor_lower,floor_upper],
        unconstrained=analysis.compact(upper_path),actual_cap_is_binding=upper_path['maxdd'] > actual_cap+1e-13,
        metrics={name:analysis.compact(p) for name,p in paths.items()},
        validation=dict(actual_canonical_accounting='PASS',optimized_decimal_replay='PASS',
                        attribution='PASS',actions='ONLY_0_55_100',drawdown_tolerance=1e-10),
        caveat='Perfect future knowledge; fixed Core/BIL tape and modeled scalar execution. Not a tradable forecast.')
    inputs.write_json(output/'summary.json',summary)
    inputs.write_json(output/'frontier.json',frontier)
    inputs.write_json(output/'frontier-paths.json',frontier_paths)
    inputs.write_json(output/'paths.json',paths)
    inputs.write_json(output/'attribution.json',attribution)
    inputs.write_json(output/'monthly.json',months)
    with (output/'daily.jsonl').open('w',encoding='utf8') as stream:
        for i,item in enumerate(attribution['daily']):
            value = dict(**item,**{name:dict(nav=p['nav'][i+1],drawdown=p['drawdown'][i+1]) for name,p in paths.items()})
            stream.write(json.dumps(value,sort_keys=True,allow_nan=False)+'\n')
    report.write_report(output,summary,rows,paths,frontier,attribution,months)
    status('COMPLETE',start=start,end=rows[-1]['session'],metrics=summary['metrics'])
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--source-run',type=Path)
    source.add_argument('--snapshot',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--cap-samples',type=int,default=7)
    parser.add_argument('--max-labels',type=int,default=5000000)
    parser.add_argument('--max-layer',type=int,default=100000)
    args = parser.parse_args()
    config = Settings(start=args.start,end=args.end,cap_samples=args.cap_samples,
                      max_labels=args.max_labels,max_layer=args.max_layer)
    run(args.source_run,args.snapshot,args.output,config)
