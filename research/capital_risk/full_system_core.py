"""Hosted own-origin Core trials, exact factual successor and stopped review."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import time

from full_system_benchmark import need,save


def hosted():
    need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
        and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_CORE_ONLY')


def arguments(root,resume=False,maximum=0):
    values=['--policy','wealth-core-v5-zero-share-fixed-2008-v1','--bundle','/frozen/bundle',
        '--archive','/frozen/archive/corpus.zip','--previous','/frozen/references/owned55',
        '--compact','/frozen/references/compact/champion-daily.csv','--output',str(root),
        '--max-transitions',str(maximum)]
    if resume:values+=['--resume','--checkpoint',str(root/'checkpoint.json.gz')]
    return values


def initial_repair(root):
    from research.pooled_vacancy_funding import backtest,runtime
    from research.pooled_vacancy_funding.journal import Journal,read_checkpoint
    from research.pooled_vacancy_funding.repair import load_repair
    saved=read_checkpoint(root/'checkpoint.json.gz')
    need(saved['completed']==0 and saved['run']['state']['last_processed_session'] is None,'OWN_ZERO_FINANCIAL_PREDECESSOR')
    run=runtime.restore(saved['run'],policy=saved['base']['policy'],input_sha256=backtest.input_hash(saved['base'],[]))
    need(runtime.checkpoint(run)==saved['run'] and saved['base']['sources']==backtest.source_files(),'OWN_SOURCE_INPUT_CANONICAL_RESTORE')
    journal=Journal(root,resume=True)
    try:journal.verify(saved['journals'])
    finally:journal.close()
    for name,spec in saved['journals'].items():
        need(spec['bytes']==0 and (root/(name+'.jsonl')).stat().st_size==0,'OWN_EMPTY_PREFIXES')
    lineage=root/'predecessor-checkpoints';lineage.mkdir();own=lineage/(saved['sha256']+'.json.gz')
    shutil.copyfile(root/'checkpoint.json.gz',own)
    suppress=[];add=[];evidence=[];facts=[]
    for case in ('dade-20071106','gldn-20080228','navteq-20080709','myovant-20230309'):
        folder=Path('/frozen/historical-repair-evidence')/case
        old=json.loads((folder/'fixed/overlay.json').read_bytes())
        future=[r for r in old['suppress']+old['add'] if r['session']>saved['source_cursor']]
        if not future:continue
        need(len(future)==len(old['suppress'])+len(old['add']),'NO_PART_CONSUMED_FACT_REUSE')
        suppress+=old['suppress'];add+=old['add'];evidence+=old['source_evidence']
        facts.append({'case':case,'overlay_sha256':backtest.file_sha(folder/'fixed/overlay.json'),
            'primary_extraction_sha256':backtest.file_sha(folder/'primary-source-extraction.json'),
            'actual_replay_proof_sha256':backtest.file_sha(folder/'post-replay-verification.json')})
    need(facts and len(facts)==1 and facts[0]['case']=='myovant-20230309','DECLARED_FUTURE_FACTS_ONLY')
    document={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':saved['run']['checkpoint_sha256'],
        'source_evidence':evidence,'suppress':suppress,'add':add}
    path=root.parent/'own-factual-successor.json';save(path,document)
    repair=load_repair(path,resume_session=saved['source_cursor'],predecessor_checkpoint_sha256=saved['run']['checkpoint_sha256'])
    save(root.parent/'origin-admission.json',{'schema':'research.full-system-own-origin/1',
        'outer_file_sha256':backtest.file_sha(own),'outer_sha256':saved['sha256'],
        'inner_sha256':saved['run']['checkpoint_sha256'],'state_sha256':saved['run']['state_sha256'],
        'input_sha256':saved['run']['input_sha256'],'source_sha256':backtest.hash_value(saved['base']['sources']),
        'resume_session':saved['source_cursor'],'all_four_prefixes_empty_verified':True,
        'canonical_roundtrip':True,'future_facts':facts,'new_repair_sha256':repair.sha256,
        'original_descriptors_used_as_predecessor_authority':False})
    return path


def measure_core(root):
    from research.pooled_vacancy_funding import backtest
    from stock_strategy_shared.wealth_core.state import HoldingEpisode,SlotState
    from stock_strategy_shared.wealth_core.funding import config
    from full_system_source import proposals
    parameters=json.loads(Path('/out/private-source-bindings.json').read_bytes())['parameters']
    cfg=config('wealth-core-v5-zero-share-fixed-2008-v1')
    need(cfg.n_slots==20 and cfg.entry_weight==.05 and cfg.transaction_cost_bps==10
        and cfg.top_fraction==parameters['leadership'],'ACTUAL_BOUND_CORE_CONFIGURATION')
    episode=HoldingEpisode('S','S','I',0,'2017-01-03','2017-01-04',100.,100.,1.,1.,100.)
    boundary=100*parameters['stop']
    need(episode.stop_triggered(boundary) and not episode.stop_triggered(boundary+.01),'ACTUAL_CANONICAL_STOP_BOUNDARY')
    episode.market_sessions_held=parameters['review']-1;need(not episode.review_due,'REVIEW_EARLY_REFUSAL')
    episode.market_sessions_held+=1;need(episode.review_due,'REVIEW_EXACT_AGE')
    episode.review_completed=True;need(not episode.review_due,'REVIEW_ONCE_ONLY')
    slot=SlotState(0,cooldown_sessions_elapsed=parameters['cooldown']-1)
    need(slot.in_cooldown,'COOLDOWN_EARLY_REFUSAL');slot.age_cooldown();need(not slot.in_cooldown,'COOLDOWN_EXACT_RELEASE')
    save(root.parent/'actual-parameter-cases.json',{'status':'ACTUAL_CANONICAL_PARAMETER_BOUNDARIES_PASSED',
        'parameters':parameters,'cases':8,'not_economic_performance':True})
    os.environ['FULL_SYSTEM_WARMUP_ONLY']='1'
    try:code=backtest.main(arguments(root))
    finally:os.environ.pop('FULL_SYSTEM_WARMUP_ONLY',None)
    need(code==0,'FEATURE_WARMUP_REFUSED')
    path=initial_repair(root)
    from research.pooled_vacancy_funding.retries import RetryStats
    original=RetryStats.advance;times=[]
    def observed(*args,**kwargs):
        value=original(*args,**kwargs);times.append(time.monotonic());return value
    RetryStats.advance=observed;start=time.monotonic()
    try:code=backtest.main(arguments(root,True,12)+['--repair-overlay',str(path)])
    finally:RetryStats.advance=original
    need(code==0 and len(times)==12,'TWELVE_COMMITTED_TRANSITIONS')
    intervals=[b-a for a,b in zip(times[1:],times[2:])]
    mean=statistics.mean(intervals);remaining=126+2156-12
    budget=(datetime(2026,10,29,17,57,tzinfo=timezone.utc)-datetime.now(timezone.utc)).total_seconds()
    estimate=mean*remaining*1.35+720
    save(root.parent/'speed-gate.json',{'ordinary_intervals_seconds':intervals,'mean_seconds':mean,
        'remaining_transitions':remaining,'projected_seconds_including_35pct_margin_and_review':estimate,
        'remaining_budget_seconds':budget,'pass':estimate<budget,'performance_scored':False})
    return estimate<budget


def finish(root):
    from research.pooled_vacancy_funding import backtest
    if not measure_core(root):return 'PRESERVED_TIMING_INFEASIBLE_NO_EFFICACY_RESULT'
    code=backtest.main(arguments(root,True))
    result=json.loads((root/'result.json').read_bytes()) if (root/'result.json').is_file() else {}
    return 'COMPLETE_REVIEW_REQUIRED' if code==0 and result.get('status')=='COMPLETE_PENDING_REVIEW' else 'INCOMPLETE_CORE_PRESERVED'


def review(root,output):
    from research.pooled_vacancy_funding import backtest,runtime
    from research.pooled_vacancy_funding.journal import Journal,read_checkpoint
    from research.pooled_input_support.bundle import axis
    from core_window_review import reconcile,factor,monthly_metrics,near
    saved=read_checkpoint(root/'checkpoint.json.gz');base=saved['base'];full=axis()
    wanted=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
    need(base['sources']==backtest.source_files(),'ACTUAL_PRIVATE_SOURCES')
    current=wanted.index(saved['source_cursor']);need(current>=298,'COMMITTED_CURSOR')
    paths=[root/'checkpoint.json.gz',*sorted((root/'pre-event').glob('*.json.gz')),
        *sorted((root/'month-end').glob('*.json.gz')),*sorted((root/'predecessor-checkpoints').glob('*.json.gz'))]
    journal=Journal(root,resume=True);checkpoints=[]
    try:
        for path in paths:
            value=read_checkpoint(path);backtest.validate_checkpoint(value,base,wanted)
            restored=runtime.restore(value['run'],policy=base['policy'],input_sha256=backtest.input_hash(base,value['repairs']))
            need(runtime.checkpoint(restored)==value['run'],'EVERY_CANONICAL_ROUNDTRIP')
            journal.verify(value['journals']);checkpoints.append(value)
    finally:journal.close()
    events=saved['run']['state']['ledger']['events'];prior=None;counts={};tails={};rows=[];accountings=0
    for stream,sessions,phase in (('formation',wanted[299:min(425,current+1)],'FORMATION'),('daily',wanted[425:current+1],'MEASURED')):
        raw=(root/(stream+'.jsonl')).read_bytes();size=saved['journals'][stream]['bytes']
        tail=raw[size:];tails[stream]={'bytes':len(tail),'sha256':hashlib.sha256(tail).hexdigest()}
        values=[json.loads(v) for v in raw[:size].splitlines()]
        need([r['session'] for r in values]==sessions,'COMPLETE_COMMITTED_AXIS')
        for row in values:
            need(row['phase']==phase,'COMMITTED_PHASE')
            audit=row['evidence']['research_entry_audit']
            for key,valuation in (('opening_accounting','parent_core_open_equity'),('closing_accounting','parent_core_close_equity')):
                snapshot=audit[key];n=snapshot['ledger'].pop('event_count')
                need(type(n) is int and 0<=n<=len(events),'ACTUAL_LEDGER_PREFIX_COUNT')
                snapshot['ledger']['events']=events[:n]
                reconcile(snapshot);near(snapshot['resolved_equity'],row['economics'][valuation],'INDEPENDENT_RAW_VALUATION')
                accountings+=1
            factor(prior,row);prior=row['economics'];rows.append(row)
        counts[stream]=len(values)
    for stream in ('monthly','watch'):
        raw=(root/(stream+'.jsonl')).read_bytes();size=saved['journals'][stream]['bytes']
        tails[stream]={'bytes':len(raw)-size,'sha256':hashlib.sha256(raw[size:]).hexdigest()}
    complete=saved['source_cursor']==backtest.END and saved['completed']==2156
    need(not complete or counts=={'formation':126,'daily':2156} and all(t['bytes']==0 for t in tails.values()),'COMPLETE_AXIS_AND_TAILS')
    # Every daily chain includes the source-bound state hash and full accounting.
    chain=backtest.hash_value(base);successors=[]
    for raw in (root/'watch.jsonl').read_bytes().splitlines():
        event=json.loads(raw)
        if event.get('schema')=='research.pooled-action-successor/1':successors.append(event)
    for row in rows:
        while successors and successors[0]['unchanged_through']<row['session']:
            event=successors.pop(0);chain=backtest.hash_value({'previous':chain,'event':event})
        chain=backtest.hash_value({'previous':chain,'session':row['session'],'state_sha256':row['state_sha256'],'economics':row['economics']})
        need(chain==row['chain_sha256'],'EVERY_DAILY_CHAIN')
    while successors and successors[0]['unchanged_through']<=saved['source_cursor']:
        event=successors.pop(0);chain=backtest.hash_value({'previous':chain,'event':event})
    need(not successors and chain==saved['chain'],'FINAL_CHAIN_COMMITMENT')
    months=monthly_metrics(root,backtest.START) if complete else None
    proof={'schema':'research.full-system-core-review/1','status':'COMPLETE_CORE_REVIEW_PASSED' if complete else 'PARTIAL_CORE_PREFIX_REVIEWED',
        'complete':complete,'counts':counts,'accounting_snapshots':accountings,'canonical_checkpoints':len(checkpoints),
        'all_prefixes_verified':True,'all_daily_factors_and_chains_verified':True,'preserved_tails':tails,
        'monthly_metrics':months,'checkpoint_sha256':saved['sha256'],'production_contacted':False}
    save(output,proof)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True);a=p.parse_args();hosted()
    if a.mode=='economic':
        root=Path('/out/book');status=finish(root);save(Path('/out/core-outcome.json'),{'status':status,'performance_interpreted':False})
        raise SystemExit(0 if status=='COMPLETE_REVIEW_REQUIRED' else 2)
    else:review(Path('/out/book'),Path('/out/core-review.json'))
