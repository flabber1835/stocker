"""One bounded, matched H0-F/P2-F comparison on the unchanged Core trace."""
import argparse,gzip,hashlib,json,os,time,inspect
from pathlib import Path
from fractions import Fraction as Q
from datetime import date
from selective_input import Source
from selective_model import Runtime
from selective_journal import Journal,encode,digest,save,load
from holding_account import need,snapshot

BOUNDARY='2020-12-31'
STRESS=(('2021-02-12','2022-09-26'),('2025-02-19','2025-04-08'),('2026-06-30','2026-07-31'))

def run_book(source,canonical,root,source_sha,*,enabled,boundary=None,checkpoints=True):
    root.mkdir(exist_ok=False);events=Journal(root/'events.jsonl.gz');daily=Journal(root/'daily.jsonl.gz');formation=Journal(root/'formation.jsonl.gz')
    runtime=Runtime(source_sha,canonical,enabled=enabled,recorder=events,checkpoint=None if boundary is None else boundary['runtime'])
    path=hashlib.sha256();suffix=hashlib.sha256();values=[];treatments=[];transitions=0;last=None;started=time.perf_counter()
    old_boundary=None;previous_cp=None
    try:
        for frame in source.frames():
            day=frame['row']['session']
            if boundary is not None and day<=boundary['runtime']['session']:continue
            if checkpoints and last is not None and last['session'][:7]!=day[:7]:
                save(root/'month-end'/(last['session']+'.json.gz'),load(root/'checkpoint.json.gz'))
            if runtime.account is not None and frame['source_events'] and checkpoints:
                previous_cp=dict(runtime=runtime.checkpoint(),journals=dict(events=events.commitment(),daily=daily.commitment(),formation=formation.commitment()))
                save(root/'pre-event'/(day+'.json.gz'),previous_cp)
            row,proof=runtime.advance(frame,source)
            if row is None:
                formation.write(dict(session=day,source_state_sha256=frame['row']['state_sha256'],policy=proof));continue
            raw=encode(row['finance'])+b'\n';path.update(raw)
            if day>BOUNDARY:suffix.update(raw)
            daily.write(row);values.append((day,row['finance']['nav']));transitions+=len(row['transitions']);last=row
            for f in row['finance']['fills']:
                t=f['target']
                if f['side']!='SELL' or not t or not t['local_active']:continue
                before=Q(f['before_shares']);after=before-Q(f['filled_shares']);neutral=Q(Q(t['neutral_dollars'])//Q(f['raw_open']))
                additional=max(Q(0),min(before,neutral)-after)
                if additional:treatments.append(dict(session=day,episode=f['episode'],security_id=f['security_id'],additional_reduction=str(additional),cause=f['cause'],stress_window=any(lo<=day<=hi for lo,hi in STRESS)))
            events.flush();daily.flush()
            cp=dict(runtime=runtime.checkpoint(),journals=dict(events=events.commitment(),daily=daily.commitment(),formation=formation.commitment()))
            save(root/'checkpoint.json.gz',cp)
            if day==BOUNDARY:
                old_boundary=cp;save(root/'restart-boundary.json.gz',cp)
        need(last is not None and last['session']=='2026-07-31','REFUSED_P2_BOOK_INCOMPLETE')
        if checkpoints:save(root/'month-end'/(last['session']+'.json.gz'),load(root/'checkpoint.json.gz'))
        result=dict(status='BOOK_COMPLETE',records=len(values),first_session=values[0][0],last_session=values[-1][0],
            finance_path_sha256=path.hexdigest(),suffix_finance_sha256=suffix.hexdigest(),events=events.commitment(),
            daily=daily.commitment(),formation=formation.commitment(),final=runtime.checkpoint(),
            treatments=treatments,transitions=transitions,processing_seconds=time.perf_counter()-started)
        (root/'book-summary.json').write_bytes(encode({k:v for k,v in result.items() if k!='final'})+b'\n')
        return result,values,old_boundary
    except Exception as exc:
        failure=dict(type=type(exc).__name__,message=str(exc),last_good_session=None if last is None else last['session'],
            actual_event_tail_commitment=events.commitment(),actual_daily_tail_commitment=daily.commitment())
        (root/'failure.json').write_bytes(encode(failure)+b'\n');raise
    finally:events.close();daily.close();formation.close()

def metrics(values,anchor=None):
    need(len(values)>=1,'REFUSED_P2_METRIC_AXIS');capital=Q(values[0][1]) if anchor is None else Q(anchor[1]);start=values[0][0] if anchor is None else anchor[0]
    peak=capital;draw=Q(0);peak_day=start;trough=start;under=0;longest=0;current=0
    for day,v in values:
        nav=Q(v)
        if nav>=peak:peak=nav;peak_day=day;current=0
        else:current+=1;under+=1;longest=max(longest,current)
        dd=1-nav/peak
        if dd>draw:draw=dd;trough=day
    elapsed=(date.fromisoformat(values[-1][0])-date.fromisoformat(start)).days;multiple=Q(values[-1][1])/capital
    cagr=float(multiple)**(365.2425/elapsed)-1 if elapsed else 0.
    return dict(start=start,end=values[-1][0],closes=len(values),nav=values[-1][1],multiple=str(multiple),total_return=str(multiple-1),
        cagr=cagr,maximum_drawdown_magnitude=str(draw),trough=trough,underwater_closes=under,longest_underwater_closes=longest)

def all_metrics(series):
    result={'full':{k:metrics(v) for k,v in series.items()}}
    windows=[('year_'+str(y),f'{y}-01-01',f'{y}-12-31',True) for y in range(2008,2027)]
    windows += [('month_'+m,m+'-01',m+'-31',True) for m in sorted({d[:7] for d,v in series['H0']})]
    blocks=[('2008-02-22','2012-12-31'),('2013-01-01','2017-12-31'),('2018-01-01','2022-12-31'),('2023-01-01','2026-07-31')]
    fixed=[('2009-01-01','2010-12-31'),('2020-01-01','2020-12-31'),('2021-02-12','2022-09-26'),('2022-09-27','2023-08-14'),('2025-02-19','2025-04-08'),('2025-04-09','2025-12-31'),('2025-01-01','2026-07-31'),('2026-06-30','2026-07-31')]
    windows += [('block_'+str(i),lo,hi,True) for i,(lo,hi) in enumerate(blocks)]
    windows += [('fixed_'+str(i),lo,hi,False) for i,(lo,hi) in enumerate(fixed)]
    for name,lo,hi,use_prior in windows:
        result[name]={}
        for arm,values in series.items():
            chosen=[v for v in values if lo<=v[0]<=hi];prior=[v for v in values if v[0]<lo]
            if chosen:result[name][arm]=metrics(chosen,prior[-1] if use_prior and prior else None)
    return result

def canonical_bindings(source):
    from stock_strategy_shared.wealth_core import terminal,shares
    from sentinel.breadth import classifier
    values={}
    for m in (terminal,shares,classifier,inspect.getmodule(classifier.is_available)):
        p=Path(m.__file__);need(str(p).startswith('/fixed/'),'REFUSED_P2_CANONICAL_LOCATION')
        rel=str(p).removeprefix('/fixed/');h=hashlib.sha256(p.read_bytes()).hexdigest();need(h==source.frozen_sources[rel],'REFUSED_P2_CANONICAL_SOURCE');values[rel]=h
    return dict(terminal=terminal,shares=shares,classifier=classifier),values

def main():
    p=argparse.ArgumentParser()
    for n in ('root','bundle','qualified','output','protocol'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();need(os.environ.get('HOLDING_QUAL_HOSTED')=='1','REFUSED_LOCAL_H0_P2')
    plan=json.loads(a.protocol.read_bytes());a.output.mkdir(exist_ok=False);started=time.perf_counter()
    source=Source(a.root,a.bundle,a.qualified,a.output);source.last_formation_global=list(source.rows())[125]['economics']['pending_allocation']
    canonical,bindings=canonical_bindings(source)
    from selective_gate import run as qualify_composed
    qualify_composed(canonical,a.output/'composed-gate.json')
    source_sha=digest(dict(protocol=hashlib.sha256(a.protocol.read_bytes()).hexdigest(),
        sources={n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in plan['account_sources']},
        canonical=bindings,original_input=source.input_sha256))
    (a.output/'source-bindings.json').write_bytes(encode(dict(source_sha256=source_sha,canonical=bindings,original_base=source.base,original_input=source.input_sha256))+b'\n')
    baseline_started=time.perf_counter()
    h0,h0v,h0boundary=run_book(source,canonical,a.output/'H0',source_sha,enabled=None)
    disabled,_,_=run_book(source,canonical,a.output/'H0-disabled',source_sha,enabled=False,checkpoints=False)
    need(h0['finance_path_sha256']==disabled['finance_path_sha256'] and h0['events']==disabled['events']
        and h0['final']['account']==disabled['final']['account'] and h0['final']['pending']==disabled['final']['pending'],'REFUSED_MATCHED_DISABLED_CONTROL')
    readiness_seconds=time.perf_counter()-baseline_started
    need(readiness_seconds<=120,'REFUSED_BASELINE_READINESS_BUDGET')
    (a.output/'baseline-readiness.json').write_bytes(encode(dict(status='MATCHED_H0_DISABLED_PASSED',financial_fields_exact=True,
        source_sha256=source_sha,baseline=h0['finance_path_sha256'],disabled=disabled['finance_path_sha256'],processing_seconds=readiness_seconds))+b'\n')
    p2,p2v,p2boundary=run_book(source,canonical,a.output/'P2',source_sha,enabled=True)
    restarts={}
    for arm,original,boundary in [('H0',h0,h0boundary),('P2',p2,p2boundary)]:
        restored,_,_=run_book(source,canonical,a.output/(arm+'-restored-suffix'),source_sha,enabled=True if arm=='P2' else None,boundary=boundary,checkpoints=False)
        need(restored['finance_path_sha256']==original['suffix_finance_sha256'] and restored['final']==original['final'],'REFUSED_P2_SERIALIZED_SUFFIX')
        restarts[arm]=dict(boundary=BOUNDARY,preserved_prefix=boundary['journals'],suffix_sha256=restored['finance_path_sha256'],full_final_state_equal=True)
    import csv
    with gzip.open(a.bundle/'benchmark.csv.gz','rt') as f:spy={r['session']:r['level'] for r in csv.DictReader(f) if r['ticker']=='SPY'}
    spyv=[(day,str(Q(50000)*Q(spy[day])/Q(spy['2008-02-22']))) for day,v in h0v]
    blocks=all_metrics(dict(H0=h0v,P2=p2v,SPY=spyv));full=blocks['full'];growth=full['P2']['cagr']-full['H0']['cagr']
    improvement=Q(full['H0']['maximum_drawdown_magnitude'])-Q(full['P2']['maximum_drawdown_magnitude'])
    treatment=any(t['stress_window'] for t in p2['treatments'])
    verdict='STRICT_JOINT_IMPROVEMENT' if growth>1e-10 and improvement>Q('1e-10') else 'REJECT_P2_FOR_JOINT_OBJECTIVE'
    if not treatment:verdict='NO_ADDITIONAL_FUNDED_STRESS_TREATMENT_UNINFORMATIVE'
    result=dict(schema='research.selective-comparison-result/1',status='H0_P2_COMPARISON_COMPLETE',verdict=verdict,
        joint_loss=max(-growth/.01,-float(improvement)/.05),additional_funded_stress_treatment=treatment,
        source_sha256=source_sha,canonical_source_bindings=bindings,formation_records=126,measured_records=4639,
        months=sum(k.startswith('month_') for k in blocks),metrics=blocks,restarts=restarts,treatments=p2['treatments'],
        baseline_readiness_seconds=readiness_seconds,total_processing_seconds=time.perf_counter()-started,
        defensive_model='BIL_TOTAL_RETURN_FACTOR_CASH_PROXY',stock_model='PERSISTENT_FUNDED_QUANTITIES',
        old_scalar_model_equivalence=False,core_transitions_executed=0,parameter_search=False,production_contacted=False)
    (a.output/'summary.json').write_bytes(encode(result)+b'\n');print('H0_P2_COMPARISON_FINISHED')

if __name__=='__main__':main()
