"""Fit and evaluate three/five-level Sentinel overlays without advancing Core."""
import argparse
from decimal import Decimal as D
import json
import math
from pathlib import Path
import time

from . import accounting as A, analysis, inputs, logic, levels_policy as P


def training_prefix(rows, train_end):
    dates=[r['session'] for r in rows]
    if train_end not in dates or not dates[0]<train_end:
        raise ValueError('training endpoint must be a completed close after the baseline')
    return rows[:dates.index(train_end)+1]


def candidate_record(policy, levels, path):
    return dict(id=f'L{levels}:{policy.key}',levels=levels,policy=policy.model_dump(),
                metrics=analysis.compact(path))


def fit(rows, train_end, progress=None):
    selected=training_prefix(rows,train_end)
    days,initial,actual=A.tape(selected)
    A.make_grid(initial,actual)
    logic.decisions(selected,verify_baseline=True)
    baseline=logic.window(A.replay(days,initial,actual,selected[0]['session']),selected,0,len(days))
    records=[dict(id='baseline',levels=0,policy=None,metrics=analysis.compact(baseline))]
    for policy in P.menu():
        paired=[]
        for levels in (3,5):
            trace=P.decisions(selected,policy,levels)
            actions=logic.apply_at_next_open(days,trace)
            full=A.replay(days,initial,actions,selected[0]['session'])
            path=logic.window(full,selected,0,len(days))
            records.append(candidate_record(policy,levels,path)); paired.append(trace)
        if any(a['state']!=b['state'] or a['reason']!=b['reason'] for a,b in zip(*paired)):
            raise ValueError('paired grids changed underlying controller states')
        if progress: progress(policy.key)
    return dict(schema='sentinel-exposure-level-fit/1',start=selected[0]['session'],end=train_end,
        sessions=len(selected),selection_rule='max_CAGR_under_baseline_MaxDD_then_turnover_switches_id',
        candidates=records,selected={str(n):P.choose(records,n) for n in (3,5)})


def definitions(selection):
    result={'baseline':(None,3)}
    for key,n in (('selected_three',3),('selected_five',5)):
        record=selection['selected'][str(n)]
        result[key]=(P.Policy.model_validate(record['policy']) if record['policy'] is not None else None,n)
    result['paired_three']=(result['selected_five'][0],3)
    result['paired_five']=(result['selected_three'][0],5)
    result['fixed_three']=(P.Policy(),3)
    result['fixed_five']=(P.Policy(),5)
    return result


def yearly(rows,paths):
    result=[]
    for year in sorted({r['session'][:4] for r in rows[1:]}):
        indices=[i for i,r in enumerate(rows) if i and r['session'].startswith(year)]
        left,right=min(indices)-1,max(indices)
        result.append(dict(year=year,baseline=rows[left]['session'],end=rows[right]['session'],
            returns={name:float(D(path['nav'][right])/D(path['nav'][left])-1) for name,path in paths.items()}))
    return result


def pair_attribution(three, five, trace, prior_reason='INITIAL'):
    groups={}
    for i in range(len(three['exposure'])):
        # Include the stage from the previous open because it owns the overnight.
        now=trace[i]['reason']; prior=trace[i-1]['reason'] if i else prior_reason
        key=f'{prior} → {now}'
        group=groups.setdefault(key,dict(sessions=0,gross_log_gap=0.,cost_log_gap=0.))
        group['sessions']+=1
        group['gross_log_gap']+=five['gross_log'][i]-three['gross_log'][i]
        group['cost_log_gap']+=five['cost_log'][i]-three['cost_log'][i]
    result=[dict(stage=k,**v,net_log_gap=v['gross_log_gap']+v['cost_log_gap']) for k,v in sorted(groups.items())]
    if abs(sum(x['net_log_gap'] for x in result)-math.log(float(D(five['multiple'])/D(three['multiple']))))>1e-10:
        raise ValueError('paired timing/cost attribution does not reconcile')
    return result


def run(snapshot: Path, output: Path, train_end='2015-12-31'):
    snapshot,output=snapshot.resolve(),output.resolve()
    if snapshot==output or snapshot in output.parents or output in snapshot.parents:
        raise ValueError('output must be separate from retained input history')
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    def status(label,**items):
        value=dict(status=label,elapsed_seconds=round(time.monotonic()-started,2),**items)
        inputs.write_json(output/'status.json',value); print(json.dumps(value),flush=True)
    status('AUTHENTICATING_RETAINED_CORE')
    binding,rows=inputs.load(snapshot)
    source_root=Path(__file__).resolve().parents[2]
    sources=inputs.verify_accountant_sources(binding,source_root)
    for name in ('sentinel/controller/owned_impairment.py','sentinel/controller/champion.py',
                 'sentinel/controller/champion_frozen.py','sentinel/core/kernel.py'):
        sources[name]=inputs.sha((source_root/name).read_bytes())
        if sources[name]!=binding['production']['files'].get(name):
            raise ValueError('recorded controller source changed: '+name)
    dates=[r['session'] for r in rows]
    if train_end not in dates or dates.index(train_end)>=len(rows)-20:
        raise ValueError('fitting must leave a later evaluation period')
    split=dates.index(train_end)
    selection=fit(rows,train_end,lambda key:status('FITTING_EARLIER_PERIOD',completed_policy=key))
    inputs.write_json(output/'selection.json',selection)
    selection_hash=inputs.sha((output/'selection.json').read_bytes())
    status('SELECTION_FROZEN',sha256=selection_hash,
        selected={key:record['id'] for key,record in selection['selected'].items()})
    days,initial,actual=A.tape(rows)
    logic.decisions(rows,verify_baseline=True)
    full_paths,holdout,traces,policies={}, {}, {}, {}
    for name,(policy,levels) in definitions(selection).items():
        trace=(P.decisions(rows,policy,levels) if policy is not None else
               [dict(session=r['session'],target=str(r['decision']['target_core_exposure']),
                     reason='RECORDED_POLICY',state=None) for r in rows])
        actions=logic.apply_at_next_open(days,trace)
        if name=='baseline' and actions!=actual:
            raise ValueError('baseline exposure does not reproduce source')
        full=A.replay(days,initial,actions,dates[0])
        full_paths[name]=logic.window(full,rows,0,len(days))
        holdout[name]=logic.window(full,rows,split,len(days))
        traces[name]=trace
        policies[name]=dict(levels=levels,policy=policy.model_dump() if policy is not None else None)
    spy=[D(r['spy']['nav'])/D(rows[0]['spy']['nav']) for r in rows]
    full_paths['spy']=dict(**A.performance(spy,dates),nav=[str(x) for x in spy])
    test_spy=[x/spy[split] for x in spy[split:]]
    holdout['spy']=dict(**A.performance(test_spy,dates[split:]),nav=[str(x) for x in test_spy])
    pairs={}
    for name,three,five in (('selected_five_settings','paired_three','selected_five'),
                           ('selected_three_settings','selected_three','paired_five'),
                           ('fixed_settings','fixed_three','fixed_five')):
        if any(a['state']!=b['state'] for a,b in zip(traces[three],traces[five])):
            raise ValueError('paired candidate history differs')
        pairs[name]=dict(three=three,five=five,
            full=pair_attribution(full_paths[three],full_paths[five],traces[five]),
            holdout=pair_attribution(holdout[three],holdout[five],traces[five][split:],
                traces[five][split-1]['reason'] if split else 'INITIAL'))
    manifest=json.loads((snapshot/'manifest.json').read_text())
    for name in ('selected_three','selected_five'):
        path=holdout[name]
        status('HOLDOUT_EVALUATED',policy=name,cagr=path['cagr'],maxdd=path['maxdd'])
    summary=dict(schema='sentinel-exposure-levels/1',start=dates[0],end=dates[-1],train_end=train_end,
        sessions=len(rows),holdout_baseline=train_end,holdout_first_return=dates[split+1],
        holdout_return_sessions=len(days)-split,source_binding=manifest['binding'],
        source_checkpoint=manifest['checkpoint'],source_daily=manifest['daily'],
        source_hashes=sources,selection_sha256=selection_hash,policies=policies,
        harness={p.name:inputs.sha(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')},
        full_metrics={n:analysis.compact(p) for n,p in full_paths.items()},
        holdout_metrics={n:analysis.compact(p) for n,p in holdout.items()},
        occupancy={n:{str(a):p['exposure'].count(float(a)) for a in P.GRIDS[5]}
                   for n,p in full_paths.items() if 'exposure' in p},
        validation=dict(authenticated_input='PASS',recorded_baseline='PASS',canonical_accounting='PASS',
            paired_state_identity='PASS',fitting_boundary=train_end,wealth_core_transitions_run=0),
        caveat='Fixed-Core scalar overlay research. Later history is excluded from fitting, '
               'but was inspected previously; not an untouched research holdout or broker-fill replay.')
    if inputs.sha((output/'selection.json').read_bytes())!=selection_hash:
        raise ValueError('holdout evaluation changed frozen selection')
    inputs.write_json(output/'summary.json',summary)
    inputs.write_json(output/'paths.json',full_paths)
    inputs.write_json(output/'holdout-paths.json',holdout)
    inputs.write_json(output/'decisions.json',traces)
    inputs.write_json(output/'pairs.json',pairs)
    inputs.write_json(output/'monthly.json',analysis.monthly(rows,full_paths))
    inputs.write_json(output/'holdout-monthly.json',analysis.monthly(rows[split:],holdout))
    inputs.write_json(output/'yearly.json',yearly(rows,full_paths))
    status('COMPLETE',holdout_metrics=summary['holdout_metrics'])
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--train-end',default='2015-12-31')
    args=parser.parse_args()
    run(args.snapshot,args.output,args.train_end)
