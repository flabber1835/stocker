"""Independent controller equations, exact values, prefixes and training locks."""
import argparse,base64,gzip,hashlib,json,os
from decimal import Decimal as D,localcontext
from fractions import Fraction as Q
from pathlib import Path
import numpy as np
from full_system_controller_policy import profiles,need,digest
from full_system_controller_vector import targets
from selective_journal import verify_prefixes
from owned_grid import metric

def journal(path):
    with gzip.open(path,'rb') as f:
        for line in f:yield json.loads(line)

def independent_factor(prior,row,events):
    e=row['economics'];new=D(prior['pending_allocation']);op=D(e['parent_core_open_equity']);cl=D(e['parent_core_close_equity'])
    bo,bc,bp=map(D,(e['bil_open_adjusted'],e['bil_close_adjusted'],e['bil_previous_close_adjusted_current_publication']))
    if prior['held_allocation'] is None:
        if e.get('formed_startup_marks') is not None:
            audit=row['evidence']['research_entry_audit'];closing=audit['closing_accounting'];opening=audit['opening_accounting']
            notional=sum((D(str(ep['current_shares']))*D(str(e['formed_startup_marks'][ep['security_id']])) for ep in closing['wealth_core']['episodes'].values()),D(0))
            fees=sum((D(str(v['fees'])) for v in events[opening['ledger']['event_count']:closing['ledger']['event_count']] if v['event_type'] in ('BUY','SELL')),D(0))
            gross=1+new*((cl+fees)/op-1)+(1-new)*(bc/bo-1);turn=new*notional/op+(1-new);net=gross-D('.001')*turn;cost=net/gross
        else:
            turn=1-new;gross=1+new*(cl/op-1)+(1-new)*(bc/bo-1);cost=1-D('.001')*turn;net=gross*cost
    else:
        old=D(prior['held_allocation']);pc=D(prior['parent_core_close_equity']);turn=abs(new-old)
        gross=(new*cl/pc+(1-new)*bc/bp if new==old else (old*op/pc+(1-old)*bo/bp)*(new*cl/op+(1-new)*bc/bo))
        cost=1-D('.001')*turn;net=gross*cost
    return dict(gross=gross,net=net,turnover=turn,cost=cost)

def check_factor(actual,expected):
    for key in ('gross','net','turnover','cost'):need(abs(D(actual[key])-expected[key])<D('1e-22'),'INDEPENDENT_FACTOR_'+key)

def value_step(nav,net):
    with localcontext() as c:c.prec=28;return format((D(nav)*D(net)).normalize(),'f')

def training_metric(series,end):
    chosen=[v for v in series[1:] if v[0]<=end];m=metric(chosen,series[0]);m['measured_closes']=len(chosen)+1;return m

def independently_select(records,baseline):
    by={r['id']:r for r in records};base=by[baseline];draw=Q(base['metrics']['maximum_drawdown_magnitude'])
    ordering=lambda r:(-Q(r['metrics']['multiple']),Q(r['turnover']),r['id']!=baseline,r['id'])
    selected=[];choices=[]
    for fraction in ('0.50','0.75','1.0'):
        eligible=[r for r in records if Q(r['metrics']['maximum_drawdown_magnitude'])<=Q(fraction)*draw]
        chosen=sorted(eligible,key=ordering)[0]['id'] if eligible else None;choices.append(chosen)
        if chosen is not None and chosen not in selected:selected.append(chosen)
    joint=[r for r in records if Q(r['metrics']['multiple'])>Q(base['metrics']['multiple']) and Q(r['metrics']['maximum_drawdown_magnitude'])<draw]
    best=sorted(joint,key=ordering)[0]['id'] if joint else None
    if best is not None and best not in selected:selected.append(best)
    return selected,choices,len(joint),best

def review(root,evidence,out):
    need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_REVIEW_ONLY')
    from research.pooled_vacancy_funding.journal import read_checkpoint
    cp=read_checkpoint(root/'checkpoint.json.gz');events=cp['run']['state']['ledger']['events']
    formation=[json.loads(v) for v in (root/'formation.jsonl').read_bytes().splitlines()];rows=[json.loads(v) for v in (root/'daily.jsonl').read_bytes().splitlines()]
    summary=json.loads((evidence/'summary.json').read_bytes());proof=json.loads((evidence/'controller-proof.json').read_bytes());registered=profiles()
    need(summary['status']=='COMPLETE_CONTROLLER_REVIEW_REQUIRED' and proof['profiles']==registered,'ACTUAL_FULL_CONTROLLER_CLASS')
    need(len(formation)==126 and len(rows)==2156 and cp['completed']==2156,'COMPLETE_CORE_REQUIRED')
    vector=targets(formation+rows,registered);vp=json.loads((evidence/'value-proof.json').read_bytes());levels=vp['exposure_levels']
    for path,spec in [('controller-checkpoints.jsonl.gz',proof['journal']),('paths.jsonl.gz',vp['path_journal']),('value-checkpoints.jsonl.gz',vp['value_checkpoint_journal'])]:verify_prefixes(evidence/path,[spec])
    paths=list(journal(evidence/'paths.jsonl.gz'));need([p['profile'] for p in paths]==[p['id'] for p in registered],'ALL_PROFILE_IDENTITIES')
    codes={};groups={}
    for i,path in enumerate(paths):
        raw=base64.b64decode(path['path_b64'],validate=True);code=np.frombuffer(raw,dtype='uint8')
        need(len(code)==2156 and max(code)<len(levels) and hashlib.sha256(raw).hexdigest()==path['group'],'EXACT_TARGET_PATH')
        need(np.array_equal(np.asarray(levels)[code],vector[i,126:]),'INDEPENDENT_ALL_TARGETS')
        codes[path['profile']]=code;groups.setdefault(path['group'],code)
    for i,row in enumerate(formation+rows):need(vector[0,i]==row['decision']['target_core_exposure'],'INDEPENDENT_COMPLETE_BASELINE')
    for item in journal(evidence/'controller-checkpoints.jsonl.gz'):
        index=next(i for i,p in enumerate(registered) if p['id']==item['profile']);end=next(i for i,r in enumerate(formation+rows) if r['session']==item['session'])+1
        need(hashlib.sha256(np.asarray(vector[index,:end],dtype='<f8').tobytes()).hexdigest()==item['target_prefix_sha256'],'EVERY_CONTROLLER_PREFIX')
    fp=json.loads((evidence/'factor-proof.json').read_bytes());verify_prefixes(evidence/'factors.jsonl.gz',[fp['journal']]);table=[{} for _ in rows];factor_count=0
    for f in journal(evidence/'factors.jsonl.gz'):
        i,pair=f['index'],f['pair'];need(0<i<len(rows) and f['session']==rows[i]['session'] and pair not in table[i],'DATED_FACTOR_IDENTITY')
        prior=dict(rows[i-1]['economics']);prior.update(strategy_nav='50000',pending_allocation=str(levels[pair if i==1 else pair%256]))
        if i>1:prior['held_allocation']=str(levels[pair//256])
        check_factor(f,independent_factor(prior,rows[i],events));table[i][pair]=f;factor_count+=1
    values={};turnovers={}
    for group,code in groups.items():
        nav='50000';series=[(rows[0]['session'],nav)];turn=[Q(0)]
        for i in range(1,len(rows)):
            pair=int(code[0]) if i==1 else int(code[i-2])*256+int(code[i-1]);f=table[i][pair]
            nav=value_step(nav,f['net']);series.append((rows[i]['session'],nav));turn.append(Q(f['turnover']))
        values[group]=series;turnovers[group]=turn
    for item in journal(evidence/'value-checkpoints.jsonl.gz'):
        series=values[item['group']];n=item['completed'];need(series[n-1]==(item['session'],item['nav']) and digest(series[:n])==item['prefix_sha256'],'EVERY_VALUE_CHECKPOINT_PREFIX')
    for name,end,lockname in [('training-scores.json','2022-12-30','locked-selection.json'),('development-scores.json','2020-12-31','locked-development-selection.json')]:
        records=json.loads((evidence/name).read_bytes());need(len(records)==256 and [r['id'] for r in records]==[r['id'] for r in registered],'ALL_TRAINING_RECORDS')
        for record in records:
            series=values[record['group']];expected=training_metric(series,end);need(record['metrics']==expected,'INDEPENDENT_RATIONAL_TRAINING_METRICS')
            turnover=sum((n for (day,_),n in zip(series,turnovers[record['group']]) if day<=end),Q(0));need(Q(record['turnover'])==turnover,'INDEPENDENT_TRAINING_COSTS')
        locked=json.loads((evidence/lockname).read_bytes());selected,choices,joint,best=independently_select(records,registered[0]['id'])
        need(locked['selected']==selected and [b['id'] for b in locked['budget_choices']]==choices and locked['training_joint_improvements']==joint and locked['best_joint']==best and locked['evaluation_used'] is False,'INDEPENDENT_TRAINING_LOCK')
    direct_count=0
    for pid,report in summary['reports'].items():
        actualid=report.get('alias_of',pid);verify_prefixes(evidence/('direct-'+actualid+'.jsonl.gz'),[report['journal']])
        code=codes[pid];group=hashlib.sha256(code.tobytes()).hexdigest();series=values[group];prior=None
        for i,item in enumerate(journal(evidence/('direct-'+actualid+'.jsonl.gz'))):
            actual=item['account'];need(item['session']==rows[i]['session'] and actual['strategy_nav']==series[i][1],'DIRECT_ALL_ACCOUNT_VALUES')
            if i:
                expected=independent_factor(prior,rows[i],events)
                check_factor({'gross':actual['gross_factor'],'net':actual['net_factor'],'turnover':actual['turnover'],'cost':actual['transaction_cost_factor']},expected)
            if pid==registered[0]['id']:need(actual==rows[i]['economics'],'BASELINE_ALL_ECONOMIC_FIELDS')
            need(D(actual['pending_allocation'])==D(str(levels[code[i]])),'DIRECT_NEXT_OPEN_COMMITMENT');prior=actual;direct_count+=1
        def period(start,end):
            wanted=[v for v in series if start<=v[0]<=end];anchor=max((v for v in series if v[0]<start),default=series[0]);chosen=[v for v in wanted if v[0]>anchor[0]]
            m=metric(chosen,anchor);m['measured_closes']=len(wanted);return m
        for key,start,end in [('full','2018-01-02','2026-07-31'),('evaluation_2021_2022','2021-01-04','2022-12-30'),('evaluation_2023_2024','2023-01-03','2024-12-31'),('diagnostic_2025_2026','2025-01-02','2026-07-31')]:need(report[key]==period(start,end),'INDEPENDENT_LATER_METRICS')
        for year,m in report['annual'].items():need(m==period(year+'-01-01',max(d for d,_ in series if d[:4]==year)),'EVERY_ANNUAL_METRIC')
    out.mkdir(exist_ok=False);(out/'independent-review.json').write_text(json.dumps({'status':'FULL_SYSTEM_CONTROLLER_REVIEW_PASSED','profiles':256,
        'independent_targets':len(rows+formation)*256,'dated_factors':factor_count,'value_steps':len(groups)*(len(rows)-1),
        'direct_account_records':direct_count,'all_controller_value_journal_prefixes_verified':True,'all_training_locks_verified':True,
        'all_metrics_verified':True,'production_contacted':False},indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('root','evidence','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();review(a.root,a.evidence,a.output)
