"""Hosted reconstruction of immutable objective values; no Core transitions."""
import argparse,base64,gzip,hashlib,json,multiprocessing,time
from copy import deepcopy
from decimal import Decimal as D
from fractions import Fraction as Q
from pathlib import Path
from types import SimpleNamespace
import owned_grid_worker as old
from owned_grid import BASELINE,canonical_leaf,configure,digest,encoded,hosted,identifier,need,profiles,select
from owned_value import Metric,ceiling_guard,factor_dependency_guard,nav_step
from selective_journal import Journal,load,save
from trace_screen import independent_factor,validate_baseline

_FACTORS=None;_VROOT=None


def controller_group(task):
    members=task
    if time.monotonic()>old._DEADLINE-180:return []
    configure(old._LEAF,members[0][1]);state=old._LEAF.fresh();codes=[bytearray() for x in members]
    lookup={v:i for i,v in enumerate(old._LEVELS)}
    for observation,parent,measured in old._OBS:
        state,evidence=old._LEAF.step(observation=observation,base_target=parent,state=state)
        if measured:
            for path,(_,config) in zip(codes,members):path.append(lookup[min(parent,float(config['active_ceiling']) if state['active'] else 1.)])
    result=[]
    for path,(index,config) in zip(codes,members):
        raw=bytes(path);result.append({'status':'CONTROLLER_PATH_COMPLETE','profile_id':identifier(config),'index':index,'config':config,
            'group':hashlib.sha256(raw).hexdigest(),'path_b64':base64.b64encode(raw).decode(),'controller_state':state})
    return result


def evaluate(task):
    group,codes=task
    if time.monotonic()>old._DEADLINE-180:return {'group':group,'status':'NOT_STARTED_BUDGET'}
    root=_VROOT/group;root.mkdir(exist_ok=False);journal=Journal(root/'checkpoints.jsonl.gz')
    nav=None;total=None;annual={};turnover=Q(0);chain='0'*64;chunk=hashlib.sha256();current=None;count=0
    try:
        for i,row in enumerate(old._ROWS):
            if time.monotonic()>old._DEADLINE-120:break
            day=row['session'];prior_nav=nav
            if i<2:nav=row['economics']['strategy_nav'];cost=row['economics']['turnover']
            else:
                f=_FACTORS[i][codes[i-2]*256+codes[i-1]];nav=nav_step(nav,f['net']);cost=f['turnover']
            chunk.update((day+'|'+nav+'\n').encode());count=i+1
            if old._P['training_start']<=day<=old._P['training_end']:
                if total is None:total=Metric((old._ROWS[i-1]['session'],prior_nav))
                total.add(day,nav);year=day[:4]
                if year not in annual:annual[year]=Metric((old._ROWS[i-1]['session'],prior_nav))
                annual[year].add(day,nav);turnover+=Q(cost)
            boundary=i==len(old._ROWS)-1 or day[:4]!=old._ROWS[i+1]['session'][:4] or i<2
            if boundary:
                state={'group':group,'completed':count,'session':day,'nav':nav,'last_two_codes':list(codes[max(0,i-1):i+1]),
                    'total':None if total is None else total.value,'annual':{y:m.value for y,m in annual.items()},'turnover':str(turnover)}
                chain=digest({'previous':chain,'block_sha256':chunk.hexdigest(),'state':state});chunk=hashlib.sha256()
                current={**state,'chain':chain};journal.write(current)
        status='COMPLETE' if count==len(old._ROWS) else 'PARTIAL'
        if current is None or current['completed']!=count:
            state={'group':group,'completed':count,'session':old._ROWS[count-1]['session'],'nav':nav,
                'last_two_codes':list(codes[max(0,count-2):count]),'total':None if total is None else total.value,
                'annual':{y:m.value for y,m in annual.items()},'turnover':str(turnover)}
            chain=digest({'previous':chain,'block_sha256':chunk.hexdigest(),'state':state});current={**state,'chain':chain};journal.write(current)
        journal.flush();save(root/'checkpoint.json.gz',{'schema':'research.owned-value-checkpoint/1','protocol_sha256':old._P['_sha256'],
            'source_checkpoint_sha256':old._P['_source_checkpoint'],**current,'journal':journal.commitment()})
    finally:journal.close()
    result={'status':status,'group':group,'completed':count,'nav':nav,'chain':chain,'turnover':str(turnover)}
    if status=='COMPLETE':result.update(metrics=total.result(),annual={y:m.result() for y,m in annual.items()})
    old.write(root/'result.json',result);return result


def factors(rows,paths,levels,out):
    import numpy as np
    from research.pooled_vacancy_funding.backtest import Account
    matrix=np.array([np.frombuffer(v,dtype='uint8') for v in paths.values()],dtype='uint16');table=[None,None];journal=Journal(out/'factors.jsonl.gz')
    account=Account(old._P['capital'],formed=False);count=0
    try:
        for i in range(2,len(rows)):
            day={}
            for pair in np.unique(matrix[:,i-2]*256+matrix[:,i-1]):
                pair=int(pair);before=deepcopy(rows[i-1]['economics']);before.update(strategy_nav='50000',held_allocation=str(levels[pair//256]),pending_allocation=str(levels[pair%256]))
                actual=old.canonical_account(before,rows[i],0.,account);independent_factor(before,rows[i],actual)
                value={'index':i,'session':rows[i]['session'],'pair':pair,'gross':actual['gross_factor'],'net':actual['net_factor'],
                    'cost':actual['transaction_cost_factor'],'turnover':actual['turnover']}
                day[pair]=value;journal.write(value);count+=1
            table.append(day)
        journal.flush();old.write(out/'factor-commitment.json',{'journal':journal.commitment(),'dated_pairs':count,'nav_independent':True,'current_target_independent':True})
    finally:journal.close()
    return table


def realize(group,codes,out):
    from research.pooled_vacancy_funding.backtest import Account
    root=out/'groups'/group;root.mkdir(parents=True,exist_ok=False);journal=Journal(root/'daily.jsonl.gz');archive=Journal(root/'checkpoints.jsonl.gz')
    account=Account(old._P['capital'],formed=False);previous=None
    try:
        for i,row in enumerate(old._ROWS):
            target=old._LEVELS[codes[i]]
            actual=old.startup_projection(row['economics'],previous,target,i) if i<2 else old.canonical_account(previous,row,target,account)
            if i>=2:
                independent_factor(previous,row,actual);need(actual['strategy_nav']==nav_step(previous['strategy_nav'],_FACTORS[i][codes[i-2]*256+codes[i-1]]['net']),'DIRECT_CANONICAL_VALUE_PARITY')
            journal.write({'session':row['session'],'nav':actual['strategy_nav'],'gross':actual['gross_factor'],'net':actual['net_factor'],
                'cost':actual['transaction_cost_factor'],'turnover':actual['turnover'],'held':actual['held_allocation'],'pending':actual['pending_allocation']})
            previous=actual
            if i<2 or i==len(old._ROWS)-1 or row['session'][:7]!=old._ROWS[i+1]['session'][:7]:
                journal.flush();cp={'schema':'research.owned-grid-value-checkpoint/1','group':group,'protocol_sha256':old._P['_sha256'],
                    'source_checkpoint_sha256':old._P['_source_checkpoint'],'session':row['session'],'completed':i+1,'account':actual,'journal':journal.commitment()}
                archive.write(cp);archive.flush();save(root/'checkpoint.json.gz',{**cp,'checkpoint_archive':archive.commitment()})
                previous=load(root/'checkpoint.json.gz')['account'];need(previous==actual,'DIRECT_SERIALIZED_STATE')
        numeric=load(_VROOT/group/'checkpoint.json.gz');need(numeric['nav']==previous['strategy_nav'],'COMPLETE_DIRECT_VALUE_PARITY')
    finally:journal.close();archive.close()
    result=json.loads((_VROOT/group/'result.json').read_bytes());result.update(account_checkpoint_sha256=hashlib.sha256((root/'checkpoint.json.gz').read_bytes()).hexdigest(),journal=cp['journal'])
    old.write(root/'result.json',result);return result


def run(a):
    hosted();started=time.monotonic();p=json.loads(a.protocol.read_bytes());registered=profiles(p);out=a.output;out.mkdir(parents=True,exist_ok=False);old.write(out/'protocol.json',p)
    p['_sha256']=hashlib.sha256(a.protocol.read_bytes()).hexdigest();p['_source_checkpoint']=validate_baseline(a.root)
    formation=[];full=[]
    for name,target in (('formation',formation),('daily',full)):
        with (a.root/(name+'.jsonl')).open('rb') as f:
            for raw in f:target.append(json.loads(raw))
    raw=Path('/fixed/sentinel/controller/owned_impairment.py').read_bytes();leaf_sha=hashlib.sha256(raw).hexdigest()
    need(leaf_sha=='699286647502b99ea9a3bf7c02b3bd839a43523d613ed3c62ad71271c2de092b','VALUE_FROZEN_LEAF')
    old.write(out/'ceiling-dependency-proof.json',ceiling_guard(raw))
    old.write(out/'factor-dependency-proof.json',factor_dependency_guard(Path('/fixed/sentinel/shadow_observation.py').read_bytes()))
    old.write(out/'baseline-gate.json',old.baseline_gate(full,formation,p,leaf_sha))
    rows=[r for r in full if r['session']<=p['training_end']];levels=sorted({0.,1.,.25,.55,.75}|{r['decision']['champion_target_core_exposure'] for r in [*formation,*rows]})
    old._ROWS=rows;old._OBS=[(SimpleNamespace(**r['evidence']['observation']),r['decision']['champion_target_core_exposure'],r['phase']=='MEASURED') for r in [*formation,*rows]]
    old._P=p;old._LEVELS=levels;old._LEAF_SHA=leaf_sha;old._DEADLINE=started+p['worker_seconds'];old._ROOT=out
    old.write(out/'source-contract.json',{'baseline_checkpoint_sha256':p['_source_checkpoint'],'protocol_sha256':p['_sha256'],'exposure_levels':levels,
        'training_measured_closes':len(rows),'source_measured_closes':len(full),'canonical_owned55_sha256':leaf_sha,'core_transitions_executed':0,'production_contacted':False,'engine':'COMPACT_EXACT_VALUE_FUNCTION'})
    tasks={}
    for i,cfg in enumerate(registered):tasks.setdefault(tuple(v for k,v in cfg.items() if k!='active_ceiling'),[]).append((i,cfg))
    need(len(tasks)==8748 and all(len(v)==3 for v in tasks.values()),'CONTROLLER_QUOTIENT_CLASS')
    states={};paths={};journal=Journal(out/'controller-paths.jsonl.gz')
    with multiprocessing.get_context('fork').Pool(processes=3,initializer=old.initialise) as pool:
        for batch in pool.imap_unordered(controller_group,tasks.values(),chunksize=4):
            for record in batch:
                states[record['profile_id']]=record;paths.setdefault(record['group'],base64.b64decode(record['path_b64']));journal.write(record)
    journal.flush();old.write(out/'controller-path-commitment.json',journal.commitment());journal.close()
    if len(states)!=26244:old.write(out/'summary.json',{'status':'CONTROLLER_CLASS_PARTIAL','profiles_completed':len(states)});return 2
    global _FACTORS,_VROOT
    _FACTORS=factors(rows,paths,levels,out);_VROOT=out/'values';_VROOT.mkdir();groups={}
    with multiprocessing.get_context('fork').Pool(processes=3) as pool:
        for result in pool.imap_unordered(evaluate,paths.items(),chunksize=1):groups[result['group']]=result
    if any(r['status']!='COMPLETE' for r in groups.values()):old.write(out/'summary.json',{'status':'FINANCIAL_VALUES_PARTIAL','unique_paths':len(paths),'completed_paths':sum(r['status']=='COMPLETE' for r in groups.values())});return 2
    base=identifier(BASELINE);base_path=base64.b64decode(states[base]['path_b64']);start=next(i for i,r in enumerate(rows) if r['session']>=p['training_start']);scores=[]
    for cfg in registered:
        pid=identifier(cfg);record=states[pid];value=groups[record['group']];codes=paths[record['group']]
        scores.append({'profile_id':pid,'config':cfg,'group':record['group'],'period':'TRAINING','evaluation_metrics_included':False,
            'different_funded_training_exposure':codes[max(0,start-2):-1]!=base_path[max(0,start-2):-1],
            'metrics':value['metrics'],'annual':value['annual'],'turnover':value['turnover']})
    save(out/'training-scores.json.gz',scores);selection=select(scores,p);old.write(out/'locked-selection.json',selection)
    realized={}
    for pid in dict.fromkeys([base]+selection['selected']):
        group=states[pid]['group']
        if group not in realized:realized[group]=realize(group,paths[group],out)
    later=old.later_profiles(full,formation,states,selection,realized,levels,p,out)
    status='COMPLETE_REVIEW_REQUIRED' if all(r['status']=='COMPLETE' for r in later.values()) else 'LATER_SUFFIX_PARTIAL'
    old.write(out/'summary.json',{'status':status,'engine':'COMPACT_EXACT_VALUE_FUNCTION','profiles':26244,'unique_training_paths':len(paths),'selection':selection,
        'later':later,'baseline_profile':base,'training_baseline':next(r for r in scores if r['profile_id']==base),'elapsed_seconds':time.monotonic()-started,
        'core_transitions_executed':0,'production_contacted':False,'lost_run_recovered':False})
    return 0 if status=='COMPLETE_REVIEW_REQUIRED' else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('root','protocol','output'):parser.add_argument('--'+name,type=Path,required=True)
    raise SystemExit(run(parser.parse_args()))
