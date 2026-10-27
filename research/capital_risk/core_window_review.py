"""Independent stopped-book accounting and canonical prefix review."""
from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal as D,localcontext
import hashlib
import json
from pathlib import Path
from datetime import date
import math

MONEY=D('0.0000001')


def require(value,code):
    if not value:raise ValueError(code)


def near(a,b,code):
    require(abs(D(str(a))-D(str(b)))<=MONEY,code)


def reconcile(snapshot):
    state=snapshot['wealth_core'];ledger=snapshot['ledger'];cash=D('50000')
    quantities=defaultdict(D);claims=defaultdict(D)
    for event in ledger['events']:
        near(event['cash_before'],cash,'REFUSED_LEDGER_CASH_BEFORE')
        cash+=D(str(event['cash_delta']))
        near(event['cash_after'],cash,'REFUSED_LEDGER_CASH_AFTER')
        require(D(str(event['cash_after']))>=0,'REFUSED_NEGATIVE_CASH')
        sid=event['security_id']
        if sid is not None:
            quantities[sid]+=D(str(event['shares_delta']))
            require(quantities[sid]>=-D('1e-10'),'REFUSED_TRANSIENT_SHORT_QUANTITY')
        kind=event['event_type']
        if kind in ('BUY','SELL'):
            q,p,fee=map(lambda x:D(str(x)),(event['shares_delta'],event['price'],event['fees']))
            near(fee,abs(q)*p*D('.001'),'REFUSED_TRADE_FEE')
            near(event['cash_delta'],-q*p-fee,'REFUSED_TRADE_CASH')
        if kind=='DIVIDEND_ACCRUED':
            detail=event['detail'];amount=D(str(detail['amount']))
            require(abs(D(str(detail['shares']))-quantities[sid])<=D('1e-9'),'REFUSED_DIVIDEND_OWNERSHIP')
            near(amount,D(str(detail['shares']))*D(str(event['price'])),'REFUSED_DIVIDEND_ENTITLEMENT')
            claims[(sid,event['session'])]+=amount
        elif kind=='DIVIDEND_PAID':
            claims[(sid,event['detail']['accrued_session'])]-=D(str(event['detail']['amount']))
    near(state['cash'],cash,'REFUSED_BOOK_CASH')
    require(D(str(state['cash']))>=0,'REFUSED_NEGATIVE_BOOK_CASH')
    actual=defaultdict(D)
    for ep in state['episodes'].values():actual[ep['security_id']]+=D(str(ep['current_shares']))
    value=D(str(state['cash']))
    for sid in set(quantities)|set(actual):
        error=abs(quantities[sid]-actual[sid])
        quote=snapshot['prices'].get(sid,{})
        price=quote.get('raw_price')
        require(quantities[sid]>=-D('1e-10') and error<=D('1e-9'),'REFUSED_LEDGER_SHARES')
        if actual[sid]:
            require(price is not None and D(str(price))>0 and quote['status'] in
                ('RAW_OPEN','CURRENT','PENDING_TERMS_CARRIED'),'REFUSED_UNRESOLVED_RAW_MARK')
            require(error*D(str(price))<=MONEY,'REFUSED_MARKED_QUANTITY_ERROR')
            value+=actual[sid]*D(str(price))
    receivables=defaultdict(D)
    for r in ledger['receivables']:
        receivables[(r['security_id'],r['accrued_session'])]+=D(str(r['amount']))
    for key in set(claims)|set(receivables):
        require(claims[key]>=-MONEY and receivables[key]>=-MONEY,'REFUSED_NEGATIVE_RECEIVABLE')
        near(claims[key],receivables[key],'REFUSED_RECEIVABLE')
    value+=sum(receivables.values(),D(0))
    near(value,snapshot['resolved_equity'],'REFUSED_RAW_MARK_EQUITY')


def factor(prior,row):
    e=row['economics']
    if prior is None or e.get('measurement_anchor_session')==row['session']:
        require(D(e['net_factor'])==1,'REFUSED_DAY_ZERO_FACTOR');return
    target=D(prior['pending_allocation']);op=D(e['parent_core_open_equity']);cl=D(e['parent_core_close_equity'])
    bo,bc,bp=map(D,(e['bil_open_adjusted'],e['bil_close_adjusted'],e['bil_previous_close_adjusted_current_publication']))
    if prior['held_allocation'] is None:
        if e.get('formed_startup_marks') is not None:
            opened=row['evidence']['research_entry_audit']['opening_accounting']
            closed=row['evidence']['research_entry_audit']['closing_accounting']
            notional=sum((D(str(ep['current_shares']))*D(str(e['formed_startup_marks'][ep['security_id']]))
                for ep in closed['wealth_core']['episodes'].values()),D(0))
            events=closed['ledger']['events'][len(opened['ledger']['events']):]
            fees=sum((D(str(v['fees'])) for v in events if v['event_type'] in ('BUY','SELL')),D(0))
            gross=1+target*((cl+fees)/op-1)+(1-target)*(bc/bo-1)
            turn=target*notional/op+(1-target)
            expected=gross-D('.001')*turn
        else:
            turn=1-target;gross=1+target*(cl/op-1)+(1-target)*(bc/bo-1)
            expected=gross*(1-D('.001')*turn)
    else:
        old=D(prior['held_allocation']);pc=D(prior['parent_core_close_equity'])
        turn=abs(target-old)
        gross=(target*cl/pc+(1-target)*bc/bp if target==old else
            (old*op/pc+(1-old)*bo/bp)*(target*cl/op+(1-target)*bc/bo))
        expected=gross*(1-D('.001')*turn)
    near(e['turnover'],turn,'REFUSED_FUNDED_TURNOVER')
    require(abs(D(e['net_factor'])-expected)<D('1e-22'),'REFUSED_FUNDED_FACTOR')
    near(e['strategy_nav'],D(prior['strategy_nav'])*expected,'REFUSED_FUNDED_NAV')


def compare_disabled(original,disabled):
    count=0
    for name in ('formation','daily'):
        with (original/(name+'.jsonl')).open('rb') as left,(disabled/(name+'.jsonl')).open('rb') as right:
            while True:
                a,b=left.readline(),right.readline()
                require(bool(a)==bool(b),'REFUSED_B0_AXIS')
                if not a:break
                a,b=json.loads(a),json.loads(b)
                for value in (a,b):
                    for key in ('state_sha256','input_sha256','chain_sha256'):value.pop(key)
                require(json.dumps(a,sort_keys=True,allow_nan=False)==json.dumps(b,sort_keys=True,allow_nan=False),
                    'REFUSED_B0_FINANCIAL_PATH_'+a['session'])
                count+=1
    return dict(status='B0_FULL_WINDOW_FINANCIAL_PATH_MATCHED',records=count,
        ignored_paths=['state_sha256','input_sha256','chain_sha256'])


def monthly_metrics(root,start):
    reports={r['session']:r for r in map(json.loads,(root/'monthly.jsonl').open('rb'))}
    prior_day=None;state={};count=0
    with localcontext() as context:
        context.prec=50
        for r in map(json.loads,(root/'daily.jsonl').open('rb')):
            day=r['session']
            for name,raw in r['comparison_navs'].items():
                nav=D(raw)
                if name not in state:state[name]=dict(initial=nav,prior=nav,month=nav,year=nav,peak=nav,dd=D(0))
                v=state[name]
                if prior_day is not None and prior_day[:7]!=day[:7]:v['month']=v['prior']
                if prior_day is not None and prior_day[:4]!=day[:4]:v['year']=v['prior']
                v['peak']=max(v['peak'],nav);v['dd']=min(v['dd'],nav/v['peak']-1)
                if day in reports:
                    actual=reports[day]['series'][name];multiple=nav/v['initial']
                    expected=dict(nav=nav,monthly_return=nav/v['month']-1,ytd_return=nav/v['year']-1,
                        cumulative_return=multiple-1,multiple=multiple,drawdown=nav/v['peak']-1,maximum_drawdown=v['dd'])
                    for key,value in expected.items():require(D(actual[key])==value,'REFUSED_MONTHLY_'+key)
                    elapsed=(date.fromisoformat(day)-date.fromisoformat(start)).days
                    cagr=math.expm1(float(multiple.ln()*D('365.2425')/elapsed)) if elapsed else None
                    require(cagr==actual['cagr'],'REFUSED_MONTHLY_CAGR')
                v['prior']=nav
            if day in reports:count+=1
            prior_day=day
    require(count==len(reports),'REFUSED_MONTHLY_AXIS')
    return count


def review(root,output):
    from research.pooled_vacancy_funding import backtest,runtime
    from research.pooled_vacancy_funding.journal import Journal,read_checkpoint
    from research.pooled_input_support.bundle import axis
    saved=read_checkpoint(root/'checkpoint.json.gz');base=saved['base']
    full=axis();selected=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
    require(saved['source_cursor']==backtest.END and saved['completed']==backtest.MEASURED_CLOSES,'REFUSED_WINDOW_INCOMPLETE')
    before={p.name:backtest.file_sha(p) for p in root.glob('*.jsonl')}
    require(base['sources']==backtest.source_files(),'REFUSED_WINDOW_SOURCES')
    checkpoints=list(root.rglob('*.json.gz'))
    journal=Journal(root,resume=True)
    try:
        for p in checkpoints:
            c=read_checkpoint(p);backtest.validate_checkpoint(c,base,selected)
            restored=runtime.restore(c['run'],policy=base['policy'],input_sha256=backtest.input_hash(base,c['repairs']))
            require(runtime.checkpoint(restored)==c['run'],'REFUSED_WINDOW_CANONICAL_ROUNDTRIP')
            journal.verify(c['journals'])
        journal.verify(saved['journals'])
    finally:journal.close()
    for name,c in saved['journals'].items():require((root/(name+'.jsonl')).stat().st_size==c['bytes'],'REFUSED_WINDOW_TAIL')
    prior=None;counts={};ledger_final=None
    with localcontext() as context:
        context.prec=50
        for name,wanted,phase in (('formation',selected[299:425],'FORMATION'),('daily',selected[425:],'MEASURED')):
            count=0
            for line in (root/(name+'.jsonl')).open('rb'):
                r=json.loads(line);require(count<len(wanted) and r['session']==wanted[count] and r['phase']==phase,'REFUSED_WINDOW_AXIS')
                audit=r['evidence']['research_entry_audit']
                for key,expected_phase,valuation in (('opening_accounting','OPEN_BEFORE_FILLS','parent_core_open_equity'),
                        ('closing_accounting','CLOSE_AFTER_DECISION','parent_core_close_equity')):
                    snap=audit[key];require(snap['session']==r['session'] and snap['phase']==expected_phase,'REFUSED_ACCOUNTING_PHASE')
                    reconcile(snap);near(snap['resolved_equity'],r['economics'][valuation],'REFUSED_SOURCE_EQUITY_BINDING')
                factor(prior,r);prior=r['economics'];count+=1
                ledger_final=audit['closing_accounting']['ledger']
            require(count==len(wanted),'REFUSED_WINDOW_COUNT');counts[name]=count
    require(before=={p.name:backtest.file_sha(p) for p in root.glob('*.jsonl')},'REFUSED_REVIEW_MUTATION')
    monthly=[json.loads(x) for x in (root/'monthly.jsonl').open('rb')]
    months_checked=monthly_metrics(root,backtest.START)
    result=dict(status='INDEPENDENT_SHORT_WINDOW_REVIEW_PASSED',start=backtest.START,end=backtest.END,
        counts=counts,policy=base['policy'],all_checkpoints=len(checkpoints),all_prefixes_verified=True,
        canonical_roundtrips=True,tails=0,ledger_events=len(ledger_final['events']),
        money_tolerance=str(MONEY),monthly_metrics_recomputed=months_checked,
        latest=monthly[-1],source_checkpoint=saved['sha256'])
    output.write_text(json.dumps(result,indent=2)+'\n');print('INDEPENDENT_SHORT_WINDOW_REVIEW_PASSED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--original',type=Path);p.add_argument('--disabled',type=Path);a=p.parse_args()
    if a.original:a.output.write_text(json.dumps(compare_disabled(a.original,a.disabled),indent=2)+'\n')
    else:review(a.root,a.output)
