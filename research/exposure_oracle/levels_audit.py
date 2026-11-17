"""Separate scalar ledger and state-machine audit; never forms a Core book."""
import argparse
from decimal import Decimal as D
import json
import math
from pathlib import Path

from . import inputs
from .target_audit import factor, metrics, assert_metrics


def actions(rows, policy, count):
    result=[]; warning=probe=False; impaired_count=healthy_count=recovery_count=0
    for row in rows:
        d=row['decision']; baseline=D(str(d['target_core_exposure']))
        if policy is None:
            result.append(baseline); continue
        unhealthy=d['owned_impairment']['impaired']; healthy=d['owned_impairment']['healthy']
        impaired_count=impaired_count+1 if unhealthy else 0
        healthy_count=healthy_count+1 if healthy else 0
        if not policy['early'] or healthy_count>=policy['release']:
            warning=False
        elif impaired_count>=policy['entry']:
            warning=True
        native=D(str(d['native_target_core_exposure']))
        waiting=native==1 and baseline==0
        recovery_count=recovery_count+1 if waiting and healthy else 0
        if not policy['recovery'] or not waiting or unhealthy:
            probe=False
        elif recovery_count>=policy['confirmation']:
            probe=True
        desired=baseline
        if waiting and probe: desired=D('.25') if count==5 else D('.55')
        elif baseline==1 and warning: desired=D('.75') if count==5 else D('.55')
        if native==0: desired=D(0)
        result.append(desired)
    return result


def replay(rows, decisions):
    first=rows[0]['economics']['held_allocation']
    old=D(first) if first is not None else D(rows[1]['economics']['held_allocation'])
    nav=[D(1)]; exposures=[]; turnover=D(0); switches=0
    for i,(previous,row) in enumerate(zip(rows,rows[1:])):
        deployment=row['economics']['initial_deployment']
        new=D(row['economics']['held_allocation']) if deployment else decisions[i]
        nav.append(nav[-1]*factor(previous,row,old,new)); exposures.append(float(new))
        turnover+=D(row['economics']['turnover']) if deployment else abs(new-old)
        switches+=int(new!=old); old=new
    values=metrics(nav,[r['session'] for r in rows])
    return nav,exposures,dict(**values,allocation_turnover=float(turnover),switches=switches)


def run(snapshot: Path, root: Path):
    summary=json.loads((root/'summary.json').read_text())
    selection=json.loads((root/'selection.json').read_text())
    _,rows=inputs.load(snapshot)
    dates=[r['session'] for r in rows]; index={s:i for i,s in enumerate(dates)}
    split=index[selection['end']]
    assert inputs.sha((root/'selection.json').read_bytes())==summary['selection_sha256']
    source=Path(__file__).parent
    for name,expected in summary['harness'].items():
        if inputs.sha((source/name).read_bytes())!=expected:
            raise ValueError('research source changed after run: '+name)
    for record in selection['candidates']:
        prefix=rows[:split+1]
        _,_,m=replay(prefix,actions(prefix,record['policy'],record['levels']))
        assert_metrics(record['metrics'],m)
        for key in ('allocation_turnover','switches'):
            if not math.isclose(float(record['metrics'][key]),m[key],rel_tol=1e-12,abs_tol=1e-12):
                raise ValueError('training turnover or switch mismatch')
    baseline=next(x for x in selection['candidates'] if x['id']=='baseline')
    for count in (3,5):
        eligible=[x for x in selection['candidates'] if x['levels'] in (0,count)
                  and x['metrics']['maxdd']<=baseline['metrics']['maxdd']+1e-10]
        winner=min(eligible,key=lambda x:(-x['metrics']['cagr'],x['metrics']['allocation_turnover'],
                                          x['metrics']['switches'],x['id']))
        if winner!=selection['selected'][str(count)]:
            raise ValueError('frozen selection does not follow training rule')
    paths=json.loads((root/'paths.json').read_text())
    holdout=json.loads((root/'holdout-paths.json').read_text())
    traces=json.loads((root/'decisions.json').read_text())
    navs={}; daily=0
    for name,spec in summary['policies'].items():
        predicted=actions(rows,spec['policy'],spec['levels'])
        if predicted!=[D(x['target']) for x in traces[name]]:
            raise ValueError('independent controller decisions differ: '+name)
        nav,exposure,m=replay(rows,predicted); navs[name]=nav
        if exposure!=paths[name]['exposure'] or len(nav)!=len(paths[name]['nav']):
            raise ValueError('daily action path or length differs')
        for value,stored in zip(nav,paths[name]['nav']):
            if abs(value-D(stored))>D('1e-20'):
                raise ValueError('independent daily Decimal NAV differs')
        assert_metrics(summary['full_metrics'][name],m)
        rebased=[x/nav[split] for x in nav[split:]]
        assert_metrics(summary['holdout_metrics'][name],metrics(rebased,dates[split:]))
        if exposure[split:]!=holdout[name]['exposure']:
            raise ValueError('holdout actions do not continue candidate history')
        if any(abs(x-D(y))>D('1e-20') for x,y in zip(rebased,holdout[name]['nav'])):
            raise ValueError('holdout NAV does not retain candidate overnight')
        daily+=len(exposure)
    navs['spy']=[D(r['spy']['nav'])/D(rows[0]['spy']['nav']) for r in rows]
    assert_metrics(summary['full_metrics']['spy'],metrics(navs['spy'],dates))
    monthly_count=0
    for filename,left in (('monthly.json',0),('holdout-monthly.json',split)):
        months=json.loads((root/filename).read_text())
        for month in months:
            right=index[month['session']]
            for name,nav in navs.items():
                assert_metrics(month['series'][name],metrics(nav[left:right+1],dates[left:right+1]))
                monthly_count+=1
    pairs=json.loads((root/'pairs.json').read_text())
    for pair in pairs.values():
        for period,series in (('full',paths),('holdout',holdout)):
            expected=math.log(float(D(series[pair['five']]['multiple'])/D(series[pair['three']]['multiple'])))
            if abs(sum(x['net_log_gap'] for x in pair[period])-expected)>1e-10:
                raise ValueError('paired gross/cost attribution mismatch')
    result=dict(status='PASS',independent_training_candidates=len(selection['candidates']),
        independent_controller_paths=len(summary['policies']),daily_return_rows=daily,
        monthly_series_rows=monthly_count,selection='TRAINING_ONLY_RULE_MATCH',
        inputs_reauthenticated='PASS',source_hashes='PASS',
        audit_source_sha256=inputs.sha(Path(__file__).read_bytes()),
        files={p.name:inputs.sha(p.read_bytes()) for p in root.iterdir()
               if p.suffix=='.json' and p.name!='audit.json'})
    inputs.write_json(root/'audit.json',result)
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--result',type=Path,required=True)
    args=parser.parse_args()
    run(args.snapshot,args.result)
