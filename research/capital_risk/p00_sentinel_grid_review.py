"""Independent grid selection, all-path metrics and frozen-control checks."""
import base64
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path
import time

from p00_sentinel_grid_policy import BASELINE, NO_EXTRA, hosted, need, profiles, targets


def lock(records, baseline):
    """Separately implement the predeclared ordering from training records only."""
    need(baseline == BASELINE and all(set(r)=={'id','core_id','group','metrics','turnover'} for r in records),
         'INDEPENDENT_TRAINING_INTERFACE')
    by={v['id']:v for v in records}
    need(set(by)=={p['id'] for p in profiles()},'INDEPENDENT_COMPLETE_CLASS')
    base,other=by[BASELINE],by[NO_EXTRA]
    def multiple(pid):return Q(by[pid]['metrics']['multiple'])
    def depth(pid):return Q(by[pid]['metrics']['maximum_drawdown_magnitude'])
    def turnover(pid):return Q(by[pid]['turnover'])
    axis=lambda r:tuple(r['metrics'][k] for k in ('anchor','start','end','closes'))
    need(all(axis(r)==axis(base) for r in records) and base['metrics']['anchor']=='2018-01-02'
         and base['metrics']['end'] in ('2020-12-31','2022-12-30')
         and len({r['core_id'] for r in records})==1,'INDEPENDENT_SELECTION_PERIOD')
    floor=max(multiple(BASELINE),multiple(NO_EXTRA));ceiling=min(depth(BASELINE),depth(NO_EXTRA))
    growth_key=lambda pid:(-multiple(pid),depth(pid),turnover(pid),pid)
    protect_key=lambda pid:(depth(pid),-multiple(pid),turnover(pid),pid)
    protect=sorted([pid for pid in by if multiple(pid)>=floor],key=protect_key)[0]
    growth=sorted([pid for pid in by if depth(pid)<=ceiling],key=growth_key)[0]
    choices=[];selected=[BASELINE,NO_EXTRA,protect,growth]
    for text in ('0.50','0.75','1.0'):
        eligible=sorted([pid for pid in by if depth(pid)<=depth(BASELINE)*Q(text)],key=growth_key)
        winner=eligible[0] if eligible else None
        choices.append(dict(relative_budget=text,id=winner))
        if winner:selected.append(winner)
    joint=[pid for pid in by if multiple(pid)>multiple(BASELINE) and depth(pid)<depth(BASELINE)]
    best=sorted(joint,key=growth_key)[0] if joint else None
    if best:selected.append(best)
    return dict(status='TRAINING_SELECTION_LOCKED',selected=list(dict.fromkeys(selected)),baseline=BASELINE,
                protection_candidate=protect,growth_candidate=growth,budget_choices=choices,
                training_joint_improvements=len(joint),best_joint=best,growth_floor_multiple=str(floor),
                drawdown_ceiling=str(ceiling),evaluation_used=False,coverage='COMPLETE_144_PROFILE_CLASS_NOT_GLOBAL_OPTIMUM')


def selection_adapter(records,baseline):
    result=lock(records,baseline)
    return result['selected'],[v['id'] for v in result['budget_choices']],result['training_joint_improvements'],result['best_joint']


def review(root,evidence,out):
    hosted()
    import numpy as np
    import full_system_controller_review as checker
    from owned_grid import metric
    from p00_recovery_hold_worker import load, windows
    from p00_sentinel_grid_worker import journal, PERIODS
    from selective_journal import verify_prefixes
    started=time.monotonic();cp,formation,rows=load(root)
    checker.profiles,checker.targets,checker.independently_select=profiles,targets,selection_adapter
    checker.review(root,evidence,out)
    check=json.loads((out/'independent-review.json').read_bytes())
    need(check['profiles']==check['registered_profiles']==144
         and check['independent_targets']==(126+2156)*144,'ACTUAL_REGISTRY_COUNTS')
    source_summary=json.loads((evidence/'summary.json').read_bytes())
    grid=json.loads((evidence/'grid-summary.json').read_bytes())
    need(grid['status']=='P00_SENTINEL_GRID_REVIEW_REQUIRED' and grid['profiles']==144
         and grid['canonical_core_transitions']==0 and grid['original_core_backtests_resumed'] is False,
         'EXACT_GRID_SCOPE')
    for name,filename in (('training','locked-selection.json'),('development','locked-development-selection.json')):
        records=json.loads((evidence/(name+'-scores.json')).read_bytes())
        need(all(v['core_id']==cp['sha256'] for v in records),'COMMON_P00_CHECKPOINT_IDENTITY')
        need(json.loads((evidence/filename).read_bytes())==lock(records,BASELINE),'EVERY_SELECTION_LOCK_FIELD')
    vp=json.loads((evidence/'value-proof.json').read_bytes());levels=vp['exposure_levels']
    path_rows=journal(evidence/'paths.jsonl.gz')
    codes={v['profile']:np.frombuffer(base64.b64decode(v['path_b64'],validate=True),dtype='uint8') for v in path_rows}
    table=[{} for _ in rows]
    for f in journal(evidence/'factors.jsonl.gz'):table[f['index']][f['pair']]=f
    grouped={}
    for code in codes.values():
        key=hashlib.sha256(code.tobytes()).hexdigest()
        if key in grouped:continue
        nav='50000';series=[(rows[0]['session'],nav)];turn=[Q(0)]
        for i in range(1,len(rows)):
            pair=int(code[0]) if i==1 else int(code[i-2])*256+int(code[i-1]);f=table[i][pair]
            nav=checker.value_step(nav,f['net']);series.append((rows[i]['session'],nav));turn.append(Q(f['turnover']))
        grouped[key]=(series,turn)
    def period(series,start,end):
        selected=[v for v in series if start<=v[0]<=end]
        anchor=next((v for v in reversed(series) if v[0]<start),series[0])
        return dict(metric([v for v in selected if v[0]>anchor[0]],anchor),measured_closes=len(selected))
    observed=json.loads((evidence/'all-grid-scores.json').read_bytes())
    need([v['id'] for v in observed]==[p['id'] for p in profiles()],'EVERY_GRID_SCORE_PROFILE')
    for score,profile in zip(observed,profiles()):
        code=codes[profile['id']];key=hashlib.sha256(code.tobytes()).hexdigest();series,turn=grouped[key]
        need(score['profile']==profile and score['group']==key,'EXACT_SCORE_PARAMETERS_AND_GROUP')
        need(score['periods']=={k:period(series,*span) for k,span in PERIODS.items()},'ALL_GRID_PERIOD_METRICS')
        need(score['annual']=={str(y):period(series,f'{y}-01-01',max(d for d,_ in series if d[:4]==str(y))) for y in range(2018,2027)},
             'ALL_GRID_ANNUAL_METRICS')
        need(Q(score['turnover'])==sum(turn,Q(0)) and score['allocation_changes']==int((code[1:-1]!=code[:-2]).sum()),
             'ALL_GRID_TURNOVER_AND_CHANGES')
        need(score['close_target_counts']=={str(v):int((np.asarray(levels)[code]==v).sum()) for v in levels},'ALL_GRID_TARGET_COUNTS')
    training=json.loads((evidence/'training-scores.json').read_bytes())
    pts={v['id']:(Q(v['metrics']['multiple']),Q(v['metrics']['maximum_drawdown_magnitude'])) for v in training}
    frontier=sorted(pid for pid,(growth,dd) in pts.items() if not any(
        g>=growth and d<=dd and (g>growth or d<dd) for g,d in pts.values()))
    need(grid['training_frontier']==frontier and grid['unique_paths']==len(grouped),'EXACT_TRAINING_FRONTIER_AND_ALIASES')
    locked=lock(training,BASELINE)
    need(grid['selection']==locked,'GRID_SELECTION_REPORT')
    selected=list(dict.fromkeys([BASELINE,NO_EXTRA]+locked['selected']+frontier))
    aligned=[]
    for first,last,complete in windows(rows):
        aligned.append(dict(anchor=rows[first]['session'],end=rows[last]['session'],complete=complete,
            profiles={pid:period(grouped[hashlib.sha256(codes[pid].tobytes()).hexdigest()][0],rows[first+1]['session'],rows[last]['session'])
                      for pid in selected}))
    need(grid['original_defensive_windows']==aligned,'EVERY_GRID_COMMON_DEFENSIVE_WINDOW')
    refs=json.loads(Path('/driver/p00-sentinel-grid-references.json').read_bytes())
    for pid in (BASELINE,NO_EXTRA):
        report=source_summary['reports'][pid]
        need(report['journal']==refs['profiles'][pid]['direct_journal'] and report['full']==refs['profiles'][pid]['full'],
             'INDEPENDENT_BOTH_PREVIOUS_CONTROLS')
        need(hashlib.sha256(np.asarray(levels)[codes[pid]].astype('<f8').tobytes()).hexdigest()
             == refs['profiles'][pid]['measured_target_sha256'],'INDEPENDENT_PREVIOUS_CONTROL_TARGETS')
        verify_prefixes(evidence/('direct-'+pid+'.jsonl.gz'),[refs['profiles'][pid]['direct_journal']])
    check.update(status='P00_SENTINEL_GRID_INDEPENDENT_REVIEW_PASSED',all_144_period_and_annual_scores_verified=True,
                 all_selection_fields_verified=True,both_previous_control_journals_exact=True,
                 exact_training_frontier_verified=True,all_common_defensive_windows_verified=True,
                 canonical_core_transitions=0,original_core_backtests_resumed=False,
                 grid_review_seconds=time.monotonic()-started)
    (out/'independent-review.json').write_text(json.dumps(check,sort_keys=True,indent=2)+'\n')
