"""Independent equations over stopped grid evidence; no account advancement."""
import argparse
import base64
from decimal import Decimal as D
from fractions import Fraction as Q
import gzip
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path

from owned_grid import BASELINE,digest,encoded,hosted,identifier,metric,need,profiles,select
from selective_journal import load
from trace_screen import independent_factor,validate_baseline

_ROWS=None;_P=None;_ROOT=None;_CODES=None;_LEVELS=None


def lines(path):
    with gzip.open(path,'rb') as f:
        for raw in f:
            need(raw.endswith(b'\n'),'REVIEW_COMPLETE_LINE');yield raw,json.loads(raw)


def text(value):return format(D(str(value)).normalize(),'f')


def check_account(previous,row,record,target,number):
    original=row['economics']
    if number<2:
        if number==0:need(previous is None and target==0 and original['held_allocation'] is None,'REVIEW_FIRST_UNFUNDED_CLOSE')
        else:need(D(previous['pending_allocation'])==0 and original['initial_deployment'] is True
            and D(original['held_allocation'])==0,'REVIEW_FIRST_FUNDED_OPEN')
        expected={**original,'pending_allocation':text(target)}
    else:
        expected={**original,'previous_strategy_nav':previous['strategy_nav'],'strategy_nav':record['nav'],
            'strategy_cumulative_return':text(D(record['nav'])/D(_P['capital'])-1),'held_allocation':record['held'],
            'pending_allocation':record['pending'],'turnover':record['turnover'],'gross_factor':record['gross'],
            'net_factor':record['net'],'transaction_cost_factor':record['cost']}
        need(D(expected['held_allocation'])==D(previous['pending_allocation'])
            and D(expected['pending_allocation'])==D(str(target)),'REVIEW_EXPOSURE_LAG_AND_TARGET')
        independent_factor(previous,row,expected)
    compact={'session':row['session'],'nav':expected['strategy_nav'],'gross':expected['gross_factor'],
        'net':expected['net_factor'],'cost':expected['transaction_cost_factor'],'turnover':expected['turnover'],
        'held':expected['held_allocation'],'pending':expected['pending_allocation']}
    need(record==compact,'REVIEW_EVERY_RECORDED_FINANCIAL_FIELD')
    return expected


def review_group(group):
    root=_ROOT/'groups'/group;result=json.loads((root/'result.json').read_bytes());need(result['status']=='COMPLETE','REVIEW_GROUP_COMPLETE')
    current=load(root/'checkpoint.json.gz');archive=list(lines(root/'checkpoints.jsonl.gz'))
    h=hashlib.sha256();size=0
    wanted={};last_cp=None
    for raw,cp in archive:
        need(cp['schema']=='research.owned-grid-value-checkpoint/1' and cp['group']==group
            and cp['protocol_sha256']==_P['_sha256'] and cp['source_checkpoint_sha256']==_P['_source_checkpoint'],'REVIEW_CHECKPOINT_LINEAGE')
        need(cp['completed'] not in wanted,'REVIEW_DISTINCT_CHECKPOINT_PREFIX');wanted[cp['completed']]=cp
        h.update(raw);size+=len(raw);last_cp=cp
    need(current=={**last_cp,'checkpoint_archive':{'bytes':size,'records':len(archive),'prefix_sha256':h.hexdigest()}},'REVIEW_CHECKPOINT_ARCHIVE')
    codes=_CODES[group];values=[];previous=None;rolling=hashlib.sha256();length=0;seen=set();turnover=Q(0);count=0
    for i,(raw,record) in enumerate(lines(root/'daily.jsonl.gz')):
        need(i<len(_ROWS),'REVIEW_EXTRA_FINANCIAL_DAY');row=_ROWS[i]
        previous=check_account(previous,row,record,_LEVELS[codes[i]],i)
        values.append((row['session'],record['nav']));rolling.update(raw);length+=len(raw);count+=1
        if _P['training_start']<=row['session']<=_P['training_end']:turnover+=Q(record['turnover'])
        if count in wanted:
            cp=wanted[count];need(cp['completed']==count and cp['session']==row['session'] and cp['account']==previous
                and cp['journal']=={'bytes':length,'records':count,'prefix_sha256':rolling.hexdigest()},'REVIEW_ALL_SERIALIZED_ACCOUNTS_AND_PREFIXES')
            seen.add(count)
    need(count==len(_ROWS) and seen==set(wanted) and current['journal']=={'bytes':length,'records':count,'prefix_sha256':rolling.hexdigest()},'REVIEW_COMPLETE_AXIS_ZERO_TAIL')
    chosen=[v for v in values if _P['training_start']<=v[0]<=_P['training_end']];anchor=max(v for v in values if v[0]<_P['training_start'])
    actual=metric(chosen,anchor);need(actual==result['metrics'] and Q(result['turnover'])==turnover,'REVIEW_TRAINING_METRICS')
    for year in range(2018,2023):
        lo=f'{year}-01-01';block=[v for v in values if lo<=v[0]<=f'{year}-12-31'];prior=max(v for v in values if v[0]<lo)
        need(metric(block,prior)==result['annual'][str(year)],'REVIEW_EVERY_TRAINING_YEAR')
    need(hashlib.sha256((root/'checkpoint.json.gz').read_bytes()).hexdigest()==result['account_checkpoint_sha256'],'REVIEW_CURRENT_ACCOUNT_FILE')
    return {'group':group,'records':count,'checkpoints':len(wanted),'all_factors_and_prefixes_equal':True}


def check_controller_paths(protocol,states,formation,rows,levels):
    import numpy as np
    configs=profiles(protocol);n=len(configs);all_codes=np.empty((n,len(rows)),dtype='uint8')
    for i,cfg in enumerate(configs):
        pid=identifier(cfg);saved=states[pid];need(saved['index']==i and saved['config']==cfg,'REVIEW_EXACT_PROFILE')
        codes=base64.b64decode(saved['path_b64'],validate=True)
        need(len(codes)==len(rows) and hashlib.sha256(codes).hexdigest()==saved['group'],'REVIEW_EXPOSURE_PATH_COMMITMENT')
        all_codes[i,:]=np.frombuffer(codes,dtype='uint8')
    numbers={k:np.array([float(c[k]) for c in configs]) for k in protocol['grid']}
    active=np.zeros(n,dtype='bool');entry=np.zeros(n,dtype='int64');recovery=np.zeros(n,dtype='int64');cursor=0
    finite=lambda v:type(v) in (float,int) and math.isfinite(v)
    for row in [*formation,*rows]:
        obs=row['evidence']['observation'];parent=row['decision']['champion_target_core_exposure']
        dd,damage,green,r20=(obs[k] for k in ('shadow_drawdown','damaged_breadth','green_breadth','shadow_r20'))
        for value in (damage,green):need(not finite(value) or 0<=value<=1,'REVIEW_SOURCE_BREADTH_RANGE')
        impaired=(dd<=numbers['entry_drawdown'])&(damage>=numbers['entry_damage'])&(green<=numbers['entry_green']) if all(finite(v) for v in (dd,damage,green)) else np.zeros(n,dtype='bool')
        healthy=(r20>numbers['recovery_core_r20_above'])&(damage<=numbers['recovery_damage'])&(green>=numbers['recovery_green']) if all(finite(v) for v in (r20,damage,green)) else np.zeros(n,dtype='bool')
        old=active.copy();entry=np.where(old,0,np.where(impaired,entry+1,0));recovery=np.where(old,np.where(healthy,recovery+1,0),0)
        entered=(~old)&(entry>=numbers['entry_sessions']);released=old&(recovery>=numbers['recovery_sessions'])
        active=(old|entered)&(~released);entry=np.where(entered,0,entry);recovery=np.where(released,0,recovery)
        if row['phase']=='MEASURED':
            target=np.minimum(parent,np.where(active,numbers['active_ceiling'],1.))
            actual=np.array(levels)[all_codes[:,cursor]];need(np.array_equal(target,actual),'REVIEW_EVERY_PROFILE_EVERY_DATED_TARGET')
            cursor+=1
    for i,cfg in enumerate(configs):
        expected={'version':1,'active':bool(active[i]),'entry_streak':int(entry[i]),'recovery_streak':int(recovery[i]),'last_session':protocol['training_end']}
        need(states[identifier(cfg)]['controller_state']==expected,'REVIEW_EVERY_FINAL_CONTROLLER_STATE')
    return {'profiles':n,'formation_observations':len(formation),'measured_observations':cursor,
        'all_canonical_controller_paths_independently_equal':True}


def scalar_step(state,config,row):
    obs=row['evidence']['observation'];day=row['session'];finite=lambda v:type(v) in (int,float) and math.isfinite(v)
    dd,damage,green,r20=(obs[k] for k in ('shadow_drawdown','damaged_breadth','green_breadth','shadow_r20'))
    impaired=all(finite(v) for v in (dd,damage,green)) and dd<=float(config['entry_drawdown']) and damage>=float(config['entry_damage']) and green<=float(config['entry_green'])
    healthy=all(finite(v) for v in (r20,damage,green)) and r20>float(config['recovery_core_r20_above']) and damage<=float(config['recovery_damage']) and green>=float(config['recovery_green'])
    active=state['active'];entry=recovery=0;reason='OWNED_NORMAL'
    if active:
        recovery=state['recovery_streak']+1 if healthy else 0
        if recovery>=config['recovery_sessions']:active=False;recovery=0;reason='OWNED_RECOVERED'
        else:reason='OWNED_IMPAIRMENT_HELD'
    else:
        entry=state['entry_streak']+1 if impaired else 0
        if entry>=config['entry_sessions']:active=True;entry=0;reason='OWNED_IMPAIRMENT_ENTER'
    after={'version':1,'active':active,'entry_streak':entry,'recovery_streak':recovery,'last_session':day}
    parent=row['decision']['champion_target_core_exposure'];ceiling=float(config['active_ceiling']) if active else 1.
    evidence={'target':min(parent,ceiling),'reason':reason,'active':active,'impaired':bool(impaired),'healthy':bool(healthy),
        'parent_target':parent,'ceiling':ceiling,'entry_streak':entry,'recovery_streak':recovery}
    return after,evidence


def review_later(pid,states,selection,all_rows):
    record=states[pid];root=_ROOT/'later'/pid;cp=load(root/'checkpoint.json.gz');result=json.loads((root/'result.json').read_bytes())
    parent=_ROOT/'groups'/record['group']/'checkpoint.json.gz';saved=load(parent)
    need(cp['parent_group']==record['group'] and cp['parent_checkpoint_sha256']==hashlib.sha256(parent.read_bytes()).hexdigest()
        and cp['own_training_controller_state']==record['controller_state'] and cp['selection_sha256']==digest(selection),'REVIEW_LATER_EXACT_SHARED_PREFIX_OWN_LATCH')
    previous=saved['account'];state=record['controller_state'];values=[];rolling=hashlib.sha256();size=0;count=0
    originals=[r for r in all_rows if r['session']>_P['training_end']]
    for raw,observed in lines(root/'daily.jsonl.gz'):
        need(count<len(originals),'REVIEW_LATER_EXTRA_DAY');row=originals[count];state,evidence=scalar_step(state,record['config'],row)
        need(observed['session']==row['session'] and observed['controller_state']==state and observed['controller_evidence']==evidence,'REVIEW_LATER_POLICY')
        actual=observed['account'];compact={'session':row['session'],'nav':actual['strategy_nav'],'gross':actual['gross_factor'],
            'net':actual['net_factor'],'cost':actual['transaction_cost_factor'],'turnover':actual['turnover'],
            'held':actual['held_allocation'],'pending':actual['pending_allocation']}
        expected=check_account(previous,row,compact,evidence['target'],count+2)
        need(actual==expected,'REVIEW_LATER_COMPLETE_ACCOUNT_FIELDS');previous=actual
        values.append((row['session'],actual['strategy_nav']));rolling.update(raw);size+=len(raw);count+=1
    need(count==len(originals) and cp['account']==previous and cp['controller_state']==state
        and cp['journal']=={'bytes':size,'records':count,'prefix_sha256':rolling.hexdigest()},'REVIEW_LATER_COMPLETE_PREFIX_ZERO_TAIL')
    anchor=(_P['training_end'],saved['account']['strategy_nav'])
    for label,lo,hi in (('evaluation',_P['evaluation_start'],_P['evaluation_end']),('2023','2023-01-03','2023-12-29'),
        ('2024','2024-01-02','2024-12-31'),('later_diagnostic',_P['diagnostic_start'],_P['diagnostic_end']),
        ('2025','2025-01-02','2025-12-31'),('2026_PARTIAL','2026-01-02',_P['diagnostic_end'])):
        chosen=[v for v in values if lo<=v[0]<=hi];prior=max([anchor]+[v for v in values if v[0]<lo])
        need(metric(chosen,prior)==result['blocks'][label],'REVIEW_LATER_PERIOD_METRICS')
    return {'profile_id':pid,'rows':count,'all_targets_factors_accounts_and_metrics_equal':True}


def run(a):
    hosted();p=json.loads(a.protocol.read_bytes());configs=profiles(p);out=a.output;out.mkdir(parents=True,exist_ok=False)
    p['_sha256']=hashlib.sha256(a.protocol.read_bytes()).hexdigest();p['_source_checkpoint']=validate_baseline(a.root)
    stop=json.loads((a.evidence.parent/'worker-inspect.json').read_bytes())
    need(stop['State']['Running'] is False and stop['State']['ExitCode']==0 and stop['State']['OOMKilled'] is False,'REVIEW_ACTUAL_STOPPED_WORKER')
    summary=json.loads((a.evidence/'summary.json').read_bytes());need(summary['status']=='COMPLETE_REVIEW_REQUIRED','REVIEW_COMPLETE_EVIDENCE')
    formation=[];all_rows=[]
    for name,target in (('formation',formation),('daily',all_rows)):
        with (a.root/(name+'.jsonl')).open('rb') as f:
            for raw in f:target.append(json.loads(raw))
    rows=[r for r in all_rows if r['session']<=p['training_end']]
    contract=json.loads((a.evidence/'source-contract.json').read_bytes());levels=contract['exposure_levels']
    expected_levels=sorted({0.,1.,.25,.55,.75}|{r['decision']['champion_target_core_exposure'] for r in [*formation,*rows]})
    need(levels==expected_levels and contract['baseline_checkpoint_sha256']==p['_source_checkpoint']
        and contract['protocol_sha256']==p['_sha256'],'REVIEW_SOURCE_VALUE_CONTRACT')
    states={};h=hashlib.sha256();length=0;count=0;codes={}
    for raw,record in lines(a.evidence/'controller-paths.jsonl.gz'):
        pid=record['profile_id'];need(pid not in states,'REVIEW_PROFILE_DUPLICATE');states[pid]=record
        path=base64.b64decode(record['path_b64'],validate=True);group=record['group']
        need(group not in codes or codes[group]==path,'REVIEW_EXACT_PATH_EQUIVALENCE');codes[group]=path
        h.update(raw);length+=len(raw);count+=1
    need(count==26244 and {identifier(c) for c in configs}==set(states)
        and json.loads((a.evidence/'controller-path-commitment.json').read_bytes())=={'bytes':length,'records':count,'prefix_sha256':h.hexdigest()},'REVIEW_COMPLETE_PROFILE_CLASS_AND_PREFIX')
    controller=check_controller_paths(p,states,formation,rows,levels)
    global _ROWS,_P,_ROOT,_CODES,_LEVELS
    _ROWS,_P,_ROOT,_CODES,_LEVELS=rows,p,a.evidence,codes,levels
    with multiprocessing.get_context('fork').Pool(processes=3) as pool:proofs=list(pool.imap_unordered(review_group,codes,chunksize=1))
    scores=load(a.evidence/'training-scores.json.gz');need(len(scores)==26244,'REVIEW_SCORE_CLASS')
    base_path=codes[states[identifier(BASELINE)]['group']];start=next(i for i,r in enumerate(rows) if r['session']>=p['training_start'])
    for row in scores:
        profile=states[row['profile_id']];actual=json.loads((a.evidence/'groups'/profile['group']/'result.json').read_bytes())
        need(row['group']==profile['group'] and row['config']==profile['config'] and row['metrics']==actual['metrics']
            and row['annual']==actual['annual'] and row['turnover']==actual['turnover']
            and row['different_funded_training_exposure']==(codes[profile['group']][max(0,start-2):-1]!=base_path[max(0,start-2):-1]),'REVIEW_ALL_TRAINING_SCORES')
    selection=select(scores,p);need(selection==json.loads((a.evidence/'locked-selection.json').read_bytes())==summary['selection'],'REVIEW_TRAINING_ONLY_SELECTION_LOCK')
    later=[review_later(pid,states,selection,all_rows) for pid in dict.fromkeys([selection['baseline']]+selection['selected'])]
    baseline=json.loads((a.evidence/'baseline-gate.json').read_bytes());need(baseline['status']=='BASELINE_CANONICAL_AND_ACCOUNTING_EXACT'
        and baseline['formation']==126 and baseline['measured']==4639 and baseline['all_daily_accounting_fields_equal'],'REVIEW_BASELINE_COMPATIBILITY_GATE')
    result={'status':'INDEPENDENT_GRID_REVIEW_PASSED','protocol_sha256':p['_sha256'],'controller':controller,
        'unique_financial_paths':len(proofs),'financial_records':sum(r['records'] for r in proofs),
        'checkpoint_prefixes':sum(r['checkpoints'] for r in proofs),'all_factors_and_prefixes_equal':True,
        'training_only_selection_recomputed':True,'later':later,'production_contacted':False,'core_transitions_executed':0}
    (out/'independent-review.json').write_bytes(encoded(result)+b'\n');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('root','protocol','evidence','output'):parser.add_argument('--'+name,type=Path,required=True)
    run(parser.parse_args());print('INDEPENDENT_OWNED_GRID_REVIEW_PASSED')
