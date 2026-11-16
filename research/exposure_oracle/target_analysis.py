"""Prior-close evidence, episode attribution and fixed causal rule diagnostics."""
import argparse
from collections import Counter
from decimal import Decimal as D
import json
from pathlib import Path

from . import accounting as A, analysis, inputs

FLAGS=('fast_signal','slow_signal','native_fast','native_slow','ordinary','base_fast',
       'owned_active','impaired','healthy','not_healthy','pending_owned_entry','recovery_wait')
SIGNATURE=('fast_signal','slow_signal','native_fast','native_slow','ordinary','base_fast',
           'owned_active','impaired','healthy','recovery_wait')
RULES=(('impaired_exit','impaired',1.,(D(0),D('.55'))),
       ('ordinary_exit','ordinary',1.,(D(0),D('.55'))),
       ('not_healthy_exit','not_healthy',1.,(D(0),D('.55'))),
       ('healthy_reentry','healthy',0.,(D('.55'),D(1))),
       ('recovery_wait_bridge','recovery_wait',0.,(D('.55'),D(1))))


def signals(row: dict) -> dict:
    d=row['decision']; e=d['evidence']; s=e['native_snapshot']['state']; o=d['owned_impairment']
    values=dict(fast_signal=e['fast_signal'],slow_signal=e['slow_signal'],
        native_fast=d['fast_severe_active'],native_slow=d['slow_severe_active'],
        ordinary=s['ordinary'],base_fast=s['base_fast'],owned_active=o['active'],
        impaired=o['impaired'],healthy=o['healthy'],not_healthy=not o['healthy'],
        pending_owned_entry=o['entry_streak']>0,
        recovery_wait=analysis.limiting_mechanism(d,float(d['target_core_exposure']))=='recovery_wait')
    if any(type(values[k]) is not bool for k in FLAGS):
        raise ValueError('recorded signal must be boolean')
    return dict(**values,fast_healthy_streak=s['fast_h'],slow_healthy_streak=s['slow_h'],
        owned_entry_streak=o['entry_streak'],owned_recovery_streak=o['recovery_streak'],
        native_reason=d['reason'],recovery_reason=d['ldrc']['reason'],owned_reason=o['reason'])


def signal_table(daily: list[dict]) -> list[dict]:
    result=[]
    for exposure in (0.,.55,1.):
        eligible=[x for x in daily if x['actual_exposure']==exposure]
        changed=[x for x in eligible if x['changed']]
        unchanged=[x for x in eligible if not x['changed']]
        for name in FLAGS:
            true=sum(x['signals'][name] for x in changed)
            false=sum(x['signals'][name] for x in unchanged)
            result.append(dict(actual_exposure=exposure,signal=name,eligible=len(eligible),
                changed_days=len(changed),unchanged_days=len(unchanged),true_positive=true,
                label_false_positive=false,precision=true/(true+false) if true+false else None,
                recall=true/len(changed) if changed else None,
                unchanged_prevalence=false/len(unchanged) if unchanged else None,
                changed_base_rate=len(changed)/len(eligible) if eligible else None))
    return result


def episodes(daily: list[dict]) -> list[dict]:
    result=[]; start=None
    for i in range(len(daily)+1):
        changed=i<len(daily) and daily[i]['changed']
        if changed and start is None: start=i
        if not changed and start is not None:
            # Include the first unchanged action: the modified holding owns its gap.
            stop=min(len(daily),i+1)
            items=daily[start:stop]
            result.append(dict(decision_start=daily[start]['decision_session'],
                first_applied=daily[start]['session'],last_applied=daily[i-1]['session'],
                rejoined=daily[i]['session'] if i<len(daily) else None,changed_days=i-start,
                actual_exposures=[x['actual_exposure'] for x in daily[start:i]],
                target_exposures=[x['oracle_exposure'] for x in daily[start:i]],
                gross_log_gap=sum(x['gross_log_gap'] for x in items),
                cost_log_gap=sum(x['cost_log_gap'] for x in items),
                net_log_gap=sum(x['net_log_gap'] for x in items),
                mechanisms=sorted({x['mechanism'] for x in daily[start:i]})))
            start=None
    if abs(sum(x['net_log_gap'] for x in result)-sum(x['net_log_gap'] for x in daily))>1e-10:
        raise ValueError('changed-episode attribution does not reconcile including rejoin gaps')
    return result


def rule_path(rows, days, actual, flag, from_exposure, to_exposure):
    path=[]
    for i,(day,a) in enumerate(zip(days,actual)):
        if day.fixed is not None:
            path.append(day.fixed)
        elif float(a)==from_exposure and signals(rows[i])[flag]:
            path.append(to_exposure)
        else:
            path.append(a)
    return path


def period_metrics(rows, path):
    dates=[r['session'] for r in rows]
    ends=[max(i for i,s in enumerate(dates) if s<=end)
          for end in ('2012-12-31','2015-12-31','2019-12-31',dates[-1]) if end>dates[0]]
    results=[]; left=0
    for right in sorted(set(ends)):
        if right<=left: continue
        metrics=A.performance([D(x) for x in path['nav'][left:right+1]],dates[left:right+1])
        metrics.pop('drawdown')
        results.append(dict(start=dates[left],end=dates[right],**metrics))
        left=right
    return results


def diagnose(rows: list[dict], paths: dict, attributed: dict) -> dict:
    days,initial,actual=A.tape(rows,canonical=False)
    target=paths['target']['exposure']
    actual_switches=[i for i,(a,b) in enumerate(zip([initial,*actual[:-1]],actual)) if a!=b]
    daily=[]
    for i,item in enumerate(attributed['daily']):
        if item['decision_session']!=rows[i]['session'] or item['session']!=rows[i+1]['session']:
            raise ValueError('signal alignment must be prior close to following open')
        evidence=signals(rows[i])
        nearest=min((abs(i-j) for j in actual_switches),default=None)
        daily.append(dict(**item,changed=item['actual_exposure']!=item['oracle_exposure'],
            signals=evidence,nearest_actual_switch_sessions=nearest))
    signature=lambda x:tuple(x['signals'][k] for k in SIGNATURE)
    for item in daily:
        if item['changed']:
            matched=[x for x in daily if x['actual_exposure']==item['actual_exposure']
                     and signature(x)==signature(item)]
            item['same_boolean_state_days']=len(matched)
            item['same_boolean_state_changed_days']=sum(x['changed'] for x in matched)
    comparisons=[]
    for name,flag,old,alternatives in RULES:
        for new in alternatives:
            path=rule_path(rows,days,actual,flag,old,new)
            replay=A.replay(days,initial,path,rows[0]['session'])
            modified=[i for i,(a,b) in enumerate(zip(actual,path)) if a!=b]
            matched=[i for i in modified if target[i]!=float(actual[i])]
            exact=sum(float(path[i])==target[i] for i in matched)
            comparisons.append(dict(name=f'{name}_{int(new*100)}',predicate=flag,
                from_exposure=old,to_exposure=float(new),modified_days=len(modified),
                oracle_changed_days_hit=len(matched),oracle_exact_action_hits=exact,
                label_false_positives=len(modified)-len(matched),
                metrics=analysis.compact(replay),
                periods=period_metrics(rows,replay),
                net_log_gap=sum(replay['gross_log'])+sum(replay['cost_log'])-
                    sum(paths['actual']['gross_log'])-sum(paths['actual']['cost_log']),
                meets_target=.25<=replay['cagr']<=.30 and replay['maxdd']<=paths['actual']['maxdd']+1e-10))
    episode_list=episodes(daily)
    changed=[x for x in daily if x['changed']]
    return dict(schema='sentinel-target-signals/1',daily=daily,signal_comparisons=signal_table(daily),
        changed_decisions=changed,episodes=episode_list,rule_diagnostics=comparisons,
        periods={name:period_metrics(rows,path) for name,path in paths.items()},
        fragmentation=dict(changed_days=len(changed),episodes=len(episode_list),
            episode_lengths=dict(Counter(x['changed_days'] for x in episode_list)),
            changed_within_5_sessions_of_actual_switch=sum(x['nearest_actual_switch_sessions'] is not None
                and x['nearest_actual_switch_sessions']<=5 for x in changed),
            directions=dict(Counter(f"{x['actual_exposure']}->{x['oracle_exposure']}" for x in changed))),
        caveat='Same-sample hindsight diagnosis. Label false positives are not necessarily economic losses. '
               'No predictive model was fitted and no out-of-sample improvement is claimed.')


def run(snapshot: Path, result: Path) -> dict:
    summary=json.loads((result/'summary.json').read_text())
    _,rows=inputs.load(snapshot,summary['start'],summary['end'])
    paths=json.loads((result/'paths.json').read_text())
    attributed=json.loads((result/'attribution.json').read_text())
    findings=diagnose(rows,paths,attributed)
    findings['analysis_source_sha256']=inputs.sha(Path(__file__).read_bytes())
    destination=result/'signal-analysis.json'
    if destination.exists():
        raise ValueError('signal results already exist; use a new result directory')
    inputs.write_json(destination,findings)
    print(json.dumps(dict(fragmentation=findings['fragmentation'],
        rules=[dict(name=x['name'],modified_days=x['modified_days'],hits=x['oracle_changed_days_hit'],
                    cagr=x['metrics']['cagr'],maxdd=x['metrics']['maxdd'])
               for x in findings['rule_diagnostics']]),sort_keys=True),flush=True)
    return findings


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--result',type=Path,required=True)
    args=p.parse_args()
    run(args.snapshot,args.result)
