"""Independent exact arithmetic over stopped compact objective evidence."""
import argparse,base64,gzip,hashlib,json,math,multiprocessing
from datetime import date
from decimal import Decimal as D,localcontext
from fractions import Fraction as Q
from pathlib import Path
import owned_grid_review as full
from owned_grid import BASELINE,digest,encoded,hosted,identifier,need,profiles,select
from selective_journal import load
from trace_screen import independent_factor,validate_baseline

_TABLE=None;_ROOT=None;_ROWS=None;_P=None;_CODES=None


class ExactMetric:
    def __init__(self,anchor):
        self.s={'anchor':anchor[0],'initial_nav':anchor[1],'peak':anchor[1],'worst_nav':anchor[1],'worst_peak':anchor[1],
            'start':None,'end':None,'closes':0,'nav':anchor[1]}
    def add(self,day,nav):
        s=self.s
        if D(nav)>D(s['peak']):s['peak']=nav
        nn,nd=D(nav).as_integer_ratio();pn,pd=D(s['peak']).as_integer_ratio()
        wn,wd=D(s['worst_nav']).as_integer_ratio();qn,qd=D(s['worst_peak']).as_integer_ratio()
        if nn*pd*wd*qn<wn*qd*nd*pn:s['worst_nav']=nav;s['worst_peak']=s['peak']
        s['start']=s['start'] or day;s['end']=day;s['closes']+=1;s['nav']=nav
    def result(self):
        s=self.s;multiple=Q(s['nav'])/Q(s['initial_nav']);days=(date.fromisoformat(s['end'])-date.fromisoformat(s['anchor'])).days
        return {'anchor':s['anchor'],'start':s['start'],'end':s['end'],'closes':s['closes'],'initial_nav':str(Q(s['initial_nav'])),
            'nav':str(Q(s['nav'])),'multiple':str(multiple),'total_return':str(multiple-1),
            'cagr':math.expm1(math.log(float(multiple))*365.2425/days),'maximum_drawdown_magnitude':str(1-Q(s['worst_nav'])/Q(s['worst_peak']))}


def review_value(group):
    root=_ROOT/'values'/group;result=json.loads((root/'result.json').read_bytes());cp=load(root/'checkpoint.json.gz')
    need(result['status']=='COMPLETE' and cp['schema']=='research.owned-value-checkpoint/1' and cp['protocol_sha256']==_P['_sha256']
        and cp['source_checkpoint_sha256']==_P['_source_checkpoint'],'VALUE_CHECKPOINT_LINEAGE')
    checkpoints={};h=hashlib.sha256();size=0;records=0
    for raw,saved in full.lines(root/'checkpoints.jsonl.gz'):
        need(saved['completed'] not in checkpoints,'VALUE_DUPLICATE_CURSOR');checkpoints[saved['completed']]=saved
        h.update(raw);size+=len(raw);records+=1
    need(cp['journal']=={'bytes':size,'records':records,'prefix_sha256':h.hexdigest()},'VALUE_CHECKPOINT_JOURNAL')
    codes=_CODES[group];nav=None;total=None;annual={};turnover=Q(0);chain='0'*64;chunk=hashlib.sha256();seen=set()
    with localcontext() as ctx:
        ctx.prec=28
        for i,row in enumerate(_ROWS):
            day=row['session'];prior=nav
            if i<2:nav=row['economics']['strategy_nav'];cost=row['economics']['turnover']
            else:
                f=_TABLE[i][codes[i-2]*256+codes[i-1]];nav=format((D(nav)*D(f['net'])).normalize(),'f');cost=f['turnover']
            chunk.update((day+'|'+nav+'\n').encode())
            if _P['training_start']<=day<=_P['training_end']:
                if total is None:total=ExactMetric((_ROWS[i-1]['session'],prior))
                total.add(day,nav);year=day[:4]
                if year not in annual:annual[year]=ExactMetric((_ROWS[i-1]['session'],prior))
                annual[year].add(day,nav);turnover+=Q(cost)
            if i+1 in checkpoints:
                state={'group':group,'completed':i+1,'session':day,'nav':nav,'last_two_codes':list(codes[max(0,i-1):i+1]),
                    'total':None if total is None else total.s,'annual':{y:m.s for y,m in annual.items()},'turnover':str(turnover)}
                chain=digest({'previous':chain,'block_sha256':chunk.hexdigest(),'state':state});chunk=hashlib.sha256()
                need(checkpoints[i+1]=={**state,'chain':chain},'EVERY_EXACT_VALUE_CHECKPOINT');seen.add(i+1)
    need(seen==set(checkpoints) and cp['completed']==len(_ROWS) and cp['nav']==nav and cp['chain']==chain,'VALUE_COMPLETE_AXIS_ZERO_TAIL')
    need(result['metrics']==total.result() and result['annual']=={y:m.result() for y,m in annual.items()}
        and result['nav']==nav and result['turnover']==str(turnover) and result['chain']==chain,'ALL_EXACT_OBJECTIVE_VALUES')
    return {'group':group,'records':len(_ROWS),'checkpoints':len(checkpoints)}


def run(a):
    import numpy as np
    hosted();out=a.output;out.mkdir(parents=True,exist_ok=False);p=json.loads(a.protocol.read_bytes());profiles(p)
    p['_sha256']=hashlib.sha256(a.protocol.read_bytes()).hexdigest();p['_source_checkpoint']=validate_baseline(a.root)
    stop=json.loads((a.evidence.parent/'worker-inspect.json').read_bytes());need(not stop['State']['Running'] and stop['State']['ExitCode']==0 and not stop['State']['OOMKilled'],'COMPACT_ACTUAL_STOP')
    summary=json.loads((a.evidence/'summary.json').read_bytes());need(summary['status']=='COMPLETE_REVIEW_REQUIRED' and summary['engine']=='COMPACT_EXACT_VALUE_FUNCTION','COMPACT_COMPLETE')
    formation=[];all_rows=[]
    for name,target in (('formation',formation),('daily',all_rows)):
        with (a.root/(name+'.jsonl')).open('rb') as f:
            for raw in f:target.append(json.loads(raw))
    rows=[r for r in all_rows if r['session']<=p['training_end']];states={};codes={};h=hashlib.sha256();size=0;count=0
    for raw,record in full.lines(a.evidence/'controller-paths.jsonl.gz'):
        pid=record['profile_id'];need(pid not in states,'COMPACT_DISTINCT_PROFILE');states[pid]=record
        path=base64.b64decode(record['path_b64'],validate=True);need(record['group']==hashlib.sha256(path).hexdigest(),'COMPACT_PATH_HASH')
        need(record['group'] not in codes or codes[record['group']]==path,'COMPACT_EQUIVALENCE');codes[record['group']]=path;h.update(raw);size+=len(raw);count+=1
    need(count==26244 and json.loads((a.evidence/'controller-path-commitment.json').read_bytes())=={'bytes':size,'records':count,'prefix_sha256':h.hexdigest()},'COMPACT_CLASS_PREFIX')
    contract=json.loads((a.evidence/'source-contract.json').read_bytes());levels=contract['exposure_levels']
    need(contract['baseline_checkpoint_sha256']==p['_source_checkpoint'] and contract['protocol_sha256']==p['_sha256'],'COMPACT_SOURCE_BINDING')
    controller=full.check_controller_paths(p,states,formation,rows,levels)
    table=[None,None]+[{} for r in rows[2:]];h=hashlib.sha256();size=0;count=0
    for raw,record in full.lines(a.evidence/'factors.jsonl.gz'):
        i=record['index'];pair=record['pair'];need(2<=i<len(rows) and pair not in table[i] and record['session']==rows[i]['session'],'FACTOR_DISTINCT_DATE_PAIR')
        before={**rows[i-1]['economics'],'strategy_nav':'50000','held_allocation':str(levels[pair//256]),'pending_allocation':str(levels[pair%256])}
        actual={'gross_factor':record['gross'],'net_factor':record['net'],'transaction_cost_factor':record['cost'],'turnover':record['turnover'],
            'strategy_nav':str(D('50000')*D(record['net']))};independent_factor(before,rows[i],actual)
        table[i][pair]=record;h.update(raw);size+=len(raw);count+=1
    need(json.loads((a.evidence/'factor-commitment.json').read_bytes())=={'journal':{'bytes':size,'records':count,'prefix_sha256':h.hexdigest()},
        'dated_pairs':count,'nav_independent':True,'current_target_independent':True},'FACTOR_COMPLETE_PREFIX')
    matrix=np.array([np.frombuffer(v,dtype='uint8') for v in codes.values()],dtype='uint16')
    for i in range(2,len(rows)):need(set(table[i])==set(int(v) for v in np.unique(matrix[:,i-2]*256+matrix[:,i-1])),'ALL_USED_DATED_FACTOR_PAIRS')
    global _TABLE,_ROOT,_ROWS,_P,_CODES
    _TABLE,_ROOT,_ROWS,_P,_CODES=table,a.evidence,rows,p,codes
    with multiprocessing.get_context('fork').Pool(processes=3) as pool:proofs=list(pool.imap_unordered(review_value,codes,chunksize=1))
    scores=load(a.evidence/'training-scores.json.gz');need(len(scores)==26244,'COMPACT_ALL_SCORES');base_path=codes[states[identifier(BASELINE)]['group']];start=next(i for i,r in enumerate(rows) if r['session']>=p['training_start'])
    for row in scores:
        state=states[row['profile_id']];value=json.loads((a.evidence/'values'/row['group']/'result.json').read_bytes())
        need(row['group']==state['group'] and row['config']==state['config'] and row['metrics']==value['metrics'] and row['annual']==value['annual']
            and row['turnover']==value['turnover'] and row['different_funded_training_exposure']==(codes[row['group']][max(0,start-2):-1]!=base_path[max(0,start-2):-1]),'COMPACT_SCORE_BINDING')
    selection=select(scores,p);need(selection==summary['selection']==json.loads((a.evidence/'locked-selection.json').read_bytes()),'COMPACT_TRAINING_ONLY_SELECTION')
    full._ROWS,full._P,full._ROOT,full._CODES,full._LEVELS=rows,p,a.evidence,codes,levels
    selected_groups={states[pid]['group'] for pid in [selection['baseline']]+selection['selected']}
    direct=[full.review_group(g) for g in selected_groups];later=[full.review_later(pid,states,selection,all_rows) for pid in dict.fromkeys([selection['baseline']]+selection['selected'])]
    result={'status':'INDEPENDENT_GRID_REVIEW_PASSED','engine':'COMPACT_EXACT_VALUE_FUNCTION','protocol_sha256':p['_sha256'],'controller':controller,
        'unique_financial_paths':len(proofs),'financial_records':sum(r['records'] for r in proofs),'checkpoint_prefixes':sum(r['checkpoints'] for r in proofs),
        'canonical_dated_factor_pairs':count,'direct_canonical_selected_paths':direct,'all_factors_and_prefixes_equal':True,
        'training_only_selection_recomputed':True,'later':later,'production_contacted':False,'core_transitions_executed':0,'lost_run_recovered':False}
    (out/'independent-review.json').write_bytes(encoded(result)+b'\n');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('root','protocol','evidence','output'):parser.add_argument('--'+name,type=Path,required=True)
    run(parser.parse_args());print('INDEPENDENT_COMPACT_VALUE_REVIEW_PASSED')
