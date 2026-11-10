"""Hosted-only descriptive attribution of already-selected hindsight paths."""
import math
import os
from pathlib import Path


def need(value, code):
    if not value:
        raise ValueError(code)


def hosted():
    need(os.environ.get('SENTINEL_ORACLE_HOSTED')=='1'
         and Path(__file__).resolve()==Path('/current/research/sentinel_oracle/attribution.py'),
         'HOSTED_ATTRIBUTION_ONLY')


def cycles(codes, axis, predicate):
    """Ranges use effective-opening row indices, with an exclusive end."""
    output=[]
    for row_index, code in enumerate(codes,1):
        active=predicate(code)
        if active and (not output or output[-1]['end_index'] is not None):
            output.append(dict(start_index=row_index,end_index=None))
        if not active and output and output[-1]['end_index'] is None:
            output[-1]['end_index']=row_index
    for index,item in enumerate(output):
        start,end=item['start_index'],item['end_index']
        item.update(id=index,start_session=axis[start],
            reduction_decision_session=axis[start-1],
            restore_session=axis[end] if end is not None else None,
            restore_decision_session=axis[end-1] if end is not None else None,
            last_reduced_session=axis[(end if end is not None else len(axis))-1],
            sessions=(end if end is not None else len(axis))-start,
            censored=end is None)
    return output


def build_attribution(source, table, baseline_codes, candidate_codes):
    hosted()
    from account import edge_at
    axis=source['axis']
    need(len(baseline_codes)==len(candidate_codes)==len(axis)-1,'ATTRIBUTION_COMPLETE_AXIS')
    levels=(0.,.55,1.)
    buckets={key:dict(sessions=0,log_advantage=0.,gross_log_advantage=0.,cost_log_advantage=0.)
             for key in ('LOWER_AFTER_OPEN','HIGHER_AFTER_OPEN','SAME_AFTER_OPEN')}
    switch_buckets={key:dict(sessions=0,log_advantage=0.) for key in ('ANY_SWITCH','NO_SWITCH')}
    days=[]
    for i in range(1,len(axis)):
        a,b=int(baseline_codes[i-1]),int(candidate_codes[i-1])
        old_a=int(baseline_codes[i-2]) if i>1 else 2
        old_b=int(candidate_codes[i-2]) if i>1 else 2
        source_edge=edge_at(table,i,old_a,a)
        oracle_edge=edge_at(table,i,old_b,b)
        delta=math.log(float(oracle_edge['net']))-math.log(float(source_edge['net']))
        gross=math.log(float(oracle_edge['gross']))-math.log(float(source_edge['gross']))
        cost=delta-gross
        label='LOWER_AFTER_OPEN' if b<a else 'HIGHER_AFTER_OPEN' if b>a else 'SAME_AFTER_OPEN'
        bucket=buckets[label]
        bucket['sessions']+=1;bucket['log_advantage']+=delta
        bucket['gross_log_advantage']+=gross;bucket['cost_log_advantage']+=cost
        switched=i>1 and (a!=old_a or b!=old_b)
        switch_bucket=switch_buckets['ANY_SWITCH' if switched else 'NO_SWITCH']
        switch_bucket['sessions']+=1;switch_bucket['log_advantage']+=delta
        days.append(dict(session=axis[i],decision_session=axis[i-1],
            baseline_old=levels[old_a] if i>1 else None,baseline_effective=levels[a],
            oracle_old=levels[old_b] if i>1 else None,oracle_effective=levels[b],
            bucket=label,any_switch=switched,log_advantage=delta,
            gross_log_advantage=gross,cost_log_advantage=cost))
    original=cycles(baseline_codes,axis,lambda code:code<2)
    hindsight=cycles(candidate_codes,axis,lambda code:code<2)
    overlaps={item['id']:[other['id'] for other in hindsight
        if max(item['start_index'],other['start_index'])
           <min(item['end_index'] or len(axis),other['end_index'] or len(axis))]
        for item in original}
    reverse={item['id']:[key for key,values in overlaps.items() if item['id'] in values] for item in hindsight}
    matches=[]
    for base in original:
        selected=overlaps[base['id']]
        if len(selected)!=1 or len(reverse[selected[0]])!=1:
            matches.append(dict(baseline_cycle=base['id'],oracle_cycles=selected,status='UNMATCHED_OR_MIXED'))
            continue
        oracle=hindsight[selected[0]]
        shift=oracle['start_index']-base['start_index']
        restore_shift=(oracle['end_index']-base['end_index']
                       if oracle['end_index'] is not None and base['end_index'] is not None else None)
        matches.append(dict(baseline_cycle=base['id'],oracle_cycles=selected,status='UNIQUE_OVERLAP',
            reduction_shift_sessions=shift,
            reduction_timing='EARLIER' if shift<0 else 'LATER' if shift>0 else 'SAME',
            restore_shift_sessions=restore_shift,
            restore_timing=None if restore_shift is None else
                'EARLIER' if restore_shift<0 else 'LATER' if restore_shift>0 else 'SAME'))
    zero_windows=cycles(baseline_codes,axis,lambda code:code==0)
    for window in zero_windows:
        start,end=window['start_index'],window['end_index'] or len(axis)
        selected=days[start-1:end-1]
        window['oracle_exposure_sessions']={str(levels[code]):sum(int(candidate_codes[i-1])==code for i in range(start,end))
                                           for code in range(3)}
        window['log_advantage']=sum(item['log_advantage'] for item in selected)
    return dict(scope='HINDSIGHT_DIAGNOSTIC_ONLY',training_eligible=False,
        units='Natural log wealth ratios, additive across observed day factors; not CAGR points.',
        exposure_buckets=buckets,switch_buckets=switch_buckets,
        total_log_advantage=sum(item['log_advantage'] for item in days),days=days,
        baseline_defensive_cycles=original,oracle_defensive_cycles=hindsight,
        unique_overlap_event_matches=matches,
        unmatched_oracle_cycle_ids=[key for key in reverse if key not in
            {item['oracle_cycles'][0] for item in matches if item['status']=='UNIQUE_OVERLAP'}],
        original_zero_windows=zero_windows,
        limits=['Descriptive timing differences are not predictable opportunities.',
                'A reduction below full is not necessarily a complete exit.',
                'After-open allocation buckets do not reassign the previous allocation overnight.'])
