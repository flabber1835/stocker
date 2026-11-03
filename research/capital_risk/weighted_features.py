"""Read actual ledger/marks only; no signal, Core transition or broker calls."""
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path
import csv,gzip,hashlib,io,json,math,zipfile
from weighted_policy import deterioration,need,number

def align(row,shares):
    held=row['evidence']['breadth']['holdings']
    ops=sorted((x for x in row['evidence']['research_entry_audit']['operations']
                if x['operation'] in ('HOLD_UNCHANGED','CLOSE_POSITION')),key=lambda x:x['slot_id'])
    need(len(ops)==len(held) and len({x['slot_id'] for x in ops})==len(ops),'REFUSED_R_SLOT_COUNT')
    need({x['security_id'] for x in ops}==set(shares),'REFUSED_R_INVENTORY_IDENTITIES')
    status={};slots=defaultdict(list)
    for op,h in zip(ops,held):
        need(op['ticker']==h['ticker'] and ('age' not in op['detail'] or op['detail']['age']==h['age_sessions']),
             'REFUSED_R_HOLDING_ALIGNMENT')
        sid=op['security_id'];value=deterioration(h['own_dd'],h['r21']);slots[sid].append(op['slot_id'])
        if value=='UNKNOWN' or status.get(sid)!='UNKNOWN' and value=='DETERIORATING':status[sid]=value
        else:status.setdefault(sid,value)
    return status,dict(slots)

def feature(row,book,quotes):
    need(set(quotes)==set(book['shares']),'REFUSED_R_HELD_QUOTES')
    core=number(row['economics']['parent_core_close_equity']);need(core>0,'REFUSED_R_CORE_EQUITY')
    status,slots=align(row,book['shares']);values={}
    for sid,q in book['shares'].items():
        price=number(quotes[sid]);need(price>0 and q>0,'REFUSED_R_RAW_QUOTE')
        values[sid]=number(q)*price
    reconstructed=number(book['cash'])+sum(map(number,book['claims'].values()),D(0))+sum(values.values(),D(0))
    need(abs(reconstructed-core)<=D('.000002'),'REFUSED_R_CORE_RECONCILIATION')
    bad=sum((v for sid,v in values.items() if status[sid]!='HEALTHY'),D(0))/core
    unknown=sum((v for sid,v in values.items() if status[sid]=='UNKNOWN'),D(0))/core
    need(0<=unknown<=bad<=1,'REFUSED_R_CAPITAL_SCORE')
    return dict(session=row['session'],score=str(bad),unknown_score=str(unknown),
        positions=len(values),episodes=sum(map(len,slots.values())),
        duplicate_security_ids=sum(len(v)>1 for v in slots.values()),
        states=status,slots=slots,marked_capital={k:str(v) for k,v in values.items()},
        core_equity=str(core),equity_difference=str(reconstructed-core),
        source_state_sha256=row['state_sha256'],source_input_sha256=row['input_sha256'],
        source_chain_sha256=row['chain_sha256'])

def make_books(rows,events):
    byday=defaultdict(list)
    for e in events:byday[e['session']].append(e)
    wanted={r['session'] for r in rows};shares={};claims=defaultdict(float);cash=50000.;books={}
    for day in sorted(set(byday)|wanted):
        for e in byday[day]:
            need(e['event_type'] in {'BUY','SELL','SPLIT','CONVERSION','CASH_MERGER','DIVIDEND_ACCRUED',
                'DIVIDEND_PAID','SPINOFF_RECEIPT','SPINOFF_LIQUIDATION'},'REFUSED_R_LEDGER_EVENT_TYPE')
            need(abs(cash-e['cash_before'])<=2e-6,'REFUSED_R_LEDGER_CASH');cash=e['cash_after']
            sid=e['security_id'];kind=e['event_type']
            if kind=='CONVERSION':
                d=e['detail'];shares[sid]=shares.get(sid,0)-d['shares_in'];other=d['delivered_security_id']
                shares[other]=shares.get(other,0)+d['shares_delivered']
            else:shares[sid]=shares.get(sid,0)+e['shares_delta']
            if kind=='DIVIDEND_ACCRUED':claims[sid]+=e['detail']['amount']
            elif kind=='DIVIDEND_PAID':claims[sid]-=e['detail']['amount']
            need(all(q>=-1e-7 for q in shares.values()) and cash>=-1e-7,'REFUSED_R_LEDGER_LONG_ONLY')
            shares={s:q for s,q in shares.items() if abs(q)>1e-7}
        if day in wanted:books[day]=dict(shares=dict(shares),claims=dict(claims),cash=cash)
    return books

def build(rows,events,archive,output):
    need(not output.exists(),'REFUSED_R_FEATURE_OVERWRITE')
    books=make_books(rows,events);byday={r['session']:r for r in rows};count=0;raw_count=0;unknown=0;duplicates=0;max_error=D(0)
    with output.open('x',encoding='utf-8') as target,zipfile.ZipFile(archive) as z:
        for year in range(2007,2027):
            last=None;quotes={}
            def consume(day,prices):
                nonlocal count,unknown,duplicates,max_error
                if day not in byday:return
                f=feature(byday[day],books[day],prices);count+=1;unknown+=number(f['unknown_score'])>0
                duplicates+=f['duplicate_security_ids']>0;max_error=max(max_error,abs(number(f['equity_difference'])))
                target.write(json.dumps(f,sort_keys=True,separators=(',',':'))+'\n')
            with z.open(f'observations-{year}.csv.gz') as raw,gzip.GzipFile(fileobj=raw) as gz,io.TextIOWrapper(gz,encoding='utf8',newline='') as text:
                reader=csv.reader(text);header=next(reader);ix={v:i for i,v in enumerate(header)}
                di,si,ci=(ix[x] for x in ('session','security_id','raw_close'))
                for row in reader:
                    raw_count+=1;day=row[di]
                    if last is not None and day!=last:consume(last,quotes);quotes={}
                    last=day
                    if day in books and row[si] in books[day]['shares']:
                        need(row[si] not in quotes,'REFUSED_R_DUPLICATE_RAW_QUOTE');quotes[row[si]]=row[ci]
                if last is not None:consume(last,quotes)
    need(count==len(rows),'REFUSED_R_FEATURE_AXIS')
    return dict(status='WEIGHTED_FEATURES_VERIFIED',observations=count,raw_rows=raw_count,
        unknown_feature_sessions=unknown,duplicate_security_sessions=duplicates,
        maximum_equity_difference=str(max_error),actual_ledger_only=True,no_core_transition=True)
