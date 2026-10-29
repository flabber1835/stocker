"""Hosted canonical parent/leaf search with dated factor reuse and exact values."""
import argparse,base64,gzip,hashlib,json,os,time
from copy import deepcopy
from decimal import Decimal as D
from fractions import Fraction as Q
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from full_system_controller_policy import profiles,parent_module,select,digest,need
from owned_grid import canonical_leaf,configure
from owned_value import Metric,nav_step,factor_dependency_guard
from selective_journal import Journal,save,load
from full_system_controller_vector import targets as independent_targets

KEYS=('shadow_drawdown','shadow_r5','shadow_r10','shadow_r20','shadow_r40','damaged_breadth','green_breadth',
    'damaged_breadth_delta5','spy_r20','spy_vol_ratio','stops20','shadow_nav')

def write(path,value):
    need(not path.exists(),'OUTPUT_COLLISION');path.write_text(json.dumps(value,sort_keys=True,allow_nan=False)+'\n')

def controller_paths(rows,out):
    registered=profiles();raw=Path('/variant/sentinel/controller/champion_frozen.py').read_bytes();parent_sha=hashlib.sha256(raw).hexdigest()
    leafpath='/variant/sentinel/controller/owned_impairment.py';leaf_sha=hashlib.sha256(Path(leafpath).read_bytes()).hexdigest()
    need(leaf_sha=='699286647502b99ea9a3bf7c02b3bd839a43523d613ed3c62ad71271c2de092b','FROZEN_OWNED_SOURCE')
    vector=independent_targets(rows,registered);paths=[];journal=Journal(out/'controller-checkpoints.jsonl.gz');restores=0
    try:
        for index,profile in enumerate(registered):
            module=parent_module(raw,profile,parent_sha);native=module.Native();candidate=module.CandidateA()
            leaf=canonical_leaf(leafpath,leaf_sha,name='_private_sharadar_owned_grid_full_'+str(index));configure(leaf,profile['owned'])
            state=leaf.fresh();effective=previous=1.;values=[]
            for i,row in enumerate(rows):
                ob=row['evidence']['observation'];w=row['evidence']['recent_leadership']
                n,_,_=native.step(tuple(ob[k] for k in KEYS))
                desired,_=candidate.step(n,effective,ob['shadow_drawdown'],w['recent_r20'],w['recent_r40'],ob['spy_r20'],ob['shadow_r20'])
                effective,previous=previous,n
                state,evidence=leaf.step(observation=SimpleNamespace(**ob),base_target=desired,state=state)
                target=evidence['target'];need(target==float(vector[index,i]),'INDEPENDENT_FULL_CONTROLLER_EQUATIONS')
                if index==0:need(target==row['decision']['target_core_exposure'],'COMPLETE_BASELINE_CONTROLLER_PATH')
                values.append(target)
                if i==len(rows)-1 or row['session'][:7]!=rows[i+1]['session'][:7]:
                    cp={'profile':profile['id'],'session':row['session'],'native':native.snapshot(),'candidate':candidate.snapshot(),
                        'owned':state,'effective':effective,'previous':previous,'target_prefix_sha256':hashlib.sha256(np.array(values,dtype='<f8').tobytes()).hexdigest()}
                    journal.write(cp);material=json.loads(json.dumps(cp,allow_nan=False));native=module.Native.from_snapshot(material['native'])
                    candidate=module.CandidateA.from_snapshot(material['candidate']);state=material['owned'];restores+=1
            paths.append(values)
        journal.flush();write(out/'controller-proof.json',{'profiles':registered,'parent_source_sha256':parent_sha,'owned_source_sha256':leaf_sha,
            'actual_canonical_steps':len(rows)*len(registered),'independent_vector_exact':True,'actual_serialized_restores':restores,
            'journal':journal.commitment(),'baseline_full_formation_and_measured_targets_exact':True})
    finally:journal.close()
    return registered,np.asarray(paths)

def view(row,events):
    audit=row['evidence']['research_entry_audit'];closed=audit['closing_accounting']
    value=SimpleNamespace(last_processed_session=row['session'],shadow_nav_history=[row['evidence']['observation']['shadow_nav']],
        last_evidence=row['evidence'],last_decision=row['decision'],wealth_core=closed['wealth_core'])
    if row['economics'].get('formed_startup_marks') is not None:
        value.ledger={**closed['ledger'],'events':events[:closed['ledger']['event_count']]}
    return value

def actual_account(prior,row,target,events):
    from research.pooled_vacancy_funding.backtest import Account
    first=prior['held_allocation'] is None;formed=first and prior.get('research_entry_mode')=='FORMED_BASKET'
    state=view(row,events);state.last_decision={**row['decision'],'target_core_exposure':target}
    result=Account(prior['starting_cash'],formed=formed).advance(previous=prior,state=state,
        strategy_prices=row['economics']['strategy_prices'],formed_startup_marks=row['economics'].get('formed_startup_marks') if formed else None)
    for key in ('research_entry_mode','measurement_anchor_session'):
        if key in prior:result[key]=prior[key]
    return result

def independently_check(prior,row,value,events):
    from core_window_review import factor
    check={**row,'economics':value}
    if prior['held_allocation'] is None and value.get('formed_startup_marks') is not None:
        evidence=dict(row['evidence']);audit=deepcopy(evidence['research_entry_audit'])
        for name in ('opening_accounting','closing_accounting'):
            ledger=audit[name]['ledger'];ledger['events']=events[:ledger['event_count']]
        evidence['research_entry_audit']=audit;check['evidence']=evidence
    factor(prior,check)

def factor_table(rows,codes,levels,events,out):
    table=[{}];journal=Journal(out/'factors.jsonl.gz');count=0
    try:
        for i in range(1,len(rows)):
            pairs=np.unique(codes[:,i-1]) if i==1 else np.unique(codes[:,i-2].astype('uint16')*256+codes[:,i-1])
            day={}
            for pair in pairs:
                pair=int(pair);prior=deepcopy(rows[i-1]['economics']);prior['strategy_nav']='50000'
                prior['pending_allocation']=str(levels[pair if i==1 else pair%256])
                if i>1:prior['held_allocation']=str(levels[pair//256])
                actual=actual_account(prior,rows[i],0.,events);independently_check(prior,rows[i],actual,events)
                item={'index':i,'session':rows[i]['session'],'pair':pair,'gross':actual['gross_factor'],'net':actual['net_factor'],
                    'cost':actual['transaction_cost_factor'],'turnover':actual['turnover']};day[pair]=item;journal.write(item);count+=1
            table.append(day)
        journal.flush();write(out/'factor-proof.json',{'dated_actual_canonical_pairs':count,'independent_accounting_passed':True,'journal':journal.commitment(),
            'dependency_proof':factor_dependency_guard(Path('/variant/sentinel/shadow_observation.py').read_bytes())})
    finally:journal.close()
    return table

def values(rows,code,table):
    nav='50000';result=[(rows[0]['session'],nav)];turn=[Q(0)]
    for i in range(1,len(rows)):
        pair=int(code[0]) if i==1 else int(code[i-2])*256+int(code[i-1]);f=table[i][pair]
        nav=nav_step(nav,f['net']);result.append((rows[i]['session'],nav));turn.append(Q(f['turnover']))
    return result,turn

def metrics(values,start,end):
    subset=[v for v in values if start<=v[0]<=end];need(subset and subset[-1][0]==end,'METRIC_COMPLETE_END')
    anchor=max((v for v in values if v[0]<start),default=values[0]);selected=[v for v in subset if v[0]>anchor[0]]
    metric=Metric(anchor)
    for d,n in selected:metric.add(d,n)
    result=metric.result();result['measured_closes']=len(subset);return result

def run(root,out):
    need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_ONLY')
    out.mkdir(exist_ok=False);started=time.monotonic()
    from research.pooled_vacancy_funding.journal import read_checkpoint
    cp=read_checkpoint(root/'checkpoint.json.gz');need(cp['completed']==2156 and cp['source_cursor']=='2026-07-31','COMPLETE_REVIEWED_CORE_REQUIRED')
    source_review=json.loads((root.parent/'core-review.json').read_bytes());need(source_review['complete'] and source_review['all_daily_factors_and_chains_verified'],'ACTUAL_CORE_REVIEW')
    formation=[json.loads(v) for v in (root/'formation.jsonl').read_bytes().splitlines()];rows=[json.loads(v) for v in (root/'daily.jsonl').read_bytes().splitlines()]
    need(len(formation)==126 and len(rows)==2156 and rows[0]['session']=='2018-01-02','FULL_CORE_AXIS')
    registered,allpaths=controller_paths(formation+rows,out);paths=allpaths[:,126:];levels=sorted(set(paths.ravel()));need(set(levels)<=set((0.,.25,.55,.75,1.)),'DECLARED_EXPOSURE_LEVELS')
    codes=np.searchsorted(levels,paths).astype('uint8');events=cp['run']['state']['ledger']['events'];table=factor_table(rows,codes,levels,events,out)
    groups={};records=[];development=[];value_cp=Journal(out/'value-checkpoints.jsonl.gz');paths_j=Journal(out/'paths.jsonl.gz')
    try:
        for index,profile in enumerate(registered):
            code=codes[index];group=hashlib.sha256(code.tobytes()).hexdigest();paths_j.write({'profile':profile['id'],'group':group,'path_b64':base64.b64encode(code.tobytes()).decode()})
            if group not in groups:
                series,turn=values(rows,code,table);groups[group]={'series':series,'turnover':turn}
                for i,(day,nav) in enumerate(series):
                    if i==len(series)-1 or day[:7]!=series[i+1][0][:7]:value_cp.write({'group':group,'session':day,'completed':i+1,'nav':nav,
                        'prefix_sha256':digest(series[:i+1])})
            g=groups[group]
            record={'id':profile['id'],'core_id':json.loads((root.parent/'private-source-bindings.json').read_bytes())['profile_sha256'],
                'group':group,'metrics':metrics(g['series'],'2018-01-02','2022-12-30'),
                'turnover':str(sum((n for (day,_),n in zip(g['series'],g['turnover']) if day<='2022-12-30'),Q(0)))}
            records.append(record)
            development.append({**record,'metrics':metrics(g['series'],'2018-01-02','2020-12-31'),
                'turnover':str(sum((n for (day,_),n in zip(g['series'],g['turnover']) if day<='2020-12-31'),Q(0)))})
        value_cp.flush();paths_j.flush();write(out/'value-proof.json',{'unique_paths':len(groups),'profiles':256,'value_checkpoint_journal':value_cp.commitment(),
            'path_journal':paths_j.commitment(),'exposure_levels':levels})
    finally:value_cp.close();paths_j.close()
    # Only the training-shaped interface is passed into the selection function.
    locked=select(records,registered[0]['id']);earlier=select(development,registered[0]['id'])
    write(out/'locked-selection.json',locked);write(out/'locked-development-selection.json',earlier)
    write(out/'training-scores.json',records);write(out/'development-scores.json',development)
    frontier=set()
    for scores in (records,development):
        # A record is excluded only when strictly higher growth is available
        # at no larger drawdown. Retain all equal-growth ties for cost ordering.
        for record in scores:
            if not any(Q(other['metrics']['multiple'])>Q(record['metrics']['multiple'])
                and Q(other['metrics']['maximum_drawdown_magnitude'])<=Q(record['metrics']['maximum_drawdown_magnitude']) for other in scores):frontier.add(record['id'])
    selected=list(dict.fromkeys([registered[0]['id']]+locked['selected']+earlier['selected']+sorted(frontier)));reports={};realized={}
    for pid in selected:
        index=next(i for i,p in enumerate(registered) if p['id']==pid);series=groups[records[index]['group']]['series'];prior=None
        group=records[index]['group']
        if group in realized:
            reports[pid]={**reports[realized[group]],'profile':registered[index],'alias_of':realized[group]};continue
        realized[group]=pid;journal=Journal(out/('direct-'+pid+'.jsonl.gz'));restores=0
        try:
            for i,row in enumerate(rows):
                target=float(paths[index,i])
                if i==0:
                    actual=deepcopy(row['economics'])
                    if D(actual['pending_allocation'])!=D(str(target)):actual['pending_allocation']=str(target)
                else:
                    actual=actual_account(prior,row,target,events);independently_check(prior,row,actual,events)
                need(actual['strategy_nav']==series[i][1],'DIRECT_COMPLETE_CANONICAL_NAV')
                if index==0:need(actual==row['economics'],'COMPLETE_BASELINE_ECONOMIC_FIELDS')
                journal.write({'session':row['session'],'account':actual})
                prior=actual
                if i==len(rows)-1 or row['session'][:7]!=rows[i+1]['session'][:7]:
                    prior=json.loads(json.dumps(actual,allow_nan=False));need(prior==actual,'ACTUAL_ACCOUNT_SERIALIZATION');restores+=1
            journal.flush();reports[pid]={'profile':registered[index],'journal':journal.commitment(),'direct_serialized_account_restores':restores,
                'full':metrics(series,'2018-01-02','2026-07-31'),'evaluation_2023_2024':metrics(series,'2023-01-03','2024-12-31'),
                'evaluation_2021_2022':metrics(series,'2021-01-04','2022-12-30'),
                'diagnostic_2025_2026':metrics(series,'2025-01-02','2026-07-31'),
                'annual':{str(y):metrics(series,f'{y}-01-01',max(d for d,_ in series if d[:4]==str(y))) for y in range(2018,2027)},
                'different_funded_evaluation_closes':sum(int(codes[index,i-1]!=codes[0,i-1]) for i,r in enumerate(rows) if i and '2023-01-03'<=r['session']<='2024-12-31')}
        finally:journal.close()
    write(out/'summary.json',{'status':'COMPLETE_CONTROLLER_REVIEW_REQUIRED','profiles':256,'unique_paths':len(groups),'selection':locked,'reports':reports,
        'development_selection':earlier,'training_frontier':sorted(frontier),
        'elapsed_seconds':time.monotonic()-started,'production_contacted':False,'persistent_execution_certified':False,'known_history_not_unseen':True})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.root,a.output)
