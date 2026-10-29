"""Hosted finite-class objective evaluations on the immutable original trace."""
import argparse
import base64
from copy import deepcopy
from decimal import Decimal as D
from fractions import Fraction as Q
import gzip
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time
from types import SimpleNamespace

from owned_grid import BASELINE,canonical_leaf,configure,digest,encoded,hosted,identifier,metric,need,profiles,select
from selective_journal import Journal,save,load
from trace_screen import validate_baseline,independent_factor

_ROWS=None;_FORM=None;_OBS=None;_LEVELS=None;_ROOT=None;_DEADLINE=None;_LEAF_SHA=None;_P=None


def write(path,value):
    path=Path(path);need(not path.exists(),'OUTPUT_COLLISION');path.write_bytes(encoded(value)+b'\n')


def initialise():
    global _LEAF
    _LEAF=canonical_leaf('/fixed/sentinel/controller/owned_impairment.py',_LEAF_SHA,
        name='_private_sharadar_owned_grid_worker_'+str(os.getpid()))


def controller_task(task):
    index,config=task;pid=identifier(config)
    if time.monotonic()>_DEADLINE-120:return {'status':'NOT_STARTED_BUDGET','profile_id':pid}
    configure(_LEAF,config);state=_LEAF.fresh();codes=bytearray();level_index={v:i for i,v in enumerate(_LEVELS)}
    for observation,parent,measured in _OBS:
        state,evidence=_LEAF.step(observation=observation,base_target=parent,state=state)
        if measured:codes.append(level_index[evidence['target']])
    need(state['last_session']==_P['training_end'] and len(codes)==len(_ROWS),'CONTROLLER_COMPLETE_AXIS')
    path=bytes(codes);group=hashlib.sha256(path).hexdigest()
    return {'status':'CONTROLLER_PATH_COMPLETE','profile_id':pid,'index':index,'config':config,
        'group':group,'path_b64':base64.b64encode(path).decode(),'controller_state':state}


def canonical_account(prior,row,target,account):
    hosted()
    view=SimpleNamespace(last_processed_session=row['session'],
        shadow_nav_history=[row['evidence']['observation']['shadow_nav']],last_evidence=row['evidence'],
        last_decision={**row['decision'],'target_core_exposure':target})
    value=account.advance(previous=prior,state=view,strategy_prices=row['economics']['strategy_prices'])
    for key in ('research_entry_mode','measurement_anchor_session'):
        if key in prior:value[key]=prior[key]
    return value


def evaluate_path(task):
    group,codes=task
    if time.monotonic()>_DEADLINE-120:return {'status':'NOT_STARTED_BUDGET','group':group}
    from research.pooled_vacancy_funding.backtest import Account
    root=_ROOT/'groups'/group;root.mkdir(parents=True,exist_ok=False)
    journal=Journal(root/'daily.jsonl.gz');checkpoints=Journal(root/'checkpoints.jsonl.gz')
    account=Account(_P['capital'],formed=False);previous=None;values=[];turnover=Q(0);current=None;status='PARTIAL';failure=None
    try:
        for i,row in enumerate(_ROWS):
            day=row['session'];target=_LEVELS[codes[i]]
            if time.monotonic()>_DEADLINE-90:break
            if i<2:
                need(target==0 and (i==0 or previous['pending_allocation']=='0'),'COLD_START_COMMON_ZERO_EXPOSURE')
                actual=deepcopy(row['economics'])
            else:
                actual=canonical_account(previous,row,target,account);independent_factor(previous,row,actual)
            value={'session':day,'nav':actual['strategy_nav'],'gross':actual['gross_factor'],'net':actual['net_factor'],
                'cost':actual['transaction_cost_factor'],'turnover':actual['turnover'],
                'held':actual['held_allocation'],'pending':actual['pending_allocation']}
            journal.write(value);values.append((day,actual['strategy_nav']))
            if _P['training_start']<=day<=_P['training_end']:turnover+=Q(actual['turnover'])
            previous=actual
            if i<2 or i==len(_ROWS)-1 or day[:7]!=_ROWS[i+1]['session'][:7]:
                journal.flush();checkpoint={'schema':'research.owned-grid-value-checkpoint/1','group':group,
                    'protocol_sha256':_P['_sha256'],'source_checkpoint_sha256':_P['_source_checkpoint'],
                    'session':day,'completed':i+1,'account':actual,'journal':journal.commitment()}
                checkpoints.write(checkpoint);checkpoints.flush();current={**checkpoint,'checkpoint_archive':checkpoints.commitment()}
                save(root/'checkpoint.json.gz',current)
                # Actual serialized state is used for the next canonical step.
                previous=load(root/'checkpoint.json.gz')['account'];need(previous==actual,'SERIALIZED_ACCOUNT_STATE')
        if previous is not None and previous['last_session']==_P['training_end']:status='COMPLETE'
    except Exception as exc:
        failure={'type':type(exc).__name__,'message':str(exc),'last_checkpoint':None if current is None else current['session']}
    finally:journal.close();checkpoints.close()
    result={'status':status,'group':group,'failure':failure,'last_checkpoint':None if current is None else current['session']}
    if status=='COMPLETE':
        anchor=max(v for v in values if v[0]<_P['training_start']);chosen=[v for v in values if _P['training_start']<=v[0]<=_P['training_end']]
        annual={}
        for year in range(2018,2023):
            lo=f'{year}-01-01';selected=[v for v in values if lo<=v[0]<=f'{year}-12-31'];prior=max(v for v in values if v[0]<lo)
            annual[str(year)]=metric(selected,prior)
        result.update(metrics=metric(chosen,anchor),annual=annual,turnover=str(turnover),
            journal=current['journal'],account_checkpoint_sha256=hashlib.sha256((root/'checkpoint.json.gz').read_bytes()).hexdigest())
    write(root/'result.json',result);return result


def baseline_gate(rows,formation,protocol,sha):
    from research.pooled_vacancy_funding.backtest import Account
    leaf=canonical_leaf('/fixed/sentinel/controller/owned_impairment.py',sha,name='_private_sharadar_owned_grid_baseline')
    configure(leaf,BASELINE);state=leaf.fresh();account=Account(protocol['capital'],formed=False);previous=None;count=0
    for row in [*formation,*rows]:
        state,evidence=leaf.step(observation=SimpleNamespace(**row['evidence']['observation']),
            base_target=row['decision']['champion_target_core_exposure'],state=state)
        need(evidence==row['decision']['owned_impairment'],'BASELINE_ALL_CANONICAL_CONTROLLER_FIELDS')
        if row['phase']=='FORMATION':continue
        if count<2:
            need(evidence['target']==0 and row['economics']['pending_allocation']=='0','BASELINE_SHARED_STARTUP')
            actual=deepcopy(row['economics'])
        else:
            actual=canonical_account(previous,row,evidence['target'],account)
            independent_factor(previous,row,actual)
            need(actual==row['economics'],'BASELINE_COMPLETE_DAILY_ACCOUNTING_FIELDS')
        previous=actual;count+=1
    need(count==4639,'BASELINE_COMPLETE_AXIS')
    return {'status':'BASELINE_CANONICAL_AND_ACCOUNTING_EXACT','formation':126,'measured':count,
        'all_controller_evidence_fields_equal':True,'all_daily_accounting_fields_equal':True,
        'reporting_fields_carried_explicitly':['research_entry_mode','measurement_anchor_session']}


def later_profiles(all_rows,formation,states,selection,groups,levels,protocol,out):
    from research.pooled_vacancy_funding.backtest import Account
    wanted=list(dict.fromkeys([selection['baseline']]+selection['selected']));results={}
    for pid in wanted:
        row=states[pid];config=row['config'];group=row['group'];parent=load(out/'groups'/group/'checkpoint.json.gz')
        need(parent['session']==protocol['training_end'] and digest(row['controller_state'])==digest(states[pid]['controller_state']),'LATER_OWN_PREFIX')
        leaf=canonical_leaf('/fixed/sentinel/controller/owned_impairment.py',_LEAF_SHA,name='_private_sharadar_owned_grid_later_'+pid)
        configure(leaf,config);state=row['controller_state'];previous=parent['account'];account=Account(protocol['capital'],formed=False)
        directory=out/'later'/pid;directory.mkdir(parents=True,exist_ok=False);journal=Journal(directory/'daily.jsonl.gz')
        values=[];stopped=None
        try:
            for original in all_rows:
                day=original['session']
                if day<=protocol['training_end']:continue
                if time.monotonic()>_DEADLINE-90:stopped=day;break
                state,evidence=leaf.step(observation=SimpleNamespace(**original['evidence']['observation']),
                    base_target=original['decision']['champion_target_core_exposure'],state=state)
                actual=canonical_account(previous,original,evidence['target'],account);independent_factor(previous,original,actual)
                if pid==selection['baseline']:need(actual==original['economics'],'LATER_BASELINE_COMPLETE_FIELDS')
                journal.write({'session':day,'controller_state':state,'controller_evidence':evidence,'account':actual})
                previous=actual;values.append((day,actual['strategy_nav']))
            journal.flush();saved={'profile_id':pid,'parent_group':group,
                'parent_checkpoint_sha256':groups[group]['account_checkpoint_sha256'],'own_training_controller_state':row['controller_state'],
                'controller_state':state,'account':previous,'journal':journal.commitment(),'selection_sha256':digest(selection)}
            save(directory/'checkpoint.json.gz',saved)
        finally:journal.close()
        record={'status':'COMPLETE' if stopped is None else 'PARTIAL','profile_id':pid,'parent_group':group,'next_unprocessed_session':stopped}
        if record['status']=='COMPLETE':
            anchor=(protocol['training_end'],parent['account']['strategy_nav']);blocks={}
            for label,lo,hi in (('evaluation',protocol['evaluation_start'],protocol['evaluation_end']),('2023','2023-01-03','2023-12-29'),
                ('2024','2024-01-02','2024-12-31'),('later_diagnostic',protocol['diagnostic_start'],protocol['diagnostic_end']),
                ('2025','2025-01-02','2025-12-31'),('2026_PARTIAL','2026-01-02',protocol['diagnostic_end'])):
                chosen=[v for v in values if lo<=v[0]<=hi];prior=max([anchor]+[v for v in values if v[0]<lo]);blocks[label]=metric(chosen,prior)
            record['blocks']=blocks
        write(directory/'result.json',record);results[pid]=record
    return results


def run(a):
    hosted();started=time.monotonic();p=json.loads(a.protocol.read_bytes());registered=profiles(p)
    out=a.output;out.mkdir(exist_ok=False,parents=True);write(out/'protocol.json',p)
    p['_sha256']=hashlib.sha256(a.protocol.read_bytes()).hexdigest();p['_source_checkpoint']=validate_baseline(a.root)
    need(p['core_financial_changes'] is False and p['execution_model']=='ORIGINAL_FROZEN_SCALAR_NEXT_OPEN_EXPOSURE_ACCOUNT','MODEL_SCOPE')
    full=[];formation=[]
    for name,target in (('formation',formation),('daily',full)):
        with (a.root/(name+'.jsonl')).open('rb') as f:
            for raw in f:target.append(json.loads(raw))
    leaf_path=Path('/fixed/sentinel/controller/owned_impairment.py');leaf_sha=hashlib.sha256(leaf_path.read_bytes()).hexdigest()
    need(leaf_sha=='699286647502b99ea9a3bf7c02b3bd839a43523d613ed3c62ad71271c2de092b','FROZEN_OWNED55_IDENTITY')
    write(out/'baseline-gate.json',baseline_gate(full,formation,p,leaf_sha))
    rows=[r for r in full if r['session']<=p['training_end']];observations=[(SimpleNamespace(**r['evidence']['observation']),r['decision']['champion_target_core_exposure'],r['phase']=='MEASURED') for r in [*formation,*rows]]
    levels=sorted({0.,1.,.25,.55,.75}|{parent for obs,parent,m in observations});need(len(levels)<256,'EXPOSURE_CODE_DOMAIN')
    global _ROWS,_FORM,_OBS,_LEVELS,_ROOT,_DEADLINE,_LEAF_SHA,_P
    _ROWS,_FORM,_OBS,_LEVELS,_ROOT,_DEADLINE,_LEAF_SHA,_P=rows,formation,observations,levels,out,started+p['worker_seconds'],leaf_sha,p
    write(out/'source-contract.json',{'baseline_checkpoint_sha256':p['_source_checkpoint'],'protocol_sha256':p['_sha256'],
        'exposure_levels':levels,'training_measured_closes':len(rows),'source_measured_closes':len(full),'canonical_owned55_sha256':leaf_sha,
        'core_transitions_executed':0,'production_contacted':False})
    states={};unique={};path_journal=Journal(out/'controller-paths.jsonl.gz')
    pool=multiprocessing.get_context('fork').Pool(processes=3,initializer=initialise)
    try:
        for record in pool.imap_unordered(controller_task,enumerate(registered),chunksize=4):
            if record['status']!='CONTROLLER_PATH_COMPLETE':continue
            states[record['profile_id']]=record;unique.setdefault(record['group'],base64.b64decode(record['path_b64']))
            path_journal.write(record)
        path_journal.flush();write(out/'controller-path-commitment.json',path_journal.commitment())
        if len(states)!=26244:
            write(out/'summary.json',{'status':'CONTROLLER_CLASS_PARTIAL','profiles_completed':len(states),'production_contacted':False});return 2
        base_id=identifier(BASELINE);base_path=base64.b64decode(states[base_id]['path_b64']);groups={}
        for result in pool.imap_unordered(evaluate_path,unique.items(),chunksize=1):
            groups[result['group']]=result
        if any(r['status']!='COMPLETE' for r in groups.values()):
            write(out/'summary.json',{'status':'FINANCIAL_VALUES_PARTIAL','profiles_completed':len(states),'unique_paths':len(unique),
                'completed_paths':sum(r['status']=='COMPLETE' for r in groups.values()),'production_contacted':False});return 2
    finally:pool.close();pool.join();path_journal.close()
    start=next(i for i,r in enumerate(rows) if r['session']>=p['training_start']);scores=[]
    for config in registered:
        pid=identifier(config);record=states[pid];result=groups[record['group']];codes=base64.b64decode(record['path_b64'])
        scores.append({'profile_id':pid,'config':config,'group':record['group'],'period':'TRAINING','evaluation_metrics_included':False,
            'different_funded_training_exposure':codes[max(0,start-2):-1]!=base_path[max(0,start-2):-1],
            'metrics':result['metrics'],'annual':result['annual'],'turnover':result['turnover']})
    save(out/'training-scores.json.gz',scores);selection=select(scores,p);write(out/'locked-selection.json',selection)
    later=later_profiles(full,formation,states,selection,groups,levels,p,out)
    status='COMPLETE_REVIEW_REQUIRED' if all(r['status']=='COMPLETE' for r in later.values()) else 'LATER_SUFFIX_PARTIAL'
    write(out/'summary.json',{'status':status,'profiles':26244,'unique_training_paths':len(unique),'selection':selection,'later':later,
        'baseline_profile':base_id,'training_baseline':next(r for r in scores if r['profile_id']==base_id),
        'elapsed_seconds':time.monotonic()-started,'core_transitions_executed':0,'production_contacted':False,
        'interpretation':'FINITE_CLASS_ORIGINAL_SCALAR_ACCOUNT_KNOWN_HISTORY_NOT_PAPER_FILL_CERTIFICATION'})
    return 0 if status=='COMPLETE_REVIEW_REQUIRED' else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ('root','protocol','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();raise SystemExit(run(args))
