"""Four predeclared causal exit/recovery cases on the same authenticated tape."""
import argparse
from decimal import Decimal as D
import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from . import accounting as A, analysis, inputs

CASES = {'baseline':(5,False),'earlier_exit':(1,False),
         'recovery_bridge':(5,True),'combined':(1,True)}


class Latch(BaseModel):
    model_config = ConfigDict(frozen=True,extra='forbid',strict=True)
    active: bool
    entry_streak: int = Field(ge=0)
    recovery_streak: int = Field(ge=0)
    session: str


def advance(state: Latch, *, session: str, impaired: bool, healthy: bool, entry_sessions: int) -> tuple[Latch,str]:
    if type(impaired) is not bool or type(healthy) is not bool or (impaired and healthy):
        raise ValueError('strict coherent boolean predicates required')
    if session <= state.session or entry_sessions not in (1,5):
        raise ValueError('invalid causal transition')
    active,entry,recovery,reason = state.active,0,0,'OWNED_NORMAL'
    if active:
        recovery = state.recovery_streak+1 if healthy else 0
        if recovery >= 8:
            active,recovery,reason = False,0,'OWNED_RECOVERED'
        else:
            reason = 'OWNED_IMPAIRMENT_HELD'
    else:
        entry = state.entry_streak+1 if impaired else 0
        if entry >= entry_sessions:
            active,entry,reason = True,0,'OWNED_IMPAIRMENT_ENTER'
    return Latch(active=active,entry_streak=entry,recovery_streak=recovery,session=session),reason


def compose(decision: dict, state: Latch, bridge: bool) -> D:
    native = A.allocation(decision['native_target_core_exposure'])
    base = A.allocation(decision['champion_target_core_exposure'])
    owned = decision['owned_impairment']
    if native not in (D(0),D(1)) or base not in (D(0),D('.55'),D(1)) or base > native:
        raise ValueError('unexpected native/recovery action')
    if A.allocation(owned['parent_target']) != base or A.allocation(decision['ldrc']['desired_allocation']) != base:
        raise ValueError('recorded stage composition changed')
    if native == 1 and base == 0:
        if 'FULL_RISK_HELD' not in decision['ldrc']['reason'].split('|'):
            raise ValueError('unrecognized native-full zero-exposure reason')
        if bridge:
            base = D('.55')
    target = min(base,D('.55') if state.active else D(1))
    if target > native or target not in (D(0),D('.55'),D(1)):
        raise ValueError('candidate violates native/action boundary')
    return target


def decisions(rows: list[dict], *, entry_sessions=5, bridge=False, verify_baseline=False) -> list[dict]:
    first = rows[0]['decision']['owned_impairment']
    state = Latch(active=first['active'],entry_streak=first['entry_streak'],
                  recovery_streak=first['recovery_streak'],session=rows[0]['session'])
    result = []
    for i,row in enumerate(rows):
        evidence = row['decision']['owned_impairment']
        if i:
            state,reason = advance(state,session=row['session'],impaired=evidence['impaired'],
                                   healthy=evidence['healthy'],entry_sessions=entry_sessions)
        else:
            reason = evidence['reason']
        target = compose(row['decision'],state,bridge)
        if verify_baseline:
            for key in ('active','entry_streak','recovery_streak'):
                if getattr(state,key) != evidence[key]:
                    raise ValueError('baseline owned state mismatch: '+key)
            if reason != evidence['reason'] or target != A.allocation(row['decision']['target_core_exposure']):
                raise ValueError('baseline reason or target mismatch')
        result.append(dict(session=row['session'],target=str(target),reason=reason,**state.model_dump(exclude={'session'})))
    return result


def underwater(values: list[D]) -> int:
    peak,current,longest = values[0],0,0
    for value in values:
        if value >= peak:
            peak,current = value,0
        else:
            current += 1
            longest = max(longest,current)
    return longest


def apply_at_next_open(days: list[A.Day], trace: list[dict]) -> list[D]:
    if len(trace) != len(days)+1 or any(day.session != trace[i+1]['session'] for i,day in enumerate(days)):
        raise ValueError('decision/return session alignment changed')
    return [day.fixed if day.fixed is not None else D(trace[i]['target']) for i,day in enumerate(days)]


def window(path: dict, rows: list[dict], left: int, right: int) -> dict:
    values = [D(x) for x in path['nav'][left:right+1]]
    values = [x/values[0] for x in values]
    selected = rows[left:right+1]
    exposures = path['exposure'][left:right]
    initial = path['exposure'][left-1] if left else rows[0]['economics']['held_allocation']
    prior = float(initial) if initial is not None else exposures[0]
    costs = path['cost_log'][left:right]
    result = A.performance(values,[r['session'] for r in selected])
    turns = [abs(a-b) for a,b in zip([prior,*exposures[:-1]],exposures)]
    if left == 0 and initial is None:
        turns[0] = float(rows[1]['economics']['turnover'])
    return dict(**result,nav=[str(x) for x in values],exposure=exposures,
        gross_log=path['gross_log'][left:right],cost_log=costs,
        switches=sum(a != b for a,b in zip([prior,*exposures[:-1]],exposures)),
        allocation_turnover=sum(turns),mean_exposure=sum(exposures)/len(exposures),
        overlay_cost_drag=1-math.exp(sum(costs)),
        longest_underwater_sessions=underwater(values))


def run(snapshot: Path, output: Path, start: str | None = None, end: str | None = None) -> dict:
    if (output.resolve() == snapshot.resolve() or snapshot.resolve() in output.resolve().parents
            or output.resolve() in snapshot.resolve().parents):
        raise ValueError('experiment output must be separate from snapshot')
    binding,all_rows = inputs.load(snapshot)
    dates = [r['session'] for r in all_rows]
    start,end = start or dates[0],end or dates[-1]
    if start not in dates or end not in dates or start >= end:
        raise ValueError('select at least two completed session closes')
    left,right = dates.index(start),dates.index(end)
    rows = all_rows[:right+1]
    root = Path(__file__).resolve().parents[2]
    sources = inputs.verify_accountant_sources(binding,root)
    names = ('sentinel/controller/owned_impairment.py','sentinel/controller/champion.py',
             'sentinel/controller/champion_frozen.py','sentinel/core/kernel.py')
    for name in names:
        sources[name] = inputs.sha((root/name).read_bytes())
        if sources[name] != binding['production']['files'].get(name):
            raise ValueError('controller source differs from fixed-input experiment: '+name)
    days,initial,actual = A.tape(rows)
    A.make_grid(initial,actual)
    full_paths,traces,paths = {},{},{}
    for name,(entry,bridge) in CASES.items():
        trace = decisions(rows,entry_sessions=entry,bridge=bridge,verify_baseline=name == 'baseline')
        exposure = apply_at_next_open(days,trace)
        full = A.replay(days,initial,exposure,rows[0]['session'])
        if name == 'baseline' and exposure != actual:
            raise ValueError('baseline next-open exposure differs')
        full_paths[name],traces[name] = full,trace
        paths[name] = window(full,rows,left,right)
    selected = rows[left:right+1]
    baseline = paths['baseline']
    episodes = analysis.attribution(selected,baseline,baseline)['defensive_episodes']
    index = {r['session']:i for i,r in enumerate(selected)}
    for episode in episodes:
        lo,hi = index[episode['baseline']],index[episode['end']]
        episode['returns'] = {name:float(D(path['nav'][hi])/D(path['nav'][lo])-1) for name,path in paths.items()}
        for key in ('oracle_return','actual_return','core_return','oracle_mean_exposure',
                    'oracle_days_at_0','oracle_days_at_55','oracle_days_at_100',
                    'gross_log_gap','cost_log_gap','net_log_gap'):
            episode.pop(key,None)
    years = []
    for year in sorted({r['session'][:4] for r in selected[1:]}):
        points = [i for i,r in enumerate(selected) if i and r['session'].startswith(year)]
        lo,hi = min(points)-1,max(points)
        years.append(dict(year=year,start=selected[lo]['session'],end=selected[hi]['session'],
            returns={name:float(D(path['nav'][hi])/D(path['nav'][lo])-1) for name,path in paths.items()}))
    summary = dict(schema='sentinel-four-timing-cases/1',start=start,end=end,sessions=len(selected),
        seed_session=rows[0]['session'],source_binding=inputs.digest(binding),
        source_checkpoint=json.loads((snapshot/'latest-checkpoint.json').read_text()),
        cases={name:dict(entry_confirmation=entry,recovery_bridge=bridge) for name,(entry,bridge) in CASES.items()},
        source_hashes=sources,harness={p.name:inputs.sha(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')},
        metrics={name:analysis.compact(path) for name,path in paths.items()},
        changed_exposure_sessions={name:sum(a != b for a,b in zip(baseline['exposure'],path['exposure'])) for name,path in paths.items()},
        validation=dict(recorded_baseline_states='PASS',recorded_baseline_targets='PASS',
                        canonical_accounting='PASS',causal_next_open_alignment='PASS'),
        status='DIAGNOSTIC_SAME_SAMPLE',future_validation_required=True)
    output.mkdir(parents=True,exist_ok=False)
    inputs.write_json(output/'summary.json',summary)
    inputs.write_json(output/'paths.json',paths)
    inputs.write_json(output/'decisions.json',traces)
    inputs.write_json(output/'episodes.json',episodes)
    inputs.write_json(output/'years.json',years)
    inputs.write_json(output/'monthly.json',analysis.monthly(selected,paths))
    from .logic_report import write_report
    write_report(output,summary,selected,paths,episodes,years)
    print(json.dumps(summary),flush=True)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--start')
    parser.add_argument('--end')
    args = parser.parse_args()
    run(args.snapshot,args.output,args.start,args.end)
