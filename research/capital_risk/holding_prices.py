"""Read-only, phase-specific raw price coverage on the frozen original trace."""
from collections import defaultdict,Counter
from fractions import Fraction as Q
from decimal import Decimal as D
from pathlib import Path
import csv,gzip,hashlib,io,json,time,zipfile
from holding_identity import encoded,sha
from weighted_features import make_books


def need(value,code):
    if not value:raise ValueError(code)


def positive(text):
    try:
        value=D(text)
        return value.is_finite() and value>0
    except Exception:return False


def requirements(rows,events):
    books=make_books(rows,events);byday=defaultdict(list)
    for e in events:byday[e['session']].append(e)
    result={};previous={}
    for row in rows:
        day=row['session'];book=books[day];uses=defaultdict(set);terminal={}
        for sid in book['shares']:uses[sid]|={'CLOSE_MARK','OPEN_CURRENT'}
        for sid in previous:uses[sid].add('OPEN_OVERNIGHT')
        trades=[]
        for e in byday[day]:
            kind=e['event_type'];sid=e['security_id']
            if kind in ('CASH_MERGER','CONVERSION'):
                terminal[sid]=dict(event_type=kind,source_sha256=hashlib.sha256(encoded(e)).hexdigest(),event=e)
                if kind=='CONVERSION':uses[e['detail']['delivered_security_id']].add('OPEN_DELIVERED')
            elif kind in ('BUY','SELL','SPINOFF_LIQUIDATION'):
                uses[sid].add('OPEN_TRADE');trades.append(e)
            elif kind=='SPINOFF_RECEIPT':uses[sid].add('OPEN_CHILD')
        result[day]=dict(row=row,book=book,uses={s:sorted(v) for s,v in uses.items()},terminal=terminal,trades=trades)
        previous=book['shares']
    return result


def qualify_prices(rows,events,archive,bundle,output):
    started=time.perf_counter();wanted=requirements(rows,events);selected={};counts=Counter();missing=[];bad=[];trade_errors=[]
    defensive={};max_difference=D(0);chain='0'*64
    overlay_raw=(bundle/'spinoff-proxy-overlay.json').read_bytes();overlay_rows=json.loads(overlay_raw)
    overlays={(r['session'],r['security_id']):r for r in overlay_rows}
    need(len(overlays)==len(overlay_rows),'REFUSED_DUPLICATE_DECLARED_OVERLAY')
    def consume(day,prices):
        nonlocal max_difference,chain
        if day not in wanted:return
        r=wanted[day];resolutions={};issues=[]
        for (effective,sid),bar in overlays.items():
            if effective==day and sid in r['uses']:
                prices[sid]={k:bar[k] for k in ('session','security_id','ticker','raw_open','raw_close','tradeable')}
                prices[sid].update(source_row_sha256=hashlib.sha256(encoded(bar)).hexdigest(),
                    source_partition='bundle/spinoff-proxy-overlay.json',full_source_row=bar)
                counts['declared_overlay_bars']+=1
        for sid,uses in r['uses'].items():
            p=prices.get(sid)
            if sid in r['terminal'] and set(uses)<={'OPEN_OVERNIGHT'}:
                resolutions[sid]=r['terminal'][sid];counts['terminal_open_resolutions']+=1
                continue
            if p is None:
                issues.append(dict(session=day,security_id=sid,uses=uses,reason='MISSING_RAW_BAR'))
                continue
            for domain in ('raw_open','raw_close'):
                required=domain=='raw_open' or 'CLOSE_MARK' in uses
                if required and not positive(p[domain]):issues.append(dict(session=day,security_id=sid,domain=domain,reason='INVALID_RAW_PRICE'))
            if any(u.startswith('OPEN_') and u!='OPEN_OVERNIGHT' for u in uses) and p['tradeable'].lower() not in ('true','1'):
                counts['untradeable_required_bars']+=1
                issues.append(dict(session=day,security_id=sid,reason='NOT_TRADEABLE',uses=uses))
        differences=[]
        for event in r['trades']:
            p=prices.get(event['security_id'])
            if p and positive(p['raw_open']):
                difference=abs(D(str(event['price']))-D(p['raw_open']))
                differences.append(dict(source_event_sha256=hashlib.sha256(encoded(event)).hexdigest(),
                    security_id=event['security_id'],event_price=str(event['price']),raw_open=p['raw_open'],difference=str(difference),reason=event['reason']))
                if difference>D('1e-9'):trade_errors.append(dict(session=day,**differences[-1]))
        close_ok=all(s in prices and positive(prices[s]['raw_close']) for s in r['book']['shares'])
        difference=None
        if close_ok:
            reconstructed=D(str(r['book']['cash']))+sum((D(str(v)) for v in r['book']['claims'].values()),D(0))
            reconstructed+=sum((D(str(q))*D(prices[s]['raw_close']) for s,q in r['book']['shares'].items()),D(0))
            difference=reconstructed-D(r['row']['economics']['parent_core_close_equity']);max_difference=max(max_difference,abs(difference))
            if abs(difference)>D('.000002'):issues.append(dict(session=day,reason='RAW_CLOSE_EQUITY_MISMATCH',difference=str(difference)))
        record=dict(session=day,phase=r['row']['phase'],source_state_sha256=r['row']['state_sha256'],
            source_input_sha256=r['row']['input_sha256'],source_chain_sha256=r['row']['chain_sha256'],
            uses=r['uses'],prices=prices,terminal_resolutions=resolutions,trades=differences,
            original_book=r['book'],expected_original_core_equity=r['row']['economics']['parent_core_close_equity'],
            original_close_difference=None if difference is None else str(difference),issues=issues)
        chain=hashlib.sha256(encoded(dict(previous=chain,record=record))).hexdigest()
        stream.write(encoded({**record,'price_chain_sha256':chain})+b'\n')
        missing.extend(x for x in issues if x['reason']=='MISSING_RAW_BAR');bad.extend(x for x in issues if x['reason']!='MISSING_RAW_BAR')
        counts['source_sessions']+=1;counts['retained_raw_bars']+=len(prices);counts['trade_price_checks']+=len(differences)
    output.mkdir(exist_ok=False)
    with (output/'price-bindings.jsonl').open('xb') as stream,zipfile.ZipFile(archive) as z:
        for year in range(2007,2027):
            last=None;prices={}
            with z.open(f'observations-{year}.csv.gz') as raw,gzip.GzipFile(fileobj=raw) as gz,io.TextIOWrapper(gz,encoding='utf8',newline='') as text:
                reader=csv.reader(text);header=next(reader);ix={n:i for i,n in enumerate(header)}
                need(all(k in ix for k in ('session','security_id','ticker','raw_open','raw_close','tradeable')),'REFUSED_RAW_HEADER')
                for fields in reader:
                    counts['archive_rows_scanned']+=1;day=fields[ix['session']];sid=fields[ix['security_id']]
                    if last is not None and day!=last:consume(last,prices);prices={}
                    need(last is None or day>=last,'REFUSED_ARCHIVE_SESSION_ORDER');last=day
                    selected_day=day in wanted
                    if selected_day and fields[ix['ticker']]=='BIL':
                        need(day not in defensive,'REFUSED_DUPLICATE_BIL_BAR')
                        defensive[day]=dict(zip(header,fields))
                    if selected_day and sid in wanted[day]['uses']:
                        need(sid not in prices,'REFUSED_DUPLICATE_REQUIRED_RAW_BAR')
                        prices[sid]={k:fields[ix[k]] for k in ('session','security_id','ticker','raw_open','raw_close','tradeable')}
                        prices[sid]['source_row_sha256']=hashlib.sha256(encoded(dict(zip(header,fields)))).hexdigest()
                        prices[sid]['source_partition']=f'observations-{year}.csv.gz'
                        prices[sid]['full_source_row']=dict(zip(header,fields))
                if last is not None:consume(last,prices)
    need(counts['source_sessions']==4765,'REFUSED_RAW_PRICE_AXIS')
    with gzip.open(bundle/'cash.csv.gz','rt') as f:cash=list(csv.DictReader(f))
    cash={r['session']:r for r in cash if r['session'] in wanted}
    need(set(cash)==set(wanted),'REFUSED_DEFENSIVE_FACTOR_AXIS')
    missing_defensive=sorted(set(wanted)-set(defensive))
    invalid_defensive=[day for day,row in defensive.items() if not positive(row['raw_open']) or not positive(row['raw_close'])]
    (output/'defensive-bars.json').write_bytes(encoded(dict(raw_bil=defensive,retained_cash_factors=cash))+b'\n')
    result=dict(status='HISTORICAL_PRICE_AUDIT_COMPLETE',counts=dict(counts),
        missing_raw=missing,invalid_or_untradeable=bad,trade_price_mismatches=trade_errors,
        maximum_original_close_equity_residual=str(max_difference),price_chain_sha256=chain,
        price_file_sha256=sha(output/'price-bindings.jsonl'),
        equity_raw_domain_covered=not missing and not bad and not trade_errors,
        defensive_raw_bil_sessions=len(defensive),defensive_missing_sessions=missing_defensive,
        defensive_invalid_sessions=invalid_defensive,retained_cash_sources=sorted({r['source'] for r in cash.values()}),
        declared_spinoff_overlay_sha256=hashlib.sha256(overlay_raw).hexdigest(),
        defensive_raw_bil_complete=not missing_defensive and not invalid_defensive,
        adjusted_prices_substituted=False,hypothetical_funded_accounts_executed=0,canonical_transitions_executed=0,
        processing_seconds=time.perf_counter()-started)
    (output/'summary.json').write_bytes(encoded(result)+b'\n');return result
